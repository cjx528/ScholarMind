"""
Agent 工具注册表和执行函数
@author ScholarMind Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rag_service import RAGService
from packages.storage.db import check_db_connection, session_scope
from packages.storage.repositories import (
    PaperRepository,
    PipelineRunRepository,
    TopicRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _parse_uuid(val: str) -> UUID | None:
    """解析 UUID 字符串，失败返回 None"""
    try:
        return UUID(val)
    except ValueError:
        return None


def _require_paper(paper_id: str):
    """校验 paper_id 格式 + 查库，返回 (paper, ToolResult|None)"""
    pid = _parse_uuid(paper_id)
    if pid is None:
        return None, ToolResult(success=False, summary="无效的 paper_id 格式")
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
            return paper, None
        except ValueError:
            return None, ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )


@dataclass
class ToolResult:
    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class ToolProgress:
    """工具执行中间进度事件"""

    message: str
    current: int = 0
    total: int = 0


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    requires_confirm: bool = False


TOOL_REGISTRY: list[ToolDef] = [
    ToolDef(
        name="recommend_profile_papers",
        description="根据用户画像和评分反馈推荐当前论文库中最适合阅读的未读论文",
        parameters={
            "type": "object",
            "properties": {
                "top_k": {
                    "type": "integer",
                    "description": "返回推荐论文数量",
                    "default": 8,
                },
            },
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="search_papers",
        description="在数据库中按关键词搜索论文（标题和摘要全文匹配）",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "limit": {
                    "type": "integer",
                    "description": "返回数量上限",
                    "default": 20,
                },
            },
            "required": ["keyword"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_paper_detail",
        description="获取单篇论文的详细信息",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="get_similar_papers",
        description="基于向量相似度获取与指定论文相似的论文 ID 列表",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
                "top_k": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 5,
                },
            },
            "required": ["paper_id"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="ask_knowledge_base",
        description="基于 RAG 向知识库提问，返回答案及引用论文 ID",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "问题内容"},
                "top_k": {
                    "type": "integer",
                    "description": "检索论文数量",
                    "default": 5,
                },
            },
            "required": ["question"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="list_topics",
        description="列出所有主题库",
        parameters={"type": "object", "properties": {}},
        requires_confirm=False,
    ),
    ToolDef(
        name="get_system_status",
        description="检查系统状态：数据库连接、论文数、主题数、Pipeline 运行数",
        parameters={"type": "object", "properties": {}},
        requires_confirm=False,
    ),
    ToolDef(
        name="search_arxiv",
        description="搜索 arXiv 论文，返回候选列表供用户筛选（不入库）",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "arXiv 搜索查询"},
                "max_results": {
                    "type": "integer",
                    "description": "最大搜索数量",
                    "default": 20,
                },
                "days_back": {
                    "type": "integer",
                    "description": (
                        "只检索最近 N 天提交的论文。默认 180 天，优先新论文；"
                        "需要经典/全时间段时显式传 0。"
                    ),
                    "default": 180,
                },
                "sort_by": {
                    "type": "string",
                    "description": "排序方式：submittedDate（默认，最新优先）/ relevance（相关性优先）",
                    "default": "submittedDate",
                },
            },
            "required": ["query"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="ingest_arxiv",
        description="将用户选定的 arXiv 论文入库（需提供 arxiv_ids 列表）",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "原始搜索查询（用于主题关联）"},
                "arxiv_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要入库的 arXiv ID 列表",
                },
            },
            "required": ["query", "arxiv_ids"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="skim_paper",
        description="对论文执行粗读 Pipeline",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="deep_read_paper",
        description="对论文执行精读 Pipeline",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="embed_paper",
        description="对论文执行向量化嵌入",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
    ToolDef(
        name="generate_wiki",
        description="生成主题或论文的 Wiki 内容",
        parameters={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "wiki 类型：topic 或 paper",
                    "enum": ["topic", "paper"],
                },
                "keyword_or_id": {
                    "type": "string",
                    "description": "topic 时为关键词，paper 时为论文 UUID",
                },
            },
            "required": ["type", "keyword_or_id"],
        },
        requires_confirm=True,
    ),

    ToolDef(
        name="suggest_keywords",
        description="根据用户自然语言描述，AI 生成 arXiv 搜索关键词建议",
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "用户的研究兴趣描述（自然语言）",
                },
            },
            "required": ["description"],
        },
        requires_confirm=False,
    ),
    ToolDef(
        name="reasoning_analysis",
        description="对论文进行推理链深度分析：方法推导链、实验验证链、创新性多维评估",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "论文 UUID"},
            },
            "required": ["paper_id"],
        },
        requires_confirm=True,
    ),
]


def get_openai_tools() -> list[dict]:
    """将 TOOL_REGISTRY 转为 OpenAI function calling 格式"""
    out: list[dict] = []
    for t in TOOL_REGISTRY:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
        )
    return out


def _get_tool_handlers() -> dict:
    return {
        "recommend_profile_papers": _recommend_profile_papers,
        "search_papers": _search_papers,
        "get_paper_detail": _get_paper_detail,
        "get_similar_papers": _get_similar_papers,
        "ask_knowledge_base": _ask_knowledge_base,
        "list_topics": _list_topics,
        "get_system_status": _get_system_status,
        "search_arxiv": _search_arxiv,
        "ingest_arxiv": _ingest_arxiv,
        "skim_paper": _skim_paper,
        "deep_read_paper": _deep_read_paper,
        "embed_paper": _embed_paper,
        "generate_wiki": _generate_wiki,
        "suggest_keywords": _suggest_keywords,
        "reasoning_analysis": _reasoning_analysis,
    }


def execute_tool_stream(name: str, arguments: dict) -> Iterator[ToolProgress | ToolResult]:
    """流式执行工具，yield 进度事件和最终结果"""
    fn = _get_tool_handlers().get(name)
    if not fn:
        yield ToolResult(success=False, summary=f"未知工具: {name}")
        return
    try:
        result = fn(**arguments)
        if hasattr(result, "__next__"):
            yield from result
        else:
            yield result
    except Exception as exc:
        logger.exception("Tool %s failed: %s", name, exc)
        yield ToolResult(success=False, summary=str(exc))


def _recommend_profile_papers(top_k: int = 8) -> ToolResult:
    """根据用户画像推荐论文库中的未读论文。"""
    try:
        from packages.ai.compass_service import CompassService

        top_k = max(1, min(20, int(top_k or 8)))
        service = CompassService()
        profile = service.get_profile()
        result = service.recommend_library(top_k=top_k)
        source = "library"
        if not result.get("items"):
            result = service.recommend_arxiv_candidates(top_k=top_k)
            source = result.get("source") or "arxiv"
        items = []
        for item in result.get("items", [])[:top_k]:
            recommendation = item.get("recommendation") or {}
            paper = item.get("paper") or {}
            items.append(
                {
                    "id": item.get("paper_id") or item.get("id"),
                    "title": item.get("title") or paper.get("title"),
                    "arxiv_id": item.get("arxiv_id"),
                    "abstract": item.get("abstract"),
                    "final_score": item.get("final_score"),
                    "reason": recommendation.get("reason"),
                    "factors": recommendation.get("factors") or {},
                    "authors": item.get("authors") or paper.get("authors") or [],
                    "categories": item.get("categories") or [],
                    "keywords": item.get("keywords") or [],
                    "status": item.get("status"),
                    "source_type": item.get("source_type"),
                    "query": item.get("query"),
                }
            )
        return ToolResult(
            success=True,
            data={
                "profile": {
                    "interests": profile.get("interests", ""),
                    "researchDirections": profile.get("researchDirections", ""),
                    "readingGoal": profile.get("readingGoal", ""),
                    "notes": profile.get("notes", []),
                    "confidence": profile.get("confidence", 0),
                },
                "papers": items,
                "count": len(items),
                "model": result.get("model"),
                "source": source,
                "queries": result.get("queries", []),
                "errors": result.get("errors", []),
            },
            summary=f"根据用户画像推荐了 {len(items)} 篇论文",
        )
    except Exception as exc:
        logger.exception("recommend_profile_papers failed: %s", exc)
        return ToolResult(success=False, summary=f"画像推荐失败: {exc!s}")


def _search_papers(keyword: str, limit: int = 20) -> ToolResult:
    try:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(query=keyword, limit=limit)
            items = [
                {
                    "id": str(p.id),
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "abstract": (p.abstract or "")[:500],
                    "publication_date": str(p.publication_date) if p.publication_date else None,
                    "read_status": p.read_status.value,
                    "categories": (p.metadata_json or {}).get("categories", []),
                }
                for p in papers
            ]
        return ToolResult(
            success=True,
            data={"papers": items, "count": len(items)},
            summary=f"搜索到 {len(items)} 篇论文",
        )
    except Exception as exc:
        logger.exception("search_papers failed: %s", exc)
        return ToolResult(success=False, summary=f"搜索论文失败: {exc!s}")


def _get_paper_detail(paper_id: str) -> ToolResult:
    p, err = _require_paper(paper_id)
    if err:
        return err
    with session_scope() as session:
        p = PaperRepository(session).get_by_id(UUID(paper_id))
        title = p.title or ""
        data = {
            "id": str(p.id),
            "title": title,
            "arxiv_id": p.arxiv_id,
            "abstract": (p.abstract or "")[:1000],
            "publication_date": str(p.publication_date) if p.publication_date else None,
            "read_status": p.read_status.value,
            "pdf_path": p.pdf_path,
            "has_embedding": p.embedding is not None,
            "categories": (p.metadata_json or {}).get("categories", []),
            "authors": (p.metadata_json or {}).get("authors", []),
        }
        return ToolResult(
            success=True,
            data=data,
            summary=f"论文: {title[:60]}" + ("..." if len(title) > 60 else ""),
        )


def _get_similar_papers(paper_id: str, top_k: int = 5) -> ToolResult:
    paper, err = _require_paper(paper_id)
    if err:
        return err
    pid = UUID(paper_id)
    if not paper.embedding:
        return ToolResult(
            success=False,
            summary="该论文未向量化，请先调用 embed_paper",
        )
    try:
        ids = RAGService().similar_papers(pid, top_k=top_k)
        items = []
        with session_scope() as session:
            repo = PaperRepository(session)
            for sid in ids:
                try:
                    sp = repo.get_by_id(sid)
                    items.append(
                        {
                            "id": str(sp.id),
                            "title": sp.title,
                            "arxiv_id": sp.arxiv_id,
                            "read_status": sp.read_status.value,
                        }
                    )
                except Exception:
                    items.append({"id": str(sid), "title": "未知论文"})
        titles = ", ".join(it["title"][:30] for it in items[:3])
        return ToolResult(
            success=True,
            data={
                "paper_id": paper_id,
                "similar_ids": [str(x) for x in ids],
                "items": items,
            },
            summary=f"找到 {len(ids)} 篇相似论文: {titles}{'...' if len(ids) > 3 else ''}",
        )
    except Exception as exc:
        logger.exception("get_similar_papers failed: %s", exc)
        return ToolResult(success=False, summary=f"查找相似论文失败: {exc!s}")


def _ask_knowledge_base(
    question: str,
    top_k: int = 5,
) -> Iterator[ToolProgress | ToolResult]:
    """迭代 RAG：多轮检索 + 自动评估答案质量"""
    with session_scope() as session:
        repo = PaperRepository(session)
        sample = repo.list_latest(limit=1)
        if not sample:
            yield ToolResult(
                success=False,
                summary="知识库为空，请先用 ingest_arxiv 导入论文",
            )
            return

    progress_msgs: list[str] = []

    def on_progress(msg: str) -> None:
        progress_msgs.append(msg)

    try:
        yield ToolProgress(message=f"开始迭代 RAG 检索：{question[:50]}...")
        resp = RAGService().ask_iterative(
            question=question,
            max_rounds=3,
            initial_top_k=top_k,
            on_progress=on_progress,
        )
        # 逐条发送进度
        for msg in progress_msgs:
            yield ToolProgress(message=msg)
    except Exception as exc:
        logger.exception("RAG iterative failed: %s", exc)
        yield ToolResult(success=False, summary=f"知识问答失败: {exc!s}")
        return

    evidence = getattr(resp, "evidence", []) or []
    rounds = getattr(resp, "rounds", 1)
    md_parts = [f"# 知识问答：{question}\n", resp.answer, "\n\n---\n## 引用来源\n"]
    for ev in evidence[:8]:
        md_parts.append(f"- **{ev.get('title', '未知')}**\n  {ev.get('snippet', '')[:200]}\n")
    if rounds > 1:
        md_parts.append(f"\n> 经过 {rounds} 轮迭代检索优化答案\n")
    markdown = "\n".join(md_parts)
    yield ToolResult(
        success=True,
        data={
            "answer": resp.answer,
            "cited_paper_ids": [str(x) for x in resp.cited_paper_ids],
            "evidence": evidence[:5],
            "rounds": rounds,
            "title": f"知识问答：{question[:40]}",
            "markdown": markdown,
        },
        summary=f"已回答，引用 {len(resp.cited_paper_ids)} 篇论文（{rounds} 轮检索）",
    )


def _list_topics() -> ToolResult:
    try:
        with session_scope() as session:
            topics = TopicRepository(session).list_topics(enabled_only=False)
            items = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "query": t.query,
                    "enabled": t.enabled,
                    "paper_count": getattr(t, "paper_count", None),
                    "max_results_per_run": t.max_results_per_run,
                    "retry_limit": t.retry_limit,
                }
                for t in topics
            ]
        enabled = sum(1 for t in items if t["enabled"])
        names = ", ".join(t["name"] for t in items[:5])
        suffix = "..." if len(items) > 5 else ""
        return ToolResult(
            success=True,
            data={"topics": items, "count": len(items)},
            summary=f"共 {len(items)} 个主题: {names}{suffix}",
        )
    except Exception as exc:
        logger.exception("list_topics failed: %s", exc)
        return ToolResult(success=False, summary=f"列出主题失败: {exc!s}")


def _get_system_status() -> ToolResult:
    try:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        from packages.storage.models import Paper, TopicSubscription

        db_ok = check_db_connection()
        with session_scope() as session:
            paper_count = session.execute(sa_select(func.count()).select_from(Paper)).scalar() or 0
            embedded_count = (
                session.execute(
                    sa_select(func.count()).select_from(Paper).where(Paper.embedding.is_not(None))
                ).scalar()
                or 0
            )
            topic_count = (
                session.execute(sa_select(func.count()).select_from(TopicSubscription)).scalar()
                or 0
            )
            run_repo = PipelineRunRepository(session)
            runs = run_repo.list_latest(limit=10)
            recent_runs = [
                {
                    "pipeline": r.pipeline_name,
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "created_at": str(r.created_at) if r.created_at else None,
                }
                for r in runs[:5]
            ]
        return ToolResult(
            success=True,
            data={
                "db_connected": db_ok,
                "paper_count": paper_count,
                "embedded_count": embedded_count,
                "topic_count": topic_count,
                "recent_runs_count": len(recent_runs),
                "recent_runs": recent_runs,
            },
            summary=(
                f"论文 {paper_count} 篇（{embedded_count} 已向量化），"
                f"主题 {topic_count} 个" + ("" if db_ok else " ⚠️数据库异常")
            ),
        )
    except Exception as exc:
        logger.exception("get_system_status failed: %s", exc)
        return ToolResult(success=False, summary=f"获取系统状态失败: {exc!s}")


def _search_arxiv(
    query: str,
    max_results: int = 20,
    days_back: int = 180,
    sort_by: str = "submittedDate",
) -> ToolResult:
    """搜索 arXiv，返回候选论文列表（不入库）

    默认检索最近 180 天并按最新提交优先；需要经典/全时间段时传 days_back=0。
    """
    from packages.integrations.arxiv_client import ArxivClient

    try:
        papers = ArxivClient().fetch_latest(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            days_back=days_back,
        )
    except Exception as exc:
        logger.exception("ArXiv search failed: %s", exc)
        return ToolResult(success=False, summary=f"ArXiv 搜索失败: {exc!s}")

    if not papers:
        return ToolResult(
            success=True,
            data={"candidates": [], "count": 0, "query": query},
            summary="未找到相关论文",
        )

    candidates = []
    for i, p in enumerate(papers, 1):
        candidates.append(
            {
                "index": i,
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "abstract": (p.abstract or "")[:300],
                "publication_date": str(p.publication_date) if p.publication_date else None,
                "categories": (p.metadata or {}).get("categories", []),
                "authors": (p.metadata or {}).get("authors", [])[:5],
            }
        )

    return ToolResult(
        success=True,
        data={"candidates": candidates, "count": len(candidates), "query": query},
        summary=f"从 arXiv 搜索到 {len(candidates)} 篇候选论文",
    )


def _ingest_arxiv(
    query: str,
    arxiv_ids: list[str] | None = None,
) -> Iterator[ToolProgress | ToolResult]:
    """将用户选定的论文入库 → 自动分配主题 → 自动向量化 → 自动粗读"""
    from packages.domain.task_tracker import global_tracker
    from packages.integrations.arxiv_client import ArxivClient

    pipelines = PaperPipelines()
    topic_name = query.strip()
    _task_id = f"ingest_{uuid4().hex[:8]}"

    if not arxiv_ids:
        yield ToolResult(
            success=False,
            summary="请先用 search_arxiv 搜索，再提供要入库的 arxiv_ids 列表",
        )
        return

    yield ToolProgress(message="正在准备入库...", current=0, total=0)

    # 查找或创建 Topic
    topic_id: str | None = None
    is_new_topic = False
    try:
        with session_scope() as session:
            topic_repo = TopicRepository(session)
            topic = topic_repo.get_by_name(topic_name)
            if not topic:
                topic = topic_repo.upsert_topic(
                    name=topic_name,
                    query=topic_name,
                    enabled=False,
                )
                is_new_topic = True
            topic_id = topic.id
    except Exception as exc:
        logger.warning("Auto-create topic '%s' failed: %s", topic_name, exc)

    # 从 arXiv 拉取选中论文的完整信息并入库
    arxiv_client = ArxivClient()
    selected_set = set(arxiv_ids)
    inserted_ids: list[str] = []

    global_tracker.start(
        _task_id,
        "ingest",
        f"入库论文: {topic_name[:30]}",
        total=len(selected_set),
    )
    yield ToolProgress(
        message=f"正在下载 {len(selected_set)} 篇选中论文...",
        current=0,
        total=len(selected_set),
    )

    failed_papers: list[dict] = []
    ingested_papers: list[dict] = []
    selected_papers = []
    try:
        selected_papers = arxiv_client.fetch_by_ids(list(selected_set))
    except Exception as exc:
        logger.warning("Failed to fetch selected arXiv papers by id: %s", exc)
        failed_papers.extend(
            {
                "arxiv_id": arxiv_id,
                "title": "",
                "error": f"arXiv 元数据获取失败: {exc!s}"[:120],
                "status": "failed",
            }
            for arxiv_id in sorted(selected_set)
        )

    found_ids = {
        (paper.arxiv_id or "").split("v")[0] if paper.arxiv_id else ""
        for paper in selected_papers
    }
    selected_keys = {arxiv_id.split("v")[0] for arxiv_id in selected_set}
    missing_ids = selected_keys - found_ids
    for mid in sorted(missing_ids):
        failed_papers.append(
            {
                "arxiv_id": mid,
                "title": "",
                "error": "未能从 arXiv 获取元数据",
                "status": "failed",
            }
        )

    selected_papers = [
        paper
        for paper in selected_papers
        if paper.arxiv_id and paper.arxiv_id.split("v")[0] in selected_keys
    ]

    with session_scope() as session:
        repo = PaperRepository(session)
        from packages.domain.enums import ActionType
        from packages.storage.repositories import ActionRepository, PipelineRunRepository

        run_repo = PipelineRunRepository(session)
        action_repo = ActionRepository(session)
        note = f"selected {len(arxiv_ids)} from query={query}"
        run = run_repo.start("ingest_arxiv", decision_note=note)
        try:
            for idx, paper in enumerate(selected_papers, 1):
                try:
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(saved.id)
                    try:
                        pdf_path = arxiv_client.download_pdf(paper.arxiv_id)
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    ingested_papers.append(
                        {
                            "arxiv_id": paper.arxiv_id,
                            "title": (paper.title or "")[:80],
                            "status": "ok",
                        }
                    )
                except Exception as exc:
                    logger.warning("Ingest paper %s failed: %s", paper.arxiv_id, exc)
                    failed_papers.append(
                        {
                            "arxiv_id": paper.arxiv_id,
                            "title": (paper.title or "")[:80],
                            "error": str(exc)[:120],
                            "status": "failed",
                        }
                    )
                global_tracker.update(
                    _task_id,
                    current=idx,
                    message=f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}",
                )
                yield ToolProgress(
                    message=f"入库 {idx}/{len(selected_papers)}: {(paper.title or '')[:40]}",
                    current=idx,
                    total=len(selected_papers),
                )

            if inserted_ids:
                action_repo.create_action(
                    action_type=ActionType.agent_collect,
                    title=f"Agent 收集: {query[:80]}",
                    paper_ids=inserted_ids,
                    query=query,
                    topic_id=topic_id,
                )

            run_repo.finish(run.id)
        except Exception as exc:
            run_repo.fail(run.id, str(exc))
            raise

    if not inserted_ids:
        global_tracker.finish(_task_id, success=False, error="未能入库任何论文")
        yield ToolResult(
            success=len(failed_papers) == 0,
            data={
                "ingested": 0,
                "query": query,
                "failed": failed_papers,
            },
            summary="未能入库任何论文"
            + (f"，{len(failed_papers)} 篇失败" if failed_papers else ""),
        )
        return

    total = len(inserted_ids)
    global_tracker.update(
        _task_id,
        current=0,
        total=total,
        message=f"入库 {total} 篇，开始向量化和粗读...",
    )
    yield ToolProgress(
        message=f"入库 {total} 篇，开始向量化和粗读...",
        current=0,
        total=total,
    )

    # 向量化 + 粗读（论文间 + 论文内双重并行）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 最多 3 篇论文同时处理，每篇 2 个 API 调用 → 最多 6 并发
    PAPER_CONCURRENCY = 3

    # 获取所有论文标题（在 session 内）
    paper_titles: dict[str, str] = {}
    with session_scope() as sess:
        for pid_str in inserted_ids:
            try:
                p = PaperRepository(sess).get_by_id(UUID(pid_str))
                paper_titles[pid_str] = (p.title or "")[:40]
            except Exception:
                paper_titles[pid_str] = pid_str[:8]

    def _process_one(pid_str: str) -> tuple[bool, bool]:
        """单篇论文：embed ∥ skim 并行"""
        pid = UUID(pid_str)
        e_ok, s_ok = False, False
        with ThreadPoolExecutor(max_workers=2) as inner:
            fe = inner.submit(pipelines.embed_paper, pid)
            fs = inner.submit(pipelines.skim, pid)
            for fut in as_completed([fe, fs]):
                try:
                    fut.result()
                    if fut is fe:
                        e_ok = True
                    else:
                        s_ok = True
                except Exception as exc:
                    label = "embed" if fut is fe else "skim"
                    logger.warning(
                        "%s %s failed: %s",
                        label,
                        pid_str[:8],
                        exc,
                    )
        return e_ok, s_ok

    embed_ok, skim_ok, done = 0, 0, 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        future_map = {pool.submit(_process_one, pid_str): pid_str for pid_str in inserted_ids}
        for fut in as_completed(future_map):
            pid_str = future_map[fut]
            done += 1
            title = paper_titles.get(pid_str, pid_str[:8])
            try:
                e_ok_i, s_ok_i = fut.result()
                embed_ok += int(e_ok_i)
                skim_ok += int(s_ok_i)
            except Exception as exc:
                logger.warning("paper %s failed: %s", pid_str[:8], exc)
            global_tracker.update(
                _task_id,
                current=done,
                message=f"嵌入+粗读 {done}/{total}: {title}",
            )
            yield ToolProgress(
                message=f"完成 {done}/{total}: {title}",
                current=done,
                total=total,
            )

    global_tracker.finish(_task_id, success=True)

    yield ToolResult(
        success=True,
        data={
            "total": total,
            "embedded": embed_ok,
            "skimmed": skim_ok,
            "query": query,
            "topic": topic_name,
            "paper_ids": inserted_ids[:10],
            "ingested": ingested_papers,
            "failed": failed_papers,
        },
        summary=(
            f"入库 {total} 篇 → 主题「{topic_name}」，"
            f"向量化 {embed_ok}，粗读 {skim_ok}"
            + (f"，{len(failed_papers)} 篇失败已跳过" if failed_papers else "")
        ),
    )



def _suggest_keywords(description: str) -> ToolResult:
    """AI 生成 arXiv 搜索关键词建议"""
    from packages.ai.keyword_service import KeywordService

    try:
        suggestions = KeywordService().suggest(description.strip())
    except Exception as exc:
        logger.exception("Keyword suggestion failed: %s", exc)
        return ToolResult(success=False, summary=f"关键词建议生成失败: {exc!s}")
    if not suggestions:
        return ToolResult(
            success=True,
            data={"suggestions": []},
            summary="未能生成有效的关键词建议",
        )
    return ToolResult(
        success=True,
        data={"suggestions": suggestions},
        summary=f"生成了 {len(suggestions)} 组搜索关键词建议",
    )


def _skim_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    if not paper.abstract:
        yield ToolResult(success=False, summary="该论文缺少摘要，无法执行粗读")
        return
    pid = UUID(paper_id)
    title = (paper.title or "")[:40]
    yield ToolProgress(message=f"正在粗读「{title}」...", current=1, total=2)
    try:
        report = PaperPipelines().skim(pid)
        one_liner = report.one_liner
        yield ToolResult(
            success=True,
            data=report.model_dump(),
            summary=f"粗读完成: {one_liner[:80]}" + ("..." if len(one_liner) > 80 else ""),
        )
    except Exception as exc:
        logger.exception("skim_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"粗读失败: {exc!s}")


def _deep_read_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    if not paper.arxiv_id and not paper.pdf_path:
        yield ToolResult(success=False, summary="该论文无 arXiv ID 且无 PDF，无法精读")
        return
    pid = UUID(paper_id)
    title = (paper.title or "")[:40]
    yield ToolProgress(message=f"正在精读「{title}」，预计 30-60 秒...", current=1, total=3)
    try:
        report = PaperPipelines().deep_dive(pid)
        yield ToolResult(
            success=True,
            data=report.model_dump(),
            summary=f"精读完成: {(paper.title or '')[:60]}",
        )
    except Exception as exc:
        logger.exception("deep_read_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"精读失败: {exc!s}")


def _embed_paper(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    paper, err = _require_paper(paper_id)
    if err:
        yield err
        return
    pid = UUID(paper_id)
    if paper.embedding:
        yield ToolResult(
            success=True,
            data={"paper_id": paper_id, "status": "already_embedded"},
            summary="该论文已有向量，跳过",
        )
        return
    if not paper.title and not paper.abstract:
        yield ToolResult(
            success=False,
            summary="该论文缺少标题和摘要，无法向量化",
        )
        return
    yield ToolProgress(message="正在向量化...", current=1, total=2)
    try:
        PaperPipelines().embed_paper(pid)
        yield ToolResult(
            success=True,
            data={"paper_id": paper_id, "status": "embedded"},
            summary="向量化完成",
        )
    except Exception as exc:
        logger.exception("embed_paper failed: %s", exc)
        yield ToolResult(success=False, summary=f"向量化失败: {exc!s}")


def _generate_wiki(type: str, keyword_or_id: str):
    """Wiki 生成 - generator，yield 进度和最终结果"""
    import time

    from packages.domain.task_tracker import global_tracker

    if type == "topic":
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(query=keyword_or_id, limit=3)
            if not papers:
                yield ToolResult(
                    success=False,
                    summary=(f"知识库中没有与 '{keyword_or_id}' 相关的论文，请先导入"),
                )
                return

        # 提交后台任务
        gs = GraphService()
        task_id = global_tracker.submit(
            task_type="topic_wiki",
            title=f"Wiki: {keyword_or_id}",
            fn=lambda progress_callback=None: gs.topic_wiki(
                keyword=keyword_or_id,
                limit=120,
                progress_callback=progress_callback,
            ),
        )
        yield ToolProgress(
            message=f"已提交后台任务，正在为「{keyword_or_id}」生成 Wiki...",
            current=1,
            total=10,
        )

        # 轮询进度
        last_msg = ""
        while True:
            time.sleep(3)
            status = global_tracker.get_task(task_id)
            if not status:
                break
            if status.get("finished"):
                if not status.get("success"):
                    yield ToolResult(
                        success=False,
                        summary=f"Wiki 生成失败: {status.get('error', '未知错误')}",
                    )
                    return
                break
            msg = status.get("message", "")
            pct = status.get("progress_pct", 0)
            step = max(1, min(9, int(pct / 10)))
            if msg and msg != last_msg:
                yield ToolProgress(message=msg, current=step, total=10)
                last_msg = msg

        result = global_tracker.get_result(task_id) or {}
        result["title"] = f"Wiki: {keyword_or_id}"
        yield ToolProgress(message="Wiki 生成完毕", current=10, total=10)
    elif type == "paper":
        try:
            pid = UUID(keyword_or_id)
        except ValueError:
            yield ToolResult(success=False, summary="无效的 paper_id 格式")
            return
        with session_scope() as session:
            try:
                paper = PaperRepository(session).get_by_id(pid)
                paper_title = paper.title
            except ValueError:
                yield ToolResult(success=False, summary=f"论文 {keyword_or_id[:8]}... 不存在")
                return
        yield ToolProgress(message="正在为论文生成 Wiki...", current=1, total=2)
        result = GraphService().paper_wiki(paper_id=keyword_or_id)
        result["title"] = f"Wiki: {paper_title[:40]}"
        yield ToolProgress(message="Wiki 生成完毕，正在渲染...", current=2, total=2)
    else:
        yield ToolResult(success=False, summary=f"无效的 type: {type}，应为 topic 或 paper")
        return
    yield ToolResult(
        success=True,
        data=result,
        summary=f"已生成 {type} wiki",
    )


def _reasoning_analysis(paper_id: str) -> Iterator[ToolProgress | ToolResult]:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    with session_scope() as session:
        repo = PaperRepository(session)
        try:
            paper = repo.get_by_id(UUID(paper_id))
        except (ValueError, Exception) as exc:
            yield ToolResult(success=False, summary=f"论文不存在: {exc}")
            return
        title = paper.title

    yield ToolProgress(message=f"正在分析「{(title or '')[:30]}」的推理链...", current=1, total=2)
    svc = ReasoningService()
    try:
        result = svc.analyze(UUID(paper_id))
    except Exception as exc:
        yield ToolResult(success=False, summary=f"推理链分析失败: {exc}")
        return

    reasoning = result.get("reasoning", {})
    steps = reasoning.get("reasoning_steps", [])
    impact = reasoning.get("impact_assessment", {})

    step_lines = []
    for s in steps[:6]:
        step_lines.append(f"**{s.get('step', '')}**: {s.get('conclusion', '')}")

    scores_text = (
        f"创新性={impact.get('novelty_score', 0):.1f} "
        f"严谨性={impact.get('rigor_score', 0):.1f} "
        f"影响力={impact.get('impact_score', 0):.1f}"
    )

    summary = (
        f"「{title}」推理链分析完成\n\n"
        + "\n".join(step_lines)
        + f"\n\n**评分**: {scores_text}\n\n"
        + f"**综合评估**: {impact.get('overall_assessment', '')[:500]}"
    )

    yield ToolResult(
        success=True,
        data=reasoning,
        summary=summary,
    )
