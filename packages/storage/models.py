"""
SQLAlchemy ORM 模型定义
@author ScholarMind Team
"""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.domain.enums import ActionType, PipelineStatus, ReadStatus
from packages.storage.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    read_status: Mapped[ReadStatus] = mapped_column(
        Enum(ReadStatus, name="read_status"),
        nullable=False,
        default=ReadStatus.unread,
        index=True,
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    favorited: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_papers_read_status_created_at", "read_status", "created_at"),)

    @property
    def source(self) -> str:
        return str((self.metadata_json or {}).get("source") or "arxiv")

    @property
    def source_id(self) -> str | None:
        value = (self.metadata_json or {}).get("source_id")
        return str(value) if value else None

    @property
    def doi(self) -> str | None:
        value = (self.metadata_json or {}).get("doi")
        return str(value) if value else None


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_dive_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_insights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    skim_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )



class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("source_paper_id", "target_paper_id", name="uq_citation_edge"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, name="pipeline_status"),
        nullable=False,
        default=PipelineStatus.pending,
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PromptTrace(Base):
    __tablename__ = "prompt_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_digest: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    input_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class TopicSubscription(Base):
    """Topic library entry."""

    __tablename__ = "topic_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    query: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_results_per_run: Mapped[int] = mapped_column(nullable=False, default=20)
    retry_limit: Mapped[int] = mapped_column(nullable=False, default=2)
    schedule_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    schedule_time_utc: Mapped[int] = mapped_column(nullable=False, default=21)

    # 完整版新增：多渠道支持
    sources: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["arxiv"]
    )  # ["arxiv", "openreview"]

    # 日期过滤配置
    enable_date_filter: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )  # 是否启用日期过滤
    date_filter_days: Mapped[int] = mapped_column(
        nullable=False, default=7
    )  # 日期范围（最近 N 天）

    intent_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "topic_id", name="uq_paper_topic"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("topic_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class LLMProviderConfig(Base):
    """用户可配置的 LLM 提供者"""

    __tablename__ = "llm_provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_skim: Mapped[str] = mapped_column(String(128), nullable=False)
    model_deep: Mapped[str] = mapped_column(String(128), nullable=False)
    model_vision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_embedding: Mapped[str] = mapped_column(String(128), nullable=False)
    model_fallback: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AppSetting(Base):
    """Global application setting stored as JSON."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class GeneratedContent(Base):
    """Generated Wiki and other reusable content."""

    __tablename__ = "generated_contents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    keyword: Mapped[str | None] = mapped_column(String(256), nullable=True)
    paper_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


# ========== Agent 对话相关 ==========


class AgentConversation(Base):
    """Agent 对话会话"""

    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AgentMessage(Base):
    """Agent 对话消息"""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,  # user/assistant/system
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


class AgentPendingAction(Base):
    """Agent 待确认操作 - 持久化存储"""

    __tablename__ = "agent_pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )

    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class CollectionAction(Base):
    """论文入库行动记录"""

    __tablename__ = "collection_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, name="action_type"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    query: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    topic_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("topic_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ActionPaper(Base):
    """行动-论文关联表"""

    __tablename__ = "action_papers"
    __table_args__ = (UniqueConstraint("action_id", "paper_id", name="uq_action_paper"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("collection_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class EmailConfig(Base):
    """Email configuration."""

    __tablename__ = "email_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    smtp_server: Mapped[str] = mapped_column(String(256), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sender_email: Mapped[str] = mapped_column(String(256), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(128), nullable=False, default="ScholarMind")
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    password: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Tag(Base):
    """用户自定义标签"""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    color: Mapped[str] = mapped_column(String(32), nullable=False, default="#3b82f6")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaperTag(Base):
    """论文-标签关联表"""

    __tablename__ = "paper_tags"
    __table_args__ = (UniqueConstraint("paper_id", "tag_id", name="uq_paper_tag"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)



# ========== Sensemaking 认知重构相关 ==========


class UserSchema(Base):
    __tablename__ = "user_schemas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    research_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    academic_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_challenges: Mapped[list[str]] = mapped_column(JSON, default=list)
    beliefs: Mapped[list[str]] = mapped_column(JSON, default=list)
    knowledge_gaps: Mapped[list[str]] = mapped_column(JSON, default=list)

    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SensemakingSession(Base):
    __tablename__ = "sensemaking_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_schema_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_schemas.id", ondelete="CASCADE"), nullable=False
    )

    act1_comprehension: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    act2_collision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    act3_reconstruction: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    conversation_history: Mapped[list[dict]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchemaPaperInteraction(Base):
    __tablename__ = "schema_paper_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_schema_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_schemas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    interaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cognitive_delta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


# ========== ScholarMind recommendation workspace ==========


class CompassUserProfile(Base):
    __tablename__ = "compass_user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    interests: Mapped[str] = mapped_column(Text, nullable=False, default="")
    research_directions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reading_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quick_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    questions_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    notes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    ai_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    codex_cli_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    codex_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=600000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CompassPreferenceModel(Base):
    __tablename__ = "compass_preference_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    weights_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    bias: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CompassAnalysisResult(Base):
    __tablename__ = "compass_analysis_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    raw_input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="done")
    paper_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recommendation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    analysis_blocks_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    trace_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    next_agent_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    user_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CompassFeedback(Base):
    __tablename__ = "compass_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    recommendation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("compass_analysis_results.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    factors_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    base_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
