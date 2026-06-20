"""
每日/每周定时任务编排 - 智能调度 + 精读限额
@author ScholarMind Team
@author ScholarMind Team
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

from packages.ai.brief_service import DailyBriefService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api
from packages.config import get_settings
from packages.domain.enums import ActionType
from packages.storage.db import session_scope
from packages.storage.models import TopicSubscription
from packages.storage.repositories import (
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


PAPER_CONCURRENCY = 3


def _process_paper(paper_id, force_deep: bool = False, deep_read_quota: int | None = None) -> dict:
    """
    单篇论文：embed ∥ skim 并行，智能精读

    Args:
        paper_id: 论文 ID
        force_deep: 是否强制精读（忽略配额）
        deep_read_quota: 剩余精读配额（None 表示不限制）

    Returns:
        dict: 处理结果 {skim_score, deep_read, success}
    """

    settings = get_settings()
    pipelines = PaperPipelines()
    result = {
        "paper_id": str(paper_id)[:8],
        "skim_score": None,
        "deep_read": False,
        "success": False,
        "error": None,
    }

    skim_result = None
    with ThreadPoolExecutor(max_workers=2) as inner:
        fe = inner.submit(pipelines.embed_paper, paper_id)
        fs = inner.submit(pipelines.skim, paper_id)
        for fut in as_completed([fe, fs]):
            try:
                r = fut.result()
                if fut is fs:
                    skim_result = r
            except Exception as exc:
                label = "embed" if fut is fe else "skim"
                logger.warning(
                    "%s %s failed: %s",
                    label,
                    str(paper_id)[:8],
                    exc,
                )
                result["error"] = f"{label}: {exc}"

    # 检查粗读结果
    if skim_result and skim_result.relevance_score is not None:
        result["skim_score"] = skim_result.relevance_score
        result["success"] = True

    # 判断是否精读
    should_deep = False
    deep_reason = ""

    if force_deep:
        should_deep = True
        deep_reason = "强制精读"
    elif skim_result and skim_result.relevance_score >= settings.skim_score_threshold:
        # 检查精读配额
        if deep_read_quota is None or deep_read_quota > 0:
            should_deep = True
            deep_reason = f"高分论文 (分数={skim_result.relevance_score:.2f})"
        else:
            deep_reason = "精读配额已用尽"

    # 执行精读
    if should_deep:
        try:
            # 获取 API 许可
            if acquire_api("llm", timeout=30.0):
                pipelines.deep_dive(UUID(paper_id))
                result["deep_read"] = True
                logger.info("🎯 %s 精读完成 - %s", str(paper_id)[:8], deep_reason)
            else:
                logger.warning("⚠️  %s 等待 API 许可超时，跳过精读", str(paper_id)[:8])
        except Exception as exc:
            logger.warning(
                "deep_dive %s failed: %s",
                str(paper_id)[:8],
                exc,
            )
            result["error"] = f"deep: {exc}"

    return result


def run_topic_ingest(topic_id: str, progress_callback: callable | None = None) -> dict:
    """
    单独处理一个主题的抓取 + 处理 - 智能精读限额

    Args:
        topic_id: 主题 ID
        progress_callback: 可选的进度回调函数，签名 callback(message, current, total)

    Returns:
        dict: 处理结果统计
    """

    pipelines = PaperPipelines()
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}
        topic_name = topic.name

        # 获取精读配额配置
        max_deep_reads = getattr(topic, "max_deep_reads_per_run", 2)

        # 读取日期过滤配置
        enable_date_filter = getattr(topic, "enable_date_filter", False)
        date_filter_days = getattr(topic, "date_filter_days", 7)
        days_back = date_filter_days if enable_date_filter else 0

        last_error: str | None = None
        ids: list[str] = []
        new_count: int = 0
        by_source: dict[str, dict] = {}
        sources = [
            str(source).strip().lower()
            for source in (getattr(topic, "sources", None) or ["arxiv"])
            if str(source).strip()
        ]
        if not sources:
            sources = ["arxiv"]
        attempts = 0
        for _attempt in range(topic.retry_limit + 1):
            attempts += 1
            try:
                # 返回详细统计信息
                if progress_callback:
                    progress_callback("正在抓取论文...", 10, 100)
                ids = []
                new_count = 0
                by_source = {}
                for index, source in enumerate(sources, start=1):
                    if progress_callback:
                        progress_callback(f"正在抓取 {source} ({index}/{len(sources)})...", 10, 100)

                    if source == "arxiv":
                        result = pipelines.ingest_arxiv_with_stats(
                            query=topic.query,
                            max_results=topic.max_results_per_run,
                            topic_id=topic.id,
                            action_type=ActionType.auto_collect,
                            days_back=days_back,
                            progress_callback=progress_callback,
                        )
                    elif source == "openreview":
                        result = pipelines.ingest_openreview_with_stats(
                            query=topic.query,
                            max_results=topic.max_results_per_run,
                            topic_id=topic.id,
                            action_type=ActionType.auto_collect,
                        )
                    else:
                        logger.warning(
                            "Topic [%s] source %s is not supported by scheduled ingest yet",
                            topic.name,
                            source,
                        )
                        by_source[source] = {
                            "status": "skipped",
                            "reason": "scheduled ingest unsupported",
                            "inserted": 0,
                            "new_count": 0,
                        }
                        continue

                    source_ids = [str(item) for item in result.get("inserted_ids", [])]
                    source_new_count = int(result.get("new_count", 0) or 0)
                    ids.extend(source_ids)
                    new_count += source_new_count
                    by_source[source] = {
                        "status": "ok",
                        "inserted": len(source_ids),
                        "new_count": source_new_count,
                    }
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)

        if last_error is not None:
            return {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "status": "failed",
                "attempts": attempts,
                "error": last_error,
                "inserted": 0,
                "sources": sources,
                "by_source": by_source,
            }

        # 如果没有新论文，直接返回
        if new_count == 0:
            logger.info(
                "⚠️  主题 [%s] 没有新论文（重复 %d 篇），跳过处理",
                topic_name,
                len(ids),
            )
            if progress_callback:
                progress_callback("没有新论文", 100, 100)
            return {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "status": "no_new_papers",
                "inserted": 0,
                "new_count": 0,
                "total_count": len(ids),
                "sources": sources,
                "by_source": by_source,
            }

        repo = PaperRepository(session)
        # 只处理这次新入库的论文
        unique = repo.list_by_ids(ids) if ids else []
        # 在 Session 关闭前提取所有需要的数据，避免 DetachedInstanceError
        papers_data = [(str(p.id), p.title) for p in unique]

    logger.info(
        "📝 主题 [%s] 新抓取 %d 篇论文（新论文 %d 篇），精读配额：%d 篇",
        topic_name,
        len(unique),
        new_count,
        max_deep_reads,
    )

    # 第一步：全部论文并行粗读 + 嵌入（不精读）
    logger.info("第一步：并行粗读 + 嵌入...")
    if progress_callback:
        progress_callback("开始粗读 + 嵌入...", 30, 100)
    skim_results = []

    total_papers = len(papers_data)
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        futs = {
            pool.submit(_process_paper, paper_id, force_deep=False, deep_read_quota=0): paper_id
            for paper_id, _ in papers_data
        }
        for i, fut in enumerate(as_completed(futs)):
            try:
                result = fut.result()
                skim_results.append(result)
                if progress_callback:
                    progress_callback(
                        f"粗读中 ({i + 1}/{total_papers})...",
                        30 + int((i + 1) / total_papers * 40),
                        100,
                    )
            except Exception as exc:
                paper_id = futs[fut]
                logger.warning(
                    "skim %s failed: %s",
                    str(paper_id)[:8],
                    exc,
                )

    # 第二步：按粗读分数排序，选前 N 篇精读
    logger.info("第二步：选择高分论文进行精读...")
    if progress_callback:
        progress_callback("选择高分论文...", 70, 100)
    # 只用 ID 和分数排序，不再引用 ORM 对象
    scored_papers = [
        (r, paper_id)
        for r, (paper_id, _) in zip(skim_results, papers_data)
        if r["success"] and r["skim_score"] is not None
    ]
    scored_papers.sort(key=lambda x: x[0]["skim_score"], reverse=True)

    # 精读前 N 篇
    deep_read_count = 0
    max_scored = len(scored_papers)
    for i, (result, paper_id) in enumerate(scored_papers):
        if deep_read_count >= max_deep_reads:
            logger.info(
                "⚠️  精读配额已用尽 (%d/%d)，剩余 %d 篇跳过精读",
                deep_read_count,
                max_deep_reads,
                len(scored_papers) - i,
            )
            break

        # 只精读分数 >= 阈值的
        if result["skim_score"] < get_settings().skim_score_threshold:
            logger.info("⚠️  %s 分数过低 (%.2f)，跳过精读", str(paper_id)[:8], result["skim_score"])
            continue

        logger.info(
            "🎯 开始精读第 %d 篇：%s (分数=%.2f)",
            deep_read_count + 1,
            str(paper_id)[:50],
            result["skim_score"],
        )

        try:
            # 获取 API 许可
            if acquire_api("llm", timeout=60.0):
                pipelines.deep_dive(UUID(paper_id))  # type: ignore[arg-type]
                deep_read_count += 1
                if progress_callback:
                    progress_callback(
                        f"精读中 ({deep_read_count}/{max_deep_reads})...",
                        70 + int((i + 1) / max_scored * 30),
                        100,
                    )
                logger.info("✅ 精读完成 (%d/%d)", deep_read_count, max_deep_reads)
            else:
                logger.warning("等待 API 许可超时，跳过精读")
        except Exception as exc:
            logger.warning(
                "deep_dive %s failed: %s",
                str(paper_id)[:8],
                exc,
            )

    if progress_callback:
        progress_callback("处理完成", 100, 100)

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "status": "ok",
        "attempts": attempts,
        "inserted": len(ids),
        "skimmed": len(skim_results),
        "deep_read": deep_read_count,
        "max_deep_reads": max_deep_reads,
        "sources": sources,
        "by_source": by_source,
    }


def run_daily_ingest() -> dict:
    """兼容旧调用：遍历所有 enabled 主题执行抓取"""
    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topics = topic_repo.list_topics(enabled_only=True)
        if not topics:
            topics = [
                topic_repo.upsert_topic(
                    name="default-ml",
                    query="cat:cs.LG OR cat:cs.CL",
                    enabled=True,
                    max_results_per_run=20,
                    retry_limit=2,
                )
            ]
        topic_ids = [t.id for t in topics]

    results = []
    for tid in topic_ids:
        results.append(run_topic_ingest(tid))

    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_processed = sum(r.get("processed", 0) for r in results)
    return {
        "newly_inserted": total_inserted,
        "processed": total_processed,
        "topics": results,
    }


def run_daily_brief() -> dict:
    """生成每日简报，从数据库读取收件人配置"""
    # 从数据库读取收件人
    from packages.storage.db import session_scope
    from packages.storage.repositories import DailyReportConfigRepository

    recipient = None
    try:
        with session_scope() as session:
            config = DailyReportConfigRepository(session).get_config()
            if config.send_email_report and config.recipient_emails:
                recipient = config.recipient_emails.split(",")[0]
    except Exception as e:
        logger.warning(f"读取收件人配置失败：{e}")

    return DailyBriefService().publish(recipient=recipient)


# ========== 完整版新增：多渠道调度支持 ==========


def run_topic_ingest_v2(topic_id: str) -> dict:
    """
    单独处理一个主题的抓取 + 处理 - 支持多渠道（完整版）

    新功能:
    - 支持按主题配置从多个论文源抓取
    - 按渠道分别统计结果

    Args:
        topic_id: 主题 ID

    Returns:
        dict: 处理结果统计（包含 by_source 字段）
    """

    pipelines = PaperPipelines()
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}

        topic_name = topic.name
        # 获取配置的渠道列表，默认只有 ArXiv
        sources = getattr(topic, "sources", ["arxiv"])

        # 按渠道分别抓取
        all_results = {}
        total_inserted = 0

        for source in sources:
            if source == "arxiv":
                result = _ingest_from_arxiv(pipelines, topic, session)
            elif source == "openreview":
                result = _ingest_from_openreview(pipelines, topic, session)
            else:
                logger.warning("未知渠道：%s，跳过", source)
                continue

            all_results[source] = result
            total_inserted += result.get("inserted", 0)

        # 汇总统计
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "sources": sources,
            "total_inserted": total_inserted,
            "by_source": all_results,
        }


def _ingest_from_arxiv(pipelines, topic, session) -> dict:
    """ArXiv 渠道抓取（保持现有逻辑）"""
    last_error: str | None = None
    ids: list[str] = []
    new_count: int = 0
    attempts = 0

    for _attempt in range(topic.retry_limit + 1):
        attempts += 1
        try:
            result = pipelines.ingest_arxiv_with_stats(
                query=topic.query,
                max_results=topic.max_results_per_run,
                topic_id=topic.id,
                action_type=ActionType.auto_collect,
            )
            ids = result["inserted_ids"]
            new_count = result["new_count"]
            last_error = None
            break
        except Exception as exc:
            last_error = str(exc)

    if last_error is not None:
        return {
            "status": "failed",
            "attempts": attempts,
            "error": last_error,
            "inserted": 0,
        }

    return {
        "status": "ok",
        "inserted": len(ids),
        "new_count": new_count,
    }


def _ingest_from_openreview(pipelines, topic, session) -> dict:
    """OpenReview channel ingest."""
    last_error: str | None = None
    ids: list[str] = []
    new_count: int = 0
    attempts = 0

    for _attempt in range(topic.retry_limit + 1):
        attempts += 1
        try:
            result = pipelines.ingest_openreview_with_stats(
                query=topic.query,
                max_results=topic.max_results_per_run,
                topic_id=topic.id,
                action_type=ActionType.auto_collect,
            )
            ids = result["inserted_ids"]
            new_count = result["new_count"]
            last_error = None
            break
        except Exception as exc:
            last_error = str(exc)

    if last_error is not None:
        return {
            "status": "failed",
            "attempts": attempts,
            "error": last_error,
            "inserted": 0,
        }

    return {
        "status": "ok",
        "inserted": len(ids),
        "new_count": new_count,
    }
