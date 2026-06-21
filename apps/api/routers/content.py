"""Wiki / 生成内容路由
@author ScholarMind Team
"""

import re
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from apps.api.deps import graph_service, iso_dt
from packages.ai.graph_service import repair_topic_wiki_payload
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.models import GeneratedContent, Paper
from packages.storage.repositories import GeneratedContentRepository, PaperRepository

router = APIRouter()


def _normalize_lookup_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _paper_ref_candidates(raw_ref: str) -> list[str]:
    ref = unquote(str(raw_ref or "")).strip()
    if not ref:
        return []

    candidates = [ref]
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", ref, flags=re.IGNORECASE)
    if arxiv_match:
        candidates.append(arxiv_match.group(1).removesuffix(".pdf"))
    if ref.lower().startswith("arxiv:"):
        candidates.append(ref.split(":", 1)[1].strip())

    expanded: list[str] = []
    for item in candidates:
        clean = item.strip().strip("/")
        if clean.endswith(".pdf"):
            clean = clean[:-4]
        if not clean:
            continue
        expanded.append(clean)
        without_version = re.sub(r"v\d+$", "", clean)
        if without_version != clean:
            expanded.append(without_version)

    seen: set[str] = set()
    ordered: list[str] = []
    for item in expanded:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def resolve_paper_reference(session, paper_ref: str) -> Paper | None:
    """Resolve a Wiki paper input to an existing Paper row.

    The UI can send a UUID, arXiv/OpenReview/source id, URL, DOI, or a pasted
    title. GeneratedContent.paper_id is a foreign key, so saving must use the
    real papers.id value.
    """

    candidates = _paper_ref_candidates(paper_ref)
    if not candidates:
        return None

    for candidate in candidates:
        try:
            paper = PaperRepository(session).get_by_id(UUID(candidate))
            return paper
        except (ValueError, TypeError):
            pass

    q = select(Paper).where(Paper.arxiv_id.in_(candidates)).limit(1)
    paper = session.execute(q).scalar_one_or_none()
    if paper is not None:
        return paper

    source_fields = ["source_id", "openreview_id", "forum", "doi", "arxiv_pdf_id"]
    for candidate in candidates:
        q = select(Paper).where(
            or_(
                *(
                    func.json_extract(Paper.metadata_json, f"$.{field}") == candidate
                    for field in source_fields
                )
            )
        )
        paper = session.execute(q.limit(1)).scalar_one_or_none()
        if paper is not None:
            return paper

    ref_norm = _normalize_lookup_text(candidates[0])
    if not ref_norm:
        return None

    exact = session.execute(
        select(Paper).where(func.lower(Paper.title) == candidates[0].lower()).limit(1)
    ).scalar_one_or_none()
    if exact is not None:
        return exact

    best: tuple[float, Paper] | None = None
    ref_tokens = set(ref_norm.split())
    for paper in PaperRepository(session).list_lightweight(limit=50000):
        title_norm = _normalize_lookup_text(paper.title)
        if not title_norm:
            continue
        title_tokens = set(title_norm.split())
        if ref_norm == title_norm:
            score = 1.0
        elif ref_norm in title_norm or title_norm in ref_norm:
            score = min(len(ref_norm), len(title_norm)) / max(len(ref_norm), len(title_norm))
        else:
            overlap = len(ref_tokens & title_tokens)
            score = overlap / max(len(ref_tokens), len(title_tokens), 1)
        if best is None or score > best[0]:
            best = (score, paper)

    if best and best[0] >= 0.72:
        return best[1]
    return None


def _resolve_paper_reference_or_404(paper_ref: str) -> dict:
    with session_scope() as session:
        paper = resolve_paper_reference(session, paper_ref)
        if paper is None:
            raise HTTPException(
                status_code=404,
                detail="未在论文库中找到这篇论文。请从论文详情页生成 Wiki，或输入论文库中的 UUID / arXiv ID / 完整标题。",
            )
        return {"id": str(paper.id), "title": paper.title}


def _result_metadata(result: dict, task_id: str | None = None) -> dict:
    metadata = {k: v for k, v in result.items() if k != "markdown"}
    if task_id:
        metadata["task_id"] = task_id
    return metadata


def _generated_detail_payload(gc: GeneratedContent) -> dict:
    metadata_json = gc.metadata_json or {}
    markdown = gc.markdown
    if gc.content_type == "topic_wiki":
        metadata_json = repair_topic_wiki_payload(metadata_json, gc.keyword)
        markdown = metadata_json.get("markdown") or markdown
    return {
        "id": gc.id,
        "content_type": gc.content_type,
        "title": gc.title,
        "keyword": gc.keyword,
        "paper_id": gc.paper_id,
        "markdown": markdown,
        "metadata_json": metadata_json,
        "created_at": iso_dt(gc.created_at),
    }


# ---------- Wiki ----------


@router.get("/wiki/paper/{paper_ref:path}")
def wiki_paper(paper_ref: str) -> dict:
    paper = _resolve_paper_reference_or_404(paper_ref)
    paper_id = paper["id"]
    result = graph_service.paper_wiki(paper_id=paper_id)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="paper_wiki",
            title=f"Paper Wiki: {result.get('title', paper['title'])}",
            markdown=result.get("markdown", ""),
            paper_id=paper_id,
            metadata_json=_result_metadata(result),
        )
        result["content_id"] = gc.id
    return result


@router.get("/wiki/topic")
def wiki_topic(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    result = graph_service.topic_wiki(keyword=keyword, limit=limit)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json=_result_metadata(result),
        )
        result["content_id"] = gc.id
    return result


# ---------- 异步任务 API ----------


def _run_topic_wiki_task(
    keyword: str,
    limit: int,
    progress_callback=None,
    task_id: str | None = None,
) -> dict:
    """后台执行 topic wiki 生成"""

    result = graph_service.topic_wiki(
        keyword=keyword,
        limit=limit,
        progress_callback=progress_callback,
    )
    if progress_callback:
        progress_callback("正在保存 Wiki...", 95, 100)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json=_result_metadata(result, task_id=task_id),
        )
        result["content_id"] = gc.id
    if task_id:
        result["task_id"] = task_id
    if progress_callback:
        progress_callback("Wiki 生成完成", 100, 100)
    return result


def _run_paper_wiki_task(
    paper_id: str,
    progress_callback=None,
    task_id: str | None = None,
) -> dict:
    """后台执行 paper wiki 生成"""
    if progress_callback:
        progress_callback("正在为论文生成 Wiki...", 10, 100)
    result = graph_service.paper_wiki(paper_id=paper_id, progress_callback=progress_callback)
    if progress_callback:
        progress_callback("正在保存 Wiki...", 90, 100)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="paper_wiki",
            title=f"Paper Wiki: {result.get('title', paper_id)}",
            markdown=result.get("markdown", ""),
            paper_id=paper_id,
            metadata_json=_result_metadata(result, task_id=task_id),
        )
        result["content_id"] = gc.id
    if task_id:
        result["task_id"] = task_id
    if progress_callback:
        progress_callback("Wiki 生成完成", 100, 100)
    return result


@router.post("/tasks/wiki/topic")
def start_topic_wiki_task(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """提交后台 wiki 生成任务"""
    task_id = global_tracker.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=_run_topic_wiki_task,
        keyword=keyword,
        limit=limit,
        category="generation",
    )
    return {"task_id": task_id, "status": "pending"}


@router.post("/tasks/wiki/paper/{paper_ref:path}")
def start_paper_wiki_task(paper_ref: str) -> dict:
    """提交后台 paper wiki 生成任务"""
    paper = _resolve_paper_reference_or_404(paper_ref)
    paper_id = paper["id"]
    task_id = global_tracker.submit(
        task_type="paper_wiki",
        title=f"Paper Wiki: {paper['title'][:40]}",
        fn=_run_paper_wiki_task,
        paper_id=paper_id,
        category="generation",
    )
    return {"task_id": task_id, "status": "pending", "paper_id": paper_id, "title": paper["title"]}


# ---------- 生成内容历史 ----------


@router.get("/generated/list")
def generated_list(
    type: str = Query(..., description="content_type: topic_wiki|paper_wiki"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        items = repo.list_by_type(type, limit=limit)
        return {
            "items": [
                {
                    "id": gc.id,
                    "content_type": gc.content_type,
                    "title": gc.title,
                    "keyword": gc.keyword,
                    "paper_id": gc.paper_id,
                    "created_at": iso_dt(gc.created_at),
                }
                for gc in items
            ]
        }


@router.get("/generated/by-task/{task_id}")
def generated_by_task(task_id: str) -> dict:
    with session_scope() as session:
        q = (
            select(GeneratedContent)
            .where(func.json_extract(GeneratedContent.metadata_json, "$.task_id") == task_id)
            .order_by(GeneratedContent.created_at.desc())
            .limit(1)
        )
        gc = session.execute(q).scalar_one_or_none()
        if gc is None:
            raise HTTPException(status_code=404, detail="Content not found")
        return _generated_detail_payload(gc)


@router.get("/generated/{content_id}")
def generated_detail(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        try:
            gc = repo.get_by_id(content_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Content not found") from exc
        return _generated_detail_payload(gc)


@router.delete("/generated/{content_id}")
def generated_delete(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        try:
            repo.get_by_id(content_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Content not found") from exc
        repo.delete(content_id)
    return {"deleted": content_id}
