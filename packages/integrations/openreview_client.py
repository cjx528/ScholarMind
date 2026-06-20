from __future__ import annotations

import logging
import re
import time
from contextlib import suppress
from datetime import date, datetime, timezone
from typing import Any

import httpx

from packages.domain.schemas import PaperCreate

logger = logging.getLogger(__name__)

_BASE_URL = "https://api2.openreview.net"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _content_value(content: dict[str, Any], key: str) -> Any:
    raw = content.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_norm(item) for item in value if _norm(item)]
    text = _norm(value)
    if not text:
        return []
    return [_norm(item) for item in re.split(r"[;,]+", text) if _norm(item)]


def _timestamp_to_date(value: Any) -> date | None:
    with suppress(Exception):
        ts = int(value)
        if ts <= 0:
            return None
        if ts > 10_000_000_000:
            ts = ts // 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date()
    return None


def _note_attr(note: dict[str, Any], key: str, default: Any = None) -> Any:
    return note.get(key, default)


def _extract_replies(note: dict[str, Any]) -> list[dict[str, Any]]:
    details = _note_attr(note, "details", {}) or {}
    replies = details.get("replies")
    return [item for item in replies if isinstance(item, dict)] if isinstance(replies, list) else []


def _reply_invitation(reply: dict[str, Any]) -> str:
    invitations = reply.get("invitations") or []
    if isinstance(invitations, list) and invitations:
        return _norm(invitations[0])
    return _norm(reply.get("invitation"))


def _extract_decision_text(note: dict[str, Any]) -> str:
    for reply in _extract_replies(note):
        invitation = _reply_invitation(reply).lower()
        if not invitation.endswith("/-/decision"):
            continue
        content = reply.get("content") or {}
        if not isinstance(content, dict):
            continue
        decision = _content_value(content, "decision")
        recommendation = _content_value(content, "recommendation")
        text = _norm(decision) or _norm(recommendation)
        if text:
            return text
    return ""


def _has_public_reader(note: dict[str, Any]) -> bool:
    readers = _note_attr(note, "readers", []) or []
    if not isinstance(readers, list):
        return False
    lowered = {str(item).strip().lower() for item in readers}
    return "everyone" in lowered or "openreview.net/everyone" in lowered


def classify_submission_status(note: dict[str, Any]) -> str:
    decision_text = _extract_decision_text(note).lower()
    if decision_text:
        if "accept" in decision_text and "reject" not in decision_text:
            return "Accepted"
        if "withdraw" in decision_text:
            return "Withdrawn-Public" if _has_public_reader(note) else "Withdrawn"
        if "reject" in decision_text:
            return "Rejected-Public" if _has_public_reader(note) else "Rejected"
    return "Public" if _has_public_reader(note) else "Submission"


def build_venue_id(conference: str, year: int) -> str:
    mapping = {
        "neurips": "NeurIPS.cc",
        "nips": "NeurIPS.cc",
        "iclr": "ICLR.cc",
        "icml": "ICML.cc",
        "aaai": "AAAI.org",
    }
    prefix = mapping.get(_norm(conference).lower(), _norm(conference))
    return f"{prefix}/{int(year)}/Conference"


def _infer_venue_id(note: dict[str, Any]) -> str:
    invitation = _norm(note.get("invitation"))
    invitations = note.get("invitations") or []
    if not invitation and isinstance(invitations, list) and invitations:
        invitation = _norm(invitations[0])
    if "/-/Submission" in invitation:
        return invitation.split("/-/Submission", 1)[0]
    if "/-/Blind_Submission" in invitation:
        return invitation.split("/-/Blind_Submission", 1)[0]
    return invitation


def _matches_query(paper: PaperCreate, query: str) -> bool:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9+\-_.]{1,}", query)]
    if not terms:
        return True
    haystack = f"{paper.title} {paper.abstract} {' '.join(paper.metadata.get('keywords', []))}".lower()
    return any(term in haystack for term in terms)


class OpenReviewClient:
    """Small REST client for public OpenReview paper search."""

    def __init__(self, base_url: str = _BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": "ScholarMind/1.0"},
            )
        return self._client

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code == 429:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning("OpenReview 429, retry %d/%d in %.1fs", attempt + 1, _MAX_RETRIES, delay)
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else None
            except httpx.TimeoutException:
                logger.warning("OpenReview timeout for %s, retry %d", path, attempt + 1)
                time.sleep(_RETRY_DELAY)
            except Exception as exc:
                logger.warning("OpenReview error for %s: %s", path, exc)
                return None
        logger.error("OpenReview exhausted retries for %s", path)
        return None

    def search_papers(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        params = {"term": query, "limit": min(max(max_results * 2, max_results), 100)}
        data = self._get("/notes/search", params=params)
        notes = data.get("notes", []) if data else []
        papers = self._parse_notes(notes, max_results=max_results)
        if papers:
            return papers[:max_results]

        # The global search endpoint can be sparse for new conferences, so fall back
        # to recent public AI conference submissions and filter locally.
        current_year = datetime.now(timezone.utc).year
        fallback: list[PaperCreate] = []
        for conference in ("ICLR", "NeurIPS", "ICML"):
            for year in (current_year, current_year - 1):
                fallback.extend(
                    paper
                    for paper in self.fetch_conference_papers(
                        conference=conference,
                        year=year,
                        max_results=max_results,
                        query=query,
                    )
                    if _matches_query(paper, query)
                )
                if len(fallback) >= max_results:
                    return fallback[:max_results]
        return fallback[:max_results]

    def fetch_conference_papers(
        self,
        conference: str,
        year: int,
        max_results: int = 50,
        query: str | None = None,
    ) -> list[PaperCreate]:
        venue_id = build_venue_id(conference, year)
        submission_id = self._submission_invitation_for_venue(venue_id)
        limit = min(max(max_results * 2, max_results), 1000)
        data = self._get(
            "/notes",
            params={
                "invitation": submission_id,
                "details": "replies",
                "sort": "tmdate:desc",
                "limit": limit,
            },
        )
        notes = data.get("notes", []) if data else []
        papers = self._parse_notes(notes, max_results=limit, fallback_venue_id=venue_id)
        if query:
            papers = [paper for paper in papers if _matches_query(paper, query)]
        return papers[:max_results]

    def _submission_invitation_for_venue(self, venue_id: str) -> str:
        data = self._get("/groups", params={"id": venue_id})
        groups = data.get("groups", []) if data else []
        if groups:
            content = groups[0].get("content") or {}
            raw = content.get("submission_id") if isinstance(content, dict) else None
            if isinstance(raw, dict) and _norm(raw.get("value")):
                return _norm(raw.get("value"))
            if _norm(raw):
                return _norm(raw)
        return f"{venue_id}/-/Submission"

    def _parse_notes(
        self,
        notes: Any,
        max_results: int,
        fallback_venue_id: str | None = None,
    ) -> list[PaperCreate]:
        if not isinstance(notes, list):
            return []
        papers: list[PaperCreate] = []
        seen: set[str] = set()
        for note in notes:
            if not isinstance(note, dict):
                continue
            paper = self._parse_note(note, fallback_venue_id=fallback_venue_id)
            if not paper or not paper.source_id or paper.source_id in seen:
                continue
            seen.add(paper.source_id)
            papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _parse_note(self, note: dict[str, Any], fallback_venue_id: str | None = None) -> PaperCreate | None:
        note_id = _norm(note.get("id"))
        forum = _norm(note.get("forum")) or note_id
        content = note.get("content") or {}
        if not isinstance(content, dict):
            return None

        title = _norm(_content_value(content, "title"))
        abstract = _norm(_content_value(content, "abstract"))
        if not title or not forum:
            return None

        authors = _normalize_list(_content_value(content, "authors"))
        keywords = _normalize_list(_content_value(content, "keywords"))
        venue_id = fallback_venue_id or _infer_venue_id(note)
        status = classify_submission_status(note)
        decision = _extract_decision_text(note)

        pdf_field = _norm(_content_value(content, "pdf"))
        if pdf_field.startswith(("http://", "https://")):
            pdf_url = pdf_field
        elif pdf_field:
            pdf_url = f"https://openreview.net{pdf_field}"
        else:
            pdf_url = f"https://openreview.net/pdf?id={forum}" if _has_public_reader(note) else None

        pub_date = (
            _timestamp_to_date(note.get("pdate"))
            or _timestamp_to_date(note.get("cdate"))
            or _timestamp_to_date(note.get("tcdate"))
        )

        metadata = {
            "source": "openreview",
            "source_id": forum,
            "openreview_id": note_id,
            "forum": forum,
            "authors": authors,
            "keywords": keywords,
            "venue": venue_id,
            "venue_id": venue_id,
            "status": status,
            "decision": decision,
            "openreview_url": f"https://openreview.net/forum?id={forum}",
            "pdf_url": pdf_url,
            "readers": note.get("readers") or [],
        }

        return PaperCreate(
            source="openreview",
            source_id=forum,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            metadata=metadata,
        )

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()
