from __future__ import annotations

from packages.domain.schemas import PaperCreate
from packages.integrations.channel_base import ChannelBase
from packages.integrations.openreview_client import OpenReviewClient


class OpenReviewChannel(ChannelBase):
    """OpenReview channel adapter."""

    def __init__(self) -> None:
        self._client = OpenReviewClient()

    @property
    def name(self) -> str:
        return "openreview"

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        return self._client.search_papers(query, max_results=max_results)

    def download_pdf(self, paper_id: str) -> str | None:
        return None

    def supports_incremental(self) -> bool:
        return True
