/**
 * ScholarMind - API 服务层
 * @author ScholarMind Team
 */
import type {
  SystemStatus,
  Topic,
  TopicCreate,
  TopicUpdate,
  TopicFetchResult,
  Paper,
  PipelineRun,
  SkimReport,
  DeepDiveReport,
  AskRequest,
  AskResponse,
  PaperAskRequest,
  PaperAskResponse,
  PaperWiki,
  TopicWiki,
  CostMetrics,
  IngestResult,
  ArxivPreviewCandidate,
  ArxivPreviewResponse,
  KeywordSuggestion,
  ReasoningAnalysisResponse,
  FolderStats,
  TopicStatsResponse,
  PaperDistributionResponse,
  PaperListResponse,
  ReferenceImportEntry,
  ImportTaskStatus,
  CollectionAction,
  EmailConfig,
  EmailConfigForm,
  TaskStatus,
  ActiveTaskInfo,
  AIBackendConfig,
  LoginResponse,
  AuthStatusResponse,
  MultiSourceSearchResult,
  ChannelSuggestion,
  Tag,
  CompassBackend,
  CompassAnalysisResult,
  CompassPaperAnalysisResponse,
  CompassProfileBuildResponse,
  CompassProfileResponse,
  CompassPreferenceModel,
  CompassQueueResponse,
} from "@/types";

export type {
  TopicFetchResult,
  FolderStats,
  PaperListResponse,
  ReferenceImportEntry,
  ImportTaskStatus,
  CollectionAction,
  EmailConfig,
  EmailConfigForm,
  TaskStatus,
  ActiveTaskInfo,
  LoginResponse,
  AuthStatusResponse,
} from "@/types";
import { resolveApiBase } from "@/lib/tauri";

function getApiBase(): string {
  return resolveApiBase();
}
/** 获取认证 token */
function getAuthToken(): string | null {
  return localStorage.getItem("auth_token");
}

/** 检查是否已认证 */
export function isAuthenticated(): boolean {
  return !!getAuthToken();
}

/** 清除认证信息 */
export function clearAuth(): void {
  localStorage.removeItem("auth_token");
}

/** 按 HTTP 状态码映射友好文案（HTML/超长响应降级用） */
function friendlyStatusMessage(status: number, statusText: string): string {
  if (status === 408 || status === 504 || status === 524) {
    return "请求超时，服务端处理时间过长，请稍后重试";
  }
  if (status === 502 || status === 503) {
    return "服务暂时不可用，请稍后重试";
  }
  if (status === 500) {
    return "服务器内部错误，请稍后重试或联系管理员";
  }
  if (status === 429) {
    return "请求过于频繁，请稍后再试";
  }
  if (status === 404) {
    return "请求的资源不存在";
  }
  return `${status} ${statusText}`.trim() || "请求失败";
}

/** 从失败响应中安全提取错误消息：JSON 走字段，HTML/超长文本走状态码降级 */
async function extractErrorMessage(resp: Response): Promise<string> {
  const fallback = friendlyStatusMessage(resp.status, resp.statusText);
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const body = await resp.json();
      const msg = body?.message || body?.detail || body?.error;
      if (typeof msg === "string" && msg.trim()) return msg.trim();
    } catch {
      // JSON 解析失败，降级到 fallback
    }
    return fallback;
  }
  // 非 JSON（text/html / text/plain 等）：可能是 Cloudflare 504 HTML 页，不能原样抛
  try {
    const text = (await resp.text()).trim();
    if (!text) return fallback;
    // HTML 直接丢弃
    if (text.startsWith("<") || text.toLowerCase().includes("<!doctype")) {
      return fallback;
    }
    // 纯文本短消息可以采纳，超长一律降级
    if (text.length <= 200) return text;
    return fallback;
  } catch {
    return fallback;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${getApiBase().replace(/\/+$/, "")}${path}`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
        ...((options.headers as Record<string, string>) || {}),
      },
      ...options,
    });
  } catch {
    throw new Error("网络连接失败，请检查后端服务是否启动");
  }
  if (!resp.ok) {
    const msg = await extractErrorMessage(resp);
    // 401 未认证，清除 token 并刷新页面跳转登录
    if (resp.status === 401) {
      clearAuth();
      window.location.reload();
    }
    throw new Error(msg);
  }
  return resp.json();
}

function get<T>(path: string, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { signal: opts?.signal });
}

function post<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
    signal: opts?.signal,
  });
}

function patch<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body ?? {}),
    signal: opts?.signal,
  });
}

function put<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }) {
  return request<T>(path, {
    method: "PUT",
    body: JSON.stringify(body ?? {}),
    signal: opts?.signal,
  });
}

function del<T>(path: string, opts?: { signal?: AbortSignal }) {
  return request<T>(path, { method: "DELETE", signal: opts?.signal });
}

/* ========== 系统 ========== */
export const systemApi = {
  health: () => get<{ status: string; app: string; env: string }>("/health"),
  status: () => get<SystemStatus>("/system/status"),
};

/* ========== 主题 ========== */
export const topicApi = {
  list: (enabledOnly = false) => get<{ items: Topic[] }>(`/topics?enabled_only=${enabledOnly}`),
  create: (data: TopicCreate) => post<Topic>("/topics", data),
  update: (id: string, data: TopicUpdate) => patch<Topic>(`/topics/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/topics/${id}`),
  fetch: (id: string) => post<TopicFetchResult>(`/topics/${id}/fetch`),
  fetchStatus: (id: string) => get<TopicFetchResult>(`/topics/${id}/fetch-status`),
  suggestKeywords: (description: string) =>
    post<{ suggestions: KeywordSuggestion[] }>("/topics/suggest-keywords", { description }),
  stats: () => get<TopicStatsResponse>("/topics/stats"),
  distribution: () => get<PaperDistributionResponse>("/topics/distribution"),
};

/* ========== 标签 ========== */
export const tagApi = {
  list: () => get<{ items: Tag[] }>("/tags"),
  create: (name: string, color?: string) => {
    const params = new URLSearchParams({ name });
    if (color) params.append("color", color);
    return post<Tag>(`/tags?${params}`);
  },
  update: (id: string, data: { name?: string; color?: string }) => {
    const params = new URLSearchParams();
    if (data.name) params.append("name", data.name);
    if (data.color) params.append("color", data.color);
    return patch<Tag>(`/tags/${id}?${params}`);
  },
  delete: (id: string) =>
    del<{ deleted: string; name: string; paper_count: number }>(`/tags/${id}`),
  getPaperTags: (paperId: string) => get<{ items: Tag[] }>(`/papers/${paperId}/tags`),
  addPaperTag: (paperId: string, tagId: string) =>
    post<{ paper_id: string; tag: Tag }>(`/papers/${paperId}/tags?tag_id=${tagId}`),
  removePaperTag: (paperId: string, tagId: string) =>
    del<{ paper_id: string; tag_id: string; removed: boolean }>(`/papers/${paperId}/tags/${tagId}`),
  batchUpdatePaperTags: (paperId: string, tagIds: string[]) =>
    post<{ paper_id: string; items: Tag[] }>(`/papers/${paperId}/tags/batch`, tagIds),
};

/* ========== 论文 ========== */
export const paperApi = {
  latest: (
    opts: {
      page?: number;
      pageSize?: number;
      status?: string;
      topicId?: string;
      folder?: string;
      date?: string;
      search?: string;
      sortBy?: string;
      sortOrder?: string;
      category?: string;
      tagIds?: string[];
    } = {}
  ) => {
    const params = new URLSearchParams();
    params.set("page", String(opts.page || 1));
    params.set("page_size", String(opts.pageSize || 20));
    if (opts.status) params.append("status", opts.status);
    if (opts.topicId) params.append("topic_id", opts.topicId);
    if (opts.folder) params.append("folder", opts.folder);
    if (opts.date) params.append("date", opts.date);
    if (opts.search) params.append("search", opts.search);
    if (opts.sortBy) params.append("sort_by", opts.sortBy);
    if (opts.sortOrder) params.append("sort_order", opts.sortOrder);
    if (opts.category) params.append("category", opts.category);
    if (opts.tagIds && opts.tagIds.length > 0) {
      opts.tagIds.forEach((tid) => params.append("tag_ids", tid));
    }
    return get<PaperListResponse>(`/papers/latest?${params}`);
  },
  recommended: (topK = 50) =>
    get<{
      items: Paper[];
      model?: CompassPreferenceModel;
    }>(`/papers/recommended?top_k=${topK}`),
  folderStats: () => get<FolderStats>("/papers/folder-stats"),
  detail: (id: string) => get<Paper>(`/papers/${id}`),
  delete: (id: string) =>
    del<{
      deleted: string;
      title: string;
      arxiv_id?: string;
      pdf_removed: boolean;
      pdf_cleanup_error?: string | null;
      related?: Record<string, number>;
    }>(`/papers/${id}`),
  similar: (id: string, topK = 5) =>
    get<{
      paper_id: string;
      similar_ids: string[];
      items?: { id: string; title: string; arxiv_id?: string; read_status?: string }[];
    }>(`/papers/${id}/similar?top_k=${topK}`),
  toggleFavorite: (id: string) =>
    patch<{ id: string; favorited: boolean }>(`/papers/${id}/favorite`),
  reasoningAnalysis: (id: string) => post<ReasoningAnalysisResponse>(`/papers/${id}/reasoning`),
  pdfUrl: (id: string, arxivId?: string) => {
    const token = getAuthToken();
    const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
    return arxivId && !arxivId.startsWith("ss-")
      ? `${getApiBase().replace(/\/+$/, "")}/papers/proxy-arxiv-pdf/${arxivId}${suffix}`
      : `${getApiBase().replace(/\/+$/, "")}/papers/${id}/pdf${suffix}`;
  },
  downloadPdf: (id: string) =>
    post<{ status: string; pdf_path: string; source?: string; arxiv_id?: string }>(
      `/papers/${id}/download-pdf`
    ),
  aiExplain: (id: string, text: string, action: "explain" | "translate" | "summarize") =>
    post<{ action: string; result: string }>(`/papers/${id}/ai/explain`, { text, action }),
  ask: (id: string, data: PaperAskRequest) =>
    post<PaperAskResponse>(`/papers/${id}/ask`, data),
  multiSourceSearch: (query: string, channels: string[]) => {
    const params = new URLSearchParams({
      query,
      channels: channels.join(","),
    });
    return post<MultiSourceSearchResult>(`/papers/search-multi?${params}`).then((res) => ({
      results: res.papers || [],
      channelStats: res.channel_stats,
    }));
  },
  suggestChannels: (query: string) =>
    get<ChannelSuggestion>(`/papers/suggest-channels?query=${encodeURIComponent(query)}`),
  enrichVenues: () =>
    post<{ total: number; updated: number; items: Array<{ id: string; venue?: string | null }> }>(
      "/papers/venues/enrich"
    ),
};

export const compassApi = {
  profile: () => get<CompassProfileResponse>("/recommendation/profile"),
  updateProfile: (data: {
    interests?: string;
    researchDirections?: string;
    readingGoal?: string;
    quickProfile?: Record<string, unknown>;
  }) => put<CompassProfileResponse>("/recommendation/profile", data),
  buildProfile: (data: {
    source: string;
    answers?: { question: string; answer: string }[];
    currentProfile?: Record<string, unknown>;
    quickProfile?: Record<string, unknown>;
    backend?: CompassBackend;
  }) => post<CompassProfileBuildResponse>("/recommendation/profile/build", data),
  analyze: (data: {
    input?: string;
    paper_id?: string | null;
    mode?: string;
    backend?: CompassBackend;
  }) => post<CompassAnalysisResult>("/recommendation/analyze", data),
  paperAnalysis: (paperId: string) =>
    get<CompassPaperAnalysisResponse>(`/recommendation/papers/${paperId}/analysis`),
  queue: (topK = 20) => get<CompassQueueResponse>(`/recommendation/queue?top_k=${topK}`),
  feedback: (data: {
    recommendation_id?: string | null;
    paper_id?: string | null;
    rating: number;
    notes?: string;
    factors?: Record<string, number>;
    base_score?: number;
  }) =>
    post<{ feedback_id: string; model: CompassQueueResponse["model"] }>(
      "/recommendation/feedback",
      data
    ),
  resetModel: () => post<{ model: CompassQueueResponse["model"] }>("/recommendation/model/reset"),
};

export const ingestApi = {
  arxivPreview: (
    query: string,
    maxResults = 20,
    sortBy = "submittedDate",
    daysBack = 180,
    csOnly = true
  ) => {
    const params = new URLSearchParams({
      query,
      max_results: String(maxResults),
      sort_by: sortBy,
      days_back: String(daysBack),
      cs_only: String(csOnly),
    });
    return post<ArxivPreviewResponse>(`/ingest/arxiv/preview?${params}`);
  },
  arxivSelected: (query: string, arxivIds: string[], topicId?: string) =>
    post<IngestResult>("/ingest/arxiv/selected", {
      query,
      arxiv_ids: arxivIds,
      topic_id: topicId || null,
    }),
  searchPreview: (
    query: string,
    maxResults = 20,
    sources: string[] = ["arxiv"],
    sortBy = "submittedDate",
    daysBack = 180,
    csOnly = true
  ) => {
    const params = new URLSearchParams({
      query,
      max_results: String(maxResults),
      sort_by: sortBy,
      days_back: String(daysBack),
      cs_only: String(csOnly),
    });
    sources.forEach((source) => params.append("sources", source));
    return post<ArxivPreviewResponse>(`/ingest/search/preview?${params}`);
  },
  searchSelected: (query: string, candidates: ArxivPreviewCandidate[]) =>
    post<IngestResult>("/ingest/search/selected", {
      query,
      candidates,
    }),
  arxiv: (
    query: string,
    maxResults = 20,
    topicId?: string,
    sortBy = "submittedDate",
    daysBack = 0
  ) => {
    const params = new URLSearchParams({
      query,
      max_results: String(maxResults),
      sort_by: sortBy,
      days_back: String(daysBack),
    });
    if (topicId) params.append("topic_id", topicId);
    return post<IngestResult>(`/ingest/arxiv?${params}`);
  },
  importReferences: (data: {
    source_paper_id: string;
    source_paper_title: string;
    entries: ReferenceImportEntry[];
    topic_ids?: string[];
  }) => post<{ task_id: string; total: number }>("/ingest/references", data),
  importStatus: (taskId: string) => get<ImportTaskStatus>(`/ingest/references/status/${taskId}`),
};

/* ========== Pipeline ========== */
export const pipelineApi = {
  skim: (paperId: string) => post<SkimReport>(`/pipelines/skim/${paperId}`),
  deep: (paperId: string) => post<DeepDiveReport>(`/pipelines/deep/${paperId}`),
  embed: (paperId: string) =>
    post<{ status: string; paper_id: string }>(`/pipelines/embed/${paperId}`),
  runs: (limit = 30) => get<{ items: PipelineRun[] }>(`/pipelines/runs?limit=${limit}`),
};

/* ========== RAG ========== */
export const ragApi = {
  ask: (data: AskRequest) => post<AskResponse>("/rag/ask", data),
};

/* ========== 行动记录 ========== */
export const actionApi = {
  list: (opts: { actionType?: string; topicId?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.actionType) params.set("action_type", opts.actionType);
    if (opts.topicId) params.set("topic_id", opts.topicId);
    if (opts.limit) params.set("limit", String(opts.limit));
    if (opts.offset) params.set("offset", String(opts.offset));
    return get<{ items: CollectionAction[]; total: number }>(`/actions?${params}`);
  },
  detail: (id: string) => get<CollectionAction>(`/actions/${id}`),
  papers: (id: string, limit = 200) =>
    get<{
      action_id: string;
      items: {
        id: string;
        title: string;
        arxiv_id: string;
        publication_date: string | null;
        read_status: string;
      }[];
    }>(`/actions/${id}/papers?limit=${limit}`),
};

/* ========== Wiki ========== */
export const wikiApi = {
  paper: (paperId: string) => get<PaperWiki>(`/wiki/paper/${paperId}`),
  topic: (keyword: string, limit = 120) =>
    get<TopicWiki>(`/wiki/topic?keyword=${encodeURIComponent(keyword)}&limit=${limit}`),
};

/* ========== 生成内容历史 ========== */
import type { GeneratedContent, GeneratedContentListItem } from "@/types";

export const generatedApi = {
  list: (type: string, limit = 50) =>
    get<{ items: GeneratedContentListItem[] }>(`/generated/list?type=${type}&limit=${limit}`),
  byTask: (taskId: string) => get<GeneratedContent>(`/generated/by-task/${taskId}`),
  detail: (id: string) => get<GeneratedContent>(`/generated/${id}`),
  delete: (id: string) => del<{ deleted: string }>(`/generated/${id}`),
};

/* ========== 任务 ========== */
export const jobApi = {
  batchProcessUnread: (maxPapers = 50) =>
    post<{ processed: number; failed: number; total: number; message: string }>(
      `/jobs/batch-process-unread?max_papers=${maxPapers}`
    ),
};

/* ========== 指标 ========== */
export const metricsApi = {
  costs: (days = 7) => get<CostMetrics>(`/metrics/costs?days=${days}`),
};

/* ========== LLM 配置 ========== */
import type {
  LLMProviderConfig,
  LLMProviderCreate,
  LLMProviderUpdate,
  ActiveLLMConfig,
} from "@/types";

export const llmConfigApi = {
  list: () => get<{ items: LLMProviderConfig[] }>("/settings/llm-providers"),
  create: (data: LLMProviderCreate) => post<LLMProviderConfig>("/settings/llm-providers", data),
  update: (id: string, data: LLMProviderUpdate) =>
    patch<LLMProviderConfig>(`/settings/llm-providers/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/settings/llm-providers/${id}`),
  activate: (id: string) => post<LLMProviderConfig>(`/settings/llm-providers/${id}/activate`),
  deactivate: () => post<{ status: string }>("/settings/llm-providers/deactivate"),
  active: () => get<ActiveLLMConfig>("/settings/llm-providers/active"),
};

export const aiBackendApi = {
  get: () => get<AIBackendConfig>("/settings/ai-backend"),
  update: (data: AIBackendConfig) => put<AIBackendConfig>("/settings/ai-backend", data),
};

/* ========== Agent ========== */
import type { AgentMessage } from "@/types";

async function fetchSSE(url: string, init?: RequestInit): Promise<Response> {
  const authHeaders: Record<string, string> = {};
  const token = getAuthToken();
  if (token) {
    authHeaders["Authorization"] = `Bearer ${token}`;
  }
  const resp = await fetch(url, {
    ...init,
    headers: {
      ...authHeaders,
      ...((init?.headers as Record<string, string>) || {}),
    },
  });
  if (!resp.ok) {
    if (resp.status === 401) {
      clearAuth();
      window.location.reload();
    }
    const msg = await extractErrorMessage(resp);
    throw new Error(`请求失败 (${resp.status}): ${msg}`);
  }
  return resp;
}

export const agentApi = {
  chat: async (
    messages: AgentMessage[],
    conversationId?: string,
    confirmedActionId?: string,
    signal?: AbortSignal
  ): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/chat`;
    return fetchSSE(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        messages,
        conversation_id: conversationId || null,
        confirmed_action_id: confirmedActionId || null,
      }),
    });
  },
  confirm: async (actionId: string, signal?: AbortSignal): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/confirm/${actionId}`;
    return fetchSSE(url, { method: "POST", signal });
  },
  reject: async (actionId: string, signal?: AbortSignal): Promise<Response> => {
    const url = `${getApiBase().replace(/\/+$/, "")}/agent/reject/${actionId}`;
    return fetchSSE(url, { method: "POST", signal });
  },
};

/* ========== 邮箱配置 ========== */
export const emailConfigApi = {
  list: () => get<EmailConfig[]>("/settings/email-configs"),
  create: (data: EmailConfigForm) => post<EmailConfig>("/settings/email-configs", data),
  update: (id: string, data: Partial<EmailConfigForm>) =>
    patch<EmailConfig>(`/settings/email-configs/${id}`, data),
  delete: (id: string) => del<{ deleted: string }>(`/settings/email-configs/${id}`),
  activate: (id: string) => post<EmailConfig>(`/settings/email-configs/${id}/activate`),
  test: (id: string) => post<{ status: string }>(`/settings/email-configs/${id}/test`),
  smtpPresets: () =>
    get<Record<string, { smtp_server: string; smtp_port: number; smtp_use_tls: boolean }>>(
      "/settings/smtp-presets"
    ),
};

/* ========== 后台任务 ========== */
export const tasksApi = {
  active: () => get<{ tasks: ActiveTaskInfo[] }>("/tasks/active"),
  startTopicWiki: (keyword: string, limit = 120) =>
    post<{ task_id: string; status: string }>(
      `/tasks/wiki/topic?keyword=${encodeURIComponent(keyword)}&limit=${limit}`
    ),
  startPaperWiki: (paperId: string) =>
    post<{ task_id: string; status: string; paper_id?: string; title?: string }>(
      `/tasks/wiki/paper/${encodeURIComponent(paperId)}`
    ),
  getStatus: (taskId: string) => get<TaskStatus>(`/tasks/${taskId}`),
  getResult: (taskId: string) => get<Record<string, unknown>>(`/tasks/${taskId}/result`),
  list: (taskType?: string, limit = 20) =>
    get<{ tasks: TaskStatus[] }>(
      `/tasks?${taskType ? `task_type=${taskType}&` : ""}limit=${limit}`
    ),
  track: (body: {
    action: string;
    task_id: string;
    task_type?: string;
    title?: string;
    total?: number;
    current?: number;
    message?: string;
    success?: boolean;
    error?: string;
  }) => post<{ ok: boolean }>("/tasks/track", body),
};

/* ========== 认证 ========== */

export const authApi = {
  login: (password: string) => post<LoginResponse>("/auth/login", { password }),
  status: () => get<AuthStatusResponse>("/auth/status"),
};
