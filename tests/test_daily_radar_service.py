import unittest

from packages.ai.daily_radar_service import BM25Index, _partition_items, _rrf_fuse


def _item(paper_id: str, score: int, zone: str = ""):
    return {
        "paper": {
            "id": paper_id,
            "title": f"Paper {paper_id}",
            "abstract": "A useful multimodal reasoning paper.",
            "arxiv_id": paper_id,
            "source": "arxiv",
            "publication_date_text": "2026-06-01",
            "read_status": "unread",
            "favorited": False,
        },
        "final_score": score,
        "zone": zone,
        "tldr": "one line",
        "reason": "matched topic",
        "matched_topics": [],
        "bm25_score": 70,
        "embedding_score": 60,
        "rrf_score": 80,
        "profile_score": 75,
        "freshness_score": 90,
    }


class DailyRadarServiceTest(unittest.TestCase):
    def test_bm25_scores_relevant_document_higher(self):
        index = BM25Index(
            [
                "multimodal reasoning with image editing and visual transformation",
                "database indexing and transaction scheduling",
            ]
        )

        scores = index.scores("multimodal visual reasoning")

        self.assertGreater(scores[0], scores[1])

    def test_rrf_fusion_rewards_repeated_high_rank(self):
        fused = _rrf_fuse([["a", "b", "c"], ["b", "a", "d"], ["a", "d"]], k=60)

        self.assertGreater(fused["a"], fused["c"])
        self.assertGreater(fused["b"], fused["d"])

    def test_partition_keeps_deep_quick_and_skip_sections(self):
        sections = _partition_items(
            [
                _item("deep", 92, "deep"),
                _item("quick", 68, "quick"),
                _item("skip", 35, "skip"),
            ],
            limit=2,
        )

        self.assertEqual(sections["deep"][0]["paper"]["id"], "deep")
        self.assertEqual(sections["quick"][0]["paper"]["id"], "quick")
        self.assertEqual(sections["skip"][0]["paper"]["id"], "skip")
        self.assertIn("score", sections["deep"][0])


if __name__ == "__main__":
    unittest.main()
