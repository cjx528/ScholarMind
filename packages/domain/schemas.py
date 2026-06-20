from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PaperCreate(BaseModel):
    """论文创建数据模型 - 支持多渠道（ArXiv / OpenReview / DOI）"""

    # 新增字段（多渠道兼容）- MVP 阶段可选
    source: str = "arxiv"  # 渠道标识：arxiv / openreview / doi
    source_id: str | None = None  # 渠道唯一 ID（arxiv_id / openreview_forum / doi）
    doi: str | None = None  # DOI 号（可选）

    # 保留字段（向后兼容）- ArXiv 特定
    # @deprecated: 使用 source_id + source 字段代替
    arxiv_id: str | None = None  # ArXiv ID（可选，仅 ArXiv 渠道使用）

    # 通用字段
    title: str
    abstract: str
    publication_date: date | None = None
    metadata: dict = Field(default_factory=dict)

    @property
    def normalized_arxiv_id(self) -> str | None:
        """归一化的 arxiv_id 获取方法"""
        if self.source == "arxiv":
            return self.source_id or self.arxiv_id
        if self.source and self.source_id:
            return f"{self.source}:{self.source_id}"
        if self.doi:
            return f"doi:{self.doi}"
        return self.arxiv_id


class SkimReport(BaseModel):
    one_liner: str
    innovations: list[str]
    keywords: list[str] = []
    title_zh: str = ""
    abstract_zh: str = ""
    relevance_score: float


class DeepDiveReport(BaseModel):
    method_summary: str
    experiments_summary: str
    ablation_summary: str
    reviewer_risks: list[str]


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


class AskResponse(BaseModel):
    answer: str
    cited_paper_ids: list[UUID]
    evidence: list[dict] = Field(default_factory=list)
    rounds: int = 1


class PaperAskRequest(BaseModel):
    question: str
    selected_text: str | None = None
    source: str = "pdf_reader"
    analysis_scope: list[str] = Field(default_factory=lambda: ["skim", "deep", "reasoning"])
    page_number: int | None = None


class PaperAskResponse(BaseModel):
    answer: str
    used_context: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class TopicCreate(BaseModel):
    name: str
    query: str
    enabled: bool = True
    paused: bool = False
    sources: list[str] = Field(default_factory=lambda: ["arxiv"])
    keywords: list[str | dict[str, Any]] = Field(default_factory=list)
    intent_queries: list[str | dict[str, Any]] = Field(default_factory=list)
    max_results_per_run: int = 20
    retry_limit: int = 2
    schedule_frequency: str = "daily"
    schedule_time_utc: int = 21
    enable_date_filter: bool = False
    date_filter_days: int = 7


class TopicUpdate(BaseModel):
    query: str | None = None
    enabled: bool | None = None
    paused: bool | None = None
    sources: list[str] | None = None
    keywords: list[str | dict[str, Any]] | None = None
    intent_queries: list[str | dict[str, Any]] | None = None
    max_results_per_run: int | None = None
    retry_limit: int | None = None
    schedule_frequency: str | None = None
    schedule_time_utc: int | None = None
    enable_date_filter: bool | None = None
    date_filter_days: int | None = None


# ---------- LLM Provider Config ----------


class LLMProviderCreate(BaseModel):
    name: str
    provider: str  # openai / anthropic / zhipu / xiaomi
    api_key: str
    api_base_url: str | None = None
    model_skim: str
    model_deep: str
    model_vision: str | None = None
    model_embedding: str
    model_fallback: str


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model_skim: str | None = None
    model_deep: str | None = None
    model_vision: str | None = None
    model_embedding: str | None = None
    model_fallback: str | None = None


# ---------- Agent ----------


class AgentMessage(BaseModel):
    """Agent 对话消息"""

    role: str  # user / assistant / tool
    content: str = ""
    meta: dict | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None


class AgentChatRequest(BaseModel):
    """Agent 对话请求"""

    messages: list[AgentMessage]
    conversation_id: str | None = None
    confirmed_action_id: str | None = None


# ---------- API Request Bodies ----------


class ReferenceImportReq(BaseModel):
    source_paper_id: str
    source_paper_title: str = ""
    entries: list[dict]
    topic_ids: list[str] = []


class SuggestKeywordsReq(BaseModel):
    description: str


class AIExplainReq(BaseModel):
    text: str
    action: str = "explain"
