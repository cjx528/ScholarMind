from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from packages.ai.compass_service import CompassService, _profile_signal_bundle, clamp_score
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import GeneratedContent, Paper, TopicSubscription
from packages.storage.repositories import GeneratedContentRepository, PaperRepository, TopicRepository

# BM25, RRF, and deep/quick/skip partitioning are adapted from
# ziwenhahaha/daily-paper-reader (MIT License), reshaped for ScholarMind's DB.

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "into",
    "using",
    "paper",
    "model",
    "method",
    "study",
    "based",
}


@dataclass
class QuerySpec:
    topic_id: str
    topic_name: str
    text: str
    kind: str
    sources: list[str]


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    return [token for token in tokens if len(token) > 1 and token not in STOPWORDS]


class BM25Index:
    def __init__(self, docs: list[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tokens = [_tokenize(doc) for doc in docs]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lengths) / max(1, len(self.doc_lengths))
        self.doc_freq: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            self.doc_freq.update(set(tokens))
        self.total_docs = max(1, len(self.doc_tokens))

    def scores(self, query: str) -> list[float]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return [0.0 for _ in self.doc_tokens]
        results: list[float] = []
        for tokens, length in zip(self.doc_tokens, self.doc_lengths, strict=False):
            tf = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                freq = tf.get(token, 0)
                if not freq:
                    continue
                df = self.doc_freq.get(token, 0)
                idf = math.log(1 + (self.total_docs - df + 0.5) / (df + 0.5))
                denom = freq + self.k1 * (1 - self.b + self.b * length / max(1.0, self.avgdl))
                score += idf * freq * (self.k1 + 1) / denom
            results.append(score)
        return results


def _rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, paper_id in enumerate(ranking, start=1):
            fused[paper_id] += 1.0 / (k + rank)
    return dict(fused)


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    max_score = max(scores.values()) or 1.0
    return {key: value / max_score for key, value in scores.items()}


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _paper_text(paper: dict[str, Any]) -> str:
    meta = paper.get("metadata") or {}
    return " ".join(
        [
            str(paper.get("title") or ""),
            str(paper.get("abstract") or ""),
            " ".join(str(x) for x in meta.get("keywords", []) if x),
            " ".join(str(x) for x in meta.get("categories", []) if x),
            " ".join(str(x) for x in meta.get("authors", []) if x),
        ]
    )


def _paper_source(paper: dict[str, Any]) -> str:
    meta = paper.get("metadata") or {}
    return str(meta.get("source") or paper.get("source") or "arxiv").lower()


def _freshness_score(value: date | None) -> int:
    if value is None:
        return 50
    age_days = max(0, (datetime.now(UTC).date() - value).days)
    if age_days <= 14:
        return 96
    if age_days <= 60:
        return 84
    if age_days <= 180:
        return 68
    if age_days <= 365:
        return 55
    return 42


def _topic_queries(topic: TopicSubscription) -> list[QuerySpec]:
    profile = topic.intent_profile_json or {}
    sources = [str(s).lower() for s in (topic.sources or ["arxiv"]) if str(s).strip()]
    specs: list[QuerySpec] = []

    def add(text: str, kind: str) -> None:
        cleaned = str(text or "").strip()
        if cleaned:
            specs.append(
                QuerySpec(
                    topic_id=topic.id,
                    topic_name=topic.name,
                    text=cleaned,
                    kind=kind,
                    sources=sources or ["arxiv"],
                )
            )

    for item in profile.get("keywords") or []:
        if isinstance(item, dict):
            add(str(item.get("query") or item.get("keyword") or ""), "keyword")
        else:
            add(str(item), "keyword")
    for item in profile.get("intent_queries") or []:
        if isinstance(item, dict):
            add(str(item.get("query") or item.get("intent") or item.get("text") or ""), "intent")
        else:
            add(str(item), "intent")
    add(topic.query, "topic")
    return specs


def _topic_payload(topic: TopicSubscription) -> dict[str, Any]:
    profile = topic.intent_profile_json or {}
    return {
        "id": topic.id,
        "name": topic.name,
        "sources": topic.sources or ["arxiv"],
        "keywords": profile.get("keywords") or [],
        "intent_queries": profile.get("intent_queries") or [],
    }


def _paper_to_dict(paper: Paper, compass_score: dict[str, Any]) -> dict[str, Any]:
    meta = paper.metadata_json or {}
    return {
        "id": paper.id,
        "title": paper.title,
        "abstract": paper.abstract or "",
        "arxiv_id": paper.arxiv_id,
        "source": paper.source,
        "source_id": paper.source_id,
        "doi": paper.doi,
        "publication_date": paper.publication_date,
        "publication_date_text": paper.publication_date.isoformat()
        if paper.publication_date
        else None,
        "created_at": paper.created_at.isoformat() if paper.created_at else None,
        "read_status": getattr(paper.read_status, "value", str(paper.read_status)),
        "favorited": paper.favorited,
        "metadata": meta,
        "embedding": paper.embedding or [],
        "profile_score": compass_score.get("final_score", 55),
        "profile_reason": (compass_score.get("recommendation") or {}).get("reason") or "",
        "profile_factors": (compass_score.get("recommendation") or {}).get("factors") or {},
    }


def _item_public_payload(item: dict[str, Any]) -> dict[str, Any]:
    paper = item["paper"]
    return {
        "paper": {
            "id": paper["id"],
            "title": paper["title"],
            "abstract": paper["abstract"][:900],
            "arxiv_id": paper.get("arxiv_id"),
            "source": paper.get("source"),
            "source_id": paper.get("source_id"),
            "doi": paper.get("doi"),
            "publication_date": paper.get("publication_date_text"),
            "read_status": paper.get("read_status"),
            "favorited": paper.get("favorited"),
        },
        "score": clamp_score(item.get("final_score"), 0),
        "zone": item.get("zone") or "",
        "tldr": item.get("tldr") or "",
        "reason": item.get("reason") or "",
        "skip_reason": item.get("skip_reason") or "",
        "matched_topics": item.get("matched_topics") or [],
        "scores": {
            "bm25": round(float(item.get("bm25_score") or 0), 4),
            "embedding": round(float(item.get("embedding_score") or 0), 4),
            "rrf": round(float(item.get("rrf_score") or 0), 4),
            "profile": clamp_score(item.get("profile_score"), 55),
            "freshness": clamp_score(item.get("freshness_score"), 50),
            "llm": item.get("llm_score"),
        },
    }


def _partition_items(items: list[dict[str, Any]], limit: int) -> dict[str, list[dict[str, Any]]]:
    sorted_items = sorted(items, key=lambda x: float(x.get("final_score") or 0), reverse=True)
    explicit = {"deep": [], "quick": [], "skip": []}
    for item in sorted_items:
        zone = item.get("zone")
        if zone in explicit:
            explicit[zone].append(item)

    deep_target = max(3, min(8, limit // 3 or 3))
    deep = explicit["deep"][:deep_target] or [
        item for item in sorted_items if float(item.get("final_score") or 0) >= 78
    ][:deep_target]
    deep_ids = {item["paper"]["id"] for item in deep}

    quick_pool = [item for item in sorted_items if item["paper"]["id"] not in deep_ids]
    quick = explicit["quick"][: max(0, limit - len(deep))]
    quick_ids = {item["paper"]["id"] for item in quick}
    if len(quick) < max(0, limit - len(deep)):
        quick.extend(
            item
            for item in quick_pool
            if item["paper"]["id"] not in quick_ids
            and float(item.get("final_score") or 0) >= 52
        )
    quick = quick[: max(0, limit - len(deep))]
    selected_ids = {item["paper"]["id"] for item in deep + quick}

    skipped = [
        item
        for item in sorted_items
        if item["paper"]["id"] not in selected_ids
    ][: max(10, min(30, limit))]
    for item in skipped:
        if not item.get("skip_reason"):
            item["skip_reason"] = "与当前主题或用户画像匹配度不足，先不进入今日阅读队列。"
    return {
        "deep": [_item_public_payload(item) for item in deep],
        "quick": [_item_public_payload(item) for item in quick],
        "skip": [_item_public_payload(item) for item in skipped],
    }


def _format_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 研究雷达 {result['generated_at'][:10]}",
        "",
        f"- 精读候选：{len(result['sections']['deep'])}",
        f"- 速读候选：{len(result['sections']['quick'])}",
        f"- 跳过记录：{len(result['sections']['skip'])}",
        "",
    ]
    for title, key in (("精读候选", "deep"), ("速读候选", "quick"), ("跳过原因", "skip")):
        lines.append(f"## {title}")
        for item in result["sections"][key]:
            paper = item["paper"]
            reason = item.get("reason") or item.get("skip_reason") or ""
            lines.append(f"- **{paper['title']}** ({item['score']})：{reason}")
        lines.append("")
    return "\n".join(lines)


class DailyRadarService:
    content_type = "daily_radar"

    def latest(self, limit: int = 30) -> dict[str, Any]:
        with session_scope() as session:
            row = session.execute(
                select(GeneratedContent)
                .where(GeneratedContent.content_type == self.content_type)
                .order_by(GeneratedContent.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return self._empty_result(limit=limit)
            metadata = row.metadata_json or {}
            result = dict(metadata.get("result") or {})
            if not result:
                result = self._empty_result(limit=limit)
            result["content_id"] = row.id
            result["title"] = row.title
            result["markdown"] = row.markdown
            return result

    def run(
        self,
        *,
        limit: int = 30,
        topic_ids: list[str] | None = None,
        use_llm: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        limit = max(5, min(80, int(limit or 30)))
        llm = LLMClient()
        compass = CompassService()
        profile = compass.get_profile()
        profile_signals = _profile_signal_bundle(profile)

        with session_scope() as session:
            topics = TopicRepository(session).list_topics(enabled_only=True)
            if topic_ids:
                allow = set(topic_ids)
                topics = [topic for topic in topics if topic.id in allow]
            topics = [topic for topic in topics if not getattr(topic, "paused", False)]
            query_specs = self._query_specs(topics, profile)
            topic_payloads = [_topic_payload(topic) for topic in topics]
            active_topic_ids = [topic.id for topic in topics]

            papers = PaperRepository(session).list_latest(limit=900)
            paper_rows: list[dict[str, Any]] = []
            for paper in papers:
                score = compass._score_paper_for_profile(paper, profile_signals)
                paper_rows.append(
                    _paper_to_dict(
                        paper,
                        {
                            "recommendation": score.recommendation,
                            "final_score": score.final_score,
                        },
                    )
                )

        if not paper_rows:
            return self._empty_result(limit=limit, topics=topic_payloads)

        items = self._rank_candidates(paper_rows, query_specs, llm=llm)
        if use_llm and items:
            self._llm_refine(items[: min(24, len(items))], llm=llm)
        sections = _partition_items(items, limit=limit)

        generated_at = datetime.now(UTC).isoformat()
        result = {
            "generated_at": generated_at,
            "content_id": None,
            "title": f"研究雷达 {generated_at[:10]}",
            "topics": topic_payloads,
            "summary": {
                "candidate_count": len(paper_rows),
                "ranked_count": len(items),
                "deep_count": len(sections["deep"]),
                "quick_count": len(sections["quick"]),
                "skip_count": len(sections["skip"]),
                "used_llm_refine": bool(use_llm),
            },
            "stages": [
                {"name": "BM25 召回", "count": len(items)},
                {"name": "Embedding 召回", "count": len([x for x in items if x.get("embedding_score")])},
                {"name": "RRF 融合", "count": len(items)},
                {"name": "Compass 画像重排", "count": len(items)},
                {"name": "LLM refine", "count": min(24, len(items)) if use_llm else 0},
                {"name": "精读/速读/跳过分区", "count": len(sections["deep"]) + len(sections["quick"])},
            ],
            "sections": sections,
        }
        result["markdown"] = _format_markdown(result)

        if persist:
            self._persist_result(result, topic_ids=active_topic_ids)
        return result

    def _empty_result(
        self,
        *,
        limit: int,
        topics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        return {
            "generated_at": now,
            "content_id": None,
            "title": f"研究雷达 {now[:10]}",
            "topics": topics or [],
            "summary": {
                "candidate_count": 0,
                "ranked_count": 0,
                "deep_count": 0,
                "quick_count": 0,
                "skip_count": 0,
                "used_llm_refine": False,
            },
            "stages": [],
            "sections": {"deep": [], "quick": [], "skip": []},
            "markdown": f"# 研究雷达\n\n当前论文库暂无可推荐论文，目标数量：{limit}。",
        }

    def _query_specs(
        self,
        topics: list[TopicSubscription],
        profile: dict[str, Any],
    ) -> list[QuerySpec]:
        specs: list[QuerySpec] = []
        for topic in topics:
            specs.extend(_topic_queries(topic))
        if specs:
            return specs
        fallback = " ".join(
            str(profile.get(key) or "")
            for key in ("interests", "researchDirections", "readingGoal")
        ).strip()
        if not fallback:
            fallback = "recent important papers aligned with my research"
        return [
            QuerySpec(
                topic_id="profile",
                topic_name="用户画像",
                text=fallback,
                kind="profile",
                sources=["arxiv", "openreview", "pdf", "web", "text"],
            )
        ]

    def _rank_candidates(
        self,
        papers: list[dict[str, Any]],
        query_specs: list[QuerySpec],
        *,
        llm: LLMClient,
    ) -> list[dict[str, Any]]:
        docs = [_paper_text(paper) for paper in papers]
        index = BM25Index(docs)
        bm25_raw: dict[str, float] = defaultdict(float)
        embedding_raw: dict[str, float] = defaultdict(float)
        rankings: list[list[str]] = []
        matched_topics: dict[str, dict[str, str]] = defaultdict(dict)

        for spec in query_specs:
            allowed = set(spec.sources or [])
            scores = index.scores(spec.text)
            ranked: list[tuple[str, float]] = []
            for paper, score in zip(papers, scores, strict=False):
                if allowed and _paper_source(paper) not in allowed:
                    continue
                if score <= 0:
                    continue
                paper_id = paper["id"]
                bm25_raw[paper_id] = max(bm25_raw[paper_id], score)
                matched_topics[paper_id][spec.topic_id] = spec.topic_name
                ranked.append((paper_id, score))
            ranked.sort(key=lambda row: row[1], reverse=True)
            rankings.append([paper_id for paper_id, _ in ranked[:160]])

        embedded_papers = [paper for paper in papers if paper.get("embedding")]
        for spec in query_specs[:8]:
            allowed = set(spec.sources or [])
            query_embedding = llm.embed_text(spec.text[:2000])
            ranked = []
            for paper in embedded_papers:
                if allowed and _paper_source(paper) not in allowed:
                    continue
                score = _cosine_similarity(query_embedding, paper.get("embedding"))
                if score <= 0:
                    continue
                paper_id = paper["id"]
                embedding_raw[paper_id] = max(embedding_raw[paper_id], score)
                matched_topics[paper_id][spec.topic_id] = spec.topic_name
                ranked.append((paper_id, score))
            ranked.sort(key=lambda row: row[1], reverse=True)
            rankings.append([paper_id for paper_id, _ in ranked[:160]])

        rrf_raw = _rrf_fuse(rankings)
        bm25 = _normalize_scores(dict(bm25_raw))
        embedding = _normalize_scores(dict(embedding_raw))
        rrf = _normalize_scores(rrf_raw)

        candidate_ids = set(rrf) or {paper["id"] for paper in papers[:120]}
        paper_map = {paper["id"]: paper for paper in papers}
        items: list[dict[str, Any]] = []
        for paper_id in candidate_ids:
            paper = paper_map.get(paper_id)
            if not paper:
                continue
            profile_score = clamp_score(paper.get("profile_score"), 55)
            freshness = _freshness_score(paper.get("publication_date"))
            bm25_score = bm25.get(paper_id, 0.0) * 100
            embedding_score = embedding.get(paper_id, 0.0) * 100
            rrf_score = rrf.get(paper_id, 0.0) * 100
            unread_bonus = 4 if paper.get("read_status") == "unread" else 0
            favorite_bonus = 3 if paper.get("favorited") else 0
            final_score = clamp_score(
                0.32 * rrf_score
                + 0.2 * bm25_score
                + 0.16 * embedding_score
                + 0.24 * profile_score
                + 0.08 * freshness
                + unread_bonus
                + favorite_bonus,
                55,
            )
            reason = paper.get("profile_reason") or "与主题订阅和用户画像有一定匹配。"
            tldr = self._fallback_tldr(paper)
            items.append(
                {
                    "paper": paper,
                    "final_score": final_score,
                    "bm25_score": bm25_score,
                    "embedding_score": embedding_score,
                    "rrf_score": rrf_score,
                    "profile_score": profile_score,
                    "freshness_score": freshness,
                    "reason": reason,
                    "tldr": tldr,
                    "matched_topics": [
                        {"id": key, "name": value}
                        for key, value in matched_topics.get(paper_id, {}).items()
                    ],
                }
            )
        items.sort(key=lambda item: float(item.get("final_score") or 0), reverse=True)
        return items[:240]

    def _fallback_tldr(self, paper: dict[str, Any]) -> str:
        abstract = re.sub(r"\s+", " ", paper.get("abstract") or "").strip()
        if not abstract:
            return "当前只有题名和元数据，建议先速读确认是否相关。"
        return abstract[:160] + ("..." if len(abstract) > 160 else "")

    def _llm_refine(self, items: list[dict[str, Any]], *, llm: LLMClient) -> None:
        payload = [
            {
                "paper_id": item["paper"]["id"],
                "title": item["paper"]["title"],
                "abstract": item["paper"]["abstract"][:1000],
                "score": item["final_score"],
                "matched_topics": item.get("matched_topics") or [],
            }
            for item in items
        ]
        prompt = (
            "你是论文推荐编辑。请根据候选论文判断今天应该精读、速读还是跳过。"
            "默认用中文输出。只返回 JSON："
            "{\"items\":[{\"paper_id\":\"...\",\"score\":0-100,"
            "\"zone\":\"deep|quick|skip\",\"tldr\":\"中文一句话\","
            "\"reason\":\"推荐或跳过理由\",\"skip_reason\":\"跳过时填写\"}]}。\n"
            f"候选论文：{json.dumps(payload, ensure_ascii=False)}"
        )
        result = llm.complete_json(prompt, stage="daily_radar_refine", max_tokens=4096, max_retries=1)
        llm.trace_result(result, stage="daily_radar_refine", prompt_digest=prompt[:500])
        parsed = result.parsed_json if isinstance(result.parsed_json, dict) else {}
        rows = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        by_id = {item["paper"]["id"]: item for item in items}
        for row in rows:
            if not isinstance(row, dict):
                continue
            paper_id = str(row.get("paper_id") or "")
            item = by_id.get(paper_id)
            if not item:
                continue
            llm_score = clamp_score(row.get("score"), item.get("final_score"))
            item["llm_score"] = llm_score
            item["final_score"] = clamp_score(0.65 * item["final_score"] + 0.35 * llm_score)
            zone = str(row.get("zone") or "").strip().lower()
            if zone in {"deep", "quick", "skip"}:
                item["zone"] = zone
            if str(row.get("tldr") or "").strip():
                item["tldr"] = str(row["tldr"]).strip()
            if str(row.get("reason") or "").strip():
                item["reason"] = str(row["reason"]).strip()
            if str(row.get("skip_reason") or "").strip():
                item["skip_reason"] = str(row["skip_reason"]).strip()

    def _persist_result(self, result: dict[str, Any], *, topic_ids: list[str]) -> None:
        with session_scope() as session:
            row = GeneratedContentRepository(session).create(
                content_type=self.content_type,
                title=result["title"],
                markdown=result["markdown"],
                keyword="daily_radar",
                metadata_json={"result": result},
            )
            result["content_id"] = row.id
            now = datetime.now(UTC)
            for topic_id in topic_ids:
                topic = session.get(TopicSubscription, topic_id)
                if topic is None:
                    continue
                topic.last_radar_at = now
                topic.last_radar_json = {
                    "content_id": row.id,
                    "generated_at": result["generated_at"],
                    "deep_count": len(result["sections"]["deep"]),
                    "quick_count": len(result["sections"]["quick"]),
                    "skip_count": len(result["sections"]["skip"]),
                }
