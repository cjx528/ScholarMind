import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from apps.api.routers.papers import ask_paper
from packages.domain.schemas import PaperAskRequest


class PaperAskEndpointTest(unittest.TestCase):
    def test_ask_paper_uses_selected_text_reports_reasoning_and_page_context(self):
        captured: dict[str, str] = {}
        paper_id = UUID("11111111-1111-1111-1111-111111111111")

        fake_paper = SimpleNamespace(
            id=str(paper_id),
            title="Demo Paper",
            abstract="Original abstract",
            pdf_path="demo.pdf",
            metadata_json={
                "title_zh": "演示论文",
                "abstract_zh": "中文摘要",
                "reasoning_chain": {"method_chain": {"core_hypothesis": "reasoning context"}},
            },
        )
        fake_report = SimpleNamespace(
            summary_md="粗读报告内容",
            deep_dive_md="精读报告内容",
        )

        class FakePaperRepository:
            def __init__(self, _session):
                pass

            def get_by_id(self, _paper_id):
                return fake_paper

        class FakeExecuteResult:
            def scalar_one_or_none(self):
                return fake_report

        class FakeSession:
            def execute(self, *_args, **_kwargs):
                return FakeExecuteResult()

        class FakeScope:
            def __enter__(self):
                return FakeSession()

            def __exit__(self, *_args):
                return False

        class FakeLLM:
            def complete_json(self, prompt, **_kwargs):
                captured["prompt"] = prompt
                return SimpleNamespace(
                    content="",
                    parsed_json={
                        "answer": "中文回答",
                        "used_context": [
                            "selected_text",
                            "paper_meta",
                            "skim",
                            "deep",
                            "reasoning",
                            "pdf_page",
                        ],
                        "confidence": 0.72,
                    },
                    input_tokens=None,
                    output_tokens=None,
                    input_cost_usd=None,
                    output_cost_usd=None,
                    total_cost_usd=None,
                    reasoning_content=None,
                )

            def trace_result(self, *_args, **_kwargs):
                return None

        with (
            patch("apps.api.routers.papers.session_scope", return_value=FakeScope()),
            patch("apps.api.routers.papers.PaperRepository", FakePaperRepository),
            patch("apps.api.routers.papers._extract_pdf_page_context", return_value="第 1 页: PDF 原文"),
            patch("packages.integrations.llm_client.LLMClient", FakeLLM),
        ):
            response = ask_paper(
                paper_id,
                PaperAskRequest(
                    question="这段为什么重要？",
                    selected_text="selected context",
                    source="pdf_reader",
                    analysis_scope=["skim", "deep", "reasoning"],
                    page_number=1,
                ),
            )

        prompt = captured["prompt"]
        self.assertEqual(response.answer, "中文回答")
        self.assertEqual(response.confidence, 0.72)
        self.assertIn("selected context", prompt)
        self.assertIn("粗读报告内容", prompt)
        self.assertIn("精读报告内容", prompt)
        self.assertIn("reasoning context", prompt)
        self.assertIn("PDF 原文", prompt)
        self.assertIn("selected_text", response.used_context)
        self.assertIn("pdf_page", response.used_context)


if __name__ == "__main__":
    unittest.main()
