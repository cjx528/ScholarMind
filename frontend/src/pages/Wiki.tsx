/**
 * Wiki - Manus 风格结构化知识百科
 * @author ScholarMind Team
 */
import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense } from "react";
import { Card, CardHeader, Button, Tabs, Spinner, Empty } from "@/components/ui";
import { generatedApi, tasksApi } from "@/services/api";
import { useGlobalTasks } from "@/contexts/GlobalTaskContext";
import type {
  PaperWiki,
  TopicWiki,
  TopicWikiContent,
  PaperWikiContent,
  WikiSection,
  TimelineEntry,
  PdfExcerpt,
  ScholarMetadataItem,
  GeneratedContentListItem,
  GeneratedContent,
  TaskStatus,
  ActiveTaskInfo,
} from "@/types";
const Markdown = lazy(() => import("@/components/Markdown"));
import {
  Search,
  BookOpen,
  FileText,
  Clock,
  Trash2,
  ChevronRight,
  Lightbulb,
  TrendingUp,
  AlertCircle,
  Layers,
  Star,
  ArrowRight,
  Compass,
  GraduationCap,
  Link2,
  ExternalLink,
  Quote,
  Loader2,
} from "lucide-react";

const wikiTabs = [
  { id: "topic", label: "主题 Wiki" },
  { id: "paper", label: "论文 Wiki" },
];

type WikiTaskKind = "topic" | "paper";

type ActiveWikiTask = {
  taskId: string;
  kind: WikiTaskKind;
  contentType: "topic_wiki" | "paper_wiki";
  keyword?: string;
  paperId?: string;
  label?: string;
};

type ActiveWikiTaskMap = Partial<Record<WikiTaskKind, ActiveWikiTask>>;

type WikiTaskState = {
  progress: number;
  message: string;
};

const ACTIVE_WIKI_TASK_KEY = "scholarmind.activeWikiTask";
const ACTIVE_WIKI_TASKS_KEY = "scholarmind.activeWikiTasks";

function contentTypeForWikiKind(kind: WikiTaskKind): ActiveWikiTask["contentType"] {
  return kind === "topic" ? "topic_wiki" : "paper_wiki";
}

function getTaskProgress(status: TaskStatus) {
  if (typeof status.progress === "number") return Math.max(0, Math.min(1, status.progress));
  if (typeof status.progress_pct === "number") return Math.max(0, Math.min(1, status.progress_pct / 100));
  if (status.total && status.total > 0) return Math.max(0, Math.min(1, (status.current || 0) / status.total));
  return 0;
}

function taskFinished(status: TaskStatus) {
  return Boolean(status.finished) || status.status === "completed" || status.status === "failed";
}

function taskSucceeded(status: TaskStatus) {
  if (typeof status.success === "boolean") return status.success;
  return status.status === "completed";
}

function validateActiveWikiTask(task: Partial<ActiveWikiTask> | null | undefined): ActiveWikiTask | null {
  if (!task?.taskId || (task.kind !== "topic" && task.kind !== "paper")) return null;
  return {
    taskId: task.taskId,
    kind: task.kind,
    contentType: task.contentType || contentTypeForWikiKind(task.kind),
    keyword: task.keyword,
    paperId: task.paperId,
    label: task.label,
  };
}

function wikiTaskFromTrackedTask(task: ActiveTaskInfo): ActiveWikiTask | null {
  if (task.task_type !== "topic_wiki" && task.task_type !== "paper_wiki") return null;
  const kind: WikiTaskKind = task.task_type === "paper_wiki" ? "paper" : "topic";
  return {
    taskId: task.task_id,
    kind,
    contentType: contentTypeForWikiKind(kind),
    label: task.title,
  };
}

function saveActiveWikiTasks(tasks: ActiveWikiTask[]) {
  try {
    localStorage.setItem(ACTIVE_WIKI_TASKS_KEY, JSON.stringify(tasks));
    localStorage.removeItem(ACTIVE_WIKI_TASK_KEY);
  } catch {
    /* ignore storage errors */
  }
}

function persistActiveWikiTask(task: ActiveWikiTask) {
  const existing = readActiveWikiTasks().filter((item) => item.kind !== task.kind);
  saveActiveWikiTasks([...existing, task]);
}

function readActiveWikiTasks(): ActiveWikiTask[] {
  try {
    const multiRaw = localStorage.getItem(ACTIVE_WIKI_TASKS_KEY);
    if (multiRaw) {
      const parsed = JSON.parse(multiRaw);
      if (Array.isArray(parsed)) {
        return parsed
          .map((item) => validateActiveWikiTask(item as Partial<ActiveWikiTask>))
          .filter((item): item is ActiveWikiTask => Boolean(item));
      }
    }

    const raw = localStorage.getItem(ACTIVE_WIKI_TASK_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<ActiveWikiTask>;
    const task = validateActiveWikiTask(parsed);
    return task ? [task] : [];
  } catch {
    return [];
  }
}

function clearActiveWikiTasks() {
  try {
    localStorage.removeItem(ACTIVE_WIKI_TASKS_KEY);
    localStorage.removeItem(ACTIVE_WIKI_TASK_KEY);
  } catch {
    /* ignore storage errors */
  }
}

function generatedItemMatchesTask(item: GeneratedContentListItem, task: ActiveWikiTask) {
  if (item.content_type !== task.contentType) return false;
  if (task.kind === "topic") {
    const keyword = (task.keyword || "").trim().toLowerCase();
    if (!keyword) return false;
    return (
      (item.keyword || "").trim().toLowerCase() === keyword ||
      item.title.trim().toLowerCase() === `topic wiki: ${keyword}`
    );
  }
  const paperId = (task.paperId || "").trim();
  if (!paperId) return false;
  return item.paper_id === paperId || item.title.includes(paperId.slice(0, 8));
}

export default function Wiki() {
  const { tasks: globalTasks } = useGlobalTasks();
  const [activeTab, setActiveTab] = useState("topic");
  const [keyword, setKeyword] = useState("");
  const [paperId, setPaperId] = useState("");
  const [topicWiki, setTopicWiki] = useState<TopicWiki | null>(null);
  const [paperWiki, setPaperWiki] = useState<PaperWiki | null>(null);
  const [queryError, setQueryError] = useState("");

  /* 后台任务状态 */
  const [activeWikiTasks, setActiveWikiTasks] = useState<ActiveWikiTaskMap>({});
  const [taskStates, setTaskStates] = useState<Record<string, WikiTaskState>>({});
  const pollTimerRefs = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const activeTabRef = useRef(activeTab);
  const handledGlobalWikiTaskIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    return () => {
      Object.values(pollTimerRefs.current).forEach((timer) => clearTimeout(timer));
      pollTimerRefs.current = {};
    };
  }, []);

  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  /* 历史记录 */
  const [history, setHistory] = useState<GeneratedContentListItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedContent, setSelectedContent] = useState<GeneratedContent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const contentType = activeTab === "topic" ? "topic_wiki" : "paper_wiki";
  const activeKind: WikiTaskKind = activeTab === "paper" ? "paper" : "topic";
  const activeTaskForTab = activeWikiTasks[activeKind] ?? null;
  const activeTaskList = useMemo(
    () => Object.values(activeWikiTasks).filter((task): task is ActiveWikiTask => Boolean(task)),
    [activeWikiTasks]
  );
  const loading = Boolean(activeTaskForTab);

  const loadHistory = useCallback(async (type: string) => {
    setHistoryLoading(true);
    try {
      const res = await generatedApi.list(type, 50);
      setHistory(res.items);
    } catch {
      /* */
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory(contentType);
  }, [contentType, loadHistory]);

  const showGeneratedContent = useCallback((content: GeneratedContent) => {
    setSelectedContent(content);
    setTopicWiki(null);
    setPaperWiki(null);
    if (content.content_type === "topic_wiki") setActiveTab("topic");
    if (content.content_type === "paper_wiki") setActiveTab("paper");
  }, []);

  const loadTaskResultContent = useCallback(
    async (task: ActiveWikiTask, display: boolean): Promise<boolean> => {
      let contentId = "";
      try {
        const result = await tasksApi.getResult(task.taskId);
        contentId = String(result.content_id || "");
      } catch {
        /* fallback to generated history below */
      }

      if (contentId) {
        const content = await generatedApi.detail(contentId);
        if (display) showGeneratedContent(content);
        return true;
      }

      try {
        const content = await generatedApi.byTask(task.taskId);
        if (content.content_type === task.contentType) {
          if (display) showGeneratedContent(content);
          return true;
        }
      } catch {
        /* fallback to strict identity matching below */
      }

      const result = await generatedApi.list(task.contentType, 50);
      const matchedItem = result.items?.find((item) => generatedItemMatchesTask(item, task));
      if (matchedItem) {
        const content = await generatedApi.detail(matchedItem.id);
        if (display) showGeneratedContent(content);
        return true;
      }
      return false;
    },
    [showGeneratedContent]
  );

  const upsertActiveWikiTask = useCallback((task: ActiveWikiTask) => {
    persistActiveWikiTask(task);
    setActiveWikiTasks((prev) => {
      const next = { ...prev, [task.kind]: task };
      saveActiveWikiTasks(Object.values(next).filter((item): item is ActiveWikiTask => Boolean(item)));
      return next;
    });
  }, []);

  const removeActiveWikiTask = useCallback((task: ActiveWikiTask) => {
    setActiveWikiTasks((prev) => {
      const next = { ...prev };
      if (next[task.kind]?.taskId === task.taskId) delete next[task.kind];
      const remaining = Object.values(next).filter((item): item is ActiveWikiTask => Boolean(item));
      if (remaining.length) saveActiveWikiTasks(remaining);
      else clearActiveWikiTasks();
      return next;
    });
  }, []);

  const pollTask = useCallback(
    (task: ActiveWikiTask) => {
      if (pollTimerRefs.current[task.taskId]) clearTimeout(pollTimerRefs.current[task.taskId]);
      upsertActiveWikiTask(task);
      setTaskStates((prev) => ({
        ...prev,
        [task.taskId]: prev[task.taskId] || { progress: 0, message: "任务已提交，正在初始化..." },
      }));

      const poll = async (): Promise<void> => {
        try {
          const status: TaskStatus = await tasksApi.getStatus(task.taskId);
          setTaskStates((prev) => ({
            ...prev,
            [task.taskId]: {
              progress: getTaskProgress(status),
              message: status.message || "处理中...",
            },
          }));

          if (taskFinished(status)) {
            if (taskSucceeded(status)) {
              await loadTaskResultContent(task, activeTabRef.current === task.kind);
            } else {
              setTaskStates((prev) => ({
                ...prev,
                [task.taskId]: {
                  progress: getTaskProgress(status),
                  message: status.error || "Wiki 生成失败",
                },
              }));
            }
            removeActiveWikiTask(task);
            delete pollTimerRefs.current[task.taskId];
            loadHistory(task.contentType);
            return;
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : "";
          if (message.includes("404") || /not found/i.test(message)) {
            await loadTaskResultContent(task, activeTabRef.current === task.kind);
            removeActiveWikiTask(task);
            delete pollTimerRefs.current[task.taskId];
            loadHistory(task.contentType);
            return;
          }
          pollTimerRefs.current[task.taskId] = setTimeout(poll, 5000);
          return;
        }
        pollTimerRefs.current[task.taskId] = setTimeout(poll, 2000);
      };
      void poll();
    },
    [loadHistory, loadTaskResultContent, removeActiveWikiTask, upsertActiveWikiTask]
  );

  useEffect(() => {
    const savedTasks = readActiveWikiTasks();
    if (savedTasks.length) {
      savedTasks.forEach((task) => pollTask(task));
    }

    let cancelled = false;
    tasksApi
      .active()
      .then((res) => {
        if (cancelled) return;
        const runningWikiTasks = res.tasks.filter(
          (task) =>
            !task.finished && (task.task_type === "topic_wiki" || task.task_type === "paper_wiki")
        );
        runningWikiTasks.forEach((runningWiki) => {
          const kind: WikiTaskKind = runningWiki.task_type === "paper_wiki" ? "paper" : "topic";
          pollTask({
            taskId: runningWiki.task_id,
            kind,
            contentType: contentTypeForWikiKind(kind),
          });
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [pollTask]);

  useEffect(() => {
    globalTasks.forEach((trackedTask) => {
      const task = wikiTaskFromTrackedTask(trackedTask);
      if (!task) return;

      if (!trackedTask.finished) {
        handledGlobalWikiTaskIdsRef.current.delete(task.taskId);
        if (!pollTimerRefs.current[task.taskId]) {
          pollTask(task);
        }
        return;
      }

      if (handledGlobalWikiTaskIdsRef.current.has(task.taskId)) return;
      handledGlobalWikiTaskIdsRef.current.add(task.taskId);

      if (trackedTask.success) {
        void loadTaskResultContent(task, activeTabRef.current === task.kind).finally(() => {
          removeActiveWikiTask(task);
          loadHistory(task.contentType);
        });
      } else {
        removeActiveWikiTask(task);
      }
    });
  }, [globalTasks, loadHistory, loadTaskResultContent, pollTask, removeActiveWikiTask]);

  const handleQuery = async () => {
    if (activeTaskForTab) return;
    setSelectedContent(null);
    setQueryError("");
    try {
      if (activeTab === "topic" && keyword.trim()) {
        // 后台任务模式
        const cleanKeyword = keyword.trim();
        const { task_id } = await tasksApi.startTopicWiki(cleanKeyword);
        const task: ActiveWikiTask = {
          taskId: task_id,
          kind: "topic",
          contentType: "topic_wiki",
          keyword: cleanKeyword,
          label: `Wiki: ${cleanKeyword}`,
        };
        setTaskStates((prev) => ({
          ...prev,
          [task_id]: { progress: 0, message: "任务已提交，正在初始化..." },
        }));
        persistActiveWikiTask(task);
        pollTask(task);
        return;
      } else if (activeTab === "paper" && paperId.trim()) {
        const cleanPaperId = paperId.trim();
        const { task_id, paper_id, title } = await tasksApi.startPaperWiki(cleanPaperId);
        const task: ActiveWikiTask = {
          taskId: task_id,
          kind: "paper",
          contentType: "paper_wiki",
          paperId: paper_id || cleanPaperId,
          label: `Paper Wiki: ${title || cleanPaperId}`,
        };
        setTaskStates((prev) => ({
          ...prev,
          [task_id]: { progress: 0, message: "任务已提交，正在初始化..." },
        }));
        persistActiveWikiTask(task);
        pollTask(task);
        return;
      }
      loadHistory(contentType);
    } catch (error) {
      setQueryError(error instanceof Error ? error.message : "Wiki 任务提交失败");
    }
  };

  const handleViewHistory = async (item: GeneratedContentListItem) => {
    setDetailLoading(true);
    setTopicWiki(null);
    setPaperWiki(null);
    try {
      const detail = await generatedApi.detail(item.id);
      setSelectedContent(detail);
    } catch {
      /* */
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDeleteHistory = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await generatedApi.delete(id);
      setHistory((prev) => prev.filter((h) => h.id !== id));
      if (selectedContent?.id === id) setSelectedContent(null);
    } catch {
      /* */
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Shanghai",
    });
  };

  /* 当前应渲染的结构化数据 */
  const topicContent: TopicWikiContent | null = topicWiki?.wiki_content ?? null;
  const paperContent: PaperWikiContent | null = paperWiki?.wiki_content ?? null;

  const hasContent = !!(topicContent || paperContent || selectedContent);

  return (
    <div className="animate-fade-in space-y-6">
      {/* 页面头 */}
      <div className="page-hero rounded-2xl p-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 rounded-xl p-2.5">
            <GraduationCap className="text-primary h-5 w-5" />
          </div>
          <div>
            <h1 className="text-ink text-2xl font-bold">Wiki</h1>
            <p className="text-ink-secondary mt-0.5 text-sm">
              AI 驱动的结构化知识百科，基于真实论文数据生成
            </p>
          </div>
        </div>
      </div>

      <Tabs
        tabs={wikiTabs}
        active={activeTab}
        onChange={(t) => {
          setActiveTab(t);
          setSelectedContent(null);
          setTopicWiki(null);
          setPaperWiki(null);
          setQueryError("");
        }}
      />

      {/* 搜索 */}
      <div className="border-border bg-surface rounded-2xl border p-6 shadow-sm">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="text-ink-tertiary absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2" />
            {activeTab === "topic" ? (
              <input
                placeholder="输入主题关键词，如: attention mechanism, transformer..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleQuery()}
                className="border-border bg-page text-ink placeholder:text-ink-placeholder focus:border-primary focus:ring-primary/20 h-11 w-full rounded-xl border pr-4 pl-10 text-sm focus:ring-2 focus:outline-none"
              />
            ) : (
              <input
                placeholder="输入论文 ID..."
                value={paperId}
                onChange={(e) => setPaperId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleQuery()}
                className="border-border bg-page text-ink placeholder:text-ink-placeholder focus:border-primary focus:ring-primary/20 h-11 w-full rounded-xl border pr-4 pl-10 text-sm focus:ring-2 focus:outline-none"
              />
            )}
          </div>
          <Button icon={<BookOpen className="h-4 w-4" />} onClick={handleQuery} loading={loading}>
            生成 Wiki
          </Button>
        </div>
        {queryError && (
          <div className="mt-3 flex items-start gap-2 rounded-xl border border-error/20 bg-error/5 px-3 py-2 text-sm text-error">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{queryError}</span>
          </div>
        )}
      </div>

      {/* 生成中 — 支持主题 Wiki 与论文 Wiki 并行 */}
      {activeTaskList.length > 0 && (
        <div className="mx-auto w-full max-w-2xl py-6">
          <div className="border-border bg-card rounded-2xl border p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-3">
              <div className="relative">
                <div className="border-primary/20 border-t-primary h-10 w-10 animate-spin rounded-full border-[3px]" />
                <BookOpen className="text-primary absolute top-1/2 left-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2" />
              </div>
              <div>
                <p className="text-ink text-sm font-semibold">Wiki 后台生成中</p>
                <p className="text-ink-tertiary text-xs">
                  主题 Wiki 和论文 Wiki 可以同时运行，完成后会写入对应历史记录
                </p>
              </div>
            </div>

            <div className="space-y-3">
              {activeTaskList.map((task) => {
                const state = taskStates[task.taskId] || { progress: 0, message: "处理中..." };
                const label = task.kind === "topic" ? "主题 Wiki" : "论文 Wiki";
                const title = task.keyword || task.paperId || task.label || task.taskId;
                return (
                  <div key={task.taskId} className="rounded-xl border border-border bg-page p-3">
                    <div className="text-ink-secondary flex items-center justify-between gap-3 text-xs">
                      <span className="min-w-0 truncate">
                        <span className="font-medium text-ink">{label}</span>
                        <span className="mx-1 text-ink-tertiary">·</span>
                        {title}
                      </span>
                      <span className="tabular-nums">{Math.round(state.progress * 100)}%</span>
                    </div>
                    <div className="bg-primary/10 mt-2 h-2 w-full overflow-hidden rounded-full">
                      <div
                        className="from-primary to-primary/70 h-full rounded-full bg-gradient-to-r transition-all duration-700 ease-out"
                        style={{ width: `${Math.max(2, state.progress * 100)}%` }}
                      />
                    </div>
                    <p className="text-ink-tertiary mt-1 text-[11px]">{state.message}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 主体：左侧历史 + 右侧内容 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* 左侧历史 */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader
              title="历史记录"
              action={<span className="text-ink-tertiary text-xs">{history.length} 条</span>}
            />
            {historyLoading ? (
              <Spinner text="加载中..." />
            ) : history.length === 0 ? (
              <Empty title="暂无历史记录" />
            ) : (
              <div className="max-h-[70vh] space-y-1 overflow-y-auto">
                {history.map((item) => (
                  <div
                    key={item.id}
                    onClick={() => handleViewHistory(item)}
                    className={`group hover:bg-primary/5 flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 transition-colors ${selectedContent?.id === item.id ? "bg-primary/10 text-primary" : "text-ink"}`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <div className="text-ink-tertiary mt-0.5 flex items-center gap-1 text-xs">
                        <Clock className="h-3 w-3" />
                        <span>{formatTime(item.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => handleDeleteHistory(item.id, e)}
                        className="text-ink-tertiary hover:bg-error/10 hover:text-error rounded p-1 opacity-0 transition-opacity group-hover:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                      <ChevronRight className="text-ink-tertiary h-4 w-4" />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 右侧内容区 */}
        <div className="space-y-6 lg:col-span-4">
          {detailLoading && <Spinner text="加载内容..." />}

          {/* 历史内容展示（markdown） */}
          {!detailLoading && selectedContent && (
            <MarkdownArticle
              title={selectedContent.title}
              markdown={selectedContent.markdown}
              metadata={selectedContent.metadata_json}
            />
          )}

          {/* === 主题 Wiki 结构化渲染 === */}
          {!loading && !selectedContent && topicContent && topicWiki && (
            <TopicWikiView
              content={topicContent}
              keyword={topicWiki.keyword}
              timeline={topicWiki.timeline}
              survey={topicWiki.survey}
            />
          )}

          {/* === 论文 Wiki 结构化渲染 === */}
          {!loading && !selectedContent && paperContent && paperWiki && (
            <PaperWikiView
              content={paperContent}
              title={paperWiki.title || ""}
            />
          )}

          {/* 空状态 */}
          {!detailLoading && !loading && !hasContent && (
            <Card className="flex items-center justify-center py-20">
              <div className="text-center">
                <GraduationCap className="text-ink-tertiary/30 mx-auto h-16 w-16" />
                <p className="text-ink-tertiary mt-4 text-sm">
                  输入关键词生成全面的主题百科，或从左侧选择历史记录
                </p>
                <p className="text-ink-tertiary/60 mt-1 text-xs">
                  Wiki 基于知识库中的真实论文数据，结合 AI 生成结构化内容
                </p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

/* ===========================================================
 * 主题 Wiki 结构化视图 (Manus 风格)
 * =========================================================== */
function TopicWikiView({
  content,
  keyword,
  timeline,
  survey,
}: {
  content: TopicWikiContent;
  keyword: string;
  timeline: TopicWiki["timeline"];
  survey: TopicWiki["survey"];
}) {
  return (
    <div className="animate-fade-in space-y-6">
      {/* 标题头 */}
      <div className="border-primary/20 from-primary/5 rounded-xl border bg-gradient-to-br to-transparent p-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 flex h-10 w-10 items-center justify-center rounded-lg">
            <BookOpen className="text-primary h-5 w-5" />
          </div>
          <div>
            <h2 className="text-ink text-xl font-bold">{keyword}</h2>
            <p className="text-ink-secondary text-sm">主题百科 · AI 生成</p>
          </div>
        </div>
      </div>

      {/* 概述 */}
      {content.overview && (
        <Card>
          <CardHeader title="概述" action={<Compass className="text-primary h-5 w-5" />} />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.overview}</Markdown></Suspense>
          </div>
        </Card>
      )}

      {/* 章节 */}
      {content.sections?.length > 0 &&
        content.sections.map((sec, idx) => <SectionCard key={sec.title || `section-${idx}`} section={sec} index={idx} />)}

      {/* 方法论演化 */}
      {content.methodology_evolution && (
        <Card>
          <CardHeader title="方法论演化" action={<TrendingUp className="text-accent h-5 w-5" />} />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.methodology_evolution}</Markdown></Suspense>
          </div>
        </Card>
      )}

      {/* 引用上下文 + PDF + Scholar */}
      <CitationContextsCard contexts={content.citation_contexts || []} />
      <PdfExcerptsCard excerpts={content.pdf_excerpts || []} />
      <ScholarMetadataCard items={content.scholar_metadata || []} />

      {/* 关键发现 */}
      {content.key_findings?.length > 0 && (
        <Card>
          <CardHeader title="关键发现" action={<Lightbulb className="text-warning h-5 w-5" />} />
          <div className="space-y-3">
            {content.key_findings.map((finding, i) => (
              <div key={`${finding}-${i}`} className="bg-warning/5 flex gap-3 rounded-lg p-3">
                <span className="bg-warning/10 text-warning flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold">
                  {i + 1}
                </span>
                <p className="text-ink text-sm leading-relaxed">{finding}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 里程碑论文时间线 */}
      {timeline?.milestones?.length > 0 && (
        <Card>
          <CardHeader
            title="里程碑论文"
            description="按年份排列的领域关键论文"
            action={<Star className="text-primary h-5 w-5" />}
          />
          <TimelineView entries={timeline.milestones} />
        </Card>
      )}

      {/* 最具影响力论文 */}
      {timeline?.seminal?.length > 0 && (
        <Card>
          <CardHeader title="最具影响力论文" description="融合本地引用图与联网外部引用量" />
          <div className="grid gap-3 sm:grid-cols-2">
            {timeline.seminal.slice(0, 8).map((s, i) => (
              <div
                key={`${s.title}-${i}`}
                className="border-border hover:border-primary/30 hover:bg-primary/3 flex items-start gap-3 rounded-lg border p-3 transition-colors"
              >
                <span className="bg-primary/10 text-primary flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold">
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-ink text-sm leading-tight font-medium">{s.title}</p>
                  <div className="text-ink-tertiary mt-1 flex items-center gap-2 text-xs">
                    <span>{s.year}</span>
                    <span>·</span>
                    {s.external && s.citation_count != null ? (
                      <span>{s.citation_count.toLocaleString()} 引用</span>
                    ) : (
                      <span>影响力 {s.seminal_score.toFixed(2)}</span>
                    )}
                    {s.external && (
                      <>
                        <span>·</span>
                        <span className="text-primary">外部 {s.source || "source"}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 综述阶段 */}
      {survey?.summary?.stages?.length > 0 && (
        <Card>
          <CardHeader title="发展阶段" action={<Layers className="text-accent h-5 w-5" />} />
          <div className="space-y-4">
            {survey.summary.stages.map(
              (stage: { name: string; description: string } | string, i: number) => {
                const name = typeof stage === "string" ? stage : stage.name;
                const desc = typeof stage === "string" ? "" : stage.description;
                return (
                  <div key={`${name}-${i}`} className="relative pl-8">
                    <div className="bg-accent/10 absolute top-1 left-0 flex h-6 w-6 items-center justify-center rounded-full">
                      <span className="text-accent text-xs font-bold">{i + 1}</span>
                    </div>
                    {i < (survey?.summary?.stages?.length || 0) - 1 && (
                      <div className="bg-accent/20 absolute top-7 left-3 h-full w-px" />
                    )}
                    <div>
                      <h4 className="text-ink text-sm font-semibold">{name}</h4>
                      {desc && (
                        <p className="text-ink-secondary mt-1 text-sm leading-relaxed">{desc}</p>
                      )}
                    </div>
                  </div>
                );
              }
            )}
          </div>
        </Card>
      )}

      {/* 未来方向 */}
      {content.future_directions?.length > 0 && (
        <Card>
          <CardHeader
            title="未来研究方向"
            action={<ArrowRight className="text-success h-5 w-5" />}
          />
          <div className="space-y-2">
            {content.future_directions.map((dir, i) => (
              <div key={`dir-${i}`} className="bg-success/5 flex gap-3 rounded-lg p-3">
                <Compass className="text-success mt-0.5 h-4 w-4 shrink-0" />
                <p className="text-ink text-sm">{dir}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 开放问题 */}
      {survey?.summary?.open_questions?.length > 0 && (
        <Card>
          <CardHeader title="开放问题" action={<AlertCircle className="text-error h-5 w-5" />} />
          <div className="space-y-2">
            {survey.summary.open_questions.map((q: string, i: number) => (
              <div key={`question-${i}`} className="border-error/10 bg-error/3 flex gap-3 rounded-lg border p-3">
                <span className="text-error/60 text-sm font-medium">Q{i + 1}</span>
                <p className="text-ink text-sm">{q}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

    </div>
  );
}

/* ===========================================================
 * 论文 Wiki 结构化视图
 * =========================================================== */
function PaperWikiView({
  content,
  title,
}: {
  content: PaperWikiContent;
  title: string;
}) {
  return (
    <div className="animate-fade-in space-y-6">
      {/* 标题头 */}
      <div className="border-accent/20 from-accent/5 rounded-xl border bg-gradient-to-br to-transparent p-6">
        <div className="flex items-center gap-3">
          <div className="bg-accent/10 flex h-10 w-10 items-center justify-center rounded-lg">
            <FileText className="text-accent h-5 w-5" />
          </div>
          <div>
            <h2 className="text-ink text-lg leading-tight font-bold">{title}</h2>
            <p className="text-ink-secondary text-sm">论文百科 · AI 生成</p>
          </div>
        </div>
      </div>

      {/* 核心摘要 */}
      {content.summary && (
        <Card>
          <CardHeader title="核心摘要" action={<BookOpen className="text-primary h-5 w-5" />} />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.summary}</Markdown></Suspense>
          </div>
        </Card>
      )}

      {/* 主要贡献 */}
      {content.contributions?.length > 0 && (
        <Card>
          <CardHeader title="主要贡献" action={<Star className="text-warning h-5 w-5" />} />
          <div className="space-y-2">
            {content.contributions.map((c, i) => (
              <div key={`contribution-${i}`} className="bg-warning/5 flex gap-3 rounded-lg p-3">
                <span className="bg-warning/10 text-warning flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold">
                  {i + 1}
                </span>
                <p className="text-ink text-sm">{c}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 方法论 */}
      {content.methodology && (
        <Card>
          <CardHeader title="方法论" action={<Layers className="text-accent h-5 w-5" />} />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.methodology}</Markdown></Suspense>
          </div>
        </Card>
      )}

      {/* 学术意义 */}
      {content.significance && (
        <Card>
          <CardHeader
            title="学术意义与影响"
            action={<TrendingUp className="text-success h-5 w-5" />}
          />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.significance}</Markdown></Suspense>
          </div>
        </Card>
      )}

      {/* 引用上下文 + PDF + Scholar */}
      <CitationContextsCard contexts={content.citation_contexts || []} />
      <PdfExcerptsCard excerpts={content.pdf_excerpts || []} />
      <ScholarMetadataCard items={content.scholar_metadata || []} />

      {/* 局限性 */}
      {content.limitations?.length > 0 && (
        <Card>
          <CardHeader title="局限性" action={<AlertCircle className="text-error h-5 w-5" />} />
          <div className="space-y-2">
            {content.limitations.map((lim, i) => (
              <div key={`limitation-${i}`} className="border-error/10 bg-error/3 flex gap-3 rounded-lg border p-3">
                <AlertCircle className="text-error/60 mt-0.5 h-4 w-4 shrink-0" />
                <p className="text-ink text-sm">{lim}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 相关工作 */}
      {content.related_work_analysis && (
        <Card>
          <CardHeader title="相关工作分析" />
          <div className="prose-custom">
            <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{content.related_work_analysis}</Markdown></Suspense>
          </div>
        </Card>
      )}

    </div>
  );
}

/* ===========================================================
 * 通用子组件
 * =========================================================== */

function SectionCard({ section, index }: { section: WikiSection; index: number }) {
  return (
    <Card>
      <div className="border-border mb-3 flex items-center gap-2 border-b pb-3">
        <div className="bg-primary/10 flex h-7 w-7 items-center justify-center rounded-lg">
          <span className="text-primary text-xs font-bold">{index + 1}</span>
        </div>
        <h3 className="text-ink text-base font-semibold">{section.title}</h3>
      </div>
      {section.key_insight && (
        <div className="bg-warning/5 mb-4 flex items-start gap-2 rounded-lg px-3 py-2">
          <Lightbulb className="text-warning mt-0.5 h-4 w-4 shrink-0" />
          <p className="text-warning-dark text-sm font-medium">{section.key_insight}</p>
        </div>
      )}
      <div className="prose-custom">
        <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{section.content}</Markdown></Suspense>
      </div>
    </Card>
  );
}

function CitationContextsCard({ contexts }: { contexts: string[] }) {
  if (!contexts?.length) return null;
  return (
    <Card>
      <CardHeader
        title="相关论文上下文"
        description="用于支撑综述生成的论文关系语境"
        action={<Link2 className="text-accent h-5 w-5" />}
      />
          <div className="space-y-2">
            {contexts.slice(0, 15).map((ctx, i) => (
              <div key={`context-${i}`} className="border-border bg-page/50 flex gap-3 rounded-lg border p-3">
                <Quote className="text-accent/60 mt-0.5 h-4 w-4 shrink-0" />
                <p className="text-ink-secondary text-sm italic">{ctx}</p>
              </div>
            ))}
          </div>
    </Card>
  );
}

function PdfExcerptsCard({ excerpts }: { excerpts: PdfExcerpt[] }) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  if (!excerpts?.length) return null;
  return (
    <Card>
      <CardHeader
        title="PDF 全文摘录"
        description="从论文 PDF 中提取的关键内容"
        action={<FileText className="text-success h-5 w-5" />}
      />
      <div className="space-y-3">
        {excerpts.map((ex, i) => (
          <div key={ex.title || `excerpt-${i}`} className="border-border rounded-lg border p-3">
            <div className="flex items-center justify-between">
              <p className="text-ink text-sm font-medium">{ex.title}</p>
              <button
                type="button"
                onClick={() => setExpanded((prev) => ({ ...prev, [i]: !prev[i] }))}
                className="text-primary text-xs hover:underline"
              >
                {expanded[i] ? "收起" : "展开"}
              </button>
            </div>
            <p
              className={`text-ink-secondary mt-2 text-xs leading-relaxed ${expanded[i] ? "" : "line-clamp-3"}`}
            >
              {ex.excerpt}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ScholarMetadataCard({ items }: { items: ScholarMetadataItem[] }) {
  if (!items?.length) return null;
  return (
    <Card>
      <CardHeader
        title="外部学术证据"
        description="联网搜索补充的高影响力论文与元数据"
        action={<ExternalLink className="text-primary h-5 w-5" />}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item, i) => (
          <div
            key={item.title || `item-${i}`}
            className="border-border hover:border-primary/30 rounded-lg border p-3 transition-colors"
          >
            <p className="text-ink text-sm leading-tight font-medium">{item.title}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {item.year && (
                <span className="bg-primary/10 text-primary inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium">
                  {item.year}
                </span>
              )}
              {item.citationCount != null && (
                <span className="bg-accent/10 text-accent inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium">
                  {item.citationCount.toLocaleString()} 引用
                </span>
              )}
              {item.venue && (
                <span className="bg-page text-ink-tertiary inline-flex items-center rounded-md px-2 py-0.5 text-xs">
                  {item.venue}
                </span>
              )}
              {(item.externalSource || item.source) && (
                <span className="bg-primary/10 text-primary inline-flex items-center rounded-md px-2 py-0.5 text-xs">
                  {item.externalSource || item.source}
                </span>
              )}
            </div>
            {item.tldr && (
              <p className="text-ink-secondary mt-2 text-xs leading-relaxed">{item.tldr}</p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function TimelineView({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="space-y-3">
      {entries.slice(0, 12).map((entry, i) => (
        <div key={entry.title || `entry-${i}`} className="relative flex gap-4 pl-4">
          <div className="bg-primary absolute top-2 left-0 h-2 w-2 rounded-full" />
          {i < entries.length - 1 && (
            <div className="bg-primary/20 absolute top-4 left-[3px] h-full w-px" />
          )}
          <div className="min-w-0 flex-1 pb-4">
            <div className="flex items-center gap-2">
              <span className="bg-primary/10 text-primary inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold">
                {entry.year}
              </span>
              <span className="text-ink-tertiary text-xs">
                影响力 {entry.seminal_score.toFixed(2)}
              </span>
            </div>
            <p className="text-ink mt-1 text-sm font-medium">{entry.title}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * 历史内容 markdown 渲染（回退用）
 */
function MarkdownArticle({
  title,
  markdown,
  metadata,
}: {
  title: string;
  markdown: string;
  metadata?: Record<string, unknown>;
}) {
  /* 尝试从 metadata 解析 wiki_content */
  const wikiContent = metadata?.wiki_content as TopicWikiContent | PaperWikiContent | undefined;
  if (wikiContent && "overview" in wikiContent) {
    return (
      <TopicWikiView
        content={wikiContent as TopicWikiContent}
        keyword={String(metadata?.keyword || title)}
        timeline={metadata?.timeline as TopicWiki["timeline"]}
        survey={metadata?.survey as TopicWiki["survey"]}
      />
    );
  }

  if (wikiContent && "summary" in wikiContent) {
    return (
      <PaperWikiView
        content={wikiContent as PaperWikiContent}
        title={title}
      />
    );
  }

  /* 纯 markdown 回退 */
  return (
    <Card className="animate-fade-in">
      <CardHeader title={title} action={<BookOpen className="text-primary h-5 w-5" />} />
      <div className="prose-custom">
        <Suspense fallback={<div className="flex items-center justify-center py-2"><Loader2 className="h-4 w-4 animate-spin text-ink-tertiary" /></div>}><Markdown>{markdown}</Markdown></Suspense>
      </div>
    </Card>
  );
}
