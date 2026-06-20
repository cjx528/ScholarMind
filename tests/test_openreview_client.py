import unittest
from unittest.mock import patch

from packages.integrations.openreview_channel import OpenReviewChannel
from packages.integrations.openreview_client import OpenReviewClient, build_venue_id
from packages.integrations.registry import ChannelRegistry


OPENREVIEW_NOTE = {
    "id": "note123",
    "forum": "forum123",
    "invitation": "ICLR.cc/2025/Conference/-/Submission",
    "readers": ["everyone"],
    "cdate": 1735689600000,
    "content": {
        "title": {"value": "LLM Agents for Scientific Discovery"},
        "abstract": {"value": "We study language model agents for scientific discovery."},
        "authors": {"value": ["Ada Lovelace", "Alan Turing"]},
        "keywords": {"value": ["LLM", "Agent", "AI4Science"]},
        "pdf": {"value": "/pdf?id=forum123"},
    },
    "details": {
        "replies": [
            {
                "invitations": ["ICLR.cc/2025/Conference/-/Decision"],
                "content": {"decision": {"value": "Accept (poster)"}},
            }
        ]
    },
}


class OpenReviewClientTest(unittest.TestCase):
    def test_build_venue_id_maps_common_ai_conferences(self):
        self.assertEqual(build_venue_id("ICLR", 2025), "ICLR.cc/2025/Conference")
        self.assertEqual(build_venue_id("neurips", 2025), "NeurIPS.cc/2025/Conference")
        self.assertEqual(build_venue_id("AAAI", 2025), "AAAI.org/2025/Conference")

    def test_parse_openreview_note_to_paper_create(self):
        paper = OpenReviewClient()._parse_note(OPENREVIEW_NOTE)

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.source, "openreview")
        self.assertEqual(paper.source_id, "forum123")
        self.assertEqual(paper.normalized_arxiv_id, "openreview:forum123")
        self.assertEqual(paper.title, "LLM Agents for Scientific Discovery")
        self.assertEqual(paper.metadata["venue"], "ICLR.cc/2025/Conference")
        self.assertEqual(paper.metadata["decision"], "Accept (poster)")
        self.assertEqual(paper.metadata["pdf_url"], "https://openreview.net/pdf?id=forum123")

    def test_search_papers_uses_notes_search_endpoint(self):
        client = OpenReviewClient()
        with patch.object(client, "_get", return_value={"notes": [OPENREVIEW_NOTE]}) as get:
            papers = client.search_papers("llm agents", max_results=5)

        get.assert_called_once()
        path, kwargs = get.call_args.args[0], get.call_args.kwargs
        self.assertEqual(path, "/notes/search")
        self.assertEqual(kwargs["params"]["term"], "llm agents")
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source, "openreview")

    def test_fetch_conference_papers_reads_group_submission_id(self):
        client = OpenReviewClient()

        def fake_get(path, params=None):
            if path == "/groups":
                return {
                    "groups": [
                        {
                            "content": {
                                "submission_id": {
                                    "value": "ICLR.cc/2025/Conference/-/Submission"
                                }
                            }
                        }
                    ]
                }
            if path == "/notes":
                return {"notes": [OPENREVIEW_NOTE]}
            return None

        with patch.object(client, "_get", side_effect=fake_get):
            papers = client.fetch_conference_papers("ICLR", 2025, max_results=5, query="scientific")

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source_id, "forum123")


class OpenReviewChannelTest(unittest.TestCase):
    def test_channel_fetch_delegates_to_client(self):
        channel = OpenReviewChannel()
        with patch.object(channel._client, "search_papers", return_value=[]) as search:
            self.assertEqual(channel.fetch("agent", max_results=3), [])
        search.assert_called_once_with("agent", max_results=3)

    def test_default_registry_contains_openreview(self):
        ChannelRegistry.register_default_channels()

        self.assertIn("openreview", ChannelRegistry.list_channels())
        self.assertEqual(ChannelRegistry.get("openreview").name, "openreview")


if __name__ == "__main__":
    unittest.main()
