"""Topic library and paper ingest routes.
@author ScholarMind Team
"""

import asyncio
import logging
import re
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.deps import pipelines
from packages.domain.enums import ActionType
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import PaperCreate, ReferenceImportReq, SuggestKeywordsReq, TopicCreate, TopicUpdate
from packages.integrations.aggregator import ResultAggregator
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.registry import ChannelRegistry
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import ActionRepository, PaperRepository, TopicRepository

logger = logging.getLogger(__name__)

router = APIRouter()

_CS_ML_CATEGORIES = (
    "cs.LG",
    "cs.AI",
    "cs.CV",
    "cs.CL",
    "cs.IR",
    "cs.NE",
    "cs.RO",
    "cs.MM",
    "cs.SD",
    "cs.GR",
)
_SOCIAL_LEANING_CATEGORIES = {"cs.CY", "cs.SI", "econ.GN", "econ.TH", "q-fin.EC"}
_SEARCH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "using",
    "based",
    "paper",
    "papers",
}


class ArxivSelectedIngestReq(BaseModel):
    query: str
    arxiv_ids: list[str] = Field(default_factory=list)
    topic_id: str | None = None


class SearchSelectedCandidate(BaseModel):
    id: str
    source: str = "arxiv"
    source_id: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    primary_category: str | None = None
    publication_date: str | None = None
    venue: str | None = None
    url: str | None = None
    topic_id: str | None = None
    topic_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class SearchSelectedIngestReq(BaseModel):
    query: str
    candidates: list[SearchSelectedCandidate] = Field(default_factory=list)


def _base_arxiv_id(arxiv_id: str | None) -> str:
    return (arxiv_id or "").strip().split("v")[0]


def _date_ordinal(value: str | None) -> int:
    if not value:
        return 0
    try:
        return date.fromisoformat(str(value)).toordinal()
    except ValueError:
        return 0


def _normalize_preview_query(raw_query: str, cs_only: bool = True) -> tuple[str, list[str], list[str]]:
    query = raw_query.strip()
    lower = re.sub(r"\s+", " ", query.lower())
    suggestions: list[str] = []
    notes: list[str] = []

    if lower in {"continue learning", "continued learning", "continuous learning"}:
        query = '(all:"continual learning" OR all:"lifelong learning")'
        suggestions = ["continual learning", "lifelong learning"]
        notes.append("已将 continue learning 规范为机器学习常用术语 continual learning / lifelong learning。")
    elif lower == "continual learning":
        query = '(all:"continual learning" OR all:"lifelong learning")'
        suggestions = ["lifelong learning"]

    has_structured = bool(re.search(r"\b(all|ti|au|abs|cat|co|jr|rn|id):", query))
    if cs_only and "cat:" not in query:
        cat_expr = "(" + " OR ".join(f"cat:{cat}" for cat in _CS_ML_CATEGORIES) + ")"
        if has_structured:
            query = f"({query}) AND {cat_expr}"
        else:
            query = f"({query}) AND {cat_expr}" if query else cat_expr
        notes.append("已启用 CS/ML 类别优先过滤，降低社会学等非目标领域结果。")

    return query, suggestions, notes


def _query_terms(raw_query: str, suggestions: list[str]) -> list[str]:
    text = " ".join([raw_query, *suggestions]).lower()
    terms = [
        t
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9+\-_.]{2,}", text)
        if t not in _SEARCH_STOPWORDS
    ]
    if "continual" in terms and "learning" in terms:
        terms.extend(["continual learning", "lifelong learning"])
    return list(dict.fromkeys(terms))


def _topic_name_from_query(query: str) -> str:
    terms = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+\-]{1,}|[\u4e00-\u9fff]{2,}", query)
        if token.lower() not in _SEARCH_STOPWORDS
    ]
    if not terms:
        return "Unclassified Search"
    return " ".join(terms[:5]).strip().title()


def _topic_terms(topic) -> set[str]:
    if isinstance(topic, dict):
        profile = topic.get("intent_profile_json") or {}
        parts: list[str] = [topic.get("name", ""), topic.get("query", "")]
    else:
        profile = getattr(topic, "intent_profile_json", None) or {}
        parts = [getattr(topic, "name", ""), getattr(topic, "query", "")]
    for key in ("keywords", "intent_queries"):
        values = profile.get(key) or []
        for item in values:
            if isinstance(item, dict):
                parts.extend(str(value) for value in item.values())
            else:
                parts.append(str(item))
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+\-]{2,}|[\u4e00-\u9fff]{2,}", " ".join(parts))
        if token.lower() not in _SEARCH_STOPWORDS
    }


def _classify_candidate_topic(paper, topics: list, fallback_query: str) -> dict:
    text = " ".join(
        [
            paper.title or "",
            paper.abstract or "",
            " ".join(str(x) for x in (paper.metadata or {}).get("categories", []) or []),
        ]
    ).lower()
    best_topic = None
    best_score = 0
    for topic in topics:
        terms = _topic_terms(topic)
        if not terms:
            continue
        score = sum(1 for term in terms if term in text)
        if score > best_score:
            best_topic = topic
            best_score = score
    if best_topic and best_score > 0:
        return {
            "topic_id": best_topic.get("id") if isinstance(best_topic, dict) else best_topic.id,
            "topic_name": best_topic.get("name") if isinstance(best_topic, dict) else best_topic.name,
            "topic_confidence": min(95, 45 + best_score * 12),
            "topic_reason": "matched_existing_topic",
        }
    return {
        "topic_id": None,
        "topic_name": _topic_name_from_query(fallback_query),
        "topic_confidence": 40,
        "topic_reason": "created_from_search_query",
    }


def _candidate_score(paper, raw_query: str, suggestions: list[str]) -> tuple[int, list[str]]:
    title = (paper.title or "").lower()
    abstract = (paper.abstract or "").lower()
    categories = set((paper.metadata or {}).get("categories") or [])
    score = 0
    reasons: list[str] = []

    if categories & set(_CS_ML_CATEGORIES):
        score += 25
        reasons.append("CS/ML 分类匹配")
    if categories & _SOCIAL_LEANING_CATEGORIES:
        score -= 20
        reasons.append("包含社会/经济相关分类，已降权")

    for term in _query_terms(raw_query, suggestions):
        # Phrase terms should carry more weight than single terms.
        if " " in term:
            if term in title:
                score += 45
                reasons.append(f"标题包含 {term}")
            elif term in abstract:
                score += 25
                reasons.append(f"摘要包含 {term}")
            continue
        if term in title:
            score += 10
        elif term in abstract:
            score += 4

    if score >= 55:
        reasons.insert(0, "高相关")
    elif score >= 35:
        reasons.insert(0, "中等相关")
    else:
        reasons.insert(0, "待人工确认")
    return max(0, min(100, score)), reasons[:5]


def _paper_identity(paper: PaperCreate) -> str:
    if paper.source == "arxiv" or paper.arxiv_id:
        return _base_arxiv_id(paper.source_id or paper.arxiv_id)
    return paper.normalized_arxiv_id or paper.source_id or paper.arxiv_id or paper.doi or paper.title.lower()


def _preview_paper_dict(
    paper,
    existing_ids: set[str],
    raw_query: str,
    suggestions: list[str],
    topic_info: dict | None = None,
    sources: list[dict] | None = None,
) -> dict:
    metadata = paper.metadata or {}
    score, reasons = _candidate_score(paper, raw_query, suggestions)
    source = paper.source or metadata.get("source") or "arxiv"
    arxiv_id = paper.arxiv_id or (paper.source_id if source == "arxiv" else "") or ""
    source_id = paper.source_id or metadata.get("source_id") or arxiv_id or paper.doi
    identity = _paper_identity(paper)
    doi = paper.doi or metadata.get("doi")
    exists = identity in existing_ids or bool(doi and doi in existing_ids)
    topic_info = topic_info or {}
    return {
        "id": identity,
        "source": source,
        "source_id": source_id,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": metadata.get("authors") or [],
        "categories": metadata.get("categories") or [],
        "primary_category": metadata.get("primary_category"),
        "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
        "venue": metadata.get("venue"),
        "exists": exists,
        "match_score": score,
        "match_reasons": reasons,
        "url": metadata.get("url")
        or metadata.get("openalex_url")
        or metadata.get("dblp_url")
        or metadata.get("biorxiv_url")
        or (f"https://arxiv.org/abs/{_base_arxiv_id(arxiv_id)}" if source == "arxiv" and arxiv_id else None),
        "topic_id": topic_info.get("topic_id"),
        "topic_name": topic_info.get("topic_name"),
        "topic_confidence": topic_info.get("topic_confidence", 0),
        "topic_reason": topic_info.get("topic_reason", ""),
        "sources": sources or [{"channel": source}],
        "metadata": metadata,
    }


def _candidate_to_paper_create(candidate: SearchSelectedCandidate) -> PaperCreate:
    pub_date = None
    if candidate.publication_date:
        try:
            pub_date = date.fromisoformat(candidate.publication_date)
        except ValueError:
            pub_date = None
    source_id = candidate.source_id or candidate.arxiv_id or candidate.doi or candidate.id
    metadata = {
        **(candidate.metadata or {}),
        "authors": candidate.authors,
        "categories": candidate.categories,
        "primary_category": candidate.primary_category,
        "venue": candidate.venue,
        "url": candidate.url,
        "source": candidate.source,
        "source_id": source_id,
        "doi": candidate.doi,
    }
    return PaperCreate(
        source=candidate.source,
        source_id=source_id,
        doi=candidate.doi,
        arxiv_id=candidate.arxiv_id if candidate.source == "arxiv" else None,
        title=candidate.title,
        abstract=candidate.abstract or "",
        publication_date=pub_date,
        metadata=metadata,
    )


def _ensure_topic_for_candidate(
    topic_repo: TopicRepository,
    candidate: SearchSelectedCandidate,
    query: str,
) -> str | None:
    if candidate.topic_id and topic_repo.get_by_id(candidate.topic_id):
        return candidate.topic_id
    topic_name = (candidate.topic_name or _topic_name_from_query(query)).strip()
    if not topic_name:
        return None
    found = topic_repo.get_by_name(topic_name)
    if found:
        return found.id
    topic = topic_repo.upsert_topic(
        name=topic_name,
        query=query,
        enabled=False,
        paused=True,
        sources=[candidate.source],
        keywords=[query],
        intent_queries=[query],
        max_results_per_run=20,
        schedule_frequency="weekly",
        schedule_time_utc=21,
    )
    return topic.id


def _topic_dict(t, session=None) -> dict:
    profile = getattr(t, "intent_profile_json", None) or {}
    d = {
        "id": t.id,
        "name": t.name,
        "query": t.query,
        "enabled": t.enabled,
        "paused": getattr(t, "paused", False),
        "sources": getattr(t, "sources", None) or ["arxiv"],
        "keywords": profile.get("keywords") or [],
        "intent_queries": profile.get("intent_queries") or [],
        "max_results_per_run": t.max_results_per_run,
        "retry_limit": t.retry_limit,
        "schedule_frequency": getattr(t, "schedule_frequency", "daily"),
        "schedule_time_utc": getattr(t, "schedule_time_utc", 21),
        "enable_date_filter": getattr(t, "enable_date_filter", False),
        "date_filter_days": getattr(t, "date_filter_days", 7),
        "paper_count": 0,
        "last_run_at": None,
        "last_run_count": None,
    }
    if session is not None:
        from sqlalchemy import func, select

        from packages.storage.models import CollectionAction, PaperTopic

        # 论文计数
        cnt = session.scalar(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == t.id)
        )
        d["paper_count"] = cnt or 0
        # 最近一次行动
        last_action = session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id == t.id)
            .order_by(CollectionAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_action:
            d["last_run_at"] = (
                last_action.created_at.isoformat() if last_action.created_at else None
            )
            d["last_run_count"] = last_action.paper_count
    return d


@router.get("/topics")
def list_topics(enabled_only: bool = False) -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=enabled_only)
        return {"items": [_topic_dict(t, session) for t in topics]}


@router.post("/topics")
def upsert_topic(req: TopicCreate) -> dict:
    with session_scope() as session:
        topic = TopicRepository(session).upsert_topic(
            name=req.name,
            query=req.query,
            enabled=req.enabled,
            paused=req.paused,
            sources=req.sources,
            keywords=req.keywords,
            intent_queries=req.intent_queries,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
            schedule_frequency=req.schedule_frequency,
            schedule_time_utc=req.schedule_time_utc,
            enable_date_filter=req.enable_date_filter,
            date_filter_days=req.date_filter_days,
        )
        return _topic_dict(topic, session)


@router.post("/topics/suggest-keywords")
def suggest_keywords(req: SuggestKeywordsReq) -> dict:
    from packages.ai.keyword_service import KeywordService

    description = req.description
    if not description.strip():
        raise HTTPException(400, "description is required")
    suggestions = KeywordService().suggest(description.strip())
    return {"suggestions": suggestions}


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: str, req: TopicUpdate) -> dict:
    with session_scope() as session:
        try:
            topic = TopicRepository(session).update_topic(
                topic_id,
                query=req.query,
                enabled=req.enabled,
                paused=req.paused,
                sources=req.sources,
                keywords=req.keywords,
                intent_queries=req.intent_queries,
                max_results_per_run=req.max_results_per_run,
                retry_limit=req.retry_limit,
                schedule_frequency=req.schedule_frequency,
                schedule_time_utc=req.schedule_time_utc,
                enable_date_filter=req.enable_date_filter,
                date_filter_days=req.date_filter_days,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
        return _topic_dict(topic, session)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    with session_scope() as session:
        TopicRepository(session).delete_topic(topic_id)
        return {"deleted": topic_id}


@router.post("/topics/{topic_id}/fetch")
def manual_fetch_topic(topic_id: str) -> dict:
    """Manually fetch papers for one topic in the background."""
    from packages.ai.daily_runner import run_topic_ingest
    from packages.storage.models import TopicSubscription

    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            raise NotFoundError("主题不存在")
        topic_name = topic.name

    def _fetch_fn(progress_callback=None):
        # 分阶段报告进度：抓取 (0-50%) -> 处理 (50-100%)
        def _stage_callback(msg, cur, tot):
            # 将内部进度映射到 0-50% 范围
            progress_callback(f"抓取：{msg}", int(cur / tot * 50), 100)

        result = run_topic_ingest(topic_id, progress_callback=_stage_callback)

        if progress_callback:
            progress_callback("处理完成", 100, 100)
        return result

    task_id = global_tracker.submit(
        task_type="fetch",
        title=f"抓取：{topic_name[:30]}",
        fn=_fetch_fn,
        category="collection",
    )
    return {
        "status": "started",
        "task_id": task_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "message": f"「{topic_name}」抓取已在后台启动",
    }


@router.get("/topics/{topic_id}/fetch-status")
def fetch_topic_status(topic_id: str) -> dict:
    """查询手动抓取的执行状态 — 通过全局 tracker 查询"""
    # 兼容旧的轮询逻辑：从 tracker 中找匹配的 fetch 任务
    active = global_tracker.get_active()
    for t in active:
        if t["task_type"] == "fetch" and topic_id[:8] in t.get("task_id", ""):
            if t["finished"]:
                return {"status": "completed" if t["success"] else "failed", **t}
            return {"status": "running", **t}
    # 没找到活跃任务，看 DB 里的主题信息
    with session_scope() as session:
        from packages.storage.models import TopicSubscription

        topic = session.get(TopicSubscription, topic_id)
        topic_info = _topic_dict(topic, session) if topic else {}
    # 没找到任务时返回空字典
    return {"topic": topic_info}


# ---------- 摄入 ----------


def _clean_search_sources(sources: list[str] | None) -> list[str]:
    clean: list[str] = []
    for item in sources or ["arxiv"]:
        for part in str(item).split(","):
            name = part.strip().lower()
            if name and name not in clean:
                clean.append(name)
    return clean or ["arxiv"]


async def _fetch_search_source(
    source: str,
    *,
    raw_query: str,
    effective_query: str,
    fallback_query: str,
    max_results: int,
    sort_by: str,
    days_back: int,
) -> tuple[str, list[PaperCreate], dict]:
    try:
        if source == "arxiv":
            papers = await asyncio.to_thread(
                ArxivClient().fetch_latest,
                query=effective_query,
                max_results=max_results,
                sort_by=sort_by,
                days_back=days_back,
            )
        else:
            channel = ChannelRegistry.get(source)
            if not channel:
                return source, [], {"error": "channel not found"}
            papers = await asyncio.to_thread(channel.fetch, fallback_query or raw_query, max_results)
        for paper in papers:
            paper.source = paper.source or source
            if paper.source == "arxiv":
                paper.source_id = paper.source_id or paper.arxiv_id
        return source, papers, {"total": len(papers)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Search source %s failed: %s", source, exc)
        return source, [], {"error": str(exc)}


@router.post("/ingest/arxiv/preview")
def preview_arxiv(
    query: str,
    max_results: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="submittedDate", pattern="^(submittedDate|relevance|lastUpdatedDate)$"),
    days_back: int = Query(default=180, ge=0, le=3650),
    cs_only: bool = Query(default=True),
) -> dict:
    """只搜索 arXiv 候选论文，不写入本地库。"""
    if not query.strip():
        raise HTTPException(400, "query is required")

    effective_query, suggestions, notes = _normalize_preview_query(query, cs_only=cs_only)
    logger.info(
        "ArXiv preview: query=%r effective=%r max_results=%d sort=%s days_back=%d cs_only=%s",
        query,
        effective_query,
        max_results,
        sort_by,
        days_back,
        cs_only,
    )
    papers = ArxivClient().fetch_latest(
        query=effective_query,
        max_results=max_results,
        sort_by=sort_by,
        days_back=days_back,
    )
    arxiv_ids = [_base_arxiv_id(p.arxiv_id or p.source_id) for p in papers]
    with session_scope() as session:
        repo = PaperRepository(session)
        existing_ids = {
            _base_arxiv_id(x)
            for x in repo.list_existing_arxiv_ids(arxiv_ids)
        }
        existing_ids.update(repo.list_existing_dois([p.doi for p in papers if p.doi]))
    candidates = [
        _preview_paper_dict(paper, existing_ids, query, suggestions)
        for paper in papers
    ]
    candidates.sort(
        key=lambda item: (
            item["exists"],
            -int(item["match_score"]),
            -_date_ordinal(item["publication_date"]),
        )
    )
    return {
        "query": query,
        "effective_query": effective_query,
        "suggestions": suggestions,
        "notes": notes,
        "sort_by": sort_by,
        "days_back": days_back,
        "cs_only": cs_only,
        "candidates": candidates,
        "total": len(candidates),
        "existing_count": sum(1 for item in candidates if item["exists"]),
    }


@router.post("/ingest/search/preview")
async def preview_search(
    query: str,
    max_results: int = Query(default=20, ge=1, le=100),
    sources: list[str] = Query(default=["arxiv"]),
    sort_by: str = Query(default="submittedDate", pattern="^(submittedDate|relevance|lastUpdatedDate)$"),
    days_back: int = Query(default=180, ge=0, le=3650),
    cs_only: bool = Query(default=True),
) -> dict:
    """Search selected paper sources and return reviewable candidates without ingesting."""
    if not query.strip():
        raise HTTPException(400, "query is required")

    clean_sources = _clean_search_sources(sources)
    ChannelRegistry.register_default_channels()

    effective_query, suggestions, notes = _normalize_preview_query(query, cs_only=cs_only)
    fallback_query = " ".join(suggestions) if suggestions else query.strip()
    tasks = [
        _fetch_search_source(
            source,
            raw_query=query,
            effective_query=effective_query,
            fallback_query=fallback_query,
            max_results=max_results,
            sort_by=sort_by,
            days_back=days_back,
        )
        for source in clean_sources
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    aggregator = ResultAggregator()
    channel_stats: dict[str, dict[str, int | str]] = {}
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Search source task failed: %s", result)
            continue
        source, papers, meta = result
        channel_stats[source] = {"total": 0, "new": 0, "duplicates": 0}
        if "error" in meta:
            channel_stats[source]["error"] = str(meta["error"])
            continue
        channel_stats[source]["total"] = int(meta.get("total", 0))
        aggregator.add_results(source, papers, {"total": len(papers)})

    aggregated = aggregator.get_sorted_results()
    identity_ids = list({_paper_identity(item.paper) for item in aggregated if _paper_identity(item.paper)})

    with session_scope() as session:
        paper_repo = PaperRepository(session)
        topic_repo = TopicRepository(session)
        existing_ids = set(paper_repo.list_existing_arxiv_ids(identity_ids))
        existing_ids.update(paper_repo.list_existing_dois([item.paper.doi for item in aggregated if item.paper.doi]))
        topics = [
            {
                "id": topic.id,
                "name": topic.name,
                "query": topic.query,
                "intent_profile_json": topic.intent_profile_json or {},
            }
            for topic in topic_repo.list_topics(enabled_only=False)
        ]

    candidates = [
        _preview_paper_dict(
            item.paper,
            existing_ids,
            query,
            suggestions,
            topic_info=_classify_candidate_topic(item.paper, topics, query),
            sources=item.sources,
        )
        for item in aggregated
    ]
    candidates.sort(
        key=lambda item: (
            item["exists"],
            -int(item["match_score"]),
            -int(item.get("topic_confidence") or 0),
            -_date_ordinal(item["publication_date"]),
        )
    )

    existing_count = sum(1 for item in candidates if item["exists"])
    for source in channel_stats:
        source_total = int(channel_stats[source].get("total", 0))
        source_unique = sum(
            1 for item in candidates if any(s.get("channel") == source for s in item.get("sources", []))
        )
        source_existing = sum(
            1
            for item in candidates
            if item["exists"] and any(s.get("channel") == source for s in item.get("sources", []))
        )
        channel_stats[source]["duplicates"] = max(0, source_total - source_unique)
        channel_stats[source]["new"] = max(0, source_unique - source_existing)

    return {
        "query": query,
        "effective_query": effective_query,
        "suggestions": suggestions,
        "notes": notes,
        "sort_by": sort_by,
        "days_back": days_back,
        "cs_only": cs_only,
        "sources": clean_sources,
        "channel_stats": channel_stats,
        "candidates": candidates[:max_results],
        "total": len(candidates),
        "existing_count": existing_count,
    }


@router.post("/ingest/arxiv/selected")
def ingest_selected_arxiv(req: ArxivSelectedIngestReq) -> dict:
    """只入库用户确认选择的 arXiv ID。"""
    query = req.query.strip()
    requested_ids = [_base_arxiv_id(x) for x in req.arxiv_ids if _base_arxiv_id(x)]
    requested_ids = list(dict.fromkeys(requested_ids))
    if not query:
        raise HTTPException(400, "query is required")
    if not requested_ids:
        raise HTTPException(400, "arxiv_ids is required")
    if len(requested_ids) > 100:
        raise HTTPException(400, "最多一次入库 100 篇论文")

    logger.info("Selected ArXiv ingest: query=%r count=%d", query, len(requested_ids))
    fetched = ArxivClient().fetch_by_ids(requested_ids)
    paper_by_id = {_base_arxiv_id(p.arxiv_id or p.source_id): p for p in fetched}

    saved_ids: list[str] = []
    papers_info: list[dict] = []
    failed: list[dict] = []

    with session_scope() as session:
        repo = PaperRepository(session)
        action_repo = ActionRepository(session)
        existing_ids = {
            _base_arxiv_id(x)
            for x in repo.list_existing_arxiv_ids(requested_ids)
        }

        for arxiv_id in requested_ids:
            paper = paper_by_id.get(arxiv_id)
            if not paper:
                failed.append(
                    {
                        "arxiv_id": arxiv_id,
                        "title": "",
                        "status": "failed",
                        "error": "未能从 arXiv 获取元数据",
                    }
                )
                continue
            saved = pipelines._save_paper(repo, paper, req.topic_id, download_pdf=False)
            saved_id = str(saved.id)
            saved_ids.append(saved_id)
            papers_info.append(
                {
                    "id": saved_id,
                    "title": saved.title,
                    "arxiv_id": saved.arxiv_id,
                    "publication_date": saved.publication_date.isoformat()
                    if saved.publication_date
                    else None,
                    "status": "existing" if arxiv_id in existing_ids else "new",
                }
            )

        if saved_ids:
            action_repo.create_action(
                action_type=ActionType.manual_collect,
                title=f"手动确认收集：{query[:80]}",
                paper_ids=saved_ids,
                query=query,
                topic_id=req.topic_id,
            )

    return {
        "ingested": len(saved_ids),
        "new_count": sum(1 for item in papers_info if item["status"] == "new"),
        "existing_count": sum(1 for item in papers_info if item["status"] == "existing"),
        "papers": papers_info,
        "failed": failed,
    }


@router.post("/ingest/search/selected")
def ingest_selected_search(req: SearchSelectedIngestReq) -> dict:
    """Ingest user-confirmed search candidates and link each paper to its classified topic."""
    query = req.query.strip()
    candidates = req.candidates
    if not query:
        raise HTTPException(400, "query is required")
    if not candidates:
        raise HTTPException(400, "candidates is required")
    if len(candidates) > 100:
        raise HTTPException(400, "at most 100 papers can be ingested at once")

    papers = [_candidate_to_paper_create(candidate) for candidate in candidates]
    identities = [_paper_identity(paper) for paper in papers]
    saved_ids: list[str] = []
    papers_info: list[dict] = []
    failed: list[dict] = []
    topic_ids: set[str] = set()

    with session_scope() as session:
        repo = PaperRepository(session)
        topic_repo = TopicRepository(session)
        action_repo = ActionRepository(session)
        existing_ids = set(repo.list_existing_arxiv_ids(identities))
        existing_ids.update(repo.list_existing_dois([paper.doi for paper in papers if paper.doi]))

        for candidate, paper in zip(candidates, papers, strict=False):
            identity = _paper_identity(paper)
            try:
                topic_id = _ensure_topic_for_candidate(topic_repo, candidate, query)
                if topic_id:
                    topic_ids.add(topic_id)
                saved = pipelines._save_paper(repo, paper, topic_id, download_pdf=False)
                saved_id = str(saved.id)
                saved_ids.append(saved_id)
                papers_info.append(
                    {
                        "id": saved_id,
                        "title": saved.title,
                        "arxiv_id": saved.arxiv_id,
                        "source": candidate.source,
                        "publication_date": saved.publication_date.isoformat()
                        if saved.publication_date
                        else None,
                        "status": "existing"
                        if identity in existing_ids or bool(paper.doi and paper.doi in existing_ids)
                        else "new",
                        "topic_id": topic_id,
                        "topic_name": candidate.topic_name,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Selected search ingest failed for %s: %s", identity, exc)
                failed.append(
                    {
                        "id": candidate.id,
                        "title": candidate.title,
                        "source": candidate.source,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        if saved_ids:
            action_repo.create_action(
                action_type=ActionType.manual_collect,
                title=f"Search collect: {query[:80]}",
                paper_ids=saved_ids,
                query=query,
                topic_id=next(iter(topic_ids)) if len(topic_ids) == 1 else None,
            )

    return {
        "ingested": len(saved_ids),
        "new_count": sum(1 for item in papers_info if item["status"] == "new"),
        "existing_count": sum(1 for item in papers_info if item["status"] == "existing"),
        "papers": papers_info,
        "failed": failed,
    }


@router.post("/ingest/arxiv")
def ingest_arxiv(
    query: str,
    max_results: int = Query(default=20, ge=1, le=200),
    topic_id: str | None = None,
    sort_by: str = Query(
        default="submittedDate", pattern="^(submittedDate|relevance|lastUpdatedDate)$"
    ),
    days_back: int = Query(
        default=0,
        ge=0,
        le=3650,
        description="只检索最近 N 天提交的论文，默认 0 = 不限日期（历史关键词搜索）",
    ),
) -> dict:
    logger.info(
        "ArXiv ingest: query=%r max_results=%d sort=%s days_back=%d",
        query,
        max_results,
        sort_by,
        days_back,
    )
    count, inserted_ids, _ = pipelines.ingest_arxiv(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        sort_by=sort_by,
        days_back=days_back,
    )
    # 查询插入论文的基本信息
    papers_info: list[dict] = []
    if inserted_ids:
        with session_scope() as session:
            repo = PaperRepository(session)
            for pid in inserted_ids[:50]:
                try:
                    p = repo.get_by_id(UUID(pid))
                    papers_info.append(
                        {
                            "id": p.id,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "publication_date": p.publication_date.isoformat()
                            if p.publication_date
                            else None,
                        }
                    )
                except Exception:
                    pass
    return {"ingested": count, "papers": papers_info}


@router.post("/ingest/references")
def ingest_references(body: ReferenceImportReq) -> dict:
    """一键导入参考文献 — 返回 task_id 用于轮询进度"""
    from packages.ai.pipelines import ReferenceImporter

    importer = ReferenceImporter()
    task_id = importer.start_import(
        source_paper_id=body.source_paper_id,
        source_paper_title=body.source_paper_title,
        entries=[dict(e) for e in body.entries],
        topic_ids=body.topic_ids,
    )
    return {"task_id": task_id, "total": len(body.entries)}


@router.get("/ingest/references/status/{task_id}")
def ingest_references_status(task_id: str) -> dict:
    """查询参考文献导入任务进度"""
    from packages.domain.task_tracker import global_tracker

    task = global_tracker.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


# ---------- 统计 ----------


@router.get("/topics/stats")
def topic_stats() -> dict:
    """主题维度统计（30s 缓存）"""
    from apps.api.deps import cache

    cached = cache.get("topic_stats")
    if cached is not None:
        return cached
    with session_scope() as session:
        result = PaperRepository(session).topic_stats()
    cache.set("topic_stats", result, ttl=30)
    return result


@router.get("/topics/distribution")
def paper_distribution() -> dict:
    """论文分布统计：年份分布 + 来源分布（30s 缓存）"""
    from apps.api.deps import cache

    cached = cache.get("paper_distribution")
    if cached is not None:
        return cached
    with session_scope() as session:
        result = PaperRepository(session).paper_distribution_stats()
    cache.set("paper_distribution", result, ttl=30)
    return result
