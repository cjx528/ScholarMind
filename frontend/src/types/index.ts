/**
 * ScholarMind - TypeScript 类型定义
 * @author ScholarMind Team
 */

/* ========== 系统 ========== */
export interface HealthResponse {
  status: string;
  app: string;
  env: string;
}

export interface SystemStatus {
  health: HealthResponse;
  counts: {
    topics: number;
    enabled_topics: number;
    papers_latest_200: number;
    runs_latest_50: number;
    failed_runs_latest_50: number;
  };
  latest_run: PipelineRun | null;
}

/* ========== 主题 ========== */
export type ScheduleFrequency = "daily" | "twice_daily" | "weekdays" | "weekly";

export interface QueryProfileKeyword {
  keyword: string;
  query?: string;
  weight?: number;
  [key: string]: unknown;
}

export interface QueryProfileIntent {
  label?: string;
  query: string;
  weight?: number;
  [key: string]: unknown;
}

export interface Topic {
  id: string;
  name: string;
  query: string;
  enabled: boolean;
  paused?: boolean;
  sources?: string[];
  keywords?: QueryProfileKeyword[];
  intent_queries?: QueryProfileIntent[];
  max_results_per_run: number;
  retry_limit: number;
  schedule_frequency: ScheduleFrequency;
  schedule_time_utc: number;
  enable_date_filter: boolean;
  date_filter_days: number;
  paper_count?: number;
  last_run_at?: string | null;
  last_run_count?: number | null;
}

export interface TopicCreate {
  name: string;
  query: string;
  enabled?: boolean;
  paused?: boolean;
  sources?: string[];
  keywords?: Array<string | QueryProfileKeyword>;
  intent_queries?: Array<string | QueryProfileIntent>;
  max_results_per_run?: number;
  retry_limit?: number;
  schedule_frequency?: ScheduleFrequency;
  schedule_time_utc?: number;
  enable_date_filter?: boolean;
  date_filter_days?: number;
}

export interface TopicUpdate {
  query?: string;
  enabled?: boolean;
  paused?: boolean;
  sources?: string[];
  keywords?: Array<string | QueryProfileKeyword>;
  intent_queries?: Array<string | QueryProfileIntent>;
  max_results_per_run?: number;
  retry_limit?: number;
  schedule_frequency?: ScheduleFrequency;
  schedule_time_utc?: number;
  enable_date_filter?: boolean;
  date_filter_days?: number;
}

export interface KeywordSuggestion {
  name: string;
  query: string;
  reason: string;
}

export interface TopicStats {
  topic_id: string;
  topic_name: string;
  paper_count: number;
  total_citations: number;
  recent_30d: number;
  status_dist: {
    unread: number;
    skimmed: number;
    deep_read: number;
  };
}

export interface TopicStatsResponse {
  topics: TopicStats[];
}

export interface PaperDistributionStats {
  by_year: { year: string; count: number }[];
  by_source: { source: string; raw_source: string; count: number }[];
}

export interface PaperDistributionResponse {
  by_year: { year: string; count: number }[];
  by_source: { source: string; raw_source: string; count: number }[];
  by_status: { status: string; raw_status: string; count: number }[];
  by_month: { month: string; count: number }[];
  by_venue: { venue: string; count: number }[];
  by_action_source: { source: string; raw_source: string; count: number }[];
}

/* ========== 抓取任务 ========== */
export interface TopicFetchResult {
  topic_id: string;
  topic_name?: string;
  status: string;
  inserted: number;
  processed?: number;
  attempts?: number;
  error?: string;
  topic?: Topic;
}

/* ========== 标签 ========== */
export interface Tag {
  id: string;
  name: string;
  color: string;
  paper_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface TagCreate {
  name: string;
  color?: string;
}

export interface TagUpdate {
  name?: string;
  color?: string;
}

/* ========== 论文 ========== */
export type ReadStatus = "unread" | "skimmed" | "deep_read";

export interface Paper {
  id: string;
  title: string;
  arxiv_id: string;
  abstract: string;
  publication_date?: string;
  read_status: ReadStatus;
  pdf_path?: string;
  metadata?: Record<string, unknown>;
  has_embedding?: boolean;
  favorited?: boolean;
  categories?: string[];
  keywords?: string[];
  authors?: string[];
  venue?: string | null;
  venue_type?: string | null;
  venue_confidence?: number | null;
  venue_source?: string | null;
  title_zh?: string;
  abstract_zh?: string;
  topics?: string[];
  tags?: Tag[];
  final_score?: number;
  similarity?: number;
  recommendation?: CompassRecommendation;
  source_type?: string;
  skim_report?: {
    summary_md: string;
    skim_score: number | null;
    key_insights: Record<string, unknown>;
  } | null;
  deep_report?: {
    deep_dive_md: string;
    key_insights: Record<string, unknown>;
  } | null;
}

/* ========== Pipeline ========== */
export type PipelineStatus = "pending" | "running" | "succeeded" | "failed";

export interface PipelineRun {
  id: string;
  pipeline_name: string;
  paper_id: string;
  status: PipelineStatus;
  decision_note?: string;
  elapsed_ms?: number;
  error_message?: string;
  created_at: string;
}

export interface SkimReport {
  one_liner: string;
  innovations: string[];
  relevance_score: number;
}

export interface DeepDiveReport {
  method_summary: string;
  experiments_summary: string;
  ablation_summary: string;
  reviewer_risks: string[];
}

/* ========== RAG ========== */
export interface AskRequest {
  question: string;
  top_k?: number;
}

export interface AskResponse {
  answer: string;
  cited_paper_ids: string[];
  evidence: Record<string, unknown>[];
}

export interface PaperAskRequest {
  question: string;
  selected_text?: string | null;
  source?: "pdf_reader" | "analysis";
  analysis_scope?: ("skim" | "deep" | "reasoning")[];
  page_number?: number | null;
}

export interface PaperAskResponse {
  answer: string;
  used_context: string[];
  confidence: number;
}

export interface TimelineEntry {
  paper_id: string;
  title: string;
  year: number;
  indegree: number;
  outdegree: number;
  pagerank: number;
  seminal_score: number;
  why_seminal?: string;
  external?: boolean;
  source?: string;
  citation_count?: number;
}

export interface TimelineResponse {
  keyword: string;
  timeline: TimelineEntry[];
  seminal: TimelineEntry[];
  milestones: TimelineEntry[];
}

export interface SurveyResponse {
  keyword: string;
  summary: {
    overview: string;
    stages: string[];
    reading_list: string[];
    open_questions: string[];
  };
  milestones: TimelineEntry[];
  seminal: TimelineEntry[];
}

/* ========== Wiki ========== */
export interface WikiSection {
  title: string;
  content: string;
  key_insight?: string;
}

export interface PdfExcerpt {
  title: string;
  excerpt: string;
}

export interface ScholarMetadataItem {
  title: string;
  year?: number;
  citationCount?: number;
  influentialCitationCount?: number;
  venue?: string;
  fieldsOfStudy?: string[];
  tldr?: string;
  source?: string;
  externalSource?: string;
}

export interface TopicWikiContent {
  overview: string;
  sections: WikiSection[];
  key_findings: string[];
  methodology_evolution: string;
  future_directions: string[];
  citation_contexts?: string[];
  pdf_excerpts?: PdfExcerpt[];
  scholar_metadata?: ScholarMetadataItem[];
}

export interface PaperWikiContent {
  summary: string;
  contributions: string[];
  methodology: string;
  significance: string;
  limitations: string[];
  related_work_analysis: string;
  citation_contexts?: string[];
  pdf_excerpts?: PdfExcerpt[];
  scholar_metadata?: ScholarMetadataItem[];
}

export interface PaperWiki {
  paper_id: string;
  title?: string;
  markdown: string;
  wiki_content?: PaperWikiContent;
  content_id?: string;
}

export interface TopicWiki {
  keyword: string;
  markdown: string;
  wiki_content?: TopicWikiContent;
  timeline: TimelineResponse;
  survey: SurveyResponse;
  content_id?: string;
}

/* ========== 推理链分析 ========== */
export interface ReasoningStep {
  step: string;
  thinking: string;
  conclusion: string;
}

export interface MethodChain {
  problem_definition: string;
  core_hypothesis: string;
  method_derivation: string;
  theoretical_basis: string;
  innovation_analysis: string;
}

export interface ExperimentChain {
  experimental_design: string;
  baseline_fairness: string;
  result_validation: string;
  ablation_insights: string;
}

export interface ImpactAssessment {
  novelty_score: number;
  rigor_score: number;
  impact_score: number;
  overall_assessment: string;
  strengths: string[];
  weaknesses: string[];
  future_suggestions: string[];
}

export interface ReasoningChainResult {
  reasoning_steps: ReasoningStep[];
  method_chain: MethodChain;
  experiment_chain: ExperimentChain;
  impact_assessment: ImpactAssessment;
}

export interface ReasoningAnalysisResponse {
  paper_id: string;
  title: string;
  reasoning: ReasoningChainResult;
}

/* ========== 生成内容 ========== */
export interface GeneratedContent {
  id: string;
  content_type: "topic_wiki" | "paper_wiki";
  title: string;
  keyword?: string;
  paper_id?: string;
  markdown: string;
  metadata_json?: Record<string, unknown>;
  created_at: string;
}

export interface GeneratedContentListItem {
  id: string;
  content_type: string;
  title: string;
  keyword?: string;
  paper_id?: string;
  created_at: string;
}

/* ========== 指标 ========== */
export interface CostStage {
  stage: string;
  calls: number;
  total_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CostModel {
  provider: string;
  model: string;
  calls: number;
  total_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface CostMetrics {
  window_days: number;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  by_stage: CostStage[];
  by_model: CostModel[];
}

/* ========== 摄入 ========== */
export interface IngestPaper {
  id: string;
  title: string;
  arxiv_id?: string;
  source?: string | null;
  publication_date?: string | null;
  status?: "new" | "existing" | "failed";
  error?: string;
  topic_id?: string | null;
  topic_name?: string | null;
}

export interface IngestResult {
  ingested: number;
  new_count?: number;
  existing_count?: number;
  papers?: IngestPaper[];
  failed?: IngestPaper[];
}

export interface ArxivPreviewCandidate {
  id?: string;
  source?: string;
  source_id?: string | null;
  doi?: string | null;
  arxiv_id: string;
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  primary_category?: string | null;
  publication_date?: string | null;
  venue?: string | null;
  exists: boolean;
  match_score: number;
  match_reasons: string[];
  url?: string | null;
  topic_id?: string | null;
  topic_name?: string | null;
  topic_confidence?: number;
  topic_reason?: string;
  sources?: { channel: string; [key: string]: unknown }[];
  metadata?: Record<string, unknown>;
}

export interface ArxivPreviewResponse {
  query: string;
  effective_query: string;
  suggestions: string[];
  notes: string[];
  sort_by: string;
  days_back?: number;
  cs_only: boolean;
  sources?: string[];
  channel_stats?: Record<string, { total: number; new: number; duplicates: number; error?: string }>;
  candidates: ArxivPreviewCandidate[];
  total: number;
  existing_count: number;
}

export type SearchPreviewCandidate = ArxivPreviewCandidate;

/* ========== 多源搜索 ========== */
export interface MultiSourcePaper {
  id: string;
  title: string;
  authors?: string[];
  abstract?: string;
  year?: number | null;
  venue?: string | null;
  sources: { channel: string; [key: string]: unknown }[];
}

export interface MultiSourceSearchResult {
  papers: MultiSourcePaper[];
  channel_stats?: Record<string, { total: number; new: number; duplicates: number; error?: string }>;
}

export interface ChannelSuggestion {
  recommended: string[];
  alternatives: string[];
  reasoning: string;
}

/* ========== User profile recommendation ========== */
export type CompassBackend = "auto" | "llm" | "codex";
export type CompassFactorKey =
  | "profileFit"
  | "novelty"
  | "paperImportance"
  | "sourceSignal"
  | "actionability"
  | "freshness";

export type CompassRecommendationFactors = Record<CompassFactorKey, number>;

export interface CompassPreferenceModel {
  weights: CompassRecommendationFactors;
  bias: number;
  ratingCount: number;
}

export interface CompassUserProfile {
  user_id: string;
  interests: string;
  researchDirections: string;
  readingGoal: string;
  quickProfile: Record<string, unknown>;
  questions: CompassProfileQuestion[];
  notes: string[];
  confidence: number;
}

export interface AIBackendConfig {
  backend: Exclude<CompassBackend, "auto">;
  codexCliPath: string;
  codexTimeoutMs: number;
}

export interface CompassProfileQuestion {
  id: string;
  question: string;
  why: string;
  placeholder: string;
}

export interface CompassRecommendation {
  score: number;
  reason: string;
  factors: CompassRecommendationFactors;
}

export interface CompassPaperProfile {
  title: string;
  authors: string[];
  venue: string | null;
  plainSummary: string | null;
  confidence: number;
}

export interface CompassAnalysisBlock {
  type: "text" | "image";
  heading: string | null;
  body: string | null;
  url: string | null;
  caption: string | null;
  alt: string | null;
}

export interface CompassAnalysisResult {
  id: string;
  user_id?: string;
  paper_id?: string | null;
  raw_input?: string;
  source_url?: string | null;
  source_type: string;
  status: "done" | "needs-browser" | "failed" | "library";
  paper: CompassPaperProfile;
  recommendation: CompassRecommendation;
  final_score: number;
  analysis_blocks?: CompassAnalysisBlock[];
  trace?: string[];
  next_agent_prompt?: string;
  ai_backend?: CompassBackend;
  user_rating?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  title?: string;
  arxiv_id?: string;
  abstract?: string;
  similarity?: number;
  keywords?: string[];
  categories?: string[];
  authors?: string[];
}

export interface CompassPaperAnalysisResponse {
  analysis: CompassAnalysisResult | null;
  profile_changed: boolean;
  profile_hash_known: boolean;
  current_profile_hash: string;
  analysis_profile_hash?: string | null;
}

export interface CompassProfileResponse {
  profile: CompassUserProfile;
  model: CompassPreferenceModel;
}

export interface CompassProfileBuildResponse {
  profile: CompassUserProfile;
  questions: CompassProfileQuestion[];
  notes: string[];
  confidence: number;
  ai_backend: CompassBackend;
}

export interface CompassQueueResponse {
  items: CompassAnalysisResult[];
  model: CompassPreferenceModel;
}

/* ========== 聊天消息 ========== */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  cited_paper_ids?: string[];
  evidence?: Record<string, unknown>[];
  timestamp: Date;
}

/* ========== LLM 配置 ========== */
export type LLMProvider = "openai" | "anthropic" | "zhipu" | "xiaomi";

export interface LLMProviderConfig {
  id: string;
  name: string;
  provider: LLMProvider;
  api_key_masked: string;
  api_base_url?: string | null;
  model_skim: string;
  model_deep: string;
  model_vision?: string | null;
  model_embedding: string;
  model_fallback: string;
  is_active: boolean;
}

export interface LLMProviderCreate {
  name: string;
  provider: LLMProvider;
  api_key: string;
  api_base_url?: string;
  model_skim: string;
  model_deep: string;
  model_vision?: string;
  model_embedding: string;
  model_fallback: string;
}

export interface LLMProviderUpdate {
  name?: string;
  provider?: string;
  api_key?: string;
  api_base_url?: string;
  model_skim?: string;
  model_deep?: string;
  model_vision?: string;
  model_embedding?: string;
  model_fallback?: string;
}

export interface ActiveLLMConfig {
  source: "database" | "env";
  config: LLMProviderConfig & { provider?: string };
}

/* ========== Agent ========== */
export interface AgentMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: Record<string, unknown>;
}

export interface AgentToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface PendingAction {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  description: string;
}

/* ========== 论文列表 ========== */
export interface FolderStats {
  total: number;
  favorites: number;
  recent_7d: number;
  unclassified: number;
  by_topic: { topic_id: string; topic_name: string; count: number }[];
  by_status: Record<string, number>;
  by_date: { date: string; count: number }[];
}

export interface PaperListResponse {
  items: Paper[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/* ========== 引用入库 ========== */
export interface ReferenceImportEntry {
  scholar_id: string | null;
  title: string;
  year: number | null;
  venue: string | null;
  citation_count: number | null;
  arxiv_id: string | null;
  abstract: string | null;
  direction?: string;
}

export interface ImportTaskStatus {
  task_id: string;
  status: "running" | "completed" | "failed";
  total: number;
  completed: number;
  imported: number;
  skipped: number;
  failed: number;
  current: string;
  error?: string;
  results: { title: string; status: string; reason?: string; paper_id?: string; source?: string }[];
}

/* ========== 行动记录 ========== */
export interface CollectionAction {
  id: string;
  action_type: string;
  title: string;
  query: string | null;
  topic_id: string | null;
  paper_count: number;
  created_at: string;
}

/* ========== 邮箱配置 ========== */
export interface EmailConfig {
  id: string;
  name: string;
  smtp_server: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  sender_email: string;
  sender_name: string;
  username: string;
  is_active: boolean;
  created_at: string;
}

export interface EmailConfigForm {
  name: string;
  smtp_server: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  sender_email: string;
  sender_name: string;
  username: string;
  password: string;
}

/* ========== 后台任务 ========== */
export interface TaskStatus {
  task_id: string;
  task_type: string;
  title: string;
  status?: "pending" | "running" | "completed" | "failed";
  progress?: number;
  progress_pct?: number;
  current?: number;
  total?: number;
  message: string;
  error: string | null;
  created_at: number;
  updated_at?: number;
  elapsed_seconds?: number;
  finished?: boolean;
  success?: boolean;
  has_result: boolean;
}

export interface ActiveTaskInfo {
  task_id: string;
  task_type: string;
  title: string;
  current: number;
  total: number;
  message: string;
  elapsed_seconds: number;
  progress_pct: number;
  finished: boolean;
  success: boolean;
  error: string | null;
  category?: string;
  created_at?: number;
}

/* ========== 认证 ========== */
export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface AuthStatusResponse {
  auth_enabled: boolean;
}

export type SSEEventType =
  | "text_delta"
  | "tool_start"
  | "tool_result"
  | "tool_progress"
  | "action_confirm"
  | "action_result"
  | "done"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
}

/**
 * 解析 SSE 文本流
 */
export function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
  onDone?: () => void,
): () => void {
  const decoder = new TextDecoder();
  let buffer = "";
  let cancelled = false;
  // 跨 chunk 保留事件类型
  let currentEvent = "";

  const processBuffer = () => {
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const dataStr = line.slice(6);
        try {
          const data = JSON.parse(dataStr);
          onEvent({ type: currentEvent as SSEEventType, data });
        } catch (e) {
          console.warn("[SSE] Failed to parse:", currentEvent, dataStr.slice(0, 200), e);
        }
        currentEvent = "";
      }
    }
  };

  const read = async () => {
    try {
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        processBuffer();
      }
      // 流结束时处理残余数据
      if (buffer.trim()) {
        buffer += "\n";
        processBuffer();
      }
    } finally {
      onDone?.();
    }
  };

  read();

  return () => {
    cancelled = true;
    reader.cancel();
  };
}
