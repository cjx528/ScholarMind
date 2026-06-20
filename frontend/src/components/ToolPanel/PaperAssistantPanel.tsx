import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  FileText,
  Languages,
  Lightbulb,
  Loader2,
  MessageSquare,
  Pin,
  PinOff,
  Send,
  Sparkles,
} from "lucide-react";
import { paperApi } from "@/services/api";

interface PaperAssistantPanelProps {
  selectedText: string;
  paperId: string;
  currentPage: number;
  paperTitle: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  usedContext?: string[];
  confidence?: number;
}

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "我可以围绕当前论文、选中文本、粗读/精读报告和推理链回答问题。选中 PDF 原文后，可以直接点快捷按钮。",
};

const MAX_STORED_MESSAGES = 80;
const MAX_RECENT_QUESTIONS = 8;
const RECENT_QUESTIONS_KEY = "scholarmind_pdf_assistant_recent_questions";
const PINNED_QUESTIONS_KEY = "scholarmind_pdf_assistant_pinned_questions";

const contextLabels: Record<string, string> = {
  selected_text: "选中文本",
  paper_meta: "论文信息",
  skim: "粗读",
  deep: "精读",
  reasoning: "推理链",
  pdf_page: "当前页",
};

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function excerpt(text: string, limit = 240) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= limit) return clean;
  return `${clean.slice(0, limit)}...`;
}

function messagesKey(paperId: string) {
  return `scholarmind_pdf_assistant:${paperId}`;
}

function loadMessages(paperId: string): ChatMessage[] {
  if (typeof window === "undefined") return [WELCOME_MESSAGE];
  try {
    const raw = localStorage.getItem(messagesKey(paperId));
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.slice(-MAX_STORED_MESSAGES);
    }
  } catch {
    // Ignore corrupt local history.
  }
  return [WELCOME_MESSAGE];
}

function saveMessages(paperId: string, messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      messagesKey(paperId),
      JSON.stringify(messages.slice(-MAX_STORED_MESSAGES))
    );
  } catch {
    // Best-effort local persistence only.
  }
}

function loadRecentQuestions(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENT_QUESTIONS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, MAX_RECENT_QUESTIONS) : [];
  } catch {
    return [];
  }
}

function saveRecentQuestions(questions: string[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(RECENT_QUESTIONS_KEY, JSON.stringify(questions.slice(0, MAX_RECENT_QUESTIONS)));
  } catch {
    // Best-effort local persistence only.
  }
}

function loadPinnedQuestions(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(PINNED_QUESTIONS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, MAX_RECENT_QUESTIONS) : [];
  } catch {
    return [];
  }
}

function savePinnedQuestions(questions: string[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(PINNED_QUESTIONS_KEY, JSON.stringify(questions.slice(0, MAX_RECENT_QUESTIONS)));
  } catch {
    // Best-effort local persistence only.
  }
}

export function PaperAssistantPanel({
  selectedText,
  paperId,
  currentPage,
  paperTitle,
}: PaperAssistantPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadMessages(paperId));
  const [historyPaperId, setHistoryPaperId] = useState(paperId);
  const [recentQuestions, setRecentQuestions] = useState<string[]>(() => loadRecentQuestions());
  const [pinnedQuestions, setPinnedQuestions] = useState<string[]>(() => loadPinnedQuestions());
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const hasSelection = selectedText.trim().length > 0;
  const selectionPreview = useMemo(() => excerpt(selectedText, 260), [selectedText]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, loading]);

  useEffect(() => {
    setMessages(loadMessages(paperId));
    setHistoryPaperId(paperId);
  }, [paperId]);

  useEffect(() => {
    if (historyPaperId !== paperId) return;
    saveMessages(paperId, messages);
  }, [historyPaperId, messages, paperId]);

  const rememberQuestion = useCallback((question: string) => {
    const cleaned = question.trim();
    if (!cleaned) return;
    setRecentQuestions((items) => {
      const next = [cleaned, ...items.filter((item) => item !== cleaned)].slice(
        0,
        MAX_RECENT_QUESTIONS
      );
      saveRecentQuestions(next);
      return next;
    });
  }, []);

  const pinQuestion = useCallback((question: string) => {
    const cleaned = question.trim();
    if (!cleaned) return;
    setPinnedQuestions((items) => {
      const next = [cleaned, ...items.filter((item) => item !== cleaned)].slice(
        0,
        MAX_RECENT_QUESTIONS
      );
      savePinnedQuestions(next);
      return next;
    });
  }, []);

  const unpinQuestion = useCallback((question: string) => {
    setPinnedQuestions((items) => {
      const next = items.filter((item) => item !== question);
      savePinnedQuestions(next);
      return next;
    });
  }, []);

  const ask = useCallback(
    async (
      question: string,
      selectedOverride = selectedText,
      options?: { remember?: boolean }
    ) => {
      const cleanQuestion = question.trim();
      if (!cleanQuestion || loading) return;
      if (options?.remember !== false) {
        rememberQuestion(cleanQuestion);
      }

      const userMessage: ChatMessage = {
        id: makeId(),
        role: "user",
        content: cleanQuestion,
      };
      setMessages((items) => [...items, userMessage]);
      setInput("");
      setLoading(true);

      try {
        const response = await paperApi.ask(paperId, {
          question: cleanQuestion,
          selected_text: selectedOverride.trim() || null,
          source: "pdf_reader",
          analysis_scope: ["skim", "deep", "reasoning"],
          page_number: currentPage,
        });
        setMessages((items) => [
          ...items,
          {
            id: makeId(),
            role: "assistant",
            content: response.answer,
            usedContext: response.used_context,
            confidence: response.confidence,
          },
        ]);
      } catch (error) {
        const detail = error instanceof Error ? error.message : "请求失败";
        setMessages((items) => [
          ...items,
          {
            id: makeId(),
            role: "assistant",
            content: `这次没有拿到可靠回答：${detail}`,
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [currentPage, loading, paperId, rememberQuestion, selectedText]
  );

  const quickActions = [
    {
      label: "翻译成中文",
      icon: <Languages className="h-3.5 w-3.5" />,
      disabled: !hasSelection,
      prompt: "请把选中的论文原文翻译成自然中文，保留必要的英文术语。",
    },
    {
      label: "解释这段",
      icon: <Lightbulb className="h-3.5 w-3.5" />,
      disabled: !hasSelection,
      prompt: "请解释选中段落的核心含义、关键术语，以及它在论文论证中的作用。",
    },
    {
      label: "总结这段",
      icon: <FileText className="h-3.5 w-3.5" />,
      disabled: !hasSelection,
      prompt: "请用中文概括选中段落的要点，并指出它支撑了论文的哪部分结论。",
    },
    {
      label: "问这篇论文",
      icon: <BookOpen className="h-3.5 w-3.5" />,
      disabled: false,
      prompt: "请用中文说明这篇论文解决的问题、核心方法和主要贡献。",
    },
  ];

  return (
    <div className="flex h-full flex-col bg-[#1e1e2e]">
      <div className="border-b border-white/10 px-4 py-4">
        <div className="flex items-center gap-2 text-sm font-medium text-white/90">
          <Sparkles className="h-4 w-4 text-primary" />
          <span>论文 AI 助手</span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs text-white/40">{paperTitle}</p>

        <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.04] p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-white/60">
              {hasSelection ? "当前选中文本" : `当前页：第 ${currentPage} 页`}
            </span>
            <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">
              解析上下文已接入
            </span>
          </div>
          {hasSelection ? (
            <p className="text-xs leading-5 text-white/70">{selectionPreview}</p>
          ) : (
            <p className="text-xs leading-5 text-white/40">
              在左侧 PDF 里选中一段文字，可让助手翻译、解释或围绕这段继续追问。
            </p>
          )}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          {quickActions.map((action) => (
            <button
              type="button"
              key={action.label}
              disabled={action.disabled || loading}
              onClick={() => ask(action.prompt, selectedText, { remember: false })}
              className="flex items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-2 text-xs text-white/70 transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary disabled:pointer-events-none disabled:opacity-40"
            >
              {action.icon}
              {action.label}
            </button>
          ))}
        </div>
        {pinnedQuestions.length > 0 && (
          <div className="mt-3">
            <div className="mb-2 text-[10px] font-medium text-white/35">置顶问题</div>
            <div className="flex flex-wrap gap-2">
              {pinnedQuestions.slice(0, 4).map((question) => (
                <span
                  key={question}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[10px] text-primary"
                >
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => ask(question, selectedText, { remember: false })}
                    className="truncate disabled:pointer-events-none disabled:opacity-40"
                    title={question}
                  >
                    {question}
                  </button>
                  <button
                    type="button"
                    onClick={() => unpinQuestion(question)}
                    className="shrink-0 rounded-full p-0.5 text-primary/70 hover:bg-primary/20 hover:text-primary"
                    title="取消置顶"
                  >
                    <PinOff className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        {recentQuestions.length > 0 && (
          <div className="mt-3">
            <div className="mb-2 text-[10px] font-medium text-white/35">最近问题</div>
            <div className="flex flex-wrap gap-2">
              {recentQuestions.slice(0, 4).map((question) => (
                <button
                  type="button"
                  key={question}
                  disabled={loading}
                  onClick={() => ask(question, selectedText, { remember: false })}
                  className="max-w-full truncate rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] text-white/50 hover:border-primary/40 hover:text-primary disabled:pointer-events-none disabled:opacity-40"
                  title={question}
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 space-y-3 overflow-auto px-4 py-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[88%] rounded-xl px-3 py-2 text-sm leading-6 ${
                message.role === "user"
                  ? "bg-primary text-white"
                  : "border border-white/10 bg-white/[0.05] text-white/80"
              }`}
            >
              <div className="whitespace-pre-wrap">{message.content}</div>
              {message.role === "assistant" && message.usedContext?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {message.usedContext.map((ctx) => (
                    <span
                      key={ctx}
                      className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/45"
                    >
                      {contextLabels[ctx] || ctx}
                    </span>
                  ))}
                  {typeof message.confidence === "number" && (
                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/45">
                      置信度 {message.confidence.toFixed(2)}
                    </span>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-3 py-2 text-sm text-white/60">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在结合原文和解析生成回答...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="border-t border-white/10 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          ask(input);
        }}
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                ask(input);
              }
            }}
            rows={2}
            placeholder="问这篇论文、当前选中文本或已有解析..."
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm leading-5 text-white outline-none placeholder:text-white/30 focus:border-primary/50"
          />
          <button
            type="button"
            disabled={!input.trim()}
            onClick={() => pinQuestion(input)}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-white/60 transition-colors hover:border-primary/40 hover:text-primary disabled:pointer-events-none disabled:opacity-40"
            title="置顶当前问题"
          >
            <Pin className="h-4 w-4" />
          </button>
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary text-white transition-colors hover:bg-primary-hover disabled:pointer-events-none disabled:opacity-40"
            title="发送"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-white/30">
          <MessageSquare className="h-3 w-3" />
          <span>当前论文会话已在本机保存。</span>
        </div>
      </form>
    </div>
  );
}
