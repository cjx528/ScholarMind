import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpenCheck,
  ChevronRight,
  Clock3,
  ExternalLink,
  Loader2,
  Radar,
  RefreshCw,
  SearchCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { dailyRadarApi } from "@/services/api";
import type { DailyRadarItem, DailyRadarResponse } from "@/types";

const EMPTY_SECTIONS = { deep: [], quick: [], skip: [] };

function fmtTime(value?: string | null) {
  if (!value) return "尚未生成";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function scoreTone(score: number) {
  if (score >= 80) return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (score >= 60) return "bg-amber-50 text-amber-700 border-amber-200";
  return "bg-slate-50 text-slate-600 border-slate-200";
}

function RadarCard({ item }: { item: DailyRadarItem }) {
  const navigate = useNavigate();
  const reason = item.reason || item.skip_reason || "暂无理由";
  return (
    <article className="rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <button
          onClick={() => navigate(`/papers/${item.paper.id}`)}
          className="text-left text-base font-semibold leading-snug text-ink hover:text-primary"
        >
          {item.paper.title}
        </button>
        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-sm font-semibold ${scoreTone(item.score)}`}>
          {item.score}
        </span>
      </div>
      <p className="mb-3 line-clamp-2 text-sm leading-6 text-ink-secondary">
        {item.tldr || item.paper.abstract || "暂无摘要"}
      </p>
      <div className="mb-3 rounded-md bg-muted/70 px-3 py-2 text-sm leading-6 text-ink-secondary">
        {reason}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-tertiary">
        {item.paper.publication_date && <span>{item.paper.publication_date}</span>}
        {item.paper.source && <span className="rounded bg-hover px-2 py-1">{item.paper.source}</span>}
        {item.matched_topics.slice(0, 3).map((topic) => (
          <span key={topic.id} className="rounded bg-primary/10 px-2 py-1 text-primary">
            {topic.name}
          </span>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-ink-tertiary">
        <span>
          BM25 {Math.round(item.scores.bm25)} · Emb {Math.round(item.scores.embedding)} · 画像 {item.scores.profile}
        </span>
        <button
          onClick={() => navigate(`/papers/${item.paper.id}`)}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-primary hover:bg-primary/10"
        >
          打开
          <ExternalLink className="h-3.5 w-3.5" />
        </button>
      </div>
    </article>
  );
}

function Section({
  title,
  icon: Icon,
  items,
  empty,
}: {
  title: string;
  icon: typeof BookOpenCheck;
  items: DailyRadarItem[];
  empty: string;
}) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="inline-flex items-center gap-2 text-lg font-semibold text-ink">
          <Icon className="h-5 w-5 text-primary" />
          {title}
        </h2>
        <span className="rounded-full bg-hover px-2.5 py-1 text-sm text-ink-secondary">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface p-6 text-sm text-ink-tertiary">
          {empty}
        </div>
      ) : (
        <div className="grid gap-3">
          {items.map((item) => (
            <RadarCard key={item.paper.id} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}

export default function DailyRadar() {
  const [radar, setRadar] = useState<DailyRadarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sections = radar?.sections ?? EMPTY_SECTIONS;
  const totalSelected = (sections.deep?.length ?? 0) + (sections.quick?.length ?? 0);

  const topicText = useMemo(() => {
    const topics = radar?.topics ?? [];
    if (!topics.length) return "用户画像";
    return topics.map((topic) => topic.name).slice(0, 4).join(" / ");
  }, [radar?.topics]);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRadar(await dailyRadarApi.latest(30));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  const runRadar = async () => {
    setRunning(true);
    setError(null);
    try {
      setRadar(await dailyRadarApi.run({ limit: 30, use_llm: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 p-6">
      <div className="flex flex-col gap-4 border-b border-border pb-5 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 text-sm font-medium text-primary">
            <Radar className="h-4 w-4" />
            研究雷达
          </div>
          <h1 className="text-2xl font-semibold text-ink">今日推荐</h1>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink-secondary">
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="h-4 w-4" />
              {fmtTime(radar?.generated_at)}
            </span>
            <span>{topicText}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={loadLatest}
            disabled={loading || running}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium text-ink hover:bg-hover disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            读取最新
          </button>
          <button
            onClick={runRadar}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            生成雷达
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="text-sm text-ink-tertiary">候选池</div>
          <div className="mt-2 text-2xl font-semibold text-ink">{radar?.summary.candidate_count ?? 0}</div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="text-sm text-ink-tertiary">已排序</div>
          <div className="mt-2 text-2xl font-semibold text-ink">{radar?.summary.ranked_count ?? 0}</div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="text-sm text-ink-tertiary">今日阅读</div>
          <div className="mt-2 text-2xl font-semibold text-ink">{totalSelected}</div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="text-sm text-ink-tertiary">LLM refine</div>
          <div className="mt-2 text-2xl font-semibold text-ink">
            {radar?.summary.used_llm_refine ? "已启用" : "未启用"}
          </div>
        </div>
      </div>

      {(radar?.stages?.length ?? 0) > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface p-3">
          <div className="flex min-w-max items-center gap-2">
            {radar!.stages.map((stage, index) => (
              <div key={`${stage.name}-${index}`} className="flex items-center gap-2">
                <div className="rounded-md bg-hover px-3 py-2 text-sm text-ink-secondary">
                  <span className="font-medium text-ink">{stage.name}</span>
                  <span className="ml-2 text-ink-tertiary">{stage.count}</span>
                </div>
                {index < radar!.stages.length - 1 && <ChevronRight className="h-4 w-4 text-ink-tertiary" />}
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && !radar ? (
        <div className="flex min-h-[260px] items-center justify-center rounded-lg border border-border bg-surface">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[1fr_1fr_1fr]">
          <Section
            title="精读候选"
            icon={BookOpenCheck}
            items={sections.deep}
            empty="暂无精读候选"
          />
          <Section
            title="速读候选"
            icon={SearchCheck}
            items={sections.quick}
            empty="暂无速读候选"
          />
          <Section
            title="跳过原因"
            icon={XCircle}
            items={sections.skip}
            empty="暂无跳过记录"
          />
        </div>
      )}
    </div>
  );
}
