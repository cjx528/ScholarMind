"""
图谱分析服务 - 引用树、时间线、质量评估、演化分析、综述生成
@author ScholarMind Team
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import TYPE_CHECKING

from packages.ai.prompts import (
    build_evolution_prompt,
    build_paper_wiki_prompt,
    build_research_gaps_prompt,
    build_survey_prompt,
    build_wiki_outline_prompt,
    build_wiki_section_prompt,
)
from packages.ai.wiki_context import WikiContextGatherer
from packages.config import get_settings
from packages.domain.schemas import PaperCreate
from packages.integrations.citation_provider import CitationProvider
from packages.integrations.llm_client import LLMClient
from packages.integrations.openalex_search_client import OpenAlexSearchClient
from packages.integrations.semantic_scholar_search_client import SemanticScholarSearchClient
from packages.storage.db import session_scope
from packages.storage.models import PaperTopic
from packages.storage.repositories import (
    CitationRepository,
    PaperRepository,
    TopicRepository,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_PSEUDO_OUTPUT_RE = re.compile(
    r"^\s*\[[\w.-]+\]\s+provider=.*?;\s*model=.*?;\s*summary=",
    re.IGNORECASE | re.DOTALL,
)
_PROMPT_LEAK_MARKERS = (
    "直接输出文本",
    "不要用 JSON",
    "不要输出 JSON",
    "不要代码块",
    "输出要求",
    "写作要求",
    "请只输出单个 JSON",
    "你是世界顶级",
    "你是一位世界顶级",
)


def _strip_markdown_fence(text: str | None) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:markdown|json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _looks_like_prompt_or_pseudo(text: str, keyword: str = "") -> bool:
    head = text[:500]
    if _PSEUDO_OUTPUT_RE.search(head):
        return True
    if "[wiki_" in head and "summary=" in head:
        return True
    if all(marker in head for marker in ("provider=", "model=", "summary=")):
        return True
    if any(marker in head for marker in _PROMPT_LEAK_MARKERS):
        return True
    return bool(keyword and f"请为「{keyword}」" in head)


def _sanitize_wiki_text(
    text: str | None,
    *,
    keyword: str = "",
    min_chars: int = 60,
    is_pseudo: bool = False,
) -> str:
    cleaned = _strip_markdown_fence(text)
    if not cleaned or is_pseudo:
        return ""
    if _looks_like_prompt_or_pseudo(cleaned, keyword):
        return ""
    if len(cleaned) < min_chars:
        return ""
    return cleaned


def _ensure_sentence_end(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped[-1] not in "。！？.!?":
        return f"{stripped}。"
    return stripped


def _paper_title(item: dict) -> str:
    return str(item.get("title") or "").strip()


def _paper_year(item: dict) -> int | None:
    year = item.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)
    return None


def _title_key(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _metadata_citation_count(item: dict) -> int:
    for key in (
        "citationCount",
        "citation_count",
        "cited_by_count",
        "influentialCitationCount",
        "influential_citation_count",
    ):
        value = _coerce_int(item.get(key))
        if value is not None:
            return value
    return 0


def _paper_create_to_scholar_metadata(paper: PaperCreate, source: str) -> dict:
    meta = paper.metadata or {}
    citation_count = (
        _coerce_int(meta.get("citation_count"))
        or _coerce_int(meta.get("cited_by_count"))
        or 0
    )
    influential_count = _coerce_int(meta.get("influential_citation_count"))
    abstract = paper.abstract or ""
    tldr = ""
    if abstract.startswith("[TL;DR]"):
        first_line, _, rest = abstract.partition("\n")
        tldr = first_line.replace("[TL;DR]", "").strip()
        abstract = rest.strip() or abstract
    if not tldr and abstract:
        tldr = abstract[:260]
    year = paper.publication_date.year if isinstance(paper.publication_date, date) else None
    return {
        "title": paper.title,
        "year": year,
        "citationCount": citation_count,
        "influentialCitationCount": influential_count,
        "venue": meta.get("venue"),
        "fieldsOfStudy": meta.get("fieldsOfStudy") or [],
        "tldr": tldr,
        "source": source,
        "externalSource": source,
        "source_id": paper.source_id,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id or meta.get("arxiv_id"),
        "openalex_url": meta.get("openalex_url"),
        "abstract": abstract,
    }


def _merge_scholar_metadata(*groups: list[dict], max_items: int = 16) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in groups:
        for item in group or []:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            key = _title_key(title)
            current = merged.get(key)
            if current is None or _metadata_citation_count(item) > _metadata_citation_count(current):
                merged[key] = dict(item)
            elif current is not None:
                current.update({k: v for k, v in item.items() if v and not current.get(k)})
    return sorted(
        merged.values(),
        key=lambda item: (
            -_metadata_citation_count(item),
            -(_coerce_int(item.get("year")) or 0),
            str(item.get("title") or ""),
        ),
    )[:max_items]


def _external_metadata_to_paper_context(items: list[dict], start_index: int = 1) -> list[dict]:
    contexts: list[dict] = []
    for item in items:
        contexts.append(
            {
                "title": item.get("title", ""),
                "year": item.get("year"),
                "abstract": item.get("abstract") or item.get("tldr") or "",
                "analysis": (
                    f"联网外部发现来源={item.get('source') or 'external'}，"
                    f"引用数={_metadata_citation_count(item)}。"
                ),
                "has_embedding": False,
                "external": True,
                "source_ref": f"[X{start_index + len(contexts)}]",
            }
        )
    return contexts


def _merge_seminal_with_external(timeline: dict, external_meta: list[dict], limit: int = 12) -> dict:
    merged_timeline = dict(timeline or {})
    seen: set[str] = set()
    merged: list[dict] = []

    for item in merged_timeline.get("seminal", []) or []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        seen.add(_title_key(title))
        merged.append(dict(item))

    for item in external_meta:
        title = str(item.get("title") or "").strip()
        if not title or _title_key(title) in seen:
            continue
        citations = _metadata_citation_count(item)
        if citations <= 0:
            continue
        seen.add(_title_key(title))
        source = str(item.get("source") or item.get("externalSource") or "external")
        merged.append(
            {
                "paper_id": f"external:{source}:{item.get('source_id') or title[:64]}",
                "title": title,
                "year": _coerce_int(item.get("year")) or 1900,
                "indegree": citations,
                "outdegree": 0,
                "pagerank": 0.0,
                "seminal_score": math.log1p(citations),
                "why_seminal": f"外部实时检索：{source} citation_count={citations}",
                "external": True,
                "source": source,
                "citation_count": citations,
            }
        )

    merged.sort(
        key=lambda item: (
            -float(item.get("seminal_score") or 0),
            -int(item.get("year") or 0),
            str(item.get("title") or ""),
        )
    )
    merged_timeline["seminal"] = merged[:limit]
    return merged_timeline


def _topic_source_papers(
    paper_contexts: list[dict] | None,
    timeline: dict | None,
) -> list[dict]:
    papers: list[dict] = []
    seen: set[str] = set()
    for source in (
        list(paper_contexts or []),
        list((timeline or {}).get("seminal", []) or []),
        list((timeline or {}).get("milestones", []) or []),
        list((timeline or {}).get("timeline", []) or []),
    ):
        for item in source:
            if not isinstance(item, dict):
                continue
            title = _paper_title(item)
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            papers.append(item)
    return papers


def _source_refs(count: int, limit: int = 3) -> list[str]:
    return [f"[P{i}]" for i in range(1, min(count, limit) + 1)]


def _fallback_section_plans(keyword: str, paper_contexts: list[dict]) -> list[dict]:
    refs = _source_refs(len(paper_contexts))
    return [
        {
            "section_title": "背景与问题定义",
            "key_points": [f"界定 {keyword} 的研究对象", "说明核心问题与评价目标"],
            "source_refs": refs,
        },
        {
            "section_title": "主要方法谱系",
            "key_points": ["归纳已有方法类别", "比较不同方法的适用条件"],
            "source_refs": refs,
        },
        {
            "section_title": "代表性论文与证据",
            "key_points": ["提炼本地论文库中的代表性工作", "说明这些工作如何支撑主题脉络"],
            "source_refs": refs,
        },
        {
            "section_title": "技术挑战与局限",
            "key_points": ["总结当前方法仍未解决的问题", "指出实验与部署中的主要限制"],
            "source_refs": refs,
        },
        {
            "section_title": "最新趋势与未来方向",
            "key_points": ["结合新近论文判断发展趋势", "提出后续阅读与研究切入点"],
            "source_refs": refs,
        },
    ]


def _fallback_topic_overview(
    *,
    keyword: str,
    paper_contexts: list[dict] | None,
    sections: list[dict] | None,
    survey_data: dict | None,
    timeline: dict | None,
) -> str:
    survey_overview = ""
    if isinstance(survey_data, dict):
        summary = survey_data.get("summary")
        if isinstance(summary, dict):
            survey_overview = _sanitize_wiki_text(
                str(summary.get("overview") or ""),
                keyword=keyword,
                min_chars=20,
            )

    papers = _topic_source_papers(paper_contexts, timeline)
    years = sorted({year for paper in papers if (year := _paper_year(paper)) is not None})
    titles = [_paper_title(paper) for paper in papers[:5] if _paper_title(paper)]
    section_titles = [
        str(sec.get("title") or sec.get("section_title") or "").strip()
        for sec in (sections or [])
        if isinstance(sec, dict)
    ]
    section_titles = [title for title in section_titles if title][:5]

    parts: list[str] = []
    if survey_overview:
        parts.append(_ensure_sentence_end(survey_overview))
    else:
        parts.append(
            f"「{keyword}」是当前知识库中需要系统梳理的研究主题。"
            "这类主题不能只停留在关键词匹配层面，而要结合论文的研究问题、方法假设、"
            "实验对象和后续影响，判断它在领域中的位置。"
        )

    if papers:
        year_text = f"，时间跨度约为 {years[0]}-{years[-1]} 年" if years else ""
        title_text = "；代表性论文包括《" + "》《".join(titles[:3]) + "》" if titles else ""
        parts.append(
            f"从当前本地论文库看，系统检索到 {len(papers)} 篇相关论文{year_text}"
            f"{title_text}。这些论文共同提供了主题定义、方法演化和实验证据，"
            "适合作为后续精读与问答的基础。"
        )
    else:
        parts.append(
            "当前本地样本仍然有限，因此这份 Wiki 会优先明确概念边界、方法谱系和待验证问题，"
            "避免在证据不足时给出过度确定的结论。"
        )

    if section_titles:
        parts.append(
            "后续章节将围绕"
            + "、".join(f"「{title}」" for title in section_titles)
            + "展开，重点说明该主题的来龙去脉、核心技术路线、关键论文证据以及值得继续追踪的新方向。"
        )
    else:
        parts.append(
            "后续章节将按背景、方法、代表性论文、挑战和未来方向组织，帮助用户先建立可复用的领域地图。"
        )

    return "\n\n".join(parts)


def _source_titles_from_text(all_sources_text: str, limit: int = 4) -> list[str]:
    titles: list[str] = []
    for line in all_sources_text.splitlines():
        match = re.match(r"\[(?:P|S)\d+\]\s+(.+?)(?:\s+\(\d{4}|\s+\(\?|$)", line.strip())
        if match:
            title = match.group(1).strip()
            if title and title not in titles:
                titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def _fallback_section_content(
    *,
    keyword: str,
    section_title: str,
    key_points: list[str] | None = None,
    source_refs: list[str] | None = None,
    all_sources_text: str = "",
) -> str:
    points = [str(point).strip() for point in (key_points or []) if str(point).strip()]
    refs = ", ".join(source_refs or [])
    titles = _source_titles_from_text(all_sources_text)

    parts = [
        f"本节围绕「{section_title}」梳理「{keyword}」的一个关键侧面。"
    ]
    if points:
        parts.append("当前资料指向的核心问题包括：" + "；".join(points[:4]) + "。")
    if titles:
        parts.append(
            "可优先对照的论文包括《"
            + "》《".join(titles[:3])
            + "》。这些论文为本节提供了基本证据，但仍需要进一步精读来确认方法细节和实验边界。"
        )
    if refs:
        parts.append(f"相关来源标记为 {refs}。")
    parts.append(
        "在后续阅读中，建议把本节作为问题清单使用：先确认每篇论文解决的具体任务，"
        "再比较其假设、数据设置、指标和失效场景。"
    )
    return "\n\n".join(parts)


def _fallback_topic_summary_data(
    *,
    keyword: str,
    sections: list[dict],
    paper_contexts: list[dict],
) -> dict:
    section_titles = [
        str(sec.get("title") or "").strip()
        for sec in sections
        if isinstance(sec, dict) and str(sec.get("title") or "").strip()
    ]
    paper_titles = [_paper_title(paper) for paper in paper_contexts if _paper_title(paper)]
    findings = [
        f"当前资料显示，「{keyword}」需要从「{title}」角度理解。"
        for title in section_titles[:3]
    ]
    if not findings:
        findings = [f"当前资料显示，「{keyword}」仍需要结合更多论文继续补充证据。"]
    directions = [
        "优先精读最新论文，核对方法假设、实验设置和指标是否与当前研究需求一致。",
        "继续补充高引用代表作和近两年的新工作，避免主题 Wiki 只覆盖单一阶段。",
        "把阅读反馈同步回用户画像和论文库标签，用于后续推荐排序。",
    ]
    return {
        "key_findings": findings,
        "future_directions": directions,
        "reading_list": paper_titles[:6],
    }


def _topic_wiki_markdown(keyword: str, wiki_content: dict) -> str:
    md_parts = [f"# {keyword}\n\n{wiki_content.get('overview', '')}"]
    for sec in wiki_content.get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        md_parts.append(f"\n## {sec.get('title', '')}\n\n{sec.get('content', '')}")
    if wiki_content.get("methodology_evolution"):
        md_parts.append(f"\n## 方法论演化\n\n{wiki_content['methodology_evolution']}")
    return "\n".join(md_parts)


def _sanitize_topic_sections(
    *,
    keyword: str,
    sections: list[dict] | None,
    all_sources_text: str = "",
) -> list[dict]:
    cleaned_sections: list[dict] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or sec.get("section_title") or "").strip()
        content = _sanitize_wiki_text(
            str(sec.get("content") or ""),
            keyword=keyword,
            min_chars=80,
        )
        if not content:
            content = _fallback_section_content(
                keyword=keyword,
                section_title=title or "主题章节",
                key_points=sec.get("key_points") if isinstance(sec.get("key_points"), list) else [],
                source_refs=sec.get("source_refs") if isinstance(sec.get("source_refs"), list) else [],
                all_sources_text=all_sources_text,
            )
        cleaned = dict(sec)
        cleaned["title"] = title or "主题章节"
        cleaned["content"] = content
        cleaned_sections.append(cleaned)
    return cleaned_sections


def repair_topic_wiki_payload(payload: dict | None, keyword: str | None = None) -> dict:
    """Repair persisted topic Wiki metadata before rendering old history records."""
    repaired = dict(payload or {})
    wiki_content = repaired.get("wiki_content")
    if not isinstance(wiki_content, dict):
        return repaired

    topic = keyword or str(repaired.get("keyword") or "").strip() or "主题"
    content = dict(wiki_content)
    sections = _sanitize_topic_sections(
        keyword=topic,
        sections=content.get("sections") if isinstance(content.get("sections"), list) else [],
    )
    overview = _sanitize_wiki_text(
        str(content.get("overview") or ""),
        keyword=topic,
        min_chars=80,
    )
    if not overview:
        overview = _fallback_topic_overview(
            keyword=topic,
            paper_contexts=[],
            sections=sections,
            survey_data=repaired.get("survey") if isinstance(repaired.get("survey"), dict) else {},
            timeline=repaired.get("timeline") if isinstance(repaired.get("timeline"), dict) else {},
        )

    content["overview"] = overview
    content["sections"] = sections
    fallback_summary = _fallback_topic_summary_data(
        keyword=topic,
        sections=sections,
        paper_contexts=[],
    )
    if not content.get("key_findings"):
        content["key_findings"] = fallback_summary["key_findings"]
    if not content.get("future_directions"):
        content["future_directions"] = fallback_summary["future_directions"]
    if not content.get("reading_list"):
        content["reading_list"] = fallback_summary["reading_list"]
    repaired["wiki_content"] = content
    repaired["markdown"] = _topic_wiki_markdown(topic, content)
    return repaired


class GraphService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.citations = CitationProvider(
            openalex_email=self.settings.openalex_email,
            scholar_api_key=self.settings.semantic_scholar_api_key,
        )
        # 保留 self.scholar 兼容别名
        self.scholar = self.citations
        self.llm = LLMClient()
        self.context_gatherer = WikiContextGatherer()

    def _fetch_external_topic_metadata(self, keyword: str, max_results: int = 8) -> list[dict]:
        """Live external discovery for topic Wiki context; does not ingest papers."""
        candidates: list[dict] = []
        searchers = [
            (
                "openalex",
                OpenAlexSearchClient(email=self.settings.openalex_email),
                min(max_results, 8),
            )
        ]
        if self.settings.semantic_scholar_api_key:
            searchers.append(
                (
                    "semantic_scholar",
                    SemanticScholarSearchClient(api_key=self.settings.semantic_scholar_api_key),
                    min(max_results, 8),
                )
            )
        else:
            logger.info("Skipping Semantic Scholar topic search because no API key is configured")
        for source, client, limit in searchers:
            try:
                papers = client.search_papers(keyword, max_results=limit)
                candidates.extend(
                    _paper_create_to_scholar_metadata(paper, source) for paper in papers
                )
            except Exception as exc:
                logger.warning("External wiki search failed for %s/%s: %s", source, keyword, exc)
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
        return _merge_scholar_metadata(candidates, max_items=max_results)

    def sync_citations_for_paper(self, paper_id: str, limit: int = 8) -> dict:
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            source = paper_repo.get_by_id(paper_id)
            edges = self.scholar.fetch_edges_by_title(source.title, limit=limit)
            inserted = 0
            for edge in edges:
                src = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=self._title_to_id(edge.source_title),
                        title=edge.source_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                dst = paper_repo.upsert_paper(
                    PaperCreate(
                        arxiv_id=self._title_to_id(edge.target_title),
                        title=edge.target_title,
                        abstract="",
                        metadata={"source": "semantic_scholar"},
                    )
                )
                cit_repo.upsert_edge(src.id, dst.id, context=edge.context)
                inserted += 1
            return {
                "paper_id": paper_id,
                "edges_inserted": inserted,
            }

    def sync_citations_for_topic(
        self,
        topic_id: str,
        paper_limit: int = 30,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        with session_scope() as session:
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            papers = PaperRepository(session).list_by_topic(topic_id, limit=paper_limit)
            paper_ids = [p.id for p in papers]

        total_edges = 0
        paper_count = 0
        # 限制并发避免 API 限速和 SQLite 锁竞争
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.sync_citations_for_paper, pid, edge_limit_per_paper): pid
                for pid in paper_ids
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    total_edges += int(result.get("edges_inserted", 0))
                    paper_count += 1
                except Exception as exc:
                    logger.warning("sync error for %s: %s", futures[future], exc)

        return {
            "topic_id": topic_id,
            "papers_processed": paper_count,
            "edges_inserted": total_edges,
        }

    def auto_link_citations(self, paper_ids: list[str]) -> dict:
        """入库后自动关联引用 — 轻量版，只匹配已在库的论文"""
        norm = self._normalize_arxiv_id
        linked = 0
        errors = 0
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            all_papers = paper_repo.list_lightweight(limit=50000)
            lib_norm: dict[str, str] = {}
            for p in all_papers:
                pn = norm(p.arxiv_id)
                if pn:
                    lib_norm[pn] = p.id

        for pid in paper_ids:
            try:
                with session_scope() as session:
                    paper = PaperRepository(session).get_by_id(pid)
                    if not paper:
                        continue
                    title = paper.title

                rich = self.scholar.fetch_rich_citations(
                    title,
                    ref_limit=30,
                    cite_limit=30,
                )
                with session_scope() as session:
                    cit_repo = CitationRepository(session)
                    for info in rich:
                        info_n = norm(info.arxiv_id)
                        if info_n and info_n in lib_norm:
                            target_id = lib_norm[info_n]
                            if target_id == pid:
                                continue
                            if info.direction == "reference":
                                cit_repo.upsert_edge(
                                    pid,
                                    target_id,
                                    context="auto-ingest",
                                )
                            else:
                                cit_repo.upsert_edge(
                                    target_id,
                                    pid,
                                    context="auto-ingest",
                                )
                            linked += 1
            except Exception as exc:
                logger.warning("auto_link_citations error for %s: %s", pid, exc)
                errors += 1

        logger.info("auto_link_citations: %d edges, %d errors", linked, errors)
        return {"papers": len(paper_ids), "edges_linked": linked, "errors": errors}

    def library_overview(self) -> dict:
        """全库概览 — 节点 + 引用边 + PageRank + 统计"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            topic_repo = TopicRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            topics = topic_repo.list_topics()
            topic_map = {t.id: t.name for t in topics}

            paper_ids = {p.id for p in papers}
            valid_edges = [
                e
                for e in edges
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids
            ]

            in_deg: dict[str, int] = defaultdict(int)
            out_deg: dict[str, int] = defaultdict(int)
            for e in valid_edges:
                out_deg[e.source_paper_id] += 1
                in_deg[e.target_paper_id] += 1

            pagerank = self._pagerank(list(paper_ids), valid_edges)

            from sqlalchemy import select as sa_select

            pt_rows = session.execute(sa_select(PaperTopic)).scalars().all()
            paper_topics: dict[str, list[str]] = defaultdict(list)
            for pt in pt_rows:
                tn = topic_map.get(pt.topic_id, "未分配")
                paper_topics[pt.paper_id].append(tn)

            nodes = []
            for p in papers:
                yr = p.publication_date.year if isinstance(p.publication_date, date) else None
                nodes.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "year": yr,
                        "in_degree": in_deg.get(p.id, 0),
                        "out_degree": out_deg.get(p.id, 0),
                        "pagerank": round(pagerank.get(p.id, 0), 6),
                        "topics": paper_topics.get(p.id, []),
                        "read_status": p.read_status.value if p.read_status else "unread",
                    }
                )

            edge_list = [
                {"source": e.source_paper_id, "target": e.target_paper_id} for e in valid_edges
            ]

            pr_sorted = sorted(nodes, key=lambda n: n["pagerank"], reverse=True)
            top_papers = pr_sorted[:10]

            topic_stats = defaultdict(lambda: {"count": 0, "edges": 0})
            for n in nodes:
                for t in n["topics"]:
                    topic_stats[t]["count"] += 1

            n_papers = len(nodes)
            max_e = n_papers * (n_papers - 1) if n_papers > 1 else 1

        return {
            "total_papers": n_papers,
            "total_edges": len(edge_list),
            "density": round(len(edge_list) / max_e, 6) if max_e else 0,
            "nodes": nodes,
            "edges": edge_list,
            "top_papers": top_papers,
            "topic_stats": dict(topic_stats),
        }

    def cross_topic_bridges(self) -> dict:
        """跨主题桥接论文 — 被多个主题的论文引用的关键论文"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            topic_repo = TopicRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            topics = topic_repo.list_topics()
            topic_map = {t.id: t.name for t in topics}

            from sqlalchemy import select as sa_select

            pt_rows = session.execute(sa_select(PaperTopic)).scalars().all()
            paper_topic: dict[str, set[str]] = defaultdict(set)
            for pt in pt_rows:
                paper_topic[pt.paper_id].add(pt.topic_id)

            paper_ids = {p.id for p in papers}
            cited_by_topics: dict[str, set[str]] = defaultdict(set)
            for e in edges:
                if e.source_paper_id not in paper_ids:
                    continue
                if e.target_paper_id not in paper_ids:
                    continue
                src_topics = paper_topic.get(e.source_paper_id, set())
                for tid in src_topics:
                    cited_by_topics[e.target_paper_id].add(tid)

            bridges = []
            paper_map = {p.id: p for p in papers}
            for pid, tids in cited_by_topics.items():
                if len(tids) >= 2:
                    p = paper_map.get(pid)
                    if not p:
                        continue
                    bridges.append(
                        {
                            "id": pid,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "topics_citing": [topic_map.get(t, t) for t in tids],
                            "cross_topic_count": len(tids),
                            "own_topics": [
                                topic_map.get(t, t) for t in paper_topic.get(pid, set())
                            ],
                        }
                    )

            bridges.sort(key=lambda b: b["cross_topic_count"], reverse=True)

        return {"bridges": bridges[:30], "total": len(bridges)}

    def research_frontier(self, days: int = 90) -> dict:
        """研究前沿检测 — 近期高被引 + 引用速度快的论文"""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=days)

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}

            in_deg: dict[str, int] = defaultdict(int)
            for e in edges:
                if e.target_paper_id in paper_ids:
                    in_deg[e.target_paper_id] += 1

            recent = [
                p
                for p in papers
                if isinstance(p.publication_date, date) and p.publication_date >= cutoff
            ]

            frontier = []
            for p in recent:
                age_days = max((date.today() - p.publication_date).days, 1)
                citations = in_deg.get(p.id, 0)
                velocity = round(citations / age_days * 30, 2)
                frontier.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "year": p.publication_date.year,
                        "publication_date": p.publication_date.isoformat(),
                        "citations_in_library": citations,
                        "citation_velocity": velocity,
                        "read_status": p.read_status.value if p.read_status else "unread",
                    }
                )

            frontier.sort(key=lambda f: f["citation_velocity"], reverse=True)

        return {
            "period_days": days,
            "total_recent": len(recent),
            "frontier": frontier[:30],
        }

    def cocitation_clusters(self, min_cocite: int = 2) -> dict:
        """共引聚类 — 被同一批论文引用的论文会聚在一起"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            papers = paper_repo.list_lightweight(limit=50000)
            edges = cit_repo.list_all()
            paper_ids = {p.id for p in papers}
            paper_map = {p.id: p for p in papers}

            cited_by_map: dict[str, set[str]] = defaultdict(set)
            for e in edges:
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids:
                    cited_by_map[e.target_paper_id].add(e.source_paper_id)

            target_ids = list(cited_by_map.keys())
            cocite_pairs: dict[tuple[str, str], int] = defaultdict(int)

            for i, a in enumerate(target_ids):
                citers_a = cited_by_map[a]
                for b in target_ids[i + 1 :]:
                    citers_b = cited_by_map[b]
                    overlap = len(citers_a & citers_b)
                    if overlap >= min_cocite:
                        cocite_pairs[(a, b)] = overlap

            clusters: list[set[str]] = []
            assigned: set[str] = set()
            sorted_pairs = sorted(
                cocite_pairs.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for (a, b), _strength in sorted_pairs:
                found = None
                for cl in clusters:
                    if a in cl or b in cl:
                        found = cl
                        break
                if found:
                    found.add(a)
                    found.add(b)
                else:
                    clusters.append({a, b})
                assigned.add(a)
                assigned.add(b)

            result_clusters = []
            for cl in clusters:
                members = []
                for pid in cl:
                    p = paper_map.get(pid)
                    if not p:
                        continue
                    members.append(
                        {
                            "id": pid,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                        }
                    )
                if len(members) >= 2:
                    result_clusters.append(
                        {
                            "size": len(members),
                            "papers": members,
                        }
                    )

            result_clusters.sort(key=lambda c: c["size"], reverse=True)

        return {
            "total_clusters": len(result_clusters),
            "clusters": result_clusters[:20],
            "cocitation_pairs": len(cocite_pairs),
        }

    def sync_incremental(
        self,
        paper_limit: int = 40,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=paper_limit * 3)
            edges = CitationRepository(session).list_all()
            touched = set()
            for e in edges:
                touched.add(e.source_paper_id)
                touched.add(e.target_paper_id)
            # 在 session 内提取 id，避免 DetachedInstanceError
            target_ids = [p.id for p in papers if p.id not in touched][:paper_limit]
        processed = 0
        inserted = 0
        for pid in target_ids:
            try:
                out = self.sync_citations_for_paper(pid, limit=edge_limit_per_paper)
                processed += 1
                inserted += int(out.get("edges_inserted", 0))
            except Exception as exc:
                logger.warning("sync_incremental skip %s: %s", pid[:8], exc)
        return {
            "processed_papers": processed,
            "edges_inserted": inserted,
            "strategy": "papers_without_existing_citation_edges",
        }

    def _project_embeddings_2d(self, vectors: list[list[float]]) -> list[tuple[float, float]]:
        if not vectors:
            return []
        dim = min(len(v) for v in vectors)
        if dim <= 0:
            return [(0.0, 0.0) for _ in vectors]

        trimmed = [[float(x) for x in v[:dim]] for v in vectors]
        means = [sum(row[i] for row in trimmed) / len(trimmed) for i in range(dim)]
        centered = [[row[i] - means[i] for i in range(dim)] for row in trimmed]
        variances = [sum(row[i] * row[i] for row in centered) for i in range(dim)]
        ranked = sorted(range(dim), key=lambda i: variances[i], reverse=True)
        x_idx = ranked[0]
        y_idx = ranked[1] if len(ranked) > 1 else ranked[0]

        coords = []
        for row in centered:
            x = row[x_idx]
            y = row[y_idx] if y_idx != x_idx else 0.0
            coords.append((x, y))

        max_abs = max((max(abs(x), abs(y)) for x, y in coords), default=0.0)
        if max_abs <= 1e-12:
            total = max(len(vectors), 1)
            return [
                (
                    math.cos(2 * math.pi * i / total),
                    math.sin(2 * math.pi * i / total),
                )
                for i in range(len(vectors))
            ]
        return [(x / max_abs, y / max_abs) for x, y in coords]

    def similarity_map(
        self,
        topic_id: str | None = None,
        limit: int = 200,
    ) -> dict:
        """用 UMAP 将论文 embedding 降维到 2D，返回散点图数据"""
        with session_scope() as session:
            repo = PaperRepository(session)
            papers = repo.list_with_embedding(topic_id=topic_id, limit=limit)
            if len(papers) < 5:
                return {"points": [], "message": "论文数量不足（至少需要 5 篇有向量的论文）"}

            topic_map = repo.get_topic_names_for_papers([str(p.id) for p in papers])

            # 提取 embedding 矩阵
            dim = len(papers[0].embedding)
            vectors = []
            valid_papers = []
            for p in papers:
                if p.embedding and len(p.embedding) == dim:
                    vectors.append(p.embedding)
                    valid_papers.append(p)

            if len(valid_papers) < 5:
                return {"points": [], "message": "有效向量不足"}

            try:
                import numpy as np
            except Exception as exc:
                logger.info("Using pure Python similarity projection: %s", exc)
                coords = self._project_embeddings_2d(vectors)
                points = []
                for i, p in enumerate(valid_papers):
                    meta = p.metadata_json or {}
                    topics = topic_map.get(str(p.id), [])
                    points.append(
                        {
                            "id": str(p.id),
                            "title": p.title,
                            "x": coords[i][0],
                            "y": coords[i][1],
                            "year": p.publication_date.year if p.publication_date else None,
                            "read_status": p.read_status.value if p.read_status else "unread",
                            "topics": topics,
                            "topic": topics[0] if topics else "未分类",
                            "arxiv_id": p.arxiv_id,
                            "title_zh": meta.get("title_zh", ""),
                        }
                    )
                return {"points": points, "total": len(points), "projection": "python"}

            mat = np.array(vectors, dtype=np.float64)

            # UMAP 降维
            try:
                from umap import UMAP

                n_neighbors = min(15, len(valid_papers) - 1)
                reducer = UMAP(
                    n_components=2, random_state=42, n_neighbors=n_neighbors, min_dist=0.1
                )
                coords = reducer.fit_transform(mat)
            except Exception as exc:
                logger.warning("UMAP failed: %s, falling back to PCA", exc)
                try:
                    from sklearn.decomposition import PCA

                    coords = PCA(n_components=2, random_state=42).fit_transform(mat)
                except Exception as fallback_exc:
                    logger.info("Using pure Python similarity projection: %s", fallback_exc)
                    coords = self._project_embeddings_2d(vectors)

            points = []
            for i, p in enumerate(valid_papers):
                meta = p.metadata_json or {}
                topics = topic_map.get(str(p.id), [])
                points.append(
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "x": float(coords[i][0]),
                        "y": float(coords[i][1]),
                        "year": p.publication_date.year if p.publication_date else None,
                        "read_status": p.read_status.value if p.read_status else "unread",
                        "topics": topics,
                        "topic": topics[0] if topics else "未分类",
                        "arxiv_id": p.arxiv_id,
                        "title_zh": meta.get("title_zh", ""),
                    }
                )

        return {"points": points, "total": len(points)}

    def citation_tree(self, root_paper_id: str, depth: int = 2) -> dict:
        with session_scope() as session:
            papers = {p.id: p for p in PaperRepository(session).list_lightweight(limit=10000)}
            edges = CitationRepository(session).list_all()
            out_edges: dict[str, list[str]] = defaultdict(list)
            in_edges: dict[str, list[str]] = defaultdict(list)
            for e in edges:
                out_edges[e.source_paper_id].append(e.target_paper_id)
                in_edges[e.target_paper_id].append(e.source_paper_id)

            def bfs(start: str, graph: dict[str, list[str]]) -> list[dict]:
                visited = {start}
                q: deque[tuple[str, int]] = deque([(start, 0)])
                result: list[dict] = []
                while q:
                    node, d = q.popleft()
                    if d >= depth:
                        continue
                    for nxt in graph.get(node, []):
                        result.append(
                            {
                                "source": node,
                                "target": nxt,
                                "depth": d + 1,
                            }
                        )
                        if nxt not in visited:
                            visited.add(nxt)
                            q.append((nxt, d + 1))
                return result

            ancestors = bfs(root_paper_id, out_edges)
            descendants = bfs(root_paper_id, in_edges)
            all_node_ids = {root_paper_id}
            for e in ancestors + descendants:
                all_node_ids.add(e["source"])
                all_node_ids.add(e["target"])
            nodes = [
                {
                    "id": pid,
                    "title": (papers[pid].title if pid in papers else None),
                    "year": (
                        papers[pid].publication_date.year
                        if pid in papers
                        and isinstance(
                            papers[pid].publication_date,
                            date,
                        )
                        else None
                    ),
                }
                for pid in all_node_ids
            ]
            root_paper = papers.get(root_paper_id)
            root_title = root_paper.title if root_paper else None
        return {
            "root": root_paper_id,
            "root_title": root_title,
            "ancestors": ancestors,
            "descendants": descendants,
            "nodes": nodes,
            "edge_count": len(ancestors) + len(descendants),
        }

    def citation_detail(self, paper_id: str) -> dict:
        """获取单篇论文的丰富引用详情"""
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)
            source = paper_repo.get_by_id(paper_id)
            if source is None:
                return {
                    "paper_id": paper_id,
                    "paper_title": "",
                    "references": [],
                    "cited_by": [],
                    "stats": {
                        "total_references": 0,
                        "total_cited_by": 0,
                        "in_library_references": 0,
                        "in_library_cited_by": 0,
                    },
                }
            source_title = source.title
            source_arxiv_id = source.arxiv_id

            try:
                rich_list = self.scholar.fetch_rich_citations(
                    source_title,
                    ref_limit=50,
                    cite_limit=50,
                    arxiv_id=source_arxiv_id,
                )
            except Exception as exc:
                logger.warning("fetch_rich_citations failed: %s", exc)
                rich_list = []

            norm = self._normalize_arxiv_id
            ext_normed = {norm(r.arxiv_id): r.arxiv_id for r in rich_list if r.arxiv_id}
            lib_norm_map: dict[str, str] = {}
            if ext_normed:
                # 只加载轻量字段，减少内存占用
                for p in paper_repo.list_lightweight(limit=50000):
                    pn = norm(p.arxiv_id)
                    if pn and pn in ext_normed:
                        lib_norm_map[pn] = p.id

            references: list[dict] = []
            cited_by: list[dict] = []

            for info in rich_list:
                info_norm = norm(info.arxiv_id)
                in_library = info_norm is not None and info_norm in lib_norm_map
                library_paper_id = lib_norm_map.get(info_norm) if in_library else None
                entry = {
                    "scholar_id": info.scholar_id,
                    "title": info.title,
                    "year": info.year,
                    "venue": info.venue,
                    "citation_count": info.citation_count,
                    "arxiv_id": info.arxiv_id,
                    "abstract": info.abstract,
                    "in_library": in_library,
                    "library_paper_id": library_paper_id,
                }
                if info.direction == "reference":
                    references.append(entry)
                    if in_library and library_paper_id:
                        cit_repo.upsert_edge(
                            paper_id,
                            library_paper_id,
                            context="reference",
                        )
                else:
                    cited_by.append(entry)
                    if in_library and library_paper_id:
                        cit_repo.upsert_edge(
                            library_paper_id,
                            paper_id,
                            context="citation",
                        )

        return {
            "paper_id": paper_id,
            "paper_title": source_title,
            "references": references,
            "cited_by": cited_by,
            "stats": {
                "total_references": len(references),
                "total_cited_by": len(cited_by),
                "in_library_references": sum(1 for r in references if r["in_library"]),
                "in_library_cited_by": sum(1 for c in cited_by if c["in_library"]),
            },
        }

    def topic_citation_network(self, topic_id: str) -> dict:
        """获取主题内论文的互引网络"""
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            topic = topic_repo.get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            topic_name = topic.name

            papers = paper_repo.list_by_topic(topic_id, limit=500)
            paper_ids = {p.id for p in papers}

            all_edges = cit_repo.list_for_paper_ids(list(paper_ids))
            internal_edges = [
                e
                for e in all_edges
                if e.source_paper_id in paper_ids and e.target_paper_id in paper_ids
            ]

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            degrees = [in_degree.get(pid, 0) for pid in paper_ids]
            median_deg = sorted(degrees)[len(degrees) // 2] if degrees else 0
            hub_threshold = max(median_deg * 2, 2)

            nodes = []
            for p in papers:
                ind = in_degree.get(p.id, 0)
                outd = out_degree.get(p.id, 0)
                nodes.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "year": (
                            p.publication_date.year
                            if isinstance(p.publication_date, date)
                            else None
                        ),
                        "arxiv_id": p.arxiv_id,
                        "in_degree": ind,
                        "out_degree": outd,
                        "is_hub": ind >= hub_threshold,
                        "is_external": False,
                    }
                )

            edges = [
                {
                    "source": e.source_paper_id,
                    "target": e.target_paper_id,
                }
                for e in internal_edges
            ]

            hub_count = sum(1 for n in nodes if n["is_hub"])
            n_papers = len(nodes)
            max_edges = n_papers * (n_papers - 1) if n_papers > 1 else 1
            density = round(len(edges) / max_edges, 4) if max_edges else 0

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_papers": n_papers,
                "total_edges": len(edges),
                "density": density,
                "hub_papers": hub_count,
            },
        }

    def topic_deep_trace(self, topic_id: str, max_concurrency: int = 3) -> dict:
        """对主题内论文执行深度溯源，拉取外部引用并进行共引分析"""
        with session_scope() as session:
            papers = PaperRepository(session).list_by_topic(
                topic_id,
                limit=500,
            )
            paper_ids = [p.id for p in papers]
            topic = TopicRepository(session).get_by_id(topic_id)
            if topic is None:
                raise ValueError(f"topic {topic_id} not found")
            topic_name = topic.name

        synced = 0
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {pool.submit(self.citation_detail, pid): pid for pid in paper_ids}
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    synced += (
                        result["stats"]["total_references"] + result["stats"]["total_cited_by"]
                    )
                except Exception as exc:
                    logger.warning("deep-trace sync error: %s", exc)

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            cit_repo = CitationRepository(session)

            topic_papers = paper_repo.list_by_topic(topic_id, limit=500)
            topic_ids_set = {p.id for p in topic_papers}
            all_edges = cit_repo.list_for_paper_ids(list(topic_ids_set))

            external_ref_count: dict[str, int] = defaultdict(int)
            internal_edges = []
            external_edges = []

            for e in all_edges:
                src_in = e.source_paper_id in topic_ids_set
                tgt_in = e.target_paper_id in topic_ids_set
                if src_in and tgt_in:
                    internal_edges.append(e)
                elif src_in and not tgt_in:
                    external_edges.append(e)
                    external_ref_count[e.target_paper_id] += 1
                elif not src_in and tgt_in:
                    external_edges.append(e)
                    external_ref_count[e.source_paper_id] += 1

            co_cited = sorted(
                external_ref_count.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:30]
            co_cited_ids = [pid for pid, _ in co_cited]
            co_cited_papers = {p.id: p for p in paper_repo.list_by_ids(co_cited_ids)}

            in_degree: dict[str, int] = defaultdict(int)
            out_degree: dict[str, int] = defaultdict(int)
            for e in internal_edges:
                out_degree[e.source_paper_id] += 1
                in_degree[e.target_paper_id] += 1

            all_node_ids = set(topic_ids_set)

            nodes = []
            for p in topic_papers:
                nodes.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "year": (
                            p.publication_date.year
                            if isinstance(p.publication_date, date)
                            else None
                        ),
                        "arxiv_id": p.arxiv_id,
                        "in_degree": in_degree.get(p.id, 0),
                        "out_degree": out_degree.get(p.id, 0),
                        "is_hub": in_degree.get(p.id, 0) >= 2,
                        "is_external": False,
                    }
                )

            for pid, count in co_cited:
                p = co_cited_papers.get(pid)
                nodes.append(
                    {
                        "id": pid,
                        "title": p.title if p else f"external-{pid[:8]}",
                        "year": (
                            p.publication_date.year
                            if p and isinstance(p.publication_date, date)
                            else None
                        ),
                        "arxiv_id": p.arxiv_id if p else None,
                        "in_degree": 0,
                        "out_degree": 0,
                        "is_hub": False,
                        "is_external": True,
                        "co_citation_count": count,
                    }
                )
                all_node_ids.add(pid)

            edges = [
                {"source": e.source_paper_id, "target": e.target_paper_id} for e in internal_edges
            ]
            for e in external_edges:
                if e.source_paper_id in all_node_ids and e.target_paper_id in all_node_ids:
                    edges.append(
                        {
                            "source": e.source_paper_id,
                            "target": e.target_paper_id,
                        }
                    )

            n_papers = len(nodes)
            max_edges = n_papers * (n_papers - 1) if n_papers > 1 else 1
            density = round(len(edges) / max_edges, 4) if max_edges else 0

            key_external = [
                {
                    "id": pid,
                    "title": (
                        co_cited_papers[pid].title
                        if pid in co_cited_papers
                        else f"external-{pid[:8]}"
                    ),
                    "co_citation_count": count,
                }
                for pid, count in co_cited
            ]

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_papers": n_papers,
                "internal_papers": len(topic_ids_set),
                "external_papers": len(co_cited),
                "total_edges": len(edges),
                "internal_edges": len(internal_edges),
                "density": density,
                "new_edges_synced": synced,
            },
            "key_external_papers": key_external,
        }

    def timeline(self, keyword: str, limit: int = 100) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(keyword, limit=limit)
            edges = CitationRepository(session).list_all()
            nodes = {p.id: p for p in papers}
            indegree: dict[str, int] = {p.id: 0 for p in papers}
            outdegree: dict[str, int] = {p.id: 0 for p in papers}
            for e in edges:
                if e.target_paper_id in nodes and e.source_paper_id in nodes:
                    indegree[e.target_paper_id] += 1
                    outdegree[e.source_paper_id] += 1
            pagerank = self._pagerank(nodes=list(nodes.keys()), edges=edges)
            items = []
            for p in papers:
                year = p.publication_date.year if isinstance(p.publication_date, date) else 1900
                pr = pagerank.get(p.id, 0.0)
                ind = indegree.get(p.id, 0)
                score = 0.65 * ind + 0.35 * pr * 100.0
                items.append(
                    {
                        "paper_id": p.id,
                        "title": p.title,
                        "year": year,
                        "indegree": ind,
                        "outdegree": outdegree.get(p.id, 0),
                        "pagerank": pr,
                        "seminal_score": score,
                        "why_seminal": (f"indegree={ind}, pagerank={pr:.4f}, score={score:.3f}"),
                    }
                )
        items.sort(
            key=lambda x: (
                x["year"],
                -x["indegree"],
                x["title"],
            )
        )
        seminal = sorted(
            items,
            key=lambda x: (-x["seminal_score"], x["year"]),
        )[:10]
        milestones = self._milestones_by_year(items)
        return {
            "keyword": keyword,
            "timeline": items,
            "seminal": seminal,
            "milestones": milestones,
        }

    def quality_metrics(self, keyword: str, limit: int = 120) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(keyword, limit=limit)
            paper_ids = [p.id for p in papers]
            edges = CitationRepository(session).list_for_paper_ids(paper_ids)
            node_set = set(paper_ids)
            internal_edges = [
                e for e in edges if e.source_paper_id in node_set and e.target_paper_id in node_set
            ]
            connected_nodes: set[str] = set()
            for e in internal_edges:
                connected_nodes.add(e.source_paper_id)
                connected_nodes.add(e.target_paper_id)
            with_pub = sum(1 for p in papers if p.publication_date is not None)
        n = max(len(paper_ids), 1)
        ie = len(internal_edges)
        return {
            "keyword": keyword,
            "node_count": len(paper_ids),
            "edge_count": ie,
            "density": ie / max(n * max(n - 1, 1), 1),
            "connected_node_ratio": (len(connected_nodes) / n),
            "publication_date_coverage": with_pub / n,
        }

    def weekly_evolution(self, keyword: str, limit: int = 160) -> dict:
        tl = self.timeline(keyword=keyword, limit=limit)
        by_year: dict[int, list[dict]] = defaultdict(list)
        for item in tl["timeline"]:
            by_year[item["year"]].append(item)
        year_buckets = []
        for year in sorted(by_year.keys())[-6:]:
            group = by_year[year]
            avg = sum(x["seminal_score"] for x in group) / max(len(group), 1)
            top_titles = [x["title"] for x in sorted(group, key=lambda t: -t["seminal_score"])[:3]]
            year_buckets.append(
                {
                    "year": year,
                    "paper_count": len(group),
                    "avg_seminal_score": avg,
                    "top_titles": top_titles,
                }
            )
        prompt = build_evolution_prompt(keyword=keyword, year_buckets=year_buckets)
        llm_result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(
            llm_result, stage="graph_evolution", prompt_digest=f"evolution:{keyword}"
        )
        summary = llm_result.parsed_json or {
            "trend_summary": "数据样本不足，建议增加领域样本后重试。",
            "phase_shift_signals": [],
            "next_week_focus": [],
        }
        return {
            "keyword": keyword,
            "year_buckets": year_buckets,
            "summary": summary,
        }

    def survey(self, keyword: str, limit: int = 120) -> dict:
        base = self.timeline(keyword=keyword, limit=limit)
        prompt = build_survey_prompt(keyword, base["milestones"], base["seminal"])
        result = self.llm.complete_json(
            prompt,
            stage="rag",
            model_override=self.settings.llm_model_skim,
        )
        self.llm.trace_result(result, stage="graph_survey", prompt_digest=f"survey:{keyword}")
        survey_obj = result.parsed_json or {
            "overview": "当前样本不足以生成高质量综述。",
            "stages": [],
            "reading_list": [x["title"] for x in base["seminal"][:5]],
            "open_questions": [],
        }
        return {
            "keyword": keyword,
            "summary": survey_obj,
            "milestones": base["milestones"],
            "seminal": base["seminal"],
        }

    def detect_research_gaps(
        self,
        keyword: str,
        limit: int = 120,
    ) -> dict:
        """分析引用网络的稀疏区域，识别研究空白"""
        tl = self.timeline(keyword=keyword, limit=limit)
        quality = self.quality_metrics(keyword=keyword, limit=limit)

        # 构造论文数据（含 indegree/outdegree/keywords）
        papers_data = []
        for item in tl["timeline"]:
            papers_data.append(
                {
                    "title": item["title"],
                    "year": item["year"],
                    "indegree": item["indegree"],
                    "outdegree": item["outdegree"],
                    "seminal_score": item["seminal_score"],
                    "keywords": [],
                    "abstract": "",
                }
            )

        # 补充 abstract 和 keywords
        with session_scope() as session:
            repo = PaperRepository(session)
            candidates = repo.full_text_candidates(keyword, limit=limit)
            paper_map = {p.title: p for p in candidates}
            for pd in papers_data:
                p = paper_map.get(pd["title"])
                if p:
                    pd["abstract"] = p.abstract[:400]
                    pd["keywords"] = (p.metadata_json or {}).get("keywords", [])

        # 计算孤立论文数（入度+出度=0）
        isolated = sum(
            1 for item in tl["timeline"] if item["indegree"] == 0 and item["outdegree"] == 0
        )

        network_stats = {
            "total_papers": quality["node_count"],
            "edge_count": quality["edge_count"],
            "density": quality["density"],
            "connected_ratio": quality["connected_node_ratio"],
            "isolated_count": isolated,
        }

        prompt = build_research_gaps_prompt(
            keyword=keyword,
            papers_data=papers_data,
            network_stats=network_stats,
        )
        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(result, stage="graph_research_gaps", prompt_digest=f"gaps:{keyword}")

        parsed = result.parsed_json or {
            "research_gaps": [],
            "method_comparison": {
                "dimensions": [],
                "methods": [],
                "underexplored_combinations": [],
            },
            "trend_analysis": {
                "hot_directions": [],
                "declining_areas": [],
                "emerging_opportunities": [],
            },
            "overall_summary": "数据不足，无法完成分析。",
        }

        return {
            "keyword": keyword,
            "network_stats": network_stats,
            "analysis": parsed,
        }

    def paper_wiki(self, paper_id: str) -> dict:
        tree = self.citation_tree(root_paper_id=paper_id, depth=2)

        # 1. 富化上下文收集（向量搜索 + 引用上下文 + PDF）
        ctx = self.context_gatherer.gather_paper_context(paper_id)
        p_title = ctx["paper"].get("title", "")
        p_abstract = ctx["paper"].get("abstract", "")
        p_arxiv = ctx["paper"].get("arxiv_id", "")
        analysis = ctx["paper"].get("analysis", "")

        # 2. Semantic Scholar 元数据
        scholar_meta: list[dict] = []
        try:
            all_titles = [p_title] + ctx.get("ancestor_titles", [])[:5]
            scholar_meta = self.scholar.fetch_batch_metadata(all_titles, max_papers=6)
        except Exception as exc:
            logger.warning("Scholar metadata fetch failed: %s", exc)

        # 3. LLM 生成结构化 wiki
        prompt = build_paper_wiki_prompt(
            title=p_title,
            abstract=p_abstract,
            analysis=analysis,
            related_papers=ctx.get("related_papers", [])[:10],
            ancestors=ctx.get("ancestor_titles", []),
            descendants=ctx.get("descendant_titles", []),
        )
        # 注入引用上下文 + PDF + Scholar 到 prompt
        extra_context = self._build_extra_context(
            citation_contexts=ctx.get("citation_contexts", []),
            pdf_excerpt=ctx.get("pdf_excerpt", ""),
            scholar_metadata=scholar_meta,
        )
        full_prompt = prompt + extra_context

        result = self.llm.complete_json(
            full_prompt,
            stage="rag",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(
            result,
            stage="wiki_paper",
            paper_id=paper_id,
            prompt_digest=f"paper_wiki:{p_title[:60]}",
        )
        wiki_content = result.parsed_json or {
            "summary": analysis or "暂无分析。",
            "contributions": [],
            "methodology": "",
            "significance": "",
            "limitations": [],
            "related_work_analysis": "",
            "reading_suggestions": [],
        }

        # 注入额外元数据供前端展示
        wiki_content["citation_contexts"] = ctx.get("citation_contexts", [])[:20]
        wiki_content["pdf_excerpts"] = (
            [{"title": p_title, "excerpt": ctx.get("pdf_excerpt", "")[:2000]}]
            if ctx.get("pdf_excerpt")
            else []
        )
        wiki_content["scholar_metadata"] = scholar_meta

        # 备用 markdown
        md_parts = [
            f"# {p_title}",
            f"\narXiv: {p_arxiv}",
            f"\n## 摘要\n\n{wiki_content.get('summary', '')}",
        ]
        if wiki_content.get("methodology"):
            md_parts.append(f"\n## 方法论\n\n{wiki_content['methodology']}")
        if wiki_content.get("significance"):
            md_parts.append(f"\n## 学术意义\n\n{wiki_content['significance']}")
        markdown = "\n".join(md_parts)

        return {
            "paper_id": paper_id,
            "title": p_title,
            "markdown": markdown,
            "wiki_content": wiki_content,
            "graph": tree,
        }

    def topic_wiki(
        self,
        keyword: str,
        limit: int = 120,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        def _progress(pct: float, msg: str):
            if progress_callback:
                progress_callback(msg, int(pct * 100), 100)

        # Phase 0: 并行收集数据
        _progress(0.05, "收集时间线和综述数据...")
        tl = self.timeline(keyword=keyword, limit=limit)
        survey_data = self.survey(keyword=keyword, limit=limit)

        _progress(0.15, "收集论文上下文和引用关系...")
        # Phase 1: 富化上下文（向量搜索 + 引用上下文 + PDF）
        ctx = self.context_gatherer.gather_topic_context(keyword, limit=limit)
        paper_contexts = ctx.get("paper_contexts", [])[:25]
        citation_contexts = ctx.get("citation_contexts", [])[:30]
        pdf_excerpts = ctx.get("pdf_excerpts", [])[:5]

        _progress(0.2, "联网补充高影响力论文...")
        external_meta = self._fetch_external_topic_metadata(keyword, max_results=8)
        external_contexts = _external_metadata_to_paper_context(
            external_meta,
            start_index=len(paper_contexts) + 1,
        )

        # Phase 2: 外部学术元数据增强
        local_scholar_meta: list[dict] = []
        try:
            top_titles = [s["title"] for s in tl.get("seminal", [])[:8] if s.get("title")]
            local_scholar_meta = self.scholar.fetch_batch_metadata(top_titles, max_papers=8)
        except Exception as exc:
            logger.warning("Scholar metadata fetch failed: %s", exc)
        scholar_meta = _merge_scholar_metadata(
            external_meta,
            local_scholar_meta,
            max_items=16,
        )
        source_contexts = paper_contexts + external_contexts[:8]
        enriched_tl = _merge_seminal_with_external(tl, external_meta, limit=12)

        _progress(0.25, "生成文章大纲...")
        # Phase 3: 多轮生成 — 先生成大纲
        outline_prompt = build_wiki_outline_prompt(
            keyword=keyword,
            paper_summaries=source_contexts,
            citation_contexts=citation_contexts,
            scholar_metadata=scholar_meta,
            pdf_excerpts=pdf_excerpts,
        )
        outline_result = self.llm.complete_json(
            outline_prompt,
            stage="rag",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )
        self.llm.trace_result(
            outline_result, stage="wiki_outline", prompt_digest=f"outline:{keyword}"
        )
        outline = outline_result.parsed_json or {
            "title": keyword,
            "outline": [],
            "total_sections": 0,
        }

        # Phase 4: 并行章节生成（直接输出 markdown 文本）
        all_sources_text = self._build_all_sources_text(
            source_contexts,
            citation_contexts,
            scholar_meta,
            pdf_excerpts,
        )
        sec_plans = outline.get("outline", [])[:5]
        if outline_result.is_pseudo or not sec_plans:
            sec_plans = _fallback_section_plans(keyword, source_contexts)
        _progress(0.35, f"并行生成 {len(sec_plans)} 个章节...")
        sections = self._generate_sections_parallel(
            keyword,
            sec_plans,
            all_sources_text,
        )
        sections = _sanitize_topic_sections(
            keyword=keyword,
            sections=sections,
            all_sources_text=all_sources_text,
        )

        _progress(0.75, "生成概述和总结...")
        # Phase 5: 生成概述（直接输出文本）+ 结构化汇总（JSON）
        # 5a: 文本概述
        section_titles = ", ".join(s.get("title", "") for s in sections)
        survey_overview = survey_data.get("summary", {}).get("overview", "")[:600]
        overview_sources = []
        for idx, paper in enumerate(source_contexts[:10], 1):
            title = paper.get("title") or "N/A"
            year = paper.get("year") or "?"
            abstract = (paper.get("abstract") or "")[:280]
            analysis = (paper.get("analysis") or "")[:220]
            overview_sources.append(
                f"[P{idx}] {title} ({year})\n摘要: {abstract}\n已有解析: {analysis}"
            )
        overview_prompt = (
            "你是世界顶级学术综述作者。"
            f"请为「{keyword}」主题撰写一段 300-500 字的概述，"
            "涵盖该主题的定义、重要性、核心思想和发展脉络。\n"
            "必须基于给定论文资料写，不要输出系统提示、provider、model 或 summary 字段。\n"
            "影响力判断要同时参考本地论文库和联网外部发现的高引用论文，"
            "不要默认本地库就是完整领域全集。\n"
            "不要泛泛而谈，要点名关键问题、方法谱系和可验证的论文证据。\n"
            "直接输出文本，不要用 JSON 或代码块包裹。\n\n"
            f"已有章节: {section_titles}\n"
            f"参考综述: {survey_overview}\n"
            f"论文资料:\n{chr(10).join(overview_sources)}\n"
        )
        overview_result = self.llm.summarize_text(
            overview_prompt,
            stage="wiki_overview",
            model_override=self.settings.llm_model_deep,
            max_tokens=2048,
        )
        self.llm.trace_result(
            overview_result,
            stage="wiki_overview",
            prompt_digest=f"overview:{keyword}",
        )
        overview_text = _sanitize_wiki_text(
            overview_result.content,
            keyword=keyword,
            min_chars=120,
            is_pseudo=overview_result.is_pseudo,
        )
        if not overview_text:
            overview_text = _fallback_topic_overview(
                keyword=keyword,
                paper_contexts=source_contexts,
                sections=sections,
                survey_data=survey_data,
                timeline=enriched_tl,
            )

        # 5b: 结构化汇总（key_findings + future_directions）
        summary_prompt = (
            "请只输出单个 JSON 对象，不要代码块。\n"
            f"根据以下「{keyword}」综述内容，提取关键发现和未来方向：\n"
            f"概述: {overview_text[:300]}\n"
            f"章节: {section_titles}\n"
            f"参考: {survey_overview[:300]}\n\n"
            f"外部高影响力论文: {', '.join(str(item.get('title', '')) for item in external_meta[:5])}\n\n"
            '输出: {"key_findings": ["发现1","发现2","发现3"],'
            ' "future_directions": ["方向1","方向2","方向3"],'
            ' "reading_list": ["论文1","论文2"]}'
        )
        summary_result = self.llm.complete_json(
            summary_prompt,
            stage="wiki_summary",
            model_override=self.settings.llm_model_deep,
            max_tokens=2048,
        )
        self.llm.trace_result(
            summary_result,
            stage="wiki_summary",
            prompt_digest=f"summary:{keyword}",
        )
        summary_data = summary_result.parsed_json or {}
        if summary_result.is_pseudo or not summary_data:
            summary_data = _fallback_topic_summary_data(
                keyword=keyword,
                sections=sections,
                paper_contexts=source_contexts,
            )

        # 组装最终 wiki_content
        wiki_content: dict = {
            "overview": overview_text,
            "sections": sections,
            "key_findings": summary_data.get("key_findings", []),
            "methodology_evolution": "",
            "future_directions": summary_data.get("future_directions", []),
            "reading_list": summary_data.get("reading_list", []),
            "citation_contexts": citation_contexts[:20],
            "pdf_excerpts": pdf_excerpts,
            "scholar_metadata": scholar_meta,
            "external_discovery": external_meta,
        }

        # 备用 markdown
        markdown = _topic_wiki_markdown(keyword, wiki_content)

        _progress(1.0, "Wiki 生成完成")
        return {
            "keyword": keyword,
            "markdown": markdown,
            "wiki_content": wiki_content,
            "timeline": enriched_tl,
            "survey": survey_data,
        }

    @staticmethod
    def _build_extra_context(
        *,
        citation_contexts: list[str],
        pdf_excerpt: str,
        scholar_metadata: list[dict],
    ) -> str:
        """拼装额外上下文注入到 paper wiki prompt"""
        parts: list[str] = []
        if citation_contexts:
            parts.append("\n## 引用关系上下文:")
            for i, c in enumerate(citation_contexts[:15], 1):
                parts.append(f"[C{i}] {c}")
        if pdf_excerpt:
            parts.append(f"\n## PDF 全文摘录（前 2000 字）:\n{pdf_excerpt[:2000]}")
        if scholar_metadata:
            parts.append("\n## Semantic Scholar 外部元数据:")
            for i, s in enumerate(scholar_metadata[:6], 1):
                parts.append(
                    f"[S{i}] {s.get('title', 'N/A')} "
                    f"({s.get('year', '?')}) "
                    f"引用数={s.get('citationCount', 'N/A')} "
                    f"Venue={s.get('venue', 'N/A')}"
                )
                if s.get("tldr"):
                    parts.append(f"  TLDR: {s['tldr'][:200]}")
        return "\n".join(parts)

    def _generate_one_section(
        self,
        keyword: str,
        sec_plan: dict,
        all_sources_text: str,
    ) -> dict:
        """生成单个 wiki 章节"""
        sec_title = sec_plan.get("section_title", "")
        sec_prompt = build_wiki_section_prompt(
            keyword=keyword,
            section_title=sec_title,
            key_points=sec_plan.get("key_points", []),
            source_refs=sec_plan.get("source_refs", []),
            all_sources_text=all_sources_text,
        )
        sec_result = self.llm.summarize_text(
            sec_prompt,
            stage="wiki_section",
            model_override=self.settings.llm_model_deep,
            max_tokens=4096,
        )
        self.llm.trace_result(
            sec_result,
            stage="wiki_section",
            prompt_digest=f"section:{sec_title[:60]}",
        )
        content = _sanitize_wiki_text(
            sec_result.content,
            keyword=keyword,
            min_chars=80,
            is_pseudo=sec_result.is_pseudo,
        )
        if not content:
            content = _fallback_section_content(
                keyword=keyword,
                section_title=sec_title or "主题章节",
                key_points=sec_plan.get("key_points", []),
                source_refs=sec_plan.get("source_refs", []),
                all_sources_text=all_sources_text,
            )
        return {
            "title": sec_title,
            "content": content,
            "key_insight": "",
        }

    def _generate_sections_parallel(
        self,
        keyword: str,
        sec_plans: list[dict],
        all_sources_text: str,
        max_workers: int = 3,
    ) -> list[dict]:
        """并行生成多个 wiki 章节"""
        if not sec_plans:
            return []
        sections: list[dict] = [{}] * len(sec_plans)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(
                    self._generate_one_section,
                    keyword,
                    plan,
                    all_sources_text,
                ): idx
                for idx, plan in enumerate(sec_plans)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    sections[idx] = future.result()
                    logger.info(
                        "wiki section %d/%d 完成: %s",
                        idx + 1,
                        len(sec_plans),
                        sections[idx].get("title", "")[:40],
                    )
                except Exception as exc:
                    logger.warning("wiki section %d 失败: %s", idx, exc)
                    sections[idx] = {
                        "title": sec_plans[idx].get("section_title", ""),
                        "content": "",
                        "key_insight": "",
                    }
        return sections

    @staticmethod
    def _build_all_sources_text(
        paper_contexts: list[dict],
        citation_contexts: list[str],
        scholar_metadata: list[dict],
        pdf_excerpts: list[dict],
    ) -> str:
        """拼装所有来源文本供逐章节生成使用"""
        parts: list[str] = []
        for i, p in enumerate(paper_contexts[:25], 1):
            parts.append(
                f"[P{i}] {p.get('title', 'N/A')} "
                f"({p.get('year', '?')})\n"
                f"Abstract: {p.get('abstract', '')[:400]}\n"
                f"Analysis: {p.get('analysis', '')[:400]}"
            )
        for i, c in enumerate(citation_contexts[:20], 1):
            parts.append(f"[C{i}] {c}")
        for i, s in enumerate(scholar_metadata[:8], 1):
            line = (
                f"[S{i}] {s.get('title', 'N/A')} "
                f"({s.get('year', '?')}) "
                f"citations={s.get('citationCount', '?')}"
            )
            if s.get("tldr"):
                line += f" TLDR: {s['tldr'][:200]}"
            parts.append(line)
        for i, ex in enumerate(pdf_excerpts[:5], 1):
            parts.append(
                f"[PDF{i}] {ex.get('title', 'N/A')}\nExcerpt: {ex.get('excerpt', '')[:500]}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
        """去版本号归一化: '2502.12082v2' -> '2502.12082'"""
        if not arxiv_id:
            return None
        return re.sub(r"v\d+$", "", arxiv_id.strip())

    @staticmethod
    def _title_to_id(title: str) -> str:
        normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
        return f"ss-{normalized[:48]}"

    @staticmethod
    def _pagerank(nodes: list[str], edges: list) -> dict[str, float]:
        if not nodes:
            return {}
        node_set = set(nodes)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for e in edges:
            if e.source_paper_id in node_set and e.target_paper_id in node_set:
                outgoing[e.source_paper_id].append(e.target_paper_id)
        n = len(nodes)
        rank = dict.fromkeys(nodes, 1.0 / n)
        damping = 0.85
        for _ in range(20):
            next_rank = dict.fromkeys(nodes, (1.0 - damping) / n)
            for node in nodes:
                refs = outgoing.get(node, [])
                if not refs:
                    continue
                share = rank[node] / len(refs)
                for dst in refs:
                    next_rank[dst] += damping * share
            rank = next_rank
        return rank

    @staticmethod
    def _milestones_by_year(
        items: list[dict],
    ) -> list[dict]:
        best_per_year: dict[int, dict] = {}
        for x in items:
            year = x["year"]
            if (
                year not in best_per_year
                or x["seminal_score"] > best_per_year[year]["seminal_score"]
            ):
                best_per_year[year] = x
        return [best_per_year[y] for y in sorted(best_per_year.keys())]
