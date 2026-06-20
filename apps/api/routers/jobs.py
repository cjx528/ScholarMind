"""定时任务 & 行动记录路由
@author ScholarMind Team
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from packages.ai.daily_runner import run_daily_ingest
from packages.domain.enums import ReadStatus
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jobs/daily/run-once")
def run_daily_once() -> dict:
    """每日任务（抓取）- 后台执行"""

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在执行订阅收集...", 10, 100)
        ingest = run_daily_ingest()
        return {"ingest": ingest}

    task_id = global_tracker.submit("daily_job", "📅 每日收集任务执行", _fn, category="collection")
    return {"task_id": task_id, "message": "每日任务已启动", "status": "running"}


@router.post("/jobs/batch-process-unread")
def batch_process_unread(
    background_tasks: BackgroundTasks,
    max_papers: int = Query(default=50, ge=1, le=200),
) -> dict:
    """批量处理未读论文（embed + skim 并行）- 后台执行"""
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from packages.ai.daily_runner import PAPER_CONCURRENCY, _process_paper

    # 先获取需要处理的论文数量
    with session_scope() as session:
        repo = PaperRepository(session)
        unread = repo.list_by_read_status(ReadStatus.unread, limit=max_papers)
        target_ids = []
        for p in unread:
            needs_embed = p.embedding is None
            needs_skim = p.read_status == ReadStatus.unread
            if needs_embed or needs_skim:
                target_ids.append(p.id)

    total = len(target_ids)
    if total == 0:
        return {"processed": 0, "total_unread": 0, "message": "没有需要处理的未读论文"}

    task_id = f"batch_unread_{uuid.uuid4().hex[:8]}"

    def _run_batch():
        processed = 0
        failed = 0
        try:
            global_tracker.start(
                task_id,
                "batch_process",
                f"📚 批量处理未读论文 ({total} 篇)",
                total=total,
                category="analysis",
            )

            with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
                futs = {pool.submit(_process_paper, pid): pid for pid in target_ids}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                        processed += 1
                        global_tracker.update(
                            task_id, processed, f"正在处理... ({processed}/{total})", total=total
                        )
                    except Exception as exc:
                        failed += 1
                        logger.warning("batch process %s failed: %s", str(futs[fut])[:8], exc)

            global_tracker.finish(task_id, success=True)
            logger.info(f"批量处理完成: {processed} 成功, {failed} 失败")
        except Exception as e:
            global_tracker.finish(task_id, success=False, error=str(e))
            logger.error(f"批量处理失败: {e}", exc_info=True)

    background_tasks.add_task(_run_batch)
    return {"task_id": task_id, "message": f"批量处理已启动 ({total} 篇论文)", "status": "running"}


# ---------- 行动记录 ----------


@router.get("/actions")
def list_actions(
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """列出论文入库行动记录"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        actions, total = repo.list_actions(
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
    """获取行动详情"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        action = repo.get_action(action_id)
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
    """获取某次行动关联的论文列表"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        papers = repo.get_papers_by_action(action_id, limit=limit)
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
