"""
Agent 核心服务 - 对话管理、工具调度、确认流程
@author ScholarMind Team
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from packages.agent_core.context_compaction import (
    CompactingStreamingAgentLoop,
    CompactionConfig,
    ContextCompactor,
)
from packages.agent_core.loop import StreamingAgentLoop
from packages.agent_core.subagents import SubagentPool, SubagentRunner, get_subagent_pool
from packages.agent_core.todos import PlannerMixin, TodoManager, get_todo_manager
from packages.ai.agent_tools import (
    TOOL_REGISTRY,
    execute_tool_stream,
    get_openai_tools,
)
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import AgentPendingActionRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 ScholarMind AI Agent，一个专业的学术论文研究助手。你能调用工具完成搜索、\
下载、分析、生成等研究任务。始终使用中文。

## 工具选择决策树（按优先级）

收到用户消息后，按此顺序判断意图：

1. **知识问答**（"什么是X"、"对比X和Y"、"X有哪些方法"）
   → 直接调 ask_knowledge_base，不要编造答案
   → 知识库无内容时告知用户并建议下载

2. **搜索本地库**（"帮我找"、"搜索"、已有论文查询）
   → 调 search_papers
   → 无结果时自动切到 search_arxiv 搜 arXiv

3. **搜索并下载新论文**（"下载"、"收集"、"拉取"、"最新的XX论文"）
   → 调 search_arxiv 获取候选
   → **停下来**，等用户在前端界面勾选要入库的论文
   → 用户确认后调 ingest_arxiv(arxiv_ids=[用户选的])
   → 调用 ingest_arxiv 前，**必须**先在文本消息中逐条列出每篇候选的
     「标题 + 第一作者 + 年份 + arXiv ID」，严禁只给出 arxiv_ids 列表让用户盲确认。
     用户对"看不见的 ID"没有判断依据，这是硬性规则。

4. **分析论文**（"粗读"、"精读"、"分析图表"）
   → 先确认目标论文 ID，再调对应工具

5. **生成内容**（"Wiki"、"综述"）
   → 调 generate_wiki

6. **订阅管理**（"订阅"、"定时"、"每天收集"）
   → 调 manage_subscription

7. **模糊描述**（用户没给具体关键词，如"3D重建相关的"）
   → 先调 suggest_keywords 获取关键词建议
   → 展示给用户选择后再搜索

## 完整工作流示例

**示例 A：用户说"帮我找最新的3D重建论文并总结"**
1. 输出：「正在搜索 arXiv...」→ 调 search_arxiv(query="3D reconstruction")
2. 结果返回后：列出候选论文，说「请在上方勾选要入库的论文」
3. 用户确认入库后：结果显示入库完成
4. 自动继续：调 ask_knowledge_base(question="3D重建最新论文总结") 基于新入库的论文回答
5. 最后总结

**示例 B：用户说"attention mechanism 是什么"**
1. 直接调 ask_knowledge_base(question="attention mechanism 是什么")
2. 用返回的 markdown 回答用户，引用论文来源

**示例 C：用户说"帮我分析这篇论文 xxx"**
1. 调 get_paper_detail(paper_id="xxx") 确认论文存在
2. 调 skim_paper(paper_id="xxx") 粗读
3. 汇报粗读结果，询问是否需要精读

## 核心规则

1. **先输出一句话再调工具**：如「正在搜索...」，不要沉默直接调。
2. **严禁预测结果**：工具返回之前不要编造结果。
   - ❌「已成功找到 20 篇论文」→ 然后才调工具
   - ✅「正在搜索...」→ 调工具 → 看到结果后再描述
3. **主动推进**：一步完成后立即进入下一步，不要等用户催促。
4. **每次只调一个写操作工具**（ingest/skim/deep_read/embed/wiki），等确认后继续。
   只读工具（search/ask/get_detail/timeline/list_topics）可以连续调多个。
5. **不重复失败操作**：工具返回 success=false 时，分析 summary 中的原因，\
   告知用户并建议替代方案，不要用相同参数重试。
6. **参数修正后可重试**：如果失败原因是参数问题，修正后重试一次。
7. **结果描述要简洁**：用自然语言概括工具返回的关键信息，\
   不要重复输出工具已返回的完整数据。
8. **订阅建议**：ingest_arxiv 返回 suggest_subscribe=true 时，\
   询问用户是否要设为持续订阅。
9. **空结果处理**：搜索无结果时主动建议换关键词或从 arXiv 下载。
10. **简洁回答**：不要长篇解释工具用途，直接执行任务。
"""

_ACTION_TTL = 1800  # 30 分钟

# 已处理（确认/拒绝）过的 action_id → 时间戳；用于幂等保护，避免重复 confirm 报"已过期"
_HANDLED_ACTION_CACHE: dict[str, float] = {}
_HANDLED_ACTION_TTL = 3600.0  # 1 小时


def _make_sse(event: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _mark_action_handled(action_id: str) -> None:
    """标记 action 已被处理过（确认/拒绝），避免重复触发时报'已过期'"""
    _HANDLED_ACTION_CACHE[action_id] = time.time()
    # 控制缓存膨胀
    if len(_HANDLED_ACTION_CACHE) > 256:
        now = time.time()
        expired = [
            aid for aid, ts in _HANDLED_ACTION_CACHE.items() if now - ts > _HANDLED_ACTION_TTL
        ]
        for aid in expired:
            _HANDLED_ACTION_CACHE.pop(aid, None)


def _is_action_handled(action_id: str) -> bool:
    """判断 action 是否已被处理过（幂等保护）"""
    ts = _HANDLED_ACTION_CACHE.get(action_id)
    if ts is None:
        return False
    if time.time() - ts > _HANDLED_ACTION_TTL:
        _HANDLED_ACTION_CACHE.pop(action_id, None)
        return False
    return True


def _record_agent_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """将 Agent 对话的 token 消耗写入 PromptTrace"""
    if not (input_tokens or output_tokens):
        return
    try:
        llm = LLMClient()
        in_cost, out_cost = llm._estimate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        with session_scope() as session:
            from packages.storage.repositories import PromptTraceRepository

            PromptTraceRepository(session).create(
                stage="agent_chat",
                provider=provider,
                model=model,
                prompt_digest="[agent streaming chat]",
                paper_id=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_usd=in_cost,
                output_cost_usd=out_cost,
                total_cost_usd=in_cost + out_cost,
            )
    except Exception as exc:
        logger.warning("Failed to record agent usage: %s", exc)


def _build_user_profile() -> str:
    """从数据库提取用户画像：阅读历史、关注领域、最近活动"""
    try:
        from packages.ai.compass_service import CompassService
        from packages.domain.enums import ReadStatus
        from packages.storage.repositories import PaperRepository, TopicRepository

        parts: list[str] = []
        compass = CompassService()
        profile = compass.get_profile()
        model = compass.get_model()

        profile_parts = [
            ("画像置信度", f"{profile.get('confidence', 0)}%"),
            ("关注偏好", profile.get("interests", "")),
            ("推荐方向", profile.get("researchDirections", "")),
            ("阅读目标", profile.get("readingGoal", "")),
        ]
        for label, value in profile_parts:
            if str(value).strip():
                parts.append(f"{label}：{value}")

        notes = profile.get("notes") or []
        if notes:
            parts.append("推荐策略：" + "；".join(str(x) for x in notes[:6]))

        quick_profile = profile.get("quickProfile") if isinstance(profile.get("quickProfile"), dict) else {}
        quick_lines = []
        for key, label in [
            ("currentInterests", "当前最想追"),
            ("downrankAreas", "暂时少推"),
            ("paperTypes", "论文类型偏好"),
            ("readingGoals", "读论文目的"),
            ("modalityFocus", "模态组合"),
        ]:
            value = quick_profile.get(key)
            if isinstance(value, list) and value:
                quick_lines.append(f"{label}：{', '.join(str(x) for x in value[:8])}")
        if quick_profile.get("riskLevel"):
            quick_lines.append(f"探索风格：{quick_profile.get('riskLevel')}")
        if quick_lines:
            parts.append("快速画像：" + "；".join(quick_lines))

        weights = model.get("weights") if isinstance(model, dict) else {}
        if weights:
            ordered = sorted(weights.items(), key=lambda item: item[1], reverse=True)
            parts.append(
                "已学习评分偏好：" + "，".join(f"{key}={round(float(value) * 100)}%" for key, value in ordered[:6])
            )

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            topic_repo = TopicRepository(session)

            topics = topic_repo.list_topics(enabled_only=True)
            if topics:
                topic_names = [t.name for t in topics[:8]]
                parts.append(f"关注领域：{', '.join(topic_names)}")

            deep_read = paper_repo.list_by_read_status(ReadStatus.deep_read, limit=5)
            if deep_read:
                titles = [p.title[:60] for p in deep_read]
                parts.append(f"最近精读：{'; '.join(titles)}")

            skimmed = paper_repo.list_by_read_status(ReadStatus.skimmed, limit=200)
            unread = paper_repo.list_by_read_status(ReadStatus.unread, limit=200)
            parts.append(
                f"论文库状态：{len(deep_read)} 篇精读、{len(skimmed)} 篇粗读、{len(unread)} 篇未读"
            )

        if parts:
            return "\n\n## 用户画像\n" + "\n".join(f"- {p}" for p in parts)
    except Exception as exc:
        logger.warning("Failed to build user profile: %s", exc)
    return ""


def _join_profile_values(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _build_compass_user_profile() -> str:
    """Build the system-context user profile used by the Agent."""
    try:
        from packages.ai.compass_service import CompassService
        from packages.domain.enums import ReadStatus
        from packages.storage.repositories import PaperRepository, TopicRepository

        service = CompassService()
        profile = service.get_profile()
        model = service.get_model()
        quick = profile.get("quickProfile") if isinstance(profile.get("quickProfile"), dict) else {}
        parts: list[str] = []

        for label, value in [
            ("profile_confidence", f"{profile.get('confidence', 0)}%"),
            ("interests", profile.get("interests", "")),
            ("research_directions", profile.get("researchDirections", "")),
            ("reading_goal", profile.get("readingGoal", "")),
            ("strategy_notes", profile.get("notes", [])),
            ("current_interests", quick.get("currentInterests", [])),
            ("downrank_areas", quick.get("downrankAreas", [])),
            ("preferred_paper_types", quick.get("paperTypes", [])),
            ("reading_goals", quick.get("readingGoals", [])),
            ("modality_focus", quick.get("modalityFocus", [])),
            ("risk_level", quick.get("riskLevel", "")),
            ("extra_notes", quick.get("extraNotes", "")),
        ]:
            text = _join_profile_values(value)
            if text:
                parts.append(f"{label}: {text}")

        weights = model.get("weights") if isinstance(model, dict) else {}
        if weights:
            ordered = sorted(weights.items(), key=lambda item: item[1], reverse=True)
            parts.append(
                "learned_factor_weights: "
                + ", ".join(f"{key}={round(float(value) * 100)}%" for key, value in ordered[:6])
            )

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            topic_repo = TopicRepository(session)
            topics = topic_repo.list_topics(enabled_only=True)
            if topics:
                parts.append("enabled_topics: " + ", ".join(t.name for t in topics[:8]))
            deep_read = paper_repo.list_by_read_status(ReadStatus.deep_read, limit=5)
            skimmed = paper_repo.list_by_read_status(ReadStatus.skimmed, limit=200)
            unread = paper_repo.list_by_read_status(ReadStatus.unread, limit=200)
            if deep_read:
                parts.append("recent_deep_read: " + "; ".join(p.title[:60] for p in deep_read))
            parts.append(
                f"library_status: deep_read={len(deep_read)}, skimmed={len(skimmed)}, unread={len(unread)}"
            )

        if not parts:
            return ""
        return (
            "\n\n## Scholar Profile User Profile\n"
            "Use this profile in every feature: search, recommendation, ingestion, paper analysis, Wiki and QA. "
            "If the user asks for paper recommendations based on their profile, suitable papers, or papers worth reading, "
            "call recommend_profile_papers before answering. For arXiv search, prefer positive interests and avoid downrank areas.\n"
            + "\n".join(f"- {part}" for part in parts)
        )
    except Exception as exc:
        logger.warning("Failed to build Scholar Profile profile: %s", exc)
        return ""


def _build_messages(user_messages: list[dict]) -> list[dict]:
    """组装发送给 LLM 的 messages，插入 system prompt + 用户画像"""
    profile = _build_compass_user_profile()
    openai_msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + profile}]
    for m in user_messages:
        role = m.get("role", "user")
        if role == "tool":
            openai_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
            )
        elif role == "assistant" and m.get("tool_calls"):
            openai_msgs.append(
                {
                    "role": "assistant",
                    "content": m.get("content", "") or None,
                    "tool_calls": m["tool_calls"],
                }
            )
        else:
            openai_msgs.append(
                {
                    "role": role,
                    "content": m.get("content", ""),
                }
            )
    return openai_msgs


def _cleanup_expired_actions() -> None:
    """清理过期的 pending actions（数据库）"""
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            deleted = repo.cleanup_expired(_ACTION_TTL)
            if deleted > 0:
                logger.info("清理 %d 个过期 pending_actions", deleted)
    except Exception as exc:
        logger.warning("清理过期 pending_actions 失败: %s", exc)


def _load_pending_action(action_id: str) -> dict | None:
    """从数据库读取 pending action"""
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            record = repo.get_by_id(action_id)
            if record:
                return {
                    "action_id": action_id,
                    "tool": record.tool_name,
                    "args": record.tool_args,
                    "tool_call_id": record.tool_call_id,
                    "conversation": (record.conversation_state or {}).get("conversation", []),
                }
    except Exception as exc:
        logger.warning("读取 pending_action 失败: %s", exc)
    return None


def _create_loop(
    conversation: list[dict],
) -> StreamingAgentLoop:
    """创建配置好的 StreamingAgentLoop 实例"""
    llm = LLMClient()
    tools = get_openai_tools()

    def on_usage(provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        _record_agent_usage(provider, model, input_tokens, output_tokens)

    loop = StreamingAgentLoop(
        llm=llm,
        tools=tools,
        tool_registry=TOOL_REGISTRY,
        execute_fn=execute_tool_stream,
        session_scope=session_scope,
        on_usage=on_usage,
    )
    return loop


def _latest_user_content(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _is_profile_recommendation_request(messages: list[dict]) -> bool:
    text = _latest_user_content(messages).strip()
    lower = text.lower()
    has_profile = "用户画像" in text or "画像" in text or "profile" in lower
    asks_papers = "论文" in text and ("推荐" in text or "适合" in text or "阅读" in text)
    return has_profile and asks_papers


def _build_profile_recommendation_answer(top_k: int = 6) -> str:
    try:
        from packages.ai.compass_service import CompassService

        service = CompassService()
        profile = service.get_profile()
        result = service.recommend_library(top_k=top_k)
        source = "library"
        items = result.get("items", [])[:top_k]
        if not items:
            result = service.recommend_arxiv_candidates(top_k=top_k)
            source = result.get("source") or "arxiv"
            items = result.get("items", [])[:top_k]
        if not items:
            errors = result.get("errors") or []
            if errors:
                return (
                    "我已经读取了你的用户画像，但当前论文库里没有可推荐的未读论文；"
                    "同时按画像搜索 arXiv 失败，可能是网络或 arXiv API 暂时不可用。\n\n"
                    f"失败信息：{errors[0]}"
                )
            return (
                "我已经读取了你的用户画像，但当前论文库里没有可推荐的未读论文。"
                "你可以先用论文收集或让我搜索 arXiv 入库一批论文，然后我会按画像重新排序。"
            )

        profile_hint = profile.get("researchDirections") or profile.get("interests") or profile.get("readingGoal")
        source_label = "论文库" if source == "library" else "arXiv"
        lines = [f"我按你的用户画像从{source_label}筛了一批更适合优先读的论文："]
        if profile_hint:
            lines.append(f"\n画像依据：{profile_hint}")
        if source != "library":
            queries = ", ".join(result.get("queries") or [])
            if queries:
                lines.append(f"\n当前库内没有可推荐的未读论文，所以我按画像关键词临时搜索了 arXiv：{queries}")
        for index, item in enumerate(items, start=1):
            recommendation = item.get("recommendation") or {}
            factors = recommendation.get("factors") or {}
            title = item.get("title") or (item.get("paper") or {}).get("title") or "未命名论文"
            arxiv_id = item.get("arxiv_id") or ""
            score = round(float(item.get("final_score") or recommendation.get("score") or 0))
            reason = recommendation.get("reason") or "与当前画像匹配度较高。"
            factor_text = (
                f"画像匹配 {factors.get('profileFit', 0)}，"
                f"新信息量 {factors.get('novelty', 0)}，"
                f"可行动性 {factors.get('actionability', 0)}"
            )
            suffix = f"（arXiv: {arxiv_id}）" if arxiv_id else ""
            lines.append(
                f"\n{index}. {title}{suffix}\n"
                f"   推荐分：{score}；{reason}\n"
                f"   关键因素：{factor_text}"
            )
        if source == "library":
            lines.append("\n你也可以在“论文库 -> 画像推荐”里看到完整排序；给论文打星后，排序会继续学习你的偏好。")
        else:
            lines.append("\n这些是还未入库的 arXiv 候选；你可以继续说“把第 1、3 篇入库并解析”。入库和评分后，它们会进入论文库的画像推荐排序。")
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("profile recommendation shortcut failed: %s", exc)
        return f"画像推荐失败：{exc!s}"


def stream_chat(
    messages: list[dict],
    confirmed_action_id: str | None = None,
) -> tuple[Iterator[str], list[dict]]:
    """
    Agent 主入口：接收消息列表，返回 (SSE事件流, 更新后的conversation)。

    注意：返回的 conversation 已包含所有 tool 消息和 assistant 回复，
    可用于持久化或后续处理。
    """
    _cleanup_expired_actions()
    conversation = _build_messages(messages)

    if not confirmed_action_id and _is_profile_recommendation_request(messages):
        def _profile_recommend_iter():
            yield _make_sse("text_delta", {"content": _build_profile_recommendation_answer()})
            yield _make_sse("done", {})

        return _profile_recommend_iter(), conversation

    # 处理确认操作
    if confirmed_action_id:
        action = _load_pending_action(confirmed_action_id)
        if not action:
            # 幂等保护：已处理过的 action 给中性提示，不再报"已过期"
            already_handled = _is_action_handled(confirmed_action_id)
            err_msg = (
                "该操作已处理过，请继续后续对话。"
                if already_handled
                else "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
            )

            def _err_iter():
                yield _make_sse("error", {"message": err_msg})
                yield _make_sse("done", {})

            return _err_iter(), conversation

        _mark_action_handled(confirmed_action_id)
        loop = _create_loop(conversation)

        def _confirm_iter():
            yield from loop.execute_and_continue(action, conversation)
            yield _make_sse("done", {})

        return _confirm_iter(), conversation

    # 正常对话
    loop = _create_loop(conversation)

    def _chat_iter():
        yield from loop.run(conversation)
        yield _make_sse("done", {})

    return _chat_iter(), conversation


def confirm_action(action_id: str) -> tuple[Iterator[str], list[dict]]:
    """确认执行挂起的操作并继续对话"""
    logger.info("用户确认操作: %s", action_id)

    action = _load_pending_action(action_id)
    if not action:
        # 幂等保护：之前确认/拒绝过就明确提示，不再和"真过期"混淆
        already_handled = _is_action_handled(action_id)
        err_msg = (
            "该操作已处理过，请继续后续对话。"
            if already_handled
            else "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
        )

        def _err_iter():
            yield _make_sse("error", {"message": err_msg})
            yield _make_sse("done", {})

        return _err_iter(), []

    # 立即标记已处理，防止用户双击 / 网络重试导致二次执行
    _mark_action_handled(action_id)

    # 删除 pending action
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            repo.delete(action_id)
    except Exception as exc:
        logger.warning("删除 pending_action 失败: %s", exc)

    conversation = action.get("conversation", [])
    loop = _create_loop(conversation)

    def _confirm_iter():
        yield from loop.execute_confirmed_action(action, conversation)
        yield _make_sse("done", {})

    return _confirm_iter(), conversation


def reject_action(action_id: str) -> tuple[Iterator[str], list[dict]]:
    """拒绝挂起的操作并让 LLM 给出替代建议"""
    logger.info("用户拒绝操作: %s", action_id)

    action = _load_pending_action(action_id)

    # 标记已处理 + 删除 pending action
    if action:
        _mark_action_handled(action_id)
        try:
            with session_scope() as session:
                repo = AgentPendingActionRepository(session)
                repo.delete(action_id)
        except Exception as exc:
            logger.warning("删除 pending_action 失败: %s", exc)

    conversation = action.get("conversation", []) if action else []
    loop = _create_loop(conversation) if conversation else None

    def _reject_iter():
        yield _make_sse(
            "action_result",
            {
                "id": action_id,
                "success": False,
                "summary": "用户已取消该操作",
                "data": {},
            },
        )
        if loop:
            yield from loop.execute_rejected_action(action, conversation)
        yield _make_sse("done", {})

    return _reject_iter(), conversation


__all__ = [
    "stream_chat",
    "confirm_action",
    "reject_action",
    "CompactingStreamingAgentLoop",
    "ContextCompactor",
    "CompactionConfig",
    "TodoManager",
    "PlannerMixin",
    "get_todo_manager",
    "SubagentPool",
    "SubagentRunner",
    "get_subagent_pool",
]
