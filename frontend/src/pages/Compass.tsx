import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Brain,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Plus,
  Radar,
  RefreshCw,
  Save,
  Star,
  Wand2,
} from "lucide-react";
import { compassApi } from "@/services/api";
import type {
  CompassAnalysisBlock,
  CompassAnalysisResult,
  CompassFactorKey,
  CompassPreferenceModel,
  CompassUserProfile,
} from "@/types";

const FACTOR_KEYS: CompassFactorKey[] = [
  "profileFit",
  "novelty",
  "paperImportance",
  "sourceSignal",
  "actionability",
  "freshness",
];

const FACTOR_LABELS: Record<CompassFactorKey, string> = {
  profileFit: "画像匹配",
  novelty: "新信息量",
  paperImportance: "论文重要性",
  sourceSignal: "来源信号",
  actionability: "可行动性",
  freshness: "近期性",
};

type QuickProfile = {
  currentInterests: string[];
  downrankAreas: string[];
  paperTypes: string[];
  readingGoals: string[];
  modalityFocus: string[];
  riskLevel: string;
  recencyPreference: string;
  extraNotes: string;
};

type QuickGroupKey = keyof Pick<
  QuickProfile,
  "currentInterests" | "downrankAreas" | "paperTypes" | "readingGoals"
>;

const EMPTY_PROFILE: CompassUserProfile = {
  user_id: "local",
  interests: "",
  researchDirections: "",
  readingGoal: "",
  quickProfile: {},
  questions: [],
  notes: [],
  confidence: 0,
};

const EMPTY_MODEL: CompassPreferenceModel = {
  weights: {
    profileFit: 0.34,
    novelty: 0.14,
    paperImportance: 0.18,
    sourceSignal: 0.1,
    actionability: 0.16,
    freshness: 0.08,
  },
  bias: 0,
  ratingCount: 0,
};

const DEFAULT_QUICK_PROFILE: QuickProfile = {
  currentInterests: [],
  downrankAreas: [],
  paperTypes: [],
  readingGoals: [],
  modalityFocus: [],
  riskLevel: "balanced",
  recencyPreference: "recent",
  extraNotes: "",
};

const EMPTY_CUSTOM_QUICK_INPUTS: Record<QuickGroupKey, string> = {
  currentInterests: "",
  downrankAreas: "",
  paperTypes: "",
  readingGoals: "",
};

const QUICK_GROUPS: Array<{
  key: QuickGroupKey;
  title: string;
  options: string[];
  customPlaceholder: string;
}> = [
  {
    key: "currentInterests",
    title: "现在最想追",
    options: [
      "LLM",
      "LLM 预训练",
      "LLM 后训练/SFT/RLHF",
      "对齐与偏好优化",
      "推理能力/数学推理",
      "长上下文/记忆",
      "RAG/知识增强",
      "Agent/工具调用",
      "多智能体协作",
      "代码大模型",
      "高效推理/模型压缩",
      "评测/Benchmark",
      "安全/鲁棒/可解释",
      "数据合成/数据治理",
      "MLLM/VLM",
      "多模态推理",
      "图像生成/编辑",
      "视频理解",
      "视频生成",
      "语音交互/语音大模型",
      "音频理解/生成",
      "具身智能/机器人",
      "世界模型",
      "AI4Science",
      "AI Infra/训练系统",
    ],
    customPlaceholder: "其他方向，例如：HCI、数据库、医学影像、计算社会科学",
  },
  {
    key: "downrankAreas",
    title: "暂时少推",
    options: ["传统语音增强", "纯 benchmark", "弱开源工作", "小修小补方法", "只做应用包装", "过时架构"],
    customPlaceholder: "其他少推方向",
  },
  {
    key: "paperTypes",
    title: "论文类型偏好",
    options: ["方法突破", "开源系统", "数据集", "评测框架", "综述地图", "产业信号"],
    customPlaceholder: "其他论文类型",
  },
  {
    key: "readingGoals",
    title: "读论文目的",
    options: ["找 idea", "找 baseline", "写 paper", "做产品判断", "建领域地图", "找可复现代码"],
    customPlaceholder: "其他阅读目标",
  },
];

const RISK_OPTIONS = [
  { value: "stable", label: "稳健可复现" },
  { value: "balanced", label: "平衡" },
  { value: "frontier", label: "高风险新想法" },
];

const RECENCY_OPTIONS = [
  { value: "recent", label: "新论文优先", desc: "默认近 180 天，必要时再放宽" },
  { value: "balanced", label: "新旧平衡", desc: "默认近 2 年，同时保留经典线索" },
  { value: "classic", label: "经典也可", desc: "不限时间，但仍按近期性加分" },
];

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "操作失败";
}

function titleOf(item: CompassAnalysisResult | null) {
  if (!item) return "";
  return item.paper?.title || item.title || "未命名论文";
}

function summaryOf(item: CompassAnalysisResult) {
  return item.paper?.plainSummary || item.abstract || "暂无摘要。";
}

function sourceLabel(item: CompassAnalysisResult) {
  if (item.status === "library") return "论文库";
  return item.source_type || "text";
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function normalizeQuickProfile(value: unknown): QuickProfile {
  const raw = value && typeof value === "object" ? (value as Partial<QuickProfile>) : {};
  return {
    currentInterests: stringArray(raw.currentInterests),
    downrankAreas: stringArray(raw.downrankAreas),
    paperTypes: stringArray(raw.paperTypes),
    readingGoals: stringArray(raw.readingGoals),
    modalityFocus: stringArray(raw.modalityFocus),
    riskLevel: RISK_OPTIONS.some((item) => item.value === raw.riskLevel)
      ? String(raw.riskLevel)
      : DEFAULT_QUICK_PROFILE.riskLevel,
    recencyPreference: RECENCY_OPTIONS.some((item) => item.value === raw.recencyPreference)
      ? String(raw.recencyPreference)
      : DEFAULT_QUICK_PROFILE.recencyPreference,
    extraNotes: String(raw.extraNotes || ""),
  };
}

function listLine(label: string, values: string[]) {
  return values.length > 0 ? `${label}：${values.join("、")}` : "";
}

function summarizeQuickProfile(quickProfile: QuickProfile) {
  const lines = [
    listLine("当前最想追", quickProfile.currentInterests),
    listLine("暂时少推", quickProfile.downrankAreas),
    listLine("论文类型偏好", quickProfile.paperTypes),
    listLine("读论文目的", quickProfile.readingGoals),
    `探索风格：${RISK_OPTIONS.find((item) => item.value === quickProfile.riskLevel)?.label ?? "平衡"}`,
    `论文新旧比例：${
      RECENCY_OPTIONS.find((item) => item.value === quickProfile.recencyPreference)?.label ??
      "新论文优先"
    }`,
    quickProfile.extraNotes.trim() ? `补充说明：${quickProfile.extraNotes.trim()}` : "",
  ].filter(Boolean);

  return lines.length > 1 ? ["快速校准选择：", ...lines].join("\n") : "";
}

function quickProfileAnswers(quickProfile: QuickProfile) {
  const answers = [
    { question: "接下来 1-3 个月最想重点读哪些方向？", answer: quickProfile.currentInterests.join("、") },
    { question: "哪些方向暂时少推？", answer: quickProfile.downrankAreas.join("、") },
    { question: "更偏好什么类型的论文？", answer: quickProfile.paperTypes.join("、") },
    { question: "读论文的主要目的是什么？", answer: quickProfile.readingGoals.join("、") },
    {
      question: "偏好稳健可复现还是高风险新想法？",
      answer: RISK_OPTIONS.find((item) => item.value === quickProfile.riskLevel)?.label ?? "",
    },
    {
      question: "推荐新论文和经典论文的比例？",
      answer:
        RECENCY_OPTIONS.find((item) => item.value === quickProfile.recencyPreference)?.label ?? "",
    },
    { question: "还有什么个性化补充？", answer: quickProfile.extraNotes.trim() },
  ];
  return answers.filter((item) => item.answer.trim());
}

export default function Compass() {
  const [profile, setProfile] = useState<CompassUserProfile>(EMPTY_PROFILE);
  const [model, setModel] = useState<CompassPreferenceModel>(EMPTY_MODEL);
  const [queue, setQueue] = useState<CompassAnalysisResult[]>([]);
  const [active, setActive] = useState<CompassAnalysisResult | null>(null);
  const [quickProfile, setQuickProfile] = useState<QuickProfile>(DEFAULT_QUICK_PROFILE);
  const [customQuickInputs, setCustomQuickInputs] = useState<Record<QuickGroupKey, string>>(
    EMPTY_CUSTOM_QUICK_INPUTS
  );
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const [profileRes, queueRes] = await Promise.all([compassApi.profile(), compassApi.queue(30)]);
    setProfile(profileRes.profile);
    setModel(profileRes.model);
    setQuickProfile(normalizeQuickProfile(profileRes.profile.quickProfile));
    setQueue(queueRes.items);
    setActive((current) => current ?? queueRes.items[0] ?? null);
  }, []);

  useEffect(() => {
    load().catch((err) => setError(errorMessage(err)));
  }, [load]);

  const weightedLabels = useMemo(
    () =>
      FACTOR_KEYS.map((key) => ({
        key,
        label: FACTOR_LABELS[key],
        weight: Math.round((model.weights?.[key] ?? 0) * 100),
      })),
    [model.weights]
  );

  const toggleQuickChoice = (key: QuickGroupKey, value: string) => {
    setQuickProfile((current) => {
      const exists = current[key].includes(value);
      return {
        ...current,
        [key]: exists ? current[key].filter((item) => item !== value) : [...current[key], value],
      };
    });
  };

  const addCustomQuickChoice = (key: QuickGroupKey) => {
    const value = customQuickInputs[key].trim();
    if (!value) return;

    setQuickProfile((current) => {
      if (current[key].includes(value)) return current;
      return {
        ...current,
        [key]: [...current[key], value],
      };
    });
    setCustomQuickInputs((current) => ({ ...current, [key]: "" }));
  };

  const saveProfile = async () => {
    setBusy("save-profile");
    setError(null);
    try {
      const res = await compassApi.updateProfile({
        interests: profile.interests,
        researchDirections: profile.researchDirections,
        readingGoal: profile.readingGoal,
        quickProfile,
      });
      setProfile(res.profile);
      setModel(res.model);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const buildProfile = async () => {
    const source = summarizeQuickProfile(quickProfile);
    if (!source.trim()) {
      setError("请先完成至少一个快速选择，或填写补充说明。");
      return;
    }
    setBusy("build-profile");
    setError(null);
    try {
      const res = await compassApi.buildProfile({
        source,
        currentProfile: profile,
        quickProfile,
        answers: [
          ...quickProfileAnswers(quickProfile),
          ...profile.questions
            .map((question) => ({
              question: question.question,
              answer: answers[question.id] || "",
            }))
            .filter((item) => item.answer.trim()),
        ],
      });
      setProfile(res.profile);
      setAnswers({});
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const analyzePaper = async (item: CompassAnalysisResult) => {
    setBusy(`paper-${item.paper_id || item.id}`);
    setError(null);
    try {
      const result = await compassApi.analyze({
        input: titleOf(item),
        paper_id: item.paper_id || item.id,
        mode: "library",
      });
      setActive(result);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const rate = async (value: number) => {
    if (!active) return;
    setBusy(`rate-${value}`);
    setError(null);
    try {
      const res = await compassApi.feedback({
        recommendation_id: active.status === "library" ? null : active.id,
        paper_id: active.paper_id || active.id,
        rating: value,
        factors: active.recommendation.factors,
        base_score: active.recommendation.score,
      });
      setModel(res.model);
      setActive((prev) => (prev ? { ...prev, user_rating: value } : prev));
      const queueRes = await compassApi.queue(30);
      setQueue(queueRes.items);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const resetModel = async () => {
    setBusy("reset-model");
    setError(null);
    try {
      const res = await compassApi.resetModel();
      setModel(res.model);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-full bg-page px-4 py-5 text-ink sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1480px] flex-col gap-5">
        <header className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-primary">
              <Radar className="h-4 w-4" />
              Scholar Profile
            </div>
            <h1 className="text-2xl font-semibold text-ink">用户画像与论文匹配</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={saveProfile}
              disabled={busy === "save-profile"}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-white disabled:opacity-60"
            >
              {busy === "save-profile" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存画像
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
            {error}
          </div>
        )}

        <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)_380px]">
          <section className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-base font-semibold">
                <Brain className="h-4 w-4 text-primary" />
                研究画像
              </h2>
              <span className="rounded-full bg-primary-light px-2 py-1 text-xs font-medium text-primary">
                {profile.confidence}%
              </span>
            </div>
            <div className="space-y-3">
              {QUICK_GROUPS.map((group) => (
                <fieldset key={group.key} className="rounded-lg border border-border bg-page p-3">
                  <legend className="px-1 text-xs font-semibold text-ink-secondary">
                    {group.title}
                  </legend>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {group.options.map((option) => {
                      const activeChoice = quickProfile[group.key].includes(option);
                      return (
                        <button
                          key={option}
                          type="button"
                          onClick={() => toggleQuickChoice(group.key, option)}
                          className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition ${
                            activeChoice
                              ? "border-primary bg-primary-light text-primary"
                              : "border-border bg-surface text-ink-secondary hover:bg-hover"
                          }`}
                        >
                          {activeChoice && <CheckCircle2 className="h-3 w-3" />}
                          {option}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <input
                      value={customQuickInputs[group.key]}
                      onChange={(event) =>
                        setCustomQuickInputs((current) => ({
                          ...current,
                          [group.key]: event.target.value,
                        }))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addCustomQuickChoice(group.key);
                        }
                      }}
                      placeholder={group.customPlaceholder}
                      className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink placeholder:text-ink-muted"
                    />
                    <button
                      type="button"
                      onClick={() => addCustomQuickChoice(group.key)}
                      disabled={!customQuickInputs[group.key].trim()}
                      className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-xs font-medium text-ink-secondary transition hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      添加
                    </button>
                  </div>
                </fieldset>
              ))}
              <fieldset className="rounded-lg border border-border bg-page p-3">
                <legend className="px-1 text-xs font-semibold text-ink-secondary">探索风格</legend>
                <div className="mt-2 flex flex-wrap gap-2">
                  {RISK_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() =>
                        setQuickProfile((current) => ({ ...current, riskLevel: option.value }))
                      }
                      className={`h-8 rounded-full border px-3 text-xs font-medium transition ${
                        quickProfile.riskLevel === option.value
                          ? "border-primary bg-primary-light text-primary"
                          : "border-border bg-surface text-ink-secondary hover:bg-hover"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </fieldset>
              <fieldset className="rounded-lg border border-border bg-page p-3">
                <legend className="px-1 text-xs font-semibold text-ink-secondary">论文新旧比例</legend>
                <div className="mt-2 grid gap-2">
                  {RECENCY_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() =>
                        setQuickProfile((current) => ({
                          ...current,
                          recencyPreference: option.value,
                        }))
                      }
                      className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                        quickProfile.recencyPreference === option.value
                          ? "border-primary bg-primary-light text-primary"
                          : "border-border bg-surface text-ink-secondary hover:bg-hover"
                      }`}
                    >
                      <span className="block font-semibold">{option.label}</span>
                      <span className="mt-0.5 block text-[11px] opacity-80">{option.desc}</span>
                    </button>
                  ))}
                </div>
              </fieldset>
            </div>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-ink-secondary">补充一句，可不填</span>
              <textarea
                value={quickProfile.extraNotes}
                onChange={(event) =>
                  setQuickProfile((current) => ({ ...current, extraNotes: event.target.value }))
                }
                placeholder="例如：我过去做音频，但现在希望 MLLM/agent 权重更高；有代码和可复现实验的论文优先。"
                className="min-h-16 w-full resize-y rounded-lg border border-border bg-page px-3 py-2 text-sm"
              />
            </label>
            {(profile.interests || profile.researchDirections || profile.readingGoal) && (
              <div className="space-y-3 rounded-lg border border-border bg-page p-3">
                <p className="text-sm font-semibold text-ink">已生成画像</p>
                {profile.interests && (
                  <ProfileParagraph title="关注偏好" body={profile.interests} />
                )}
                {profile.researchDirections && (
                  <ProfileParagraph title="推荐方向" body={profile.researchDirections} />
                )}
                {profile.readingGoal && (
                  <ProfileParagraph title="阅读目标" body={profile.readingGoal} />
                )}
                {profile.notes.length > 0 && (
                  <div className="rounded-md bg-surface px-3 py-2">
                    <p className="mb-1 text-xs font-semibold text-ink-secondary">推荐策略</p>
                    <ul className="space-y-1 text-xs leading-5 text-ink-secondary">
                      {profile.notes.slice(0, 5).map((note, index) => (
                        <li key={`${note}-${index}`}>{note}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {profile.questions.length > 0 && (
              <div className="space-y-3">
                {profile.questions.slice(0, 4).map((question) => (
                  <label key={question.id} className="block space-y-1.5">
                    <span className="text-xs font-medium text-ink-secondary">{question.question}</span>
                    <input
                      value={answers[question.id] || ""}
                      onChange={(event) =>
                        setAnswers((prev) => ({ ...prev, [question.id]: event.target.value }))
                      }
                      placeholder={question.placeholder}
                      className="h-10 w-full rounded-lg border border-border bg-page px-3 text-sm"
                    />
                  </label>
                ))}
              </div>
            )}
            <button
              onClick={buildProfile}
              disabled={busy === "build-profile"}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary-light px-3 text-sm font-medium text-primary disabled:opacity-60"
            >
              {busy === "build-profile" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              生成画像
            </button>
            <div className="border-t border-border pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-ink-secondary">学习权重</span>
                <button
                  onClick={resetModel}
                  disabled={busy === "reset-model"}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-ink-tertiary hover:bg-hover"
                >
                  <RefreshCw className="h-3 w-3" />
                  重置
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {weightedLabels.map((item) => (
                  <div key={item.key} className="rounded-md bg-page px-2 py-1.5 text-xs">
                    <span className="text-ink-secondary">{item.label}</span>
                    <strong className="float-right text-ink">{item.weight}%</strong>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-ink-tertiary">已评分 {model.ratingCount}</p>
            </div>
          </section>

          <main className="flex min-w-0 flex-col gap-4">
            <ActiveResult
              item={active}
              busy={busy}
              onAnalyzePaper={analyzePaper}
              onRate={rate}
            />
          </main>

          <aside className="rounded-lg border border-border bg-surface p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold">画像匹配队列</h2>
              <span className="text-xs text-ink-tertiary">{queue.length} 篇</span>
            </div>
            <div className="space-y-2">
              {queue.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-ink-tertiary">
                  暂无推荐项
                </div>
              ) : (
                queue.map((item) => (
                  <button
                    key={`${item.status}-${item.id}`}
                    onClick={() => setActive(item)}
                    className={`w-full rounded-lg border px-3 py-3 text-left transition ${
                      active?.id === item.id
                        ? "border-primary bg-primary-light"
                        : "border-border bg-page hover:bg-hover"
                    }`}
                  >
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <strong className="line-clamp-2 text-sm text-ink">{titleOf(item)}</strong>
                      <span className="shrink-0 rounded-md bg-surface px-2 py-1 text-xs font-semibold text-primary">
                        {Math.round(item.final_score)}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs text-ink-secondary">{item.recommendation.reason}</p>
                    <div className="mt-2 flex items-center justify-between text-xs text-ink-tertiary">
                      <span>{sourceLabel(item)}</span>
                      <span>{item.user_rating ? `${item.user_rating} 星` : "未评分"}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

function ProfileParagraph({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-md bg-surface px-3 py-2">
      <p className="mb-1 text-xs font-semibold text-ink-secondary">{title}</p>
      <p className="text-xs leading-5 text-ink-secondary">{body}</p>
    </div>
  );
}

function ActiveResult({
  item,
  busy,
  onAnalyzePaper,
  onRate,
}: {
  item: CompassAnalysisResult | null;
  busy: string | null;
  onAnalyzePaper: (item: CompassAnalysisResult) => void;
  onRate: (value: number) => void;
}) {
  if (!item) {
    return (
      <section className="rounded-lg border border-dashed border-border bg-surface px-6 py-14 text-center text-sm text-ink-tertiary">
        选择推荐项或解析新材料
      </section>
    );
  }
  const isLibrary = item.status === "library";
  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-primary-light px-2 py-1 text-xs font-semibold text-primary">
            推荐 {Math.round(item.final_score)}
          </span>
          <span className="rounded-md bg-page px-2 py-1 text-xs text-ink-secondary">
            {sourceLabel(item)}
          </span>
          {item.source_url && (
            <a
              href={item.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-primary hover:bg-primary-light"
            >
              <ExternalLink className="h-3 w-3" />
              来源
            </a>
          )}
        </div>
        <h2 className="text-xl font-semibold leading-snug text-ink">{titleOf(item)}</h2>
        <p className="mt-2 text-sm leading-6 text-ink-secondary">{summaryOf(item)}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {isLibrary && (
            <button
              onClick={() => onAnalyzePaper(item)}
              disabled={busy === `paper-${item.paper_id || item.id}`}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-primary/30 bg-primary-light px-3 text-sm font-medium text-primary disabled:opacity-60"
            >
              {busy === `paper-${item.paper_id || item.id}` ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <BookOpen className="h-4 w-4" />
              )}
              深度解析
            </button>
          )}
          <div className="flex items-center gap-1">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                onClick={() => onRate(value)}
                disabled={busy === `rate-${value}`}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-amber-500 hover:bg-amber-50 disabled:opacity-60"
                title={`${value} 星`}
              >
                <Star
                  className={`h-4 w-4 ${
                    (item.user_rating || 0) >= value ? "fill-current" : ""
                  }`}
                />
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-3">
          {FACTOR_KEYS.map((key) => (
            <FactorBar key={key} label={FACTOR_LABELS[key]} value={item.recommendation.factors[key]} />
          ))}
          <div className="rounded-lg bg-page p-3 text-sm leading-6 text-ink-secondary">
            <CheckCircle2 className="mb-2 h-4 w-4 text-primary" />
            {item.recommendation.reason}
          </div>
        </div>
        <div className="min-w-0 space-y-4">
          {(item.analysis_blocks || []).length > 0 ? (
            item.analysis_blocks?.map((block, index) => <AnalysisBlock key={index} block={block} />)
          ) : (
            <div className="rounded-lg bg-page p-4 text-sm leading-6 text-ink-secondary">
              {summaryOf(item)}
            </div>
          )}
          {item.trace && item.trace.length > 0 && (
            <div className="rounded-lg border border-border bg-page p-3">
              <p className="mb-2 text-xs font-semibold text-ink-tertiary">Trace</p>
              <ul className="space-y-1 text-xs text-ink-secondary">
                {item.trace.slice(0, 6).map((line, index) => (
                  <li key={`${line}-${index}`}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function FactorBar({ label, value }: { label: string; value: number }) {
  const safeValue = Math.max(0, Math.min(100, Math.round(value || 0)));
  return (
    <div className="rounded-lg bg-page p-3">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="font-medium text-ink-secondary">{label}</span>
        <strong className="text-ink">{safeValue}</strong>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-border">
        <div className="h-full rounded-full bg-primary" style={{ width: `${safeValue}%` }} />
      </div>
    </div>
  );
}

function AnalysisBlock({ block }: { block: CompassAnalysisBlock }) {
  if (block.type === "image" && block.url) {
    return (
      <figure className="overflow-hidden rounded-lg border border-border bg-page">
        <img src={block.url} alt={block.alt || block.caption || ""} className="max-h-[420px] w-full object-contain" />
        {(block.caption || block.heading) && (
          <figcaption className="border-t border-border px-3 py-2 text-sm text-ink-secondary">
            {block.caption || block.heading}
          </figcaption>
        )}
      </figure>
    );
  }
  return (
    <article className="rounded-lg bg-page p-4">
      {block.heading && <h3 className="mb-2 text-base font-semibold text-ink">{block.heading}</h3>}
      <p className="whitespace-pre-wrap text-sm leading-7 text-ink-secondary">{block.body}</p>
    </article>
  );
}
