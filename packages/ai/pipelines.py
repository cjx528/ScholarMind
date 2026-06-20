"""
论文处理 Pipeline - 摄入 / 粗读 / 精读 / 向量化 / 参考文献导入
@author ScholarMind Team
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from datetime import date, datetime
from uuid import UUID, uuid4

from packages.ai.cost_guard import CostGuardService
from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_deep_prompt, build_skim_prompt
from packages.ai.vision_reader import VisionPdfReader
from packages.config import get_settings
from packages.domain.enums import ActionType, ReadStatus
from packages.domain.schemas import DeepDiveReport, PaperCreate, SkimReport
from packages.domain.task_tracker import global_tracker
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.llm_client import LLMClient
from packages.integrations.openreview_client import OpenReviewClient
from packages.integrations.semantic_scholar_client import SemanticScholarClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    ActionRepository,
    AnalysisRepository,
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
)

logger = logging.getLogger(__name__)

_PROMPT_LEAK_RE = re.compile(
    r"(\[skim\]\s*provider=|provider=|model=|summary=|请只输出|单个\s*JSON|"
    r"markdown\s*代码块|不要输出|保持\s*JSON|你是科研助手|你是论文粗读助手|"
    r"字段固定为|字段要求|硬性要求|relevance_score|one_liner|innovations|title_zh|abstract_zh|"
    r"60\s*[-到]\s*100\s*字|120\s*[-到]\s*220\s*字|3\s*[-到]\s*5\s*条|3\s*[-到]\s*8\s*个|"
    r"直接说明论文解决的问题|核心方法和最主要贡献|核心方法和主要贡献|"
    r"每条必须来自标题或摘要|英文技术关键词|不能写占位符|不能写模板说明)",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r"^(创新点\d*|keyword\d*|中文标题|中文摘要|方法总结|实验总结|一句话|3\s*[-到]\s*5|"
    r"用一句话概括论文核心贡献|从摘要中提取的创新点\d*)$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-_/]{2,}")


def _compact_text(value: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _is_bad_skim_text(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return bool(_PROMPT_LEAK_RE.search(text) or _PLACEHOLDER_RE.match(text))


def _clean_skim_text(value: object, limit: int) -> str:
    text = _compact_text(str(value or ""), limit)
    return "" if _is_bad_skim_text(text) else text


def _first_abstract_sentences(abstract: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", abstract or "").strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    joined = " ".join([p for p in parts if p][:2]) or cleaned
    return _compact_text(joined, limit)


def _fallback_keywords(title: str, abstract: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "using",
        "based",
        "paper",
        "model",
        "models",
        "method",
        "methods",
        "approach",
        "results",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for match in _WORD_RE.findall(f"{title} {abstract}"):
        key = match.strip("-_/").lower()
        if key in stop or len(key) < 3 or key in seen:
            continue
        seen.add(key)
        keywords.append(match.strip("-_/")[:60])
        if len(keywords) >= 8:
            break
    return keywords


def _fallback_skim(title: str, abstract: str, score: float = 0.5) -> SkimReport:
    title = _compact_text(title, 180) or "这篇论文"
    abstract_head = _first_abstract_sentences(abstract, 220)
    keywords = _fallback_keywords(title, abstract)
    keyword_text = "、".join(keywords[:5])
    if keyword_text:
        one_liner = (
            f"仅基于标题和摘要可判断，这篇论文围绕 {title} 展开，"
            f"重点涉及 {keyword_text}；建议先看方法图、实验表和消融结果确认核心贡献。"
        )
    elif abstract_head:
        one_liner = (
            f"仅基于标题和摘要可判断，这篇论文围绕 {title} 展开；"
            "建议先补充方法图和实验部分，再决定是否进入精读。"
        )
    else:
        one_liner = f"当前只获得题名 {title}，信息不足，建议先补全摘要或下载 PDF 后再判断是否值得精读。"
    innovations = [
        "研究问题：从题名和摘要中先定位论文要解决的具体任务、输入输出和应用场景。",
        "方法线索：优先检查摘要里是否出现新框架、新训练策略、新数据或新的推理流程。",
        "证据线索：继续精读时需要核对实验指标、对比基线、消融结果和是否有可复现资源。",
    ]
    if keyword_text:
        innovations[0] = f"主题线索：标题和摘要显示该工作主要关联 {keyword_text}。"
    if abstract_head:
        innovations[1] = f"摘要线索：{_compact_text(abstract_head, 170)}"
    return SkimReport(
        one_liner=_compact_text(one_liner, 280),
        innovations=innovations,
        keywords=keywords,
        title_zh="",
        abstract_zh="",
        relevance_score=min(max(score, 0.0), 1.0),
    )


class PaperPipelines:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.llm = LLMClient()
        self.vision = VisionPdfReader()
        self.pdf_extractor = PdfTextExtractor()

    def _save_paper(self, repo, paper, topic_id=None, download_pdf=False):
        """入库 + 下载 PDF 的公共逻辑

        Args:
            repo: PaperRepository
            paper: PaperCreate 数据
            topic_id: 可选的主题 ID
            download_pdf: 是否下载 PDF（默认 False，只在精读时下载）
        """
        saved = repo.upsert_paper(paper)
        if topic_id:
            repo.link_to_topic(saved.id, topic_id)

        # 只在明确需要时才下载 PDF
        if download_pdf:
            try:
                pdf_path = self.arxiv.download_pdf(paper.arxiv_id)
                repo.set_pdf_path(saved.id, pdf_path)
            except Exception as exc:
                logger.warning("PDF download failed for %s: %s", paper.arxiv_id, exc)

        return saved

    def ingest_arxiv(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.manual_collect,
        sort_by: str = "submittedDate",
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> tuple[int, list[str], int]:
        """搜索 arXiv 并入库，upsert 去重。返回 (total_count, inserted_ids, new_papers_count)

        智能递归抓取：如果前 N 篇有重复，继续抓取更早的论文，直到找到 max_results 篇新论文

        Args:
            progress_callback: 可选的进度回调函数，签名 callback(message, current, total)
        """
        inserted_ids: list[str] = []
        new_papers_count: int = 0
        total_fetched = 0
        batch_size = 20
        max_pages = 10  # 最多抓取 10 批（200 篇），直到找到 max_results 篇新论文
        arxiv_request_delay = 3.0  # arXiv API 建议请求间隔 3 秒

        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            action_repo = ActionRepository(session)
            run = run_repo.start("ingest_arxiv", decision_note=f"query={query}")

            try:
                # 分批抓取，直到找到足够的新论文或达到最大页数
                for page in range(max_pages):
                    if new_papers_count >= max_results:
                        break  # 已找到足够的新论文

                    start = page * batch_size
                    # 计算本批需要抓取的数量（避免超目标）
                    needed = max_results - new_papers_count
                    this_batch = min(batch_size, needed + 20)  # 多抓 20 篇作为缓冲

                    if progress_callback:
                        progress_callback(f"抓取第 {page + 1}/{max_pages} 批", page + 1, max_pages)

                    papers = self.arxiv.fetch_latest(
                        query=query,
                        max_results=this_batch,
                        sort_by=sort_by,
                        start=start,
                        days_back=days_back,
                    )
                    total_fetched += len(papers)

                    if not papers:
                        break  # 没有更多论文了

                    # 提前检查哪些论文已存在
                    existing_arxiv_ids = repo.list_existing_arxiv_ids([p.arxiv_id for p in papers])

                    # 只处理新论文
                    for paper in papers:
                        is_new = paper.arxiv_id not in existing_arxiv_ids
                        if is_new:
                            saved = self._save_paper(repo, paper, topic_id)
                            new_papers_count += 1
                            inserted_ids.append(saved.id)

                            # 达到目标就停止
                            if new_papers_count >= max_results:
                                break

                    # 日志
                    new_in_batch = len(papers) - len(existing_arxiv_ids)
                    logger.info(
                        "第 %d 批：抓取 %d 篇，新论文 %d 篇（累计 %d/%d）",
                        page + 1,
                        len(papers),
                        new_in_batch,
                        new_papers_count,
                        max_results,
                    )

                    # 只在还会继续分页时等待，避免达到目标后额外阻塞。
                    if page < max_pages - 1 and new_papers_count < max_results:
                        time.sleep(arxiv_request_delay)

                if inserted_ids:
                    action_repo.create_action(
                        action_type=action_type,
                        title=f"收集：{query[:80]}",
                        paper_ids=inserted_ids,
                        query=query,
                        topic_id=topic_id,
                    )

                run_repo.finish(run.id)
                logger.info(
                    "抓取完成：共 %d 篇新论文（从 %d 篇中筛选）",
                    new_papers_count,
                    total_fetched,
                )
                return len(inserted_ids), inserted_ids, new_papers_count
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def ingest_arxiv_with_ids(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
        sort_by: str = "submittedDate",
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> list[str]:
        """ingest_arxiv 的别名，返回 inserted_ids"""
        _, ids, _ = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
            sort_by=sort_by,
            days_back=days_back,
            progress_callback=progress_callback,
        )
        return ids

    def ingest_arxiv_with_stats(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
        sort_by: str = "submittedDate",
        days_back: int = 7,
        progress_callback: callable | None = None,
    ) -> dict:
        """ingest_arxiv 返回详细统计信息"""
        total_count, inserted_ids, new_count = self.ingest_arxiv(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
            sort_by=sort_by,
            days_back=days_back,
            progress_callback=progress_callback,
        )
        return {
            "total_count": total_count,
            "inserted_ids": inserted_ids,
            "new_count": new_count,
        }

    def ingest_openreview(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.manual_collect,
    ) -> tuple[int, list[str], int]:
        """Search OpenReview public papers and insert unseen records."""
        client = OpenReviewClient()
        inserted_ids: list[str] = []
        new_papers_count = 0

        with session_scope() as session:
            repo = PaperRepository(session)
            run_repo = PipelineRunRepository(session)
            action_repo = ActionRepository(session)
            run = run_repo.start("ingest_openreview", decision_note=f"query={query}")

            try:
                papers = client.search_papers(query=query, max_results=max_results)
                if not papers:
                    run_repo.finish(run.id)
                    return 0, [], 0

                normalized_ids = [p.normalized_arxiv_id for p in papers if p.normalized_arxiv_id]
                existing_ids = repo.list_existing_arxiv_ids(normalized_ids)

                for paper in papers:
                    normalized_id = paper.normalized_arxiv_id
                    if normalized_id and normalized_id in existing_ids:
                        continue
                    saved = repo.upsert_paper(paper)
                    if topic_id:
                        repo.link_to_topic(saved.id, topic_id)
                    inserted_ids.append(str(saved.id))
                    new_papers_count += 1

                    if new_papers_count >= max_results:
                        break

                if inserted_ids:
                    action_repo.create_action(
                        action_type=action_type,
                        title=f"OpenReview 收集：{query[:80]}",
                        paper_ids=inserted_ids,
                        query=query,
                        topic_id=topic_id,
                    )

                run_repo.finish(run.id)
                logger.info(
                    "OpenReview ingest finished: %d new papers from query=%s",
                    new_papers_count,
                    query,
                )
                return len(inserted_ids), inserted_ids, new_papers_count
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                logger.error("OpenReview ingest failed: %s", exc)
                raise
            finally:
                client.close()

    def ingest_openreview_with_stats(
        self,
        query: str,
        max_results: int = 20,
        topic_id: str | None = None,
        action_type: ActionType = ActionType.subscription_ingest,
    ) -> dict:
        total_count, inserted_ids, new_count = self.ingest_openreview(
            query=query,
            max_results=max_results,
            topic_id=topic_id,
            action_type=action_type,
        )
        return {
            "total_count": total_count,
            "inserted_ids": inserted_ids,
            "new_count": new_count,
        }

    def skim(self, paper_id: UUID) -> SkimReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("skim", paper_id=paper_id)
            try:
                paper = paper_repo.get_by_id(paper_id)
                prompt = build_skim_prompt(paper.title, paper.abstract)
                decision = CostGuardService(session, self.llm).choose_model(
                    stage="skim",
                    prompt=prompt,
                    default_model=self.settings.llm_model_skim,
                )
                result = self.llm.complete_json(
                    prompt,
                    stage="skim",
                    model_override=decision.chosen_model,
                )
                skim = self._build_skim_structured(
                    paper.abstract,
                    result.content,
                    result.parsed_json,
                    title=paper.title,
                )
                analysis_repo.upsert_skim(paper_id, skim)
                meta = dict(paper.metadata_json or {})
                if skim.keywords:
                    meta["keywords"] = skim.keywords
                if skim.title_zh:
                    meta["title_zh"] = skim.title_zh
                if skim.abstract_zh:
                    meta["abstract_zh"] = skim.abstract_zh
                paper.metadata_json = meta
                paper_repo.update_read_status(paper_id, ReadStatus.skimmed)
                trace_repo.create(
                    stage="skim",
                    provider=self.llm.provider,
                    model=decision.chosen_model,
                    prompt_digest=prompt[:500],
                    paper_id=paper_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return skim
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def deep_dive(self, paper_id: UUID) -> DeepDiveReport:
        started = time.perf_counter()
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            analysis_repo = AnalysisRepository(session)
            trace_repo = PromptTraceRepository(session)
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("deep_dive", paper_id=paper_id)
            try:
                paper = paper_repo.get_by_id(paper_id)
                if not paper.pdf_path:
                    paper_repo.set_pdf_path(
                        paper_id,
                        self.arxiv.download_pdf(paper.arxiv_id),
                    )
                    paper = paper_repo.get_by_id(paper_id)
                extracted = self.vision.extract_page_descriptions(paper.pdf_path)
                extracted_text = self.pdf_extractor.extract_text(paper.pdf_path, max_pages=10)
                combined = f"{extracted}\n\n[TextLayer]\n{extracted_text[:8000]}"
                prompt = build_deep_prompt(paper.title, combined)
                decision = CostGuardService(session, self.llm).choose_model(
                    stage="deep",
                    prompt=prompt,
                    default_model=self.settings.llm_model_deep,
                )
                result = self.llm.complete_json(
                    prompt,
                    stage="deep",
                    model_override=decision.chosen_model,
                )
                deep = self._build_deep_structured(result.content, result.parsed_json)
                analysis_repo.upsert_deep_dive(paper_id, deep)
                paper_repo.update_read_status(paper_id, ReadStatus.deep_read)
                trace_repo.create(
                    stage="deep_dive",
                    provider=self.llm.provider,
                    model=decision.chosen_model,
                    prompt_digest=prompt[:500],
                    paper_id=paper_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    input_cost_usd=result.input_cost_usd,
                    output_cost_usd=result.output_cost_usd,
                    total_cost_usd=result.total_cost_usd,
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
                return deep
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def embed_paper(self, paper_id: UUID) -> None:
        """向量化嵌入（带追踪）"""
        started = time.perf_counter()
        with session_scope() as session:
            run_repo = PipelineRunRepository(session)
            run = run_repo.start("embed_paper", paper_id=paper_id)
            try:
                paper_repo = PaperRepository(session)
                paper = paper_repo.get_by_id(paper_id)
                content = f"{paper.title}\n{paper.abstract}"
                vector = self.llm.embed_text(content)
                paper_repo.update_embedding(paper_id, vector)
                elapsed = int((time.perf_counter() - started) * 1000)
                run_repo.finish(run.id, elapsed_ms=elapsed)
            except Exception as exc:
                run_repo.fail(run.id, str(exc))
                raise

    def _build_skim_structured(
        self,
        abstract: str,
        llm_text: str,
        parsed_json: dict | None = None,
        title: str = "",
    ) -> SkimReport:
        fallback = _fallback_skim(title, abstract)
        if parsed_json:
            innovations = parsed_json.get("innovations") or []
            if not isinstance(innovations, list):
                innovations = [str(innovations)]
            keywords = parsed_json.get("keywords") or []
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            title_zh = _clean_skim_text(parsed_json.get("title_zh", ""), 500)
            abstract_zh = _clean_skim_text(parsed_json.get("abstract_zh", ""), 3000)
            try:
                score = float(parsed_json.get("relevance_score", 0.5))
            except (TypeError, ValueError):
                score = 0.5
            score = min(max(score, 0.0), 1.0)
            one_liner = _clean_skim_text(parsed_json.get("one_liner", ""), 280)

            # 过滤 LLM 返回的字面占位符
            innovations = [
                cleaned
                for x in innovations
                if (cleaned := _clean_skim_text(x, 180))
            ]
            if not innovations:
                innovations = fallback.innovations
            keywords = [
                cleaned
                for k in keywords
                if (cleaned := _clean_skim_text(k, 60)) and cleaned.lower() != "keyword"
            ]
            if not keywords:
                keywords = fallback.keywords
            if not one_liner:
                one_liner = fallback.one_liner

            return SkimReport(
                one_liner=one_liner,
                innovations=innovations[:5],
                keywords=keywords[:8],
                title_zh=title_zh[:500],
                abstract_zh=abstract_zh[:3000],
                relevance_score=score,
            )

        score = min(max(len(abstract or "") / 3000, 0.2), 0.95)
        return _fallback_skim(title, abstract, score=score)

    @staticmethod
    def _build_deep_structured(
        llm_text: str,
        parsed_json: dict | None = None,
    ) -> DeepDiveReport:
        if parsed_json:
            risks = parsed_json.get("reviewer_risks") or []
            if not isinstance(risks, list):
                risks = [str(risks)]
            return DeepDiveReport(
                method_summary=(
                    str(parsed_json.get("method_summary", ""))[:3600] or llm_text[:360]
                ),
                experiments_summary=(
                    str(parsed_json.get("experiments_summary", ""))[:3600]
                    or "原文摘录中未充分呈现实验部分。"
                ),
                ablation_summary=(
                    str(parsed_json.get("ablation_summary", ""))[:3000]
                    or "原文摘录中未充分呈现消融实验。"
                ),
                reviewer_risks=(
                    [str(x)[:500] for x in risks[:8]]
                    or ["原文摘录中未充分呈现局限性与风险点。"]
                ),
            )

        return DeepDiveReport(
            method_summary=(f"精读提取结果：{llm_text[:360]}"),
            experiments_summary=("原文摘录中未充分呈现实验部分，需要回到 PDF 核对主实验、基线和指标。"),
            ablation_summary=("原文摘录中未充分呈现消融实验，需要检查组件贡献和因果证据。"),
            reviewer_risks=[
                "泛化到域外数据或不同任务设置的证据可能不足。",
                "计算资源、实现细节或训练配置可能限制复现。",
            ],
        )


# ==================== 参考文献一键导入引擎 ====================


class ReferenceImporter:
    """将引用详情中的外部论文批量导入到论文库"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.arxiv = ArxivClient()
        self.scholar = SemanticScholarClient(
            api_key=self.settings.semantic_scholar_api_key,
        )
        self.llm = LLMClient()

    @staticmethod
    def _normalize_arxiv_id(aid: str | None) -> str | None:
        if not aid:
            return None
        return aid.split("v")[0] if "v" in aid else aid

    def start_import(
        self,
        *,
        source_paper_id: str,
        source_paper_title: str,
        entries: list[dict],
        topic_ids: list[str] | None = None,
    ) -> str:
        """启动后台导入任务，返回 task_id"""

        def _run_import_with_progress(progress_callback=None):
            return self._run_import(
                source_paper_id=source_paper_id,
                source_paper_title=source_paper_title,
                entries=entries,
                topic_ids=topic_ids or [],
                progress_callback=progress_callback,
            )

        return global_tracker.submit(
            task_type="reference_import",
            title=f"参考文献导入：{source_paper_title[:60]}",
            fn=_run_import_with_progress,
            total=len(entries),
            category="collection",
        )

    def _run_import(
        self,
        *,
        source_paper_id: str,
        source_paper_title: str,
        entries: list[dict],
        topic_ids: list[str],
        progress_callback=None,
    ) -> dict:
        """执行导入任务，返回导入结果统计"""
        inserted_ids: list[str] = []
        skipped_count = 0
        imported_count = 0
        failed_count = 0
        results: list[dict] = []

        try:
            # 1) 建立库内已有 arxiv_id 集合（用于去重）
            with session_scope() as session:
                repo = PaperRepository(session)
                existing_norms: set[str] = set()
                for p in repo.list_all(limit=50000):
                    n = self._normalize_arxiv_id(p.arxiv_id)
                    if n:
                        existing_norms.add(n)

            # 2) 把 entries 分成两组：有 arxiv_id / 无 arxiv_id
            arxiv_entries: list[dict] = []
            ss_only_entries: list[dict] = []
            skip_entries: list[dict] = []

            for entry in entries:
                arxiv_id = entry.get("arxiv_id")
                norm = self._normalize_arxiv_id(arxiv_id)
                if norm and norm in existing_norms:
                    skip_entries.append(entry)
                elif arxiv_id:
                    arxiv_entries.append(entry)
                else:
                    ss_only_entries.append(entry)

            skipped_count = len(skip_entries)
            for e in skip_entries:
                results.append(
                    {
                        "title": e.get("title", ""),
                        "status": "skipped",
                        "reason": "已在库中",
                    }
                )

            # 3) 批量通过 arXiv API 拉取有 arxiv_id 的论文
            if arxiv_entries:
                self._import_arxiv_batch(
                    arxiv_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                    existing_norms,
                    results,
                    progress_callback,
                )

            # 4) 无 arxiv_id 的论文用 SS 元数据导入
            if ss_only_entries:
                self._import_ss_batch(
                    ss_only_entries,
                    source_paper_id,
                    topic_ids,
                    inserted_ids,
                    results,
                    progress_callback,
                )

            imported_count = sum(1 for item in results if item.get("status") == "imported")
            failed_count = sum(1 for item in results if item.get("status") == "failed")

            # 5) 记录 CollectionAction
            if inserted_ids:
                with session_scope() as session:
                    action_repo = ActionRepository(session)
                    action_repo.create_action(
                        action_type=ActionType.reference_import,
                        title=f"参考文献导入：{source_paper_title[:60]}",
                        paper_ids=inserted_ids,
                        query=source_paper_id,
                    )

            # 6) 后台触发粗读 + 向量化
            if inserted_ids:
                threading.Thread(
                    target=self._bg_skim_and_embed,
                    args=(inserted_ids,),
                    daemon=True,
                ).start()

            return {
                "status": "completed",
                "total": len(entries),
                "imported": imported_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "results": results,
            }

        except Exception as exc:
            logger.exception("Reference import failed: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
                "results": results,
            }

    def _import_arxiv_batch(
        self,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
        existing_norms: set[str],
        results: list[dict],
        progress_callback=None,
    ) -> None:
        """批量从 arXiv 拉取完整论文数据"""
        arxiv_ids = [e["arxiv_id"] for e in entries]
        imported_count = len(inserted_ids)

        # arXiv API 一次最多获取 50 个，分批处理
        batch_size = 30
        arxiv_papers_map: dict[str, PaperCreate] = {}
        for i in range(0, len(arxiv_ids), batch_size):
            batch = arxiv_ids[i : i + batch_size]
            try:
                papers = self.arxiv.fetch_by_ids(batch)
                for p in papers:
                    n = self._normalize_arxiv_id(p.arxiv_id)
                    if n:
                        arxiv_papers_map[n] = p
            except Exception as exc:
                logger.warning("arXiv batch fetch failed: %s", exc)
            time.sleep(1)

        for entry in entries:
            title = entry.get("title", "Unknown")
            arxiv_id = entry["arxiv_id"]
            norm = self._normalize_arxiv_id(arxiv_id)

            arxiv_paper = arxiv_papers_map.get(norm) if norm else None

            if arxiv_paper:
                # 用 arXiv 的完整数据 + SS 的额外信息合并
                meta = dict(arxiv_paper.metadata or {})
                meta["source"] = "reference_import"
                meta["source_paper_id"] = source_paper_id
                meta["scholar_id"] = entry.get("scholar_id")
                if entry.get("venue"):
                    meta["venue"] = entry["venue"]
                if entry.get("citation_count") is not None:
                    meta["citation_count"] = entry["citation_count"]
                arxiv_paper.metadata = meta
                paper_data = arxiv_paper
            else:
                # arXiv API 没找到（可能是旧论文），用 SS 数据创建
                paper_data = self._build_paper_from_entry(
                    entry,
                    source_paper_id,
                )

            try:
                with session_scope() as session:
                    repo = PaperRepository(session)
                    saved = repo.upsert_paper(paper_data)
                    for tid in topic_ids:
                        repo.link_to_topic(saved.id, tid)
                    # 下载 PDF
                    try:
                        pdf_path = self.arxiv.download_pdf(
                            paper_data.arxiv_id,
                        )
                        repo.set_pdf_path(saved.id, pdf_path)
                    except Exception:
                        pass
                    inserted_ids.append(saved.id)
                    existing_norms.add(norm or "")
                    imported_count += 1
                    results.append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "arxiv",
                        }
                    )
            except Exception as exc:
                logger.warning("Import failed for %s: %s", title, exc)
                results.append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            # 更新进度
            if progress_callback:
                progress_callback(f"正在导入：{title[:50]}", imported_count, len(entries))

    def _import_ss_batch(
        self,
        entries: list[dict],
        source_paper_id: str,
        topic_ids: list[str],
        inserted_ids: list[str],
        results: list[dict],
        progress_callback=None,
    ) -> None:
        """用 Semantic Scholar 元数据导入没有 arXiv ID 的论文"""
        imported_count = len(inserted_ids)
        for entry in entries:
            title = entry.get("title", "Unknown")
            scholar_id = entry.get("scholar_id")

            # 尝试从 SS 获取更丰富的信息
            detail = None
            if scholar_id:
                try:
                    detail = self.scholar.fetch_paper_by_scholar_id(
                        scholar_id,
                    )
                    time.sleep(0.5)
                except Exception:
                    pass

            if detail and detail.get("arxiv_id"):
                # SS 返回了 arXiv ID，升级为 arXiv 导入
                entry["arxiv_id"] = detail["arxiv_id"]
                paper_data = self._build_paper_from_detail(
                    detail,
                    source_paper_id,
                )
            elif detail:
                paper_data = self._build_paper_from_detail(
                    detail,
                    source_paper_id,
                )
            else:
                paper_data = self._build_paper_from_entry(
                    entry,
                    source_paper_id,
                )

            try:
                with session_scope() as session:
                    repo = PaperRepository(session)
                    saved = repo.upsert_paper(paper_data)
                    for tid in topic_ids:
                        repo.link_to_topic(saved.id, tid)
                    # 有 arxiv_id 的尝试下载 PDF
                    if paper_data.arxiv_id and not paper_data.arxiv_id.startswith("ss-"):
                        try:
                            pdf_path = self.arxiv.download_pdf(
                                paper_data.arxiv_id,
                            )
                            repo.set_pdf_path(saved.id, pdf_path)
                        except Exception:
                            pass
                    inserted_ids.append(saved.id)
                    imported_count += 1
                    results.append(
                        {
                            "title": title,
                            "status": "imported",
                            "paper_id": saved.id,
                            "source": "semantic_scholar",
                        }
                    )
            except Exception as exc:
                logger.warning("SS import failed for %s: %s", title, exc)
                results.append(
                    {
                        "title": title,
                        "status": "failed",
                        "reason": str(exc)[:100],
                    }
                )

            # 更新进度
            if progress_callback:
                progress_callback(f"正在导入：{title[:50]}", imported_count, len(entries))

    @staticmethod
    def _build_paper_from_entry(
        entry: dict,
        source_paper_id: str,
    ) -> PaperCreate:
        """从 citation entry 构建 PaperCreate"""
        arxiv_id = entry.get("arxiv_id")
        scholar_id = entry.get("scholar_id") or str(uuid4())[:12]
        if not arxiv_id:
            arxiv_id = f"ss-{scholar_id}"
        return PaperCreate(
            arxiv_id=arxiv_id,
            title=entry.get("title", "Unknown"),
            abstract=entry.get("abstract") or "",
            publication_date=(date(entry["year"], 1, 1) if entry.get("year") else None),
            metadata={
                "source": "reference_import",
                "source_paper_id": source_paper_id,
                "scholar_id": entry.get("scholar_id"),
                "venue": entry.get("venue"),
                "citation_count": entry.get("citation_count"),
                "import_source": "semantic_scholar",
            },
        )

    @staticmethod
    def _build_paper_from_detail(
        detail: dict,
        source_paper_id: str,
    ) -> PaperCreate:
        """从 SS 完整详情构建 PaperCreate（含作者、领域等）"""
        arxiv_id = detail.get("arxiv_id")
        scholar_id = detail.get("scholar_id") or str(uuid4())[:12]
        if not arxiv_id:
            arxiv_id = f"ss-{scholar_id}"

        pub_date = None
        if detail.get("publication_date"):
            with contextlib.suppress(ValueError, TypeError):
                pub_date = datetime.strptime(
                    detail["publication_date"],
                    "%Y-%m-%d",
                ).date()
        if not pub_date and detail.get("year"):
            pub_date = date(detail["year"], 1, 1)

        return PaperCreate(
            arxiv_id=arxiv_id,
            title=detail.get("title") or "Unknown",
            abstract=detail.get("abstract") or "",
            publication_date=pub_date,
            metadata={
                "source": "reference_import",
                "source_paper_id": source_paper_id,
                "scholar_id": detail.get("scholar_id"),
                "authors": detail.get("authors", []),
                "venue": detail.get("venue"),
                "citation_count": detail.get("citation_count"),
                "fields_of_study": detail.get("fields_of_study", []),
                "import_source": "semantic_scholar",
            },
        )

    def _bg_skim_and_embed(self, paper_ids: list[str]) -> None:
        """后台并行执行粗读 + 向量化"""
        pipeline = PaperPipelines()
        for pid in paper_ids:
            try:
                pipeline.embed_paper(UUID(pid))
            except Exception as exc:
                logger.warning("Embed failed for %s: %s", pid, exc)
            try:
                pipeline.skim(UUID(pid))
            except Exception as exc:
                logger.warning("Skim failed for %s: %s", pid, exc)
