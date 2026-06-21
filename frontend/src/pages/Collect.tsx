/**
 * ScholarMind - paper collection workspace
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowUpDown,
  Calendar,
  CheckCircle2,
  CheckSquare,
  Database,
  Download,
  ExternalLink,
  Hash,
  Loader2,
  Search,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { Button, Empty } from "@/components/ui";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useToast } from "@/contexts/ToastContext";
import { compassApi, ingestApi } from "@/services/api";
import type { ArxivPreviewCandidate, ArxivPreviewResponse, IngestPaper } from "@/types";

type SortBy = "submittedDate" | "relevance" | "lastUpdatedDate";
type RecencyPreference = "recent" | "balanced" | "classic";

const DEFAULT_MAX_RESULTS = 20;

function parseMaxResultsInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return DEFAULT_MAX_RESULTS;
  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed)) return DEFAULT_MAX_RESULTS;
  return Math.max(1, Math.min(100, parsed));
}

interface SourceOption {
  id: string;
  label: string;
  desc: string;
}

interface PreviewState extends ArxivPreviewResponse {
  time: string;
}

interface SearchResult {
  ingested: number;
  newCount?: number;
  existingCount?: number;
  papers: IngestPaper[];
  query: string;
  time: string;
  sources: string[];
  expanded: boolean;
}

const SOURCE_OPTIONS: SourceOption[] = [
  { id: "arxiv", label: "arXiv", desc: "预印本" },
  { id: "semantic_scholar", label: "Semantic Scholar", desc: "引用与元数据" },
  { id: "openalex", label: "OpenAlex", desc: "开放学术库" },
  { id: "dblp", label: "DBLP", desc: "计算机文献" },
  { id: "openreview", label: "OpenReview", desc: "会议评审" },
  { id: "biorxiv", label: "bioRxiv", desc: "生命科学预印本" },
];

const RECENCY_FILTERS: Record<
  RecencyPreference,
  { label: string; windowLabel: string; daysBack: number; sortBy: SortBy }
> = {
  recent: { label: "新论文优先", windowLabel: "近 180 天", daysBack: 180, sortBy: "submittedDate" },
  balanced: { label: "新旧平衡", windowLabel: "近 2 年", daysBack: 730, sortBy: "submittedDate" },
  classic: { label: "经典也可", windowLabel: "不限时间", daysBack: 0, sortBy: "relevance" },
};

const SORT_LABEL: Record<SortBy, string> = {
  submittedDate: "提交时间",
  lastUpdatedDate: "更新时间",
  relevance: "相关性",
};

function normalizeRecencyPreference(value: unknown): RecencyPreference {
  if (typeof value !== "string") return "recent";
  const v = value.toLowerCase();
  if (["classic", "old", "foundational", "prefer_classic"].includes(v)) return "classic";
  if (["balanced", "mix", "mixed", "new_old_balance"].includes(v)) return "balanced";
  return "recent";
}

function candidateId(candidate: ArxivPreviewCandidate): string {
  return (
    candidate.id ||
    candidate.source_id ||
    candidate.arxiv_id ||
    candidate.doi ||
    `${candidate.source || "paper"}:${candidate.title}`
  );
}

function sourceLabel(source?: string | null): string {
  if (!source) return "Unknown";
  return SOURCE_OPTIONS.find((item) => item.id === source)?.label || source.replace(/_/g, " ");
}

function sourceBadges(candidate: ArxivPreviewCandidate): string[] {
  const channels = (candidate.sources || [])
    .map((item) => String(item.channel || ""))
    .filter(Boolean);
  if (!channels.length && candidate.source) channels.push(candidate.source);
  return Array.from(new Set(channels)).slice(0, 4);
}

function formatDate(value?: string | null): string {
  if (!value) return "未知日期";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN");
}

function formatAuthors(authors?: string[]): string {
  if (!authors || authors.length === 0) return "作者未知";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")} 等`;
}

function chooseDefaultCandidates(candidates: ArxivPreviewCandidate[]): Set<string> {
  const defaults = candidates.filter((item) => !item.exists && item.match_score >= 35);
  if (defaults.length) return new Set(defaults.map(candidateId));
  return new Set(candidates.filter((item) => !item.exists).slice(0, 10).map(candidateId));
}

export default function Collect() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [maxResultsInput, setMaxResultsInput] = useState(String(DEFAULT_MAX_RESULTS));
  const [selectedSources, setSelectedSources] = useState<string[]>(["arxiv"]);
  const [recencyPreference, setRecencyPreference] = useState<RecencyPreference>("recent");
  const [sortBy, setSortBy] = useState<SortBy>("submittedDate");
  const [csOnly, setCsOnly] = useState(true);
  const [searching, setSearching] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const recencyFilter = RECENCY_FILTERS[recencyPreference];
  const maxResults = useMemo(() => parseMaxResultsInput(maxResultsInput), [maxResultsInput]);
  const candidates = useMemo(() => preview?.candidates ?? [], [preview]);
  const selectedCandidates = useMemo(
    () => candidates.filter((item) => selectedCandidateIds.has(candidateId(item))),
    [candidates, selectedCandidateIds]
  );
  const selectableCount = candidates.filter((item) => !item.exists).length;
  const selectedTopicNames = useMemo(
    () =>
      Array.from(
        new Set(
          selectedCandidates
            .map((item) => item.topic_name || "未归类")
            .filter(Boolean)
        )
      ),
    [selectedCandidates]
  );

  useEffect(() => {
    let alive = true;
    compassApi
      .profile()
      .then((res) => {
        if (!alive) return;
        const quickProfile = res.profile.quickProfile || {};
        const preference = normalizeRecencyPreference(
          quickProfile.recencyPreference ?? quickProfile.paperAgePreference
        );
        setRecencyPreference(preference);
        setSortBy(RECENCY_FILTERS[preference].sortBy);
      })
      .catch(() => {
        // Profile is optional for collection; default to recent papers.
      });
    return () => {
      alive = false;
    };
  }, []);

  const toggleSource = useCallback((source: string) => {
    setSelectedSources((prev) => {
      if (prev.includes(source)) {
        return prev.length === 1 ? prev : prev.filter((item) => item !== source);
      }
      return [...prev, source];
    });
  }, []);

  const handleRecencyChange = useCallback((value: RecencyPreference) => {
    setRecencyPreference(value);
    setSortBy(RECENCY_FILTERS[value].sortBy);
  }, []);

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) {
      toast("warning", "请输入搜索关键词");
      return;
    }
    setSearching(true);
    setError(null);
    setPreview(null);
    setSelectedCandidateIds(new Set());
    try {
      const res = await ingestApi.searchPreview(
        trimmed,
        maxResults,
        selectedSources,
        sortBy,
        recencyFilter.daysBack,
        csOnly
      );
      setPreview({ ...res, time: new Date().toLocaleTimeString("zh-CN") });
      setSelectedCandidateIds(chooseDefaultCandidates(res.candidates));
      toast("success", `找到 ${res.total} 篇候选论文`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "搜索失败";
      setError(message);
      toast("error", message);
    } finally {
      setSearching(false);
    }
  }, [csOnly, maxResults, query, recencyFilter.daysBack, selectedSources, sortBy, toast]);

  const toggleCandidate = useCallback((id: string) => {
    setSelectedCandidateIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAllNew = useCallback(() => {
    setSelectedCandidateIds(new Set(candidates.filter((item) => !item.exists).map(candidateId)));
  }, [candidates]);

  const clearSelected = useCallback(() => setSelectedCandidateIds(new Set()), []);

  const handleConfirmIngest = useCallback(async () => {
    if (!preview || selectedCandidates.length === 0) return;
    setIngesting(true);
    try {
      const res = await ingestApi.searchSelected(preview.query, selectedCandidates);
      setResults((prev) => [
        {
          ingested: res.ingested,
          newCount: res.new_count,
          existingCount: res.existing_count,
          papers: [...(res.papers || []), ...(res.failed || [])],
          query: preview.query,
          time: new Date().toLocaleTimeString("zh-CN"),
          sources: preview.sources || selectedSources,
          expanded: true,
        },
        ...prev,
      ]);
      const ingestedIds = new Set(selectedCandidates.map(candidateId));
      setPreview((prev) =>
        prev
          ? {
              ...prev,
              candidates: prev.candidates.map((item) =>
                ingestedIds.has(candidateId(item)) ? { ...item, exists: true } : item
              ),
              existing_count: prev.existing_count + ingestedIds.size,
            }
          : prev
      );
      setSelectedCandidateIds(new Set());
      setConfirmOpen(false);
      toast("success", `已入库 ${res.ingested} 篇论文`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "入库失败";
      toast("error", message);
    } finally {
      setIngesting(false);
    }
  }, [preview, selectedCandidates, selectedSources, toast]);

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-6 py-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal text-ink">论文收集</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-secondary">
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                画像偏好：{recencyFilter.label}
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1">
                <Calendar className="h-3.5 w-3.5" />
                {recencyFilter.windowLabel}
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1">
                <ArrowUpDown className="h-3.5 w-3.5" />
                {SORT_LABEL[sortBy]}
              </span>
            </div>
          </div>
        </header>

        <section className="rounded-lg border border-border bg-surface p-4 shadow-sm">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div className="min-w-0">
              <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                搜索主题
              </label>
              <div className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-tertiary" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !searching) void handleSearch();
                    }}
                    placeholder="例如 continual learning, test-time adaptation, RAG evaluation"
                    className="h-11 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <Button
                  onClick={() => void handleSearch()}
                  loading={searching}
                  icon={<Search className="h-4 w-4" />}
                  className="h-11"
                >
                  搜索
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:w-[420px]">
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                  数量
                </span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={maxResultsInput}
                  onChange={(event) => {
                    const next = event.target.value;
                    if (/^\s*\d{0,3}\s*$/.test(next)) setMaxResultsInput(next);
                  }}
                  onBlur={() => setMaxResultsInput(String(maxResults))}
                  className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                  排序
                </span>
                <select
                  value={sortBy}
                  onChange={(event) => setSortBy(event.target.value as SortBy)}
                  className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                >
                  <option value="submittedDate">提交时间</option>
                  <option value="lastUpdatedDate">更新时间</option>
                  <option value="relevance">相关性</option>
                </select>
              </label>
              <label className="flex h-[68px] items-end">
                <span className="flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 text-sm text-ink-secondary hover:bg-hover">
                  <input
                    type="checkbox"
                    checked={csOnly}
                    onChange={(event) => setCsOnly(event.target.checked)}
                    className="h-4 w-4 rounded border-border text-primary"
                  />
                  CS/ML
                </span>
              </label>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                <Database className="h-3.5 w-3.5" />
                论文来源
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {SOURCE_OPTIONS.map((source) => {
                  const active = selectedSources.includes(source.id);
                  return (
                    <button
                      key={source.id}
                      type="button"
                      onClick={() => toggleSource(source.id)}
                      className={`flex h-16 items-center justify-between rounded-lg border px-3 text-left transition ${
                        active
                          ? "border-primary bg-primary/5 text-ink"
                          : "border-border bg-background text-ink-secondary hover:bg-hover"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{source.label}</span>
                        <span className="block truncate text-xs text-ink-tertiary">{source.desc}</span>
                      </span>
                      {active ? (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
                      ) : (
                        <Square className="h-4 w-4 shrink-0 text-ink-tertiary" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                <Calendar className="h-3.5 w-3.5" />
                新旧比例
              </div>
              <div className="grid gap-2">
                {(Object.keys(RECENCY_FILTERS) as RecencyPreference[]).map((key) => {
                  const item = RECENCY_FILTERS[key];
                  const active = key === recencyPreference;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => handleRecencyChange(key)}
                      className={`flex h-12 items-center justify-between rounded-lg border px-3 text-sm transition ${
                        active
                          ? "border-primary bg-primary/5 text-ink"
                          : "border-border bg-background text-ink-secondary hover:bg-hover"
                      }`}
                    >
                      <span>{item.label}</span>
                      <span className="text-xs text-ink-tertiary">{item.windowLabel}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-error/30 bg-error/5 px-4 py-3 text-sm text-error">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 rounded-lg border border-border bg-surface shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <h2 className="text-base font-semibold text-ink">候选论文</h2>
                {preview && (
                  <p className="mt-1 text-xs text-ink-tertiary">
                    {preview.time} · {preview.total} 篇候选 · 已在库 {preview.existing_count} ·
                    已选 {selectedCandidateIds.size}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={selectAllNew}
                  disabled={!preview || selectableCount === 0}
                  icon={<CheckSquare className="h-4 w-4" />}
                >
                  选择新论文
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearSelected}
                  disabled={selectedCandidateIds.size === 0}
                  icon={<X className="h-4 w-4" />}
                >
                  清空
                </Button>
                <Button
                  size="sm"
                  onClick={() => setConfirmOpen(true)}
                  disabled={!preview || selectedCandidateIds.size === 0 || ingesting}
                  loading={ingesting}
                  icon={<Download className="h-4 w-4" />}
                >
                  入库
                </Button>
              </div>
            </div>

            {searching && (
              <div className="flex items-center justify-center gap-2 py-20 text-sm text-ink-secondary">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                正在搜索所选来源
              </div>
            )}

            {!searching && !preview && (
              <Empty
                icon={<Search className="h-12 w-12" />}
                title="还没有搜索结果"
                description="选择论文来源后搜索，候选论文会先停留在这里等待确认。"
              />
            )}

            {!searching && preview && candidates.length === 0 && (
              <Empty
                icon={<Database className="h-12 w-12" />}
                title="没有候选论文"
                description="换一个关键词或放宽时间范围再试。"
              />
            )}

            {!searching && candidates.length > 0 && (
              <div className="divide-y divide-border">
                {candidates.map((candidate) => {
                  const id = candidateId(candidate);
                  const checked = selectedCandidateIds.has(id);
                  return (
                    <article
                      key={id}
                      className={`grid gap-3 px-4 py-4 transition hover:bg-hover/50 sm:grid-cols-[32px_minmax(0,1fr)] ${
                        checked ? "bg-primary/5" : ""
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => toggleCandidate(id)}
                        className="mt-1 flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-background hover:text-primary"
                        aria-label={checked ? "取消选择" : "选择论文"}
                      >
                        {checked ? (
                          <CheckSquare className="h-5 w-5 text-primary" />
                        ) : (
                          <Square className="h-5 w-5" />
                        )}
                      </button>

                      <div className="min-w-0">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <h3 className="min-w-0 flex-1 text-sm font-semibold leading-6 text-ink">
                            {candidate.title}
                          </h3>
                          <div className="flex shrink-0 items-center gap-2">
                            {candidate.exists && (
                              <span className="rounded-md bg-success/10 px-2 py-1 text-xs font-medium text-success">
                                已在库
                              </span>
                            )}
                            {candidate.url && (
                              <a
                                href={candidate.url}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded-md p-1.5 text-ink-tertiary hover:bg-background hover:text-primary"
                                aria-label="打开论文链接"
                              >
                                <ExternalLink className="h-4 w-4" />
                              </a>
                            )}
                          </div>
                        </div>

                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-tertiary">
                          <span>{formatAuthors(candidate.authors)}</span>
                          <span>{formatDate(candidate.publication_date)}</span>
                          {candidate.primary_category && <span>{candidate.primary_category}</span>}
                          {candidate.venue && <span>{candidate.venue}</span>}
                        </div>

                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {sourceBadges(candidate).map((source) => (
                            <span
                              key={source}
                              className="rounded-md border border-border bg-background px-2 py-1 text-xs text-ink-secondary"
                            >
                              {sourceLabel(source)}
                            </span>
                          ))}
                          <span className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
                            <Hash className="h-3 w-3" />
                            {candidate.topic_name || "未归类"}
                          </span>
                          <span className="rounded-md bg-background px-2 py-1 text-xs text-ink-tertiary">
                            匹配 {candidate.match_score}
                          </span>
                          {candidate.topic_confidence !== undefined && (
                            <span className="rounded-md bg-background px-2 py-1 text-xs text-ink-tertiary">
                              主题 {candidate.topic_confidence}
                            </span>
                          )}
                        </div>

                        {candidate.abstract && (
                          <p className="mt-2 line-clamp-2 text-xs leading-5 text-ink-secondary">
                            {candidate.abstract}
                          </p>
                        )}

                        {candidate.match_reasons?.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {candidate.match_reasons.slice(0, 4).map((reason) => (
                              <span
                                key={reason}
                                className="rounded bg-background px-1.5 py-0.5 text-[11px] text-ink-tertiary"
                              >
                                {reason}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>

          <aside className="space-y-5">
            <div className="rounded-lg border border-border bg-surface p-4 shadow-sm">
              <h2 className="text-base font-semibold text-ink">来源状态</h2>
              {!preview?.channel_stats && (
                <p className="mt-3 text-sm text-ink-secondary">搜索后显示每个来源的返回情况。</p>
              )}
              {preview?.channel_stats && (
                <div className="mt-3 space-y-2">
                  {Object.entries(preview.channel_stats).map(([source, stat]) => (
                    <div
                      key={source}
                      className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-ink">{sourceLabel(source)}</span>
                        <span className="text-xs text-ink-tertiary">{stat.total} 条</span>
                      </div>
                      {stat.error ? (
                        <p className="mt-1 text-xs text-error">{stat.error}</p>
                      ) : (
                        <p className="mt-1 text-xs text-ink-tertiary">
                          新候选 {stat.new} · 去重 {stat.duplicates}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-border bg-surface p-4 shadow-sm">
              <h2 className="text-base font-semibold text-ink">最近入库</h2>
              {results.length === 0 && (
                <p className="mt-3 text-sm text-ink-secondary">本轮确认入库的论文会显示在这里。</p>
              )}
              {results.length > 0 && (
                <div className="mt-3 space-y-3">
                  {results.map((result, index) => (
                    <div key={`${result.time}-${index}`} className="rounded-lg border border-border bg-background">
                      <button
                        type="button"
                        onClick={() =>
                          setResults((prev) =>
                            prev.map((item, i) =>
                              i === index ? { ...item, expanded: !item.expanded } : item
                            )
                          )
                        }
                        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-ink">{result.query}</span>
                          <span className="block text-xs text-ink-tertiary">
                            {result.time} · 入库 {result.ingested} · 新增 {result.newCount ?? 0}
                          </span>
                        </span>
                        <span className="shrink-0 rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">
                          {result.sources.map(sourceLabel).join(", ")}
                        </span>
                      </button>
                      {result.expanded && (
                        <div className="border-t border-border px-3 py-2">
                          {result.papers.slice(0, 8).map((paper) => (
                            <button
                              key={`${paper.id}-${paper.title}`}
                              type="button"
                              onClick={() => paper.id && navigate(`/papers/${paper.id}`)}
                              className="block w-full rounded-md px-2 py-2 text-left hover:bg-hover"
                            >
                              <span className="line-clamp-1 text-xs font-medium text-ink">
                                {paper.title}
                              </span>
                              <span className="mt-1 flex flex-wrap gap-2 text-[11px] text-ink-tertiary">
                                {paper.status && <span>{paper.status === "new" ? "新增" : paper.status}</span>}
                                {paper.topic_name && <span>{paper.topic_name}</span>}
                                {paper.source && <span>{sourceLabel(paper.source)}</span>}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>
        </section>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="确认入库"
        description={`将入库 ${selectedCandidates.length} 篇候选论文，并归入 ${selectedTopicNames.length} 个主题库。`}
        confirmLabel={ingesting ? "入库中" : "确认入库"}
        cancelLabel="取消"
        onConfirm={handleConfirmIngest}
        onCancel={() => !ingesting && setConfirmOpen(false)}
      />
    </div>
  );
}
