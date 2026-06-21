"""论文管理路由
@author ScholarMind Team
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from apps.api.deps import cache, paper_list_response, rag_service
from packages.config import get_settings
from packages.domain.schemas import AIExplainReq, PaperAskRequest, PaperAskResponse
from packages.storage.models import AnalysisReport
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

# 全局 HTTP 客户端复用（避免每次请求创建新客户端）
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """获取或创建全局 HTTP 客户端"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    return _http_client


router = APIRouter()


def _remove_local_pdf(pdf_path: str | None) -> tuple[bool, str | None]:
    if not pdf_path:
        return False, None
    try:
        root = get_settings().pdf_storage_root.expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        root = root.resolve()

        target = Path(pdf_path).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target
        target = target.resolve()

        if target != root and root not in target.parents:
            return False, "PDF path is outside PDF_STORAGE_ROOT"
        if not target.exists():
            return False, None
        if not target.is_file():
            return False, "PDF path is not a file"
        target.unlink()
        return True, None
    except OSError as exc:
        return False, str(exc)


def _valid_arxiv_id(arxiv_id: str | None) -> bool:
    return bool(arxiv_id and not arxiv_id.startswith("ss-") and ":" not in arxiv_id)


def _normalize_title_for_match(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _title_similarity(a: str | None, b: str | None) -> float:
    left = _normalize_title_for_match(a)
    right = _normalize_title_for_match(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.92
    return SequenceMatcher(None, left, right).ratio()


def _find_arxiv_match_by_title(title: str):
    from packages.integrations.arxiv_client import ArxivClient

    clean_title = " ".join((title or "").split())
    if not clean_title:
        return None
    client = ArxivClient()
    quoted = clean_title.replace('"', "")
    queries = [f'ti:"{quoted}"', f'"{quoted}"', clean_title]
    best = None
    best_score = 0.0
    for query in queries:
        try:
            candidates = client.fetch_latest(query, max_results=5, sort_by="relevance")
        except Exception:
            continue
        for candidate in candidates:
            score = _title_similarity(title, candidate.title)
            if score > best_score:
                best = candidate
                best_score = score
        if best_score >= 0.88:
            return best
    return best if best_score >= 0.82 else None


@router.get("/papers/folder-stats")
def paper_folder_stats() -> dict:
    """论文文件夹统计（30s 缓存）"""
    cached = cache.get("folder_stats")
    if cached is not None:
        return cached
    with session_scope() as session:
        repo = PaperRepository(session)
        result = repo.folder_stats()
    cache.set("folder_stats", result, ttl=30)
    return result


@router.get("/papers/latest")
def latest(
    limit: int = Query(default=50, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    folder: str | None = Query(default=None),
    date: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    category: str | None = Query(default=None),
    tag_ids: list[str] | None = Query(default=None),
) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        papers, total = repo.list_paginated(
            page=page,
            page_size=page_size,
            folder=folder,
            topic_id=topic_id,
            status=status,
            date_str=date,
            search=search.strip() if search else None,
            sort_by=sort_by
            if sort_by in ("created_at", "publication_date", "title")
            else "created_at",
            sort_order=sort_order if sort_order in ("asc", "desc") else "desc",
            category=category,
            tag_ids=tag_ids,
        )
        resp = paper_list_response(papers, repo)
        resp["total"] = total
        resp["page"] = page
        resp["page_size"] = page_size
        resp["total_pages"] = max(1, (total + page_size - 1) // page_size)
        return resp


@router.get("/papers/recommended")
def recommended_papers(top_k: int = Query(default=10, ge=1, le=50)) -> dict:
    from packages.ai.compass_service import CompassService

    return CompassService().recommend_library(top_k=top_k)


@router.post("/papers/search-multi")
async def search_multi(
    query: str,
    channels: list[str] = Query(default=["arxiv"]),
    max_results_per_channel: int = Query(default=50, ge=1, le=100),
    topic_id: str | None = Query(default=None),
) -> dict:
    """多渠道并行搜索论文"""
    import asyncio
    import logging

    from packages.integrations.aggregator import ResultAggregator
    from packages.integrations.registry import ChannelRegistry

    logger = logging.getLogger(__name__)

    ChannelRegistry.register_default_channels()

    async def fetch_channel(ch: str) -> tuple[str, list, dict]:
        try:
            channel = ChannelRegistry.get(ch)
            if not channel:
                return ch, [], {"error": "channel not found"}
            papers = await asyncio.to_thread(channel.fetch, query, max_results_per_channel)
            return ch, papers, {"total": len(papers)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Channel %s failed: %s", ch, exc)
            return ch, [], {"error": str(exc)}

    tasks = [fetch_channel(ch) for ch in channels]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    aggregator = ResultAggregator()
    channel_stats: dict[str, dict[str, int | str]] = {}

    for result in results:
        if isinstance(result, Exception):
            logger.error("Channel task failed: %s", result)
            continue
        ch, papers, meta = result
        channel_stats[ch] = {"total": 0, "new": 0, "duplicates": 0}
        if "error" in meta:
            channel_stats[ch]["error"] = meta["error"]
        else:
            channel_stats[ch]["total"] = meta.get("total", 0)
            aggregator.add_results(ch, papers, meta)

    aggregated = aggregator.get_sorted_results()

    return {
        "papers": [
            {
                "id": f"temp-{i}",
                "title": r.paper.title,
                "authors": r.paper.metadata.get("authors", []),
                "year": r.paper.publication_date.year if r.paper.publication_date else None,
                "venue": r.paper.metadata.get("venue"),
                "abstract": r.paper.abstract,
                "sources": r.sources,
            }
            for i, r in enumerate(aggregated)
        ],
        "channel_stats": channel_stats,
    }


@router.get("/papers/suggest-channels")
def suggest_channels(query: str) -> dict:
    """根据关键词推荐合适的渠道"""
    from packages.integrations.registry import ChannelRegistry
    from packages.worker.smart_router import suggest_channels as get_suggestion

    ChannelRegistry.register_default_channels()
    available = ChannelRegistry.list_channels()

    recommended, alternatives, reasoning = get_suggestion(query, available)

    return {
        "recommended": recommended,
        "alternatives": alternatives,
        "reasoning": reasoning,
    }


@router.post("/papers/venues/enrich")
def enrich_paper_venues(limit: int = Query(default=200, ge=1, le=500)) -> dict:
    """Backfill venue/conference hints from arXiv metadata for existing papers."""
    from packages.integrations.arxiv_client import ArxivClient

    with session_scope() as session:
        repo = PaperRepository(session)
        papers = [p for p in repo.list_latest(limit=limit) if p.arxiv_id and not p.arxiv_id.startswith("ss-")]
        arxiv_ids = [p.arxiv_id for p in papers]

    if not arxiv_ids:
        return {"total": 0, "updated": 0, "items": []}

    fetched = ArxivClient().fetch_by_ids(arxiv_ids)
    fetched_by_id = {p.arxiv_id.split("v")[0]: p for p in fetched if p.arxiv_id}
    updated = []
    with session_scope() as session:
        repo = PaperRepository(session)
        for arxiv_id in arxiv_ids:
            fetched_paper = fetched_by_id.get(arxiv_id.split("v")[0])
            if not fetched_paper:
                continue
            paper = repo.upsert_paper(fetched_paper)
            meta = paper.metadata_json or {}
            updated.append(
                {
                    "id": str(paper.id),
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "venue": meta.get("venue"),
                    "venue_type": meta.get("venue_type"),
                    "venue_confidence": meta.get("venue_confidence"),
                    "venue_source": meta.get("venue_source"),
                }
            )

    cache.invalidate("folder_stats")
    return {"total": len(arxiv_ids), "updated": len(updated), "items": updated}


@router.get("/papers/proxy-arxiv-pdf/{arxiv_id:path}")
async def proxy_arxiv_pdf(arxiv_id: str):
    """代理访问 arXiv PDF（解决 CORS 问题）"""

    # 清理 arxiv_id（移除版本号）
    clean_id = arxiv_id.split("v")[0]
    arxiv_url = f"https://arxiv.org/pdf/{clean_id}.pdf"

    try:
        # 使用后端服务器访问 arXiv（绕过 CORS）
        client = _get_http_client()
        response = await client.get(arxiv_url, follow_redirects=True)

        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"arXiv 论文不存在：{clean_id}")

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"arXiv 访问失败：{response.status_code}")

        # 返回 PDF 内容
        from fastapi.responses import Response

        return Response(
            content=response.content,
            media_type="application/pdf",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f'inline; filename="{clean_id}.pdf"',
                "Cache-Control": "public, max-age=3600",
            },
        )
    except httpx.TimeoutException as err:
        raise HTTPException(status_code=504, detail="arXiv 请求超时") from err
    except httpx.RequestError as exc:
        raise HTTPException(status_code=500, detail=f"arXiv 访问失败：{str(exc)}") from exc


@router.get("/papers/{paper_id}")
def paper_detail(paper_id: UUID) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        topic_map = repo.get_topic_names_for_papers([str(p.id)])
        tag_map = repo.get_tags_for_papers([str(p.id)])
        # 查询已有分析报告
        from sqlalchemy import select as _sel

        from packages.storage.models import AnalysisReport as AR

        ar = session.execute(_sel(AR).where(AR.paper_id == str(p.id))).scalar_one_or_none()
        skim_data = None
        deep_data = None
        if ar:
            if ar.summary_md:
                skim_data = {
                    "summary_md": ar.summary_md,
                    "skim_score": ar.skim_score,
                    "key_insights": ar.key_insights or {},
                }
            if ar.deep_dive_md:
                deep_data = {
                    "deep_dive_md": ar.deep_dive_md,
                    "key_insights": ar.key_insights or {},
                }
        return {
            "id": str(p.id),
            "title": p.title,
            "arxiv_id": p.arxiv_id,
            "abstract": p.abstract,
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "read_status": p.read_status.value,
            "pdf_path": p.pdf_path,
            "favorited": getattr(p, "favorited", False),
            "categories": (p.metadata_json or {}).get("categories", []),
            "authors": (p.metadata_json or {}).get("authors", []),
            "venue": (p.metadata_json or {}).get("venue"),
            "venue_type": (p.metadata_json or {}).get("venue_type"),
            "venue_confidence": (p.metadata_json or {}).get("venue_confidence"),
            "venue_source": (p.metadata_json or {}).get("venue_source"),
            "source_type": (p.metadata_json or {}).get("source"),
            "keywords": (p.metadata_json or {}).get("keywords", []),
            "title_zh": (p.metadata_json or {}).get("title_zh", ""),
            "abstract_zh": (p.metadata_json or {}).get("abstract_zh", ""),
            "topics": topic_map.get(str(p.id), []),
            "tags": tag_map.get(str(p.id), []),
            "metadata": p.metadata_json,
            "has_embedding": p.embedding is not None,
            "skim_report": skim_data,
            "deep_report": deep_data,
        }


@router.delete("/papers/{paper_id}")
def delete_paper(paper_id: UUID) -> dict:
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            deleted = repo.delete_paper(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    pdf_removed, pdf_error = _remove_local_pdf(deleted.get("pdf_path"))
    cache.invalidate("folder_stats")
    return {
        "deleted": deleted["id"],
        "title": deleted["title"],
        "arxiv_id": deleted["arxiv_id"],
        "pdf_removed": pdf_removed,
        "pdf_cleanup_error": pdf_error,
        "related": deleted.get("related", {}),
    }


@router.patch("/papers/{paper_id}/favorite")
def toggle_favorite(paper_id: UUID) -> dict:
    """切换论文收藏状态"""
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            p = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        current = getattr(p, "favorited", False)
        p.favorited = not current
        session.commit()
        cache.invalidate("folder_stats")
        return {"id": str(p.id), "favorited": p.favorited}


# ---------- PDF 服务 ----------


@router.post("/papers/{paper_id}/download-pdf")
def download_paper_pdf(paper_id: UUID) -> dict:
    """下载论文 PDF：优先 arXiv，其次 OpenReview 原文，再按标题匹配 arXiv。"""
    from packages.integrations.arxiv_client import ArxivClient
    from packages.integrations.openreview_client import OpenReviewClient

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if paper.pdf_path and Path(paper.pdf_path).exists():
            return {"status": "exists", "pdf_path": paper.pdf_path}
        metadata = dict(paper.metadata_json or {})
        errors: list[str] = []

        if _valid_arxiv_id(paper.arxiv_id):
            try:
                pdf_path = ArxivClient().download_pdf(paper.arxiv_id)
                repo.set_pdf_path(paper_id, pdf_path)
                return {"status": "downloaded", "pdf_path": pdf_path, "source": "arxiv"}
            except Exception as exc:
                errors.append(f"arXiv 下载失败: {exc}")

        source = str(metadata.get("source") or "").lower()
        openreview_id = (
            str(metadata.get("source_id") or metadata.get("forum") or metadata.get("openreview_id") or "")
            or (paper.arxiv_id.removeprefix("openreview:") if paper.arxiv_id else "")
        ).strip()
        if source == "openreview" or (paper.arxiv_id or "").startswith("openreview:"):
            try:
                pdf_path = OpenReviewClient().download_pdf(
                    openreview_id,
                    pdf_url=str(metadata.get("pdf_url") or ""),
                )
                repo.set_pdf_path(paper_id, pdf_path)
                return {"status": "downloaded", "pdf_path": pdf_path, "source": "openreview"}
            except Exception as exc:
                errors.append(f"OpenReview PDF 下载失败: {exc}")

        arxiv_match = _find_arxiv_match_by_title(paper.title)
        if arxiv_match and arxiv_match.arxiv_id:
            try:
                pdf_path = ArxivClient().download_pdf(arxiv_match.arxiv_id)
                repo.set_pdf_path(paper_id, pdf_path)
                metadata["arxiv_pdf_id"] = arxiv_match.arxiv_id
                metadata["arxiv_pdf_match_title"] = arxiv_match.title
                paper.metadata_json = metadata
                return {
                    "status": "downloaded",
                    "pdf_path": pdf_path,
                    "source": "arxiv_title_match",
                    "arxiv_id": arxiv_match.arxiv_id,
                }
            except Exception as exc:
                errors.append(f"arXiv 标题匹配下载失败: {exc}")

        detail = "；".join(errors) if errors else "该论文没有可下载 PDF，且未在 arXiv 找到高置信匹配"
        raise HTTPException(status_code=400, detail=detail)


@router.get("/papers/{paper_id}/pdf")
def serve_paper_pdf(paper_id: UUID) -> FileResponse:
    """提供论文 PDF 文件下载/预览"""
    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        pdf_path = paper.pdf_path
    if not pdf_path:
        raise HTTPException(status_code=404, detail="论文没有 PDF 文件")
    full_path = Path(pdf_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        headers={"Access-Control-Allow-Origin": "*"},
    )



def _clip_context(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n...[已截断]"


def _json_context(value: object, limit: int) -> str:
    try:
        return _clip_context(json.dumps(value, ensure_ascii=False, indent=2), limit)
    except TypeError:
        return _clip_context(str(value), limit)


def _extract_pdf_page_context(pdf_path: str | None, page_number: int | None) -> str:
    if not pdf_path:
        return ""
    full_path = Path(pdf_path)
    if not full_path.exists():
        return ""
    try:
        import fitz

        doc = fitz.open(str(full_path))
        try:
            if len(doc) == 0:
                return ""
            if page_number and page_number > 0:
                center = min(max(page_number - 1, 0), len(doc) - 1)
                start = max(0, center - 1)
                end = min(len(doc), center + 2)
            else:
                start = 0
                end = min(len(doc), 3)

            chunks = []
            for idx in range(start, end):
                text = doc.load_page(idx).get_text("text").strip()
                if text:
                    chunks.append(f"第 {idx + 1} 页:\n{_clip_context(text, 2400)}")
            return _clip_context("\n\n".join(chunks), 6000)
        finally:
            doc.close()
    except Exception:
        return ""


@router.post("/papers/{paper_id}/ask", response_model=PaperAskResponse)
def ask_paper(paper_id: UUID, body: PaperAskRequest) -> PaperAskResponse:
    """围绕单篇论文、选中文本和已有解析结果进行问答。"""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    requested_scope = set(body.analysis_scope or ["skim", "deep", "reasoning"])
    context_parts: list[tuple[str, str]] = []
    used_context: list[str] = []

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        metadata = paper.metadata_json or {}
        report = session.execute(
            select(AnalysisReport).where(AnalysisReport.paper_id == str(paper.id))
        ).scalar_one_or_none()

        if body.selected_text and body.selected_text.strip():
            context_parts.append(("selected_text", _clip_context(body.selected_text, 3000)))
            used_context.append("selected_text")

        paper_meta = "\n".join(
            [
                f"标题: {paper.title}",
                f"中文标题: {metadata.get('title_zh') or ''}",
                f"摘要: {_clip_context(paper.abstract, 2600)}",
                f"中文摘要: {_clip_context(metadata.get('abstract_zh'), 1800)}",
            ]
        ).strip()
        context_parts.append(("paper_meta", paper_meta))
        used_context.append("paper_meta")

        if report and report.summary_md and "skim" in requested_scope:
            context_parts.append(("skim", _clip_context(report.summary_md, 2600)))
            used_context.append("skim")
        if report and report.deep_dive_md and "deep" in requested_scope:
            context_parts.append(("deep", _clip_context(report.deep_dive_md, 3600)))
            used_context.append("deep")

        reasoning = metadata.get("reasoning_chain")
        if reasoning and "reasoning" in requested_scope:
            context_parts.append(("reasoning", _json_context(reasoning, 3600)))
            used_context.append("reasoning")

        pdf_path = paper.pdf_path

    page_context = _extract_pdf_page_context(pdf_path, body.page_number)
    if page_context:
        context_parts.append(("pdf_page", page_context))
        used_context.append("pdf_page")

    joined_context = "\n\n".join(f"[{name}]\n{text}" for name, text in context_parts if text)
    prompt = (
        "你是 ScholarMind 的论文阅读助手。请只根据给定上下文回答用户问题，默认使用中文。\n"
        "如果用户提供了 selected_text，优先解释这段文本；如果问题涉及粗读、精读或推理链，"
        "优先使用对应解析上下文。\n"
        "不要编造上下文中没有的论文事实；信息不足时要明确说明“当前上下文不足”。\n"
        "输出严格 JSON 对象，字段为 answer、used_context、confidence。\n\n"
        f"用户入口: {body.source}\n"
        f"用户问题: {question}\n\n"
        f"可用上下文:\n{joined_context}"
    )

    from packages.integrations.llm_client import LLMClient

    llm = LLMClient()
    result = llm.complete_json(prompt, stage="paper_ask", max_tokens=1600)
    llm.trace_result(
        result,
        stage="paper_ask",
        prompt_digest=f"{body.source}:{question[:160]}",
        paper_id=str(paper_id),
    )

    parsed = result.parsed_json or {}
    answer = parsed.get("answer") if isinstance(parsed.get("answer"), str) else result.content
    parsed_used = parsed.get("used_context")
    if isinstance(parsed_used, list):
        response_used = [str(item) for item in parsed_used if str(item) in used_context]
    else:
        response_used = used_context
    if not response_used:
        response_used = used_context

    try:
        confidence = float(parsed.get("confidence", 0.55))
    except (TypeError, ValueError):
        confidence = 0.55
    confidence = max(0.0, min(confidence, 1.0))

    return PaperAskResponse(
        answer=answer.strip() or "当前上下文不足，无法生成可靠回答。",
        used_context=response_used,
        confidence=confidence,
    )


@router.post("/papers/{paper_id}/ai/explain")
def ai_explain_text(paper_id: UUID, body: AIExplainReq) -> dict:
    """AI 解释/翻译选中文本"""
    text = body.text.strip()
    action = body.action
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    prompts = {
        "explain": (
            f"你是学术论文解读专家。请用中文简洁解释以下学术文本的含义，"
            f"包括专业术语解释和核心意思。如果是公式，解释公式的含义和各变量。\n\n"
            f"文本：{text[:2000]}"
        ),
        "translate": (
            f"请将以下学术文本翻译为流畅的中文，保留专业术语的英文原文（括号标注）。\n\n"
            f"文本：{text[:2000]}"
        ),
        "summarize": (f"请用中文简要总结以下内容的核心观点（3-5 句话）：\n\n{text[:3000]}"),
    }
    prompt = prompts.get(action, prompts["explain"])

    from packages.integrations.llm_client import LLMClient

    llm = LLMClient()
    result = llm.summarize_text(prompt, stage="rag", max_tokens=1024)
    llm.trace_result(
        result, stage="pdf_reader_ai", prompt_digest=f"{action}:{text[:80]}", paper_id=str(paper_id)
    )
    return {"action": action, "result": result.content}

@router.get("/papers/{paper_id}/similar")
def similar(
    paper_id: UUID,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    ids = rag_service.similar_papers(paper_id, top_k=top_k)
    items = []
    if ids:
        with session_scope() as session:
            repo = PaperRepository(session)
            for pid in ids:
                try:
                    p = repo.get_by_id(pid)
                    items.append(
                        {
                            "id": str(p.id),
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "read_status": p.read_status.value if p.read_status else "unread",
                        }
                    )
                except Exception:
                    items.append(
                        {
                            "id": str(pid),
                            "title": str(pid),
                            "arxiv_id": None,
                            "read_status": "unread",
                        }
                    )
    return {
        "paper_id": str(paper_id),
        "similar_ids": [str(x) for x in ids],
        "items": items,
    }


@router.post("/papers/{paper_id}/reasoning")
def paper_reasoning(paper_id: UUID) -> dict:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            repo.get_by_id(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReasoningService().analyze(paper_id)
