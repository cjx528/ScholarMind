from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VenueInference:
    venue: str | None
    venue_type: str
    confidence: float
    source: str
    raw: str

    def as_metadata(self) -> dict:
        return {
            "venue": self.venue,
            "venue_type": self.venue_type,
            "venue_confidence": self.confidence,
            "venue_source": self.source,
            "venue_raw": self.raw,
        }


CONFERENCE_ALIASES: dict[str, tuple[str, str]] = {
    "CVPR": ("CVPR", "conference"),
    "ICCV": ("ICCV", "conference"),
    "ECCV": ("ECCV", "conference"),
    "WACV": ("WACV", "conference"),
    "BMVC": ("BMVC", "conference"),
    "NeurIPS": ("NeurIPS", "conference"),
    "NIPS": ("NeurIPS", "conference"),
    "ICML": ("ICML", "conference"),
    "ICLR": ("ICLR", "conference"),
    "AISTATS": ("AISTATS", "conference"),
    "COLT": ("COLT", "conference"),
    "ACL": ("ACL", "conference"),
    "EMNLP": ("EMNLP", "conference"),
    "NAACL": ("NAACL", "conference"),
    "COLING": ("COLING", "conference"),
    "AAAI": ("AAAI", "conference"),
    "IJCAI": ("IJCAI", "conference"),
    "KDD": ("KDD", "conference"),
    "WWW": ("WWW", "conference"),
    "SIGIR": ("SIGIR", "conference"),
    "SIGGRAPH": ("SIGGRAPH", "conference"),
    "SIGGRAPH Asia": ("SIGGRAPH Asia", "conference"),
    "ACM MM": ("ACM MM", "conference"),
    "MM": ("ACM MM", "conference"),
    "CHI": ("CHI", "conference"),
    "UIST": ("UIST", "conference"),
    "ICRA": ("ICRA", "conference"),
    "IROS": ("IROS", "conference"),
    "RSS": ("RSS", "conference"),
    "MICCAI": ("MICCAI", "conference"),
    "ICASSP": ("ICASSP", "conference"),
    "INTERSPEECH": ("INTERSPEECH", "conference"),
    "SIGMOD": ("SIGMOD", "conference"),
    "VLDB": ("VLDB", "conference"),
    "ICDE": ("ICDE", "conference"),
    "SOSP": ("SOSP", "conference"),
    "OSDI": ("OSDI", "conference"),
    "NSDI": ("NSDI", "conference"),
    "USENIX": ("USENIX", "conference"),
    "CCS": ("ACM CCS", "conference"),
    "NDSS": ("NDSS", "conference"),
    "ICSE": ("ICSE", "conference"),
    "FSE": ("FSE", "conference"),
    "ASE": ("ASE", "conference"),
    "PLDI": ("PLDI", "conference"),
    "POPL": ("POPL", "conference"),
    "OOPSLA": ("OOPSLA", "conference"),
}


JOURNAL_HINTS = (
    "journal",
    "transactions",
    "letters",
    "magazine",
    "nature",
    "science",
    "proceedings of the national academy",
    "pnas",
    "pattern recognition",
    "medical image analysis",
)


def _clean_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _with_year(name: str, raw: str) -> str:
    year = re.search(r"\b(20\d{2}|19\d{2})\b", raw)
    return f"{name} {year.group(1)}" if year else name


def _extract_journal_name(journal_ref: str) -> str:
    text = _clean_space(journal_ref)
    text = re.sub(r"\b(arXiv|preprint)\b.*$", "", text, flags=re.I).strip(" ,.;")
    parts = re.split(r",|\s+\d+\s*(?:\(|:|,)|\bvol\.|\bvolume\b", text, maxsplit=1, flags=re.I)
    return parts[0].strip(" .;,:") or text


def infer_venue(
    *,
    journal_ref: str | None = None,
    comment: str | None = None,
    doi: str | None = None,
    categories: list[str] | None = None,
) -> VenueInference:
    journal_ref = _clean_space(journal_ref)
    comment = _clean_space(comment)
    raw = " | ".join(x for x in [journal_ref, comment, _clean_space(doi)] if x)

    searchable = f"{journal_ref} {comment}"
    for alias in sorted(CONFERENCE_ALIASES, key=len, reverse=True):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?:\s*(?:20\d{{2}}|19\d{{2}}))?(?![A-Za-z0-9])"
        if re.search(pattern, searchable, flags=re.I):
            name, venue_type = CONFERENCE_ALIASES[alias]
            return VenueInference(
                venue=_with_year(name, searchable),
                venue_type=venue_type,
                confidence=0.86 if comment else 0.9,
                source="arxiv_comment" if comment else "arxiv_journal_ref",
                raw=raw,
            )

    if journal_ref:
        venue = _extract_journal_name(journal_ref)
        venue_type = "journal" if any(h in journal_ref.lower() for h in JOURNAL_HINTS) else "publication"
        return VenueInference(
            venue=venue,
            venue_type=venue_type,
            confidence=0.82,
            source="arxiv_journal_ref",
            raw=raw,
        )

    if doi:
        return VenueInference(
            venue=None,
            venue_type="published_unknown",
            confidence=0.45,
            source="doi_present",
            raw=raw,
        )

    category = (categories or [None])[0]
    return VenueInference(
        venue="arXiv preprint",
        venue_type="preprint",
        confidence=0.3,
        source="arxiv_category" if category else "arxiv",
        raw=category or "",
    )
