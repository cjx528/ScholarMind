/**
 * Agent 对话页面 - 纯渲染壳，核心状态由 AgentSessionContext 管理
 * 切换页面不会丢失 SSE 流和进度
 * @author ScholarMind Team
 */
import { useState, useRef, useEffect, useCallback, memo, lazy, Suspense } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";

// Markdown 含 katex，懒加载避免首屏拉取大 chunk
const Markdown = lazy(() => import("@/components/Markdown"));
import {
  Send,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Sparkles,
  Search,
  Download,
  BookOpen,
  Brain,
  FileText,
  ChevronDown,
  ChevronRight,
  Circle,
  Square,
  X,
  PanelRightOpen,
  Hash,
  RotateCcw,
  ArrowDown,
} from "lucide-react";
import { useAgentSession, type ChatItem } from "@/contexts/AgentSessionContext";
import { ActionConfirmCard } from "./AgentSteps";
import { UserMessage, AssistantMessage, StepGroupCard } from "./AgentMessages";
import { ChatNavBar } from "./ChatNavBar";

/* ========== 工具元数据 ========== */

const TOOL_META: Record<string, { icon: typeof Search; label: string }> = {
  recommend_profile_papers: { icon: Sparkles, label: "画像推荐" },
  search_papers: { icon: Search, label: "搜索论文" },
  get_paper_detail: { icon: FileText, label: "论文详情" },
  get_similar_papers: { icon: Search, label: "相似论文" },
  ask_knowledge_base: { icon: Brain, label: "知识问答" },
  list_topics: { icon: Search, label: "主题列表" },
  get_system_status: { icon: Search, label: "系统状态" },
  search_arxiv: { icon: Search, label: "搜索 arXiv" },
  ingest_arxiv: { icon: Download, label: "入库论文" },
  skim_paper: { icon: BookOpen, label: "粗读论文" },
  deep_read_paper: { icon: BookOpen, label: "精读论文" },
  embed_paper: { icon: Brain, label: "向量嵌入" },
  generate_wiki: { icon: FileText, label: "生成 Wiki" },
  manage_subscription: { icon: BookOpen, label: "订阅管理" },
};

function getToolMeta(name: string) {
  return TOOL_META[name] || { icon: Circle, label: name };
}

/* ========== 主组件 ========== */

export default function Agent() {
  const navigate = useNavigate();
  const {
    items,
    loading,
    pendingActions,
    confirmingActions,
    canvas,
    hasPendingConfirm,
    setCanvas,
    sendMessage,
    handleConfirm,
    handleReject,
    stopGeneration,
  } = useAgentSession();

  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /* ---- 滚动控制 ---- */
  const isAtBottomRef = useRef(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const handleScroll = useCallback(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    isAtBottomRef.current = atBottom;
    setShowScrollBtn(!atBottom);
  }, []);

  const scrollRafRef = useRef<number | null>(null);
  const scrollToBottom = useCallback((force = false) => {
    if (!force && !isAtBottomRef.current) return;
    if (scrollRafRef.current) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, []);

  useEffect(() => {
    scrollToBottom(loading);
  }, [items, loading, scrollToBottom]);

  // 有新的 pendingAction 时强制滚动到底部
  useEffect(() => {
    if (pendingActions.size > 0) {
      isAtBottomRef.current = true;
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }, [pendingActions]);

  const inputDisabled = loading || hasPendingConfirm;

  const handleSend = useCallback(
    async (text: string) => {
      const savedInput = text;
      isAtBottomRef.current = true;
      setInput("");
      try {
        await sendMessage(text);
      } catch {
        setInput(savedInput);
      }
    },
    [sendMessage]
  );

  const handleConfirmAction = useCallback(
    (actionId: string) => {
      isAtBottomRef.current = true;
      handleConfirm(actionId);
    },
    [handleConfirm]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
  };

  return (
    <div className="flex h-full">
      {/* 主对话区域 */}
      <div className={cn("flex flex-1 flex-col transition-all", canvas ? "mr-0" : "")}>
        <div
          ref={scrollAreaRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto"
        >
          {items.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="mx-auto max-w-3xl px-4 py-6">
              {items.map((item, idx) => {
                const retryFn =
                  item.type === "error"
                    ? () => {
                        for (let i = idx - 1; i >= 0; i--) {
                          if (items[i].type === "user") {
                            handleSend(items[i].content);
                            return;
                          }
                        }
                      }
                    : undefined;
                return (
                  <ChatBlock
                    key={item.id}
                    item={item}
                    isPending={item.actionId ? pendingActions.has(item.actionId) : false}
                    isConfirming={item.actionId ? confirmingActions.has(item.actionId) : false}
                    onConfirm={handleConfirmAction}
                    onReject={handleReject}
                    onOpenArtifact={(title, content, isHtml) =>
                      setCanvas({ title, markdown: content, isHtml })
                    }
                    onRetry={retryFn}
                  />
                );
              })}
              {loading && items[items.length - 1]?.type !== "action_confirm" && (
                <div className="text-ink-tertiary flex items-center gap-2 py-3 text-sm">
                  <div className="flex gap-1">
                    <span className="bg-primary inline-block h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:0ms]" />
                    <span className="bg-primary inline-block h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:150ms]" />
                    <span className="bg-primary inline-block h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:300ms]" />
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}

          {/* 滚到底部按钮 */}
          {showScrollBtn && items.length > 0 && (
            <button
              onClick={() => {
                isAtBottomRef.current = true;
                endRef.current?.scrollIntoView({ behavior: "smooth" });
              }}
              className="border-border bg-surface text-ink-secondary hover:bg-hover hover:text-ink absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium shadow-lg transition-all"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              回到底部
            </button>
          )}
        </div>

        {/* 对话导航条 - 固定在右侧 */}
        <ChatNavBar items={items} scrollAreaRef={scrollAreaRef} />

        {/* 输入区域 */}
        <div className="border-border bg-surface border-t px-4 py-3">
          <div className="mx-auto max-w-3xl space-y-2">
            {hasPendingConfirm && (
              <div className="bg-warning-light text-warning flex items-center gap-2 rounded-lg px-3 py-2 text-xs">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>请先处理上方的确认请求，再继续对话</span>
              </div>
            )}

            {/* 输入框 */}
            <div
              className={cn(
                "border-border bg-page focus-within:border-primary/40 flex items-end gap-3 rounded-2xl border px-4 py-3 shadow-sm transition-all focus-within:shadow-md",
                hasPendingConfirm && "opacity-60"
              )}
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  hasPendingConfirm
                    ? "请先处理上方确认..."
                    : "描述你的研究需求..."
                }
                className="text-ink placeholder:text-ink-placeholder max-h-32 min-h-[40px] flex-1 resize-none bg-transparent text-sm focus:outline-none"
                rows={1}
                disabled={inputDisabled}
              />
              {loading ? (
                <button
                  aria-label="停止生成"
                  onClick={stopGeneration}
                  className="bg-error/90 hover:bg-error flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white shadow-sm transition-all"
                >
                  <Square className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button
                  aria-label="发送消息"
                  onClick={() => handleSend(input)}
                  disabled={!input.trim() || inputDisabled}
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all",
                    input.trim() && !inputDisabled
                      ? "bg-primary hover:bg-primary-hover text-white shadow-sm"
                      : "bg-hover text-ink-tertiary"
                  )}
                >
                  <Send className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Canvas 面板 - 小屏全屏覆盖，大屏侧边 */}
      {canvas && (
        <div className="bg-surface lg:border-border fixed inset-0 z-50 flex flex-col lg:static lg:inset-auto lg:z-auto lg:h-full lg:w-[480px] lg:shrink-0 lg:border-l">
          <div className="border-border flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <PanelRightOpen className="text-ink-tertiary h-4 w-4" />
              <span className="text-ink text-sm font-medium">{canvas.title}</span>
            </div>
            <button
              aria-label="关闭面板"
              onClick={() => setCanvas(null)}
              className="text-ink-tertiary hover:bg-hover hover:text-ink flex h-7 w-7 items-center justify-center rounded-lg"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div
            className="flex-1 overflow-y-auto px-6 py-4"
            onClick={(e) => {
              const card = (e.target as HTMLElement).closest<HTMLElement>("[data-paper-id]");
              if (card?.dataset.paperId) navigate(`/papers/${card.dataset.paperId}`);
            }}
          >
            {canvas.isHtml ? (
              <div
                className="prose-custom artifact-html-preview artifact-content"
                dangerouslySetInnerHTML={{ __html: canvas.markdown }}
              />
            ) : (
              <div className="prose-custom">
                <Suspense fallback={<div className="bg-surface h-4 animate-pulse rounded" />}>
                  <Markdown>{canvas.markdown}</Markdown>
                </Suspense>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ========== 空状态 ========== */

const EmptyState = memo(function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center overflow-y-auto px-4 py-12">
      <div className="bg-primary/10 mb-6 flex h-16 w-16 items-center justify-center rounded-2xl">
        <Sparkles className="text-primary h-8 w-8" />
      </div>
      <h2 className="text-ink mb-1 text-2xl font-bold">ScholarMind Agent</h2>
      <p className="text-ink-secondary mb-6 max-w-lg text-center text-sm leading-relaxed">
        告诉我你的研究需求，我会自动规划执行步骤：搜索论文、下载、分析、生成综述。
      </p>
    </div>
  );
});

/* ========== 消息块 ========== */

const ChatBlock = memo(function ChatBlock({
  item,
  isPending,
  isConfirming,
  onConfirm,
  onReject,
  onOpenArtifact,
  onRetry,
}: {
  item: ChatItem;
  isPending: boolean;
  isConfirming: boolean;
  onConfirm: (id: string) => void;
  onReject: (id: string) => void;
  onOpenArtifact: (title: string, content: string, isHtml?: boolean) => void;
  onRetry?: () => void;
}) {
  switch (item.type) {
    case "user":
      return <UserMessage content={item.content} messageId={item.id} />;
    case "assistant":
      return <AssistantMessage content={item.content} streaming={!!item.streaming} />;
    case "step_group":
      return <StepGroupCard steps={item.steps || []} />;
    case "action_confirm":
      return (
        <ActionConfirmCard
          actionId={item.actionId || ""}
          description={item.actionDescription || ""}
          tool={item.actionTool || ""}
          args={item.toolArgs}
          isPending={isPending}
          isConfirming={isConfirming}
          onConfirm={onConfirm}
          onReject={onReject}
        />
      );
    case "artifact":
      return (
        <ArtifactCard
          title={item.artifactTitle || ""}
          content={item.artifactContent || ""}
          isHtml={item.artifactIsHtml}
          onOpen={() =>
            onOpenArtifact(
              item.artifactTitle || "",
              item.artifactContent || "",
              item.artifactIsHtml
            )
          }
        />
      );
    case "error":
      return <ErrorCard content={item.content} onRetry={onRetry} />;
    default:
      return null;
  }
});

/**
 * 论文列表卡片（search_papers / search_arxiv 共用）
 */
const PaperListView = memo(function PaperListView({
  papers,
  label,
}: {
  papers: Array<Record<string, unknown>>;
  label: string;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-ink-secondary text-[11px] font-medium">{label}</p>
      <div className="max-h-56 space-y-1 overflow-y-auto">
        {papers.slice(0, 30).map((p, i) => (
          <div
            key={String(p.id ?? "")}
            className="bg-surface hover:bg-hover flex items-start gap-2 rounded-lg px-2.5 py-2 text-[11px] transition-colors"
          >
            <span className="bg-primary/10 text-primary mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-ink leading-snug font-medium">{String(p.title ?? "")}</p>
              <div className="text-ink-tertiary mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                {p.arxiv_id ? <span className="font-mono">{String(p.arxiv_id)}</span> : null}
                {p.publication_date ? <span>{String(p.publication_date)}</span> : null}
                {p.read_status ? (
                  <span className="bg-primary/10 text-primary rounded px-1 py-0.5">
                    {String(p.read_status)}
                  </span>
                ) : null}
              </div>
              {Array.isArray(p.authors) && (p.authors as string[]).length > 0 && (
                <p className="text-ink-tertiary mt-0.5 truncate text-[10px]">
                  {(p.authors as string[]).slice(0, 3).join(", ")}
                  {(p.authors as string[]).length > 3 ? " ..." : ""}
                </p>
              )}
              {Array.isArray(p.categories) && (p.categories as string[]).length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {(p.categories as string[]).slice(0, 3).map((c) => (
                    <span
                      key={c}
                      className="bg-hover text-ink-tertiary rounded px-1.5 py-0.5 text-[9px]"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

/**
 * 入库结果卡片
 */
const IngestResultView = memo(function IngestResultView({
  data,
}: {
  data: Record<string, unknown>;
}) {
  const total = Number(data.total ?? 0);
  const embedded = Number(data.embedded ?? 0);
  const skimmed = Number(data.skimmed ?? 0);
  const topic = String(data.topic ?? "");
  const ingested = Array.isArray(data.ingested)
    ? (data.ingested as Array<Record<string, unknown>>)
    : [];
  const failed = Array.isArray(data.failed) ? (data.failed as Array<Record<string, unknown>>) : [];
  const suggestSub = !!data.suggest_subscribe;

  return (
    <div className="space-y-2.5">
      {/* 统计条 */}
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: "入库", value: total, color: "text-primary", bg: "bg-primary/10" },
          { label: "向量化", value: embedded, color: "text-success", bg: "bg-success/10" },
          {
            label: "粗读",
            value: skimmed,
            color: "text-blue-600 dark:text-blue-400",
            bg: "bg-blue-500/10",
          },
          {
            label: "失败",
            value: failed.length,
            color: failed.length > 0 ? "text-error" : "text-ink-tertiary",
            bg: failed.length > 0 ? "bg-error/10" : "bg-hover",
          },
        ].map((s) => (
          <div key={s.label} className={cn("flex flex-col items-center rounded-lg py-2", s.bg)}>
            <span className={cn("text-base font-bold", s.color)}>{s.value}</span>
            <span className="text-ink-tertiary text-[10px]">{s.label}</span>
          </div>
        ))}
      </div>

      {topic && (
        <div className="flex items-center gap-1.5 text-[11px]">
          <Hash className="text-primary h-3 w-3" />
          <span className="text-ink-secondary">主题：</span>
          <span className="bg-primary/10 text-primary rounded-md px-1.5 py-0.5 font-medium">
            {topic}
          </span>
          {suggestSub && (
            <span className="bg-warning-light text-warning rounded px-1.5 py-0.5 text-[10px]">
              新主题，建议订阅
            </span>
          )}
        </div>
      )}

      {/* 入库论文列表 */}
      {ingested.length > 0 && (
        <div className="space-y-1">
          <p className="text-success text-[10px] font-medium">已入库 ({ingested.length})</p>
          <div className="max-h-32 space-y-0.5 overflow-y-auto">
            {ingested.map((p) => (
              <div key={String(p.arxiv_id ?? p.title ?? "")} className="flex items-center gap-1.5 rounded px-2 py-1 text-[11px]">
                <CheckCircle2 className="text-success h-3 w-3 shrink-0" />
                <span className="text-ink truncate">{String(p.title ?? p.arxiv_id ?? "")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 失败列表 */}
      {failed.length > 0 && (
        <div className="space-y-1">
          <p className="text-error text-[10px] font-medium">失败 ({failed.length})</p>
          <div className="max-h-24 space-y-0.5 overflow-y-auto">
            {failed.map((p) => (
              <div
                key={String(p.arxiv_id ?? p.title ?? "")}
                className="bg-error/5 flex items-center gap-1.5 rounded px-2 py-1 text-[11px]"
              >
                <XCircle className="text-error h-3 w-3 shrink-0" />
                <span className="text-ink truncate">{String(p.title ?? p.arxiv_id ?? "")}</span>
                {p.error ? (
                  <span className="text-error ml-auto shrink-0 text-[10px]">
                    {String(p.error).slice(0, 40)}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

const ErrorCard = memo(function ErrorCard({
  content,
  onRetry,
}: {
  content: string;
  onRetry?: () => void;
}) {
  return (
    <div className="py-2">
      <div className="border-error/30 bg-error-light flex items-start gap-2 rounded-xl border px-3.5 py-2.5">
        <AlertTriangle className="text-error mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p className="text-error flex-1 text-sm">{content}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-error hover:bg-error/10 flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors"
          >
            <RotateCcw className="h-3 w-3" />
            重试
          </button>
        )}
      </div>
    </div>
  );
});

/* ========== 嵌入式内容卡片（Artifact） ========== */

const ArtifactCard = memo(function ArtifactCard({
  title,
  content,
  isHtml,
  onOpen,
}: {
  title: string;
  content: string;
  isHtml?: boolean;
  onOpen: () => void;
}) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const isWiki = !isHtml;
  const iconColor = isWiki ? "text-primary" : "text-amber-500";
  const borderColor = isWiki ? "border-primary/30" : "border-amber-400/30";
  const bgAccent = isWiki ? "bg-primary/5" : "bg-amber-50 dark:bg-amber-900/10";
  const IconComp = FileText;

  const preview = (
    isHtml
      ? content.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ")
      : content.replace(/[#*_`[\]()>-]/g, "").replace(/\s+/g, " ")
  )
    .trim()
    .slice(0, 200);

  return (
    <div className="py-2">
      <div
        className={cn(
          "overflow-hidden rounded-xl border transition-all",
          borderColor,
          "bg-surface hover:shadow-md"
        )}
      >
        <button
          onClick={onOpen}
          className={cn(
            "hover:bg-hover flex w-full items-center gap-3 px-4 py-3 text-left transition-colors",
            bgAccent
          )}
        >
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
              isWiki ? "bg-primary/10" : "bg-amber-100 dark:bg-amber-900/20"
            )}
          >
            <IconComp className={cn("h-4.5 w-4.5", iconColor)} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-ink text-sm font-semibold">{title}</p>
            <p className="text-ink-tertiary mt-0.5 truncate text-xs">{preview}...</p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="bg-primary/10 text-primary rounded-md px-2 py-0.5 text-[10px] font-medium">
              点击查看
            </span>
            <PanelRightOpen className="text-ink-tertiary h-4 w-4" />
          </div>
        </button>

        <div className="border-border-light flex items-center gap-1 border-t px-4 py-1.5">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-ink-tertiary hover:text-ink-secondary flex items-center gap-1 text-[11px]"
          >
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {expanded ? "收起预览" : "展开预览"}
          </button>
        </div>

        {expanded && (
          <div
            className="border-border-light max-h-80 overflow-y-auto border-t px-5 py-4"
            onClick={(e) => {
              const card = (e.target as HTMLElement).closest<HTMLElement>("[data-paper-id]");
              if (card?.dataset.paperId) navigate(`/papers/${card.dataset.paperId}`);
            }}
          >
            {isHtml ? (
              <div
                className="prose-custom artifact-html-preview artifact-content text-sm"
                dangerouslySetInnerHTML={{ __html: content }}
              />
            ) : (
              <div className="prose-custom text-sm">
                <Suspense fallback={<div className="bg-surface h-4 animate-pulse rounded" />}>
                  <Markdown>{content}</Markdown>
                </Suspense>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
