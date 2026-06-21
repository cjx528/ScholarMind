"""Background jobs and collection action routes."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from packages.ai.daily_runner import PAPER_CONCURRENCY, _process_paper
from packages.domain.enums import ReadStatus
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import ActionRepository, PaperRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jobs/batch-process-unread")
def batch_process_unread(
    background_tasks: BackgroundTasks,
    max_papers: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Embed and skim unread papers in the background."""

    with session_scope() as session:
        repo = PaperRepository(session)
        unread = repo.list_by_read_status(ReadStatus.unread, limit=max_papers)
        target_ids = [
            p.id
            for p in unread
            if p.embedding is None or p.read_status == ReadStatus.unread
        ]

    total = len(target_ids)
    if total == 0:
        return {"processed": 0, "total_unread": 0, "message": "没有需要处理的未读论文"}

    task_id = f"batch_unread_{uuid.uuid4().hex[:8]}"

    def _run_batch() -> None:
        processed = 0
        failed = 0
        try:
            global_tracker.start(
                task_id,
                "batch_process",
                f"批量处理未读论文 ({total} 篇)",
                total=total,
                category="analysis",
            )

            with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
                futures = {pool.submit(_process_paper, pid): pid for pid in target_ids}
                for fut in as_completed(futures):
                    try:
                        fut.result()
                        processed += 1
                        global_tracker.update(
                            task_id,
                            processed,
                            f"正在处理... ({processed}/{total})",
                            total=total,
                        )
                    except Exception as exc:
                        failed += 1
                        logger.warning("batch process %s failed: %s", str(futures[fut])[:8], exc)

            global_tracker.finish(task_id, success=True)
            logger.info("Batch processing finished: %s success, %s failed", processed, failed)
        except Exception as exc:
            global_tracker.finish(task_id, success=False, error=str(exc))
            logger.error("Batch processing failed: %s", exc, exc_info=True)

    background_tasks.add_task(_run_batch)
    return {"task_id": task_id, "message": f"批量处理已启动 ({total} 篇论文)", "status": "running"}


@router.get("/actions")
def list_actions(
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List paper collection actions."""

    with session_scope() as session:
        actions, total = ActionRepository(session).list_actions(
            action_type=action_type,
            topic_id=topic_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": a.id,
                    "action_type": a.action_type,
                    "title": a.title,
                    "query": a.query,
                    "topic_id": a.topic_id,
                    "paper_count": a.paper_count,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ],
            "total": total,
        }


@router.get("/actions/{action_id}")
def get_action_detail(action_id: str) -> dict:
    """Return one collection action."""

    with session_scope() as session:
        action = ActionRepository(session).get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="行动记录不存在")
        return {
            "id": action.id,
            "action_type": action.action_type,
            "title": action.title,
            "query": action.query,
            "topic_id": action.topic_id,
            "paper_count": action.paper_count,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }


@router.get("/actions/{action_id}/papers")
def get_action_papers(
    action_id: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """Return papers linked to one collection action."""

    with session_scope() as session:
        papers = ActionRepository(session).get_papers_by_action(action_id, limit=limit)
        return {
            "action_id": action_id,
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "publication_date": p.publication_date.isoformat()
                    if p.publication_date
                    else None,
                    "read_status": p.read_status,
                }
                for p in papers
            ],
        }
