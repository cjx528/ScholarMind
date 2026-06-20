import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from packages.domain.schemas import PaperCreate
from packages.ai.backend_config import normalize_ai_backend_config
from packages.ai.compass_service import (
    CompassService,
    _analysis_blocks,
    _extract_arxiv_id,
    _profile_signal_bundle,
    normalize_recommendation,
    normalize_weights,
    score_with_model,
)


class CompassServiceTest(unittest.TestCase):
    def test_global_ai_backend_config_normalization(self):
        self.assertEqual(normalize_ai_backend_config({"backend": "codex"})["backend"], "codex")
        self.assertEqual(normalize_ai_backend_config({"backend": "bad"})["backend"], "llm")
        self.assertEqual(
            normalize_ai_backend_config({"backend": "codex", "codexTimeoutMs": 1})[
                "codexTimeoutMs"
            ],
            30000,
        )

    def test_extract_arxiv_id_from_link_or_plain_id(self):
        self.assertEqual(
            _extract_arxiv_id("https://arxiv.org/abs/2512.18746v1"),
            "2512.18746v1",
        )
        self.assertEqual(_extract_arxiv_id("arXiv:2512.18746"), "2512.18746")
        self.assertEqual(_extract_arxiv_id("2512.18746v2"), "2512.18746v2")

    def test_material_context_fetches_arxiv_metadata(self):
        paper = PaperCreate(
            arxiv_id="2512.18746v1",
            title="Demo Paper",
            abstract="Useful abstract",
            publication_date=date(2025, 12, 25),
            metadata={"authors": ["Ada Lovelace"], "categories": ["cs.CV"]},
        )
        service = CompassService()

        with patch("packages.ai.compass_service.ArxivClient") as client_cls:
            client_cls.return_value.fetch_by_ids.return_value = [paper]
            text, trace = service._material_context("https://arxiv.org/abs/2512.18746v1", None)

        client_cls.return_value.fetch_by_ids.assert_called_once_with(["2512.18746v1"])
        self.assertIn("Title: Demo Paper", text)
        self.assertIn("Authors: Ada Lovelace", text)
        self.assertIn("Abstract: Useful abstract", text)
        self.assertIn("arXiv metadata fetched: 2512.18746v1", trace)

    def test_normalize_recommendation_clamps_factors(self):
        rec = normalize_recommendation(
            {
                "score": 1,
                "reason": "",
                "factors": {
                    "profileFit": 120,
                    "novelty": -10,
                    "paperImportance": 0.8,
                },
            }
        )

        self.assertEqual(rec["score"], 100)
        self.assertEqual(rec["factors"]["profileFit"], 100)
        self.assertEqual(rec["factors"]["novelty"], 0)
        self.assertEqual(rec["factors"]["paperImportance"], 80)
        self.assertIn("推荐分", rec["reason"])

    def test_score_with_model_uses_learned_weights(self):
        rec = normalize_recommendation(
            {
                "score": 50,
                "reason": "ok",
                "factors": {
                    "profileFit": 100,
                    "novelty": 10,
                    "paperImportance": 10,
                    "sourceSignal": 10,
                    "actionability": 10,
                    "freshness": 10,
                },
            }
        )
        score = score_with_model(
            rec,
            {
                "weights": normalize_weights({"profileFit": 0.7}),
                "bias": 0,
            },
        )

        self.assertGreater(score, 50)

    def test_codex_request_selects_codex_backend(self):
        service = CompassService()
        self.assertEqual(service._select_backend("codex", {"backend": "llm"}), "codex")
        self.assertEqual(service._select_backend(None, {"backend": "codex"}), "codex")
        self.assertEqual(service._select_backend("auto", {"backend": "codex"}), "codex")

    def test_run_codex_json_invokes_cli_and_parses_output_file(self):
        service = CompassService()

        def fake_run(cmd, **_kwargs):
            output_path = cmd[cmd.index("--output-last-message") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write('{"profile":{"interests":"agent"},"confidence":80}')
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch("packages.ai.compass_service.shutil.which", return_value="codex"),
            patch("packages.ai.compass_service.subprocess.run", side_effect=fake_run) as run_mock,
        ):
            result = service._run_codex_json("prompt", "compass_profile", {})

        self.assertEqual(result["profile"]["interests"], "agent")
        cmd = run_mock.call_args.args[0]
        self.assertIn("exec", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("read-only", cmd)
        self.assertIn("--output-last-message", cmd)

    def test_analysis_blocks_are_padded_for_short_llm_output(self):
        blocks = _analysis_blocks(
            {"analysisBlocks": [{"type": "text", "heading": "核心理解", "body": "short"}]},
            {"title": "Demo", "plainSummary": "summary"},
            "Title: Demo\nAuthors: Ada\nCategories: cs.AI\nAbstract: detailed abstract",
            {"reason": "值得读", "factors": {"profileFit": 80}},
        )

        self.assertGreaterEqual(len(blocks), 6)
        self.assertIn("研究问题与背景", {block["heading"] for block in blocks})

    def test_quick_profile_changes_library_recommendation_score(self):
        service = CompassService()
        profile = {
            "interests": "",
            "researchDirections": "",
            "readingGoal": "",
            "notes": ["优先推荐有 GitHub 代码、可复现的 agent 论文"],
            "quickProfile": {
                "currentInterests": ["Agent"],
                "downrankAreas": ["benchmark"],
                "paperTypes": ["开源系统"],
                "readingGoals": ["找可复现代码"],
                "modalityFocus": [],
                "riskLevel": "stable",
            },
        }
        signals = _profile_signal_bundle(profile)
        preferred = SimpleNamespace(
            title="Agent memory system with GitHub code",
            abstract="A reproducible agent framework with open source code.",
            metadata_json={"keywords": ["agent", "github"], "categories": ["cs.AI"], "code_url": "https://github.com/demo"},
            publication_date=date.today(),
        )
        downranked = SimpleNamespace(
            title="Benchmark report",
            abstract="A benchmark only paper without code.",
            metadata_json={"keywords": ["benchmark"], "categories": ["cs.AI"]},
            publication_date=date.today(),
        )

        preferred_score = service._score_paper_for_profile(preferred, signals).recommendation
        downranked_score = service._score_paper_for_profile(downranked, signals).recommendation

        self.assertGreater(preferred_score["factors"]["profileFit"], downranked_score["factors"]["profileFit"])
        self.assertGreater(preferred_score["factors"]["actionability"], downranked_score["factors"]["actionability"])

    def test_recommend_arxiv_candidates_uses_profile_queries_and_scores(self):
        service = CompassService()
        profile = {
            "interests": "",
            "researchDirections": "multimodal large language model agents",
            "readingGoal": "find reproducible papers",
            "notes": [],
            "quickProfile": {
                "currentInterests": ["MLLM", "Agent"],
                "downrankAreas": [],
                "paperTypes": ["open source system"],
                "readingGoals": ["find reproducible code"],
                "modalityFocus": [],
                "riskLevel": "frontier",
            },
        }
        papers = [
            PaperCreate(
                arxiv_id="2601.00001",
                title="Multimodal Agent Systems with Code",
                abstract="A multimodal large language model agent framework with released code.",
                publication_date=date.today(),
                metadata={"authors": ["Ada"], "categories": ["cs.AI"], "code_url": "https://github.com/demo"},
            ),
            PaperCreate(
                arxiv_id="2601.00002",
                title="General Benchmark Notes",
                abstract="A benchmark note.",
                publication_date=date.today(),
                metadata={"authors": ["Grace"], "categories": ["cs.LG"]},
            ),
        ]

        class FakeSession:
            def execute(self, *_args, **_kwargs):
                return SimpleNamespace(scalars=lambda: [])

        class FakeScope:
            def __enter__(self):
                return FakeSession()

            def __exit__(self, *_args):
                return False

        with (
            patch.object(service, "get_profile", return_value=profile),
            patch.object(
                service,
                "get_model",
                return_value={"weights": normalize_weights({"profileFit": 0.5}), "bias": 0},
            ),
            patch("packages.ai.compass_service.session_scope", return_value=FakeScope()),
            patch("packages.ai.compass_service.ArxivClient") as client_cls,
        ):
            client_cls.return_value.fetch_latest.return_value = papers
            result = service.recommend_arxiv_candidates(top_k=2)

        self.assertEqual(result["source"], "arxiv")
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["status"], "arxiv_candidate")
        self.assertEqual(result["items"][0]["arxiv_id"], "2601.00001")
        self.assertGreaterEqual(result["items"][0]["final_score"], result["items"][1]["final_score"])
        self.assertIn("multimodal large language model", result["queries"])
        client_cls.return_value.fetch_latest.assert_called()


if __name__ == "__main__":
    unittest.main()
