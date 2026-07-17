#!/usr/bin/env python3
"""Title normalization and similarity helpers for cross-index matching.

Adapted from Academic Research Skills (ARS) v3.17.0 `scripts/_text_similarity.py`
(c) 2026 Cheng-I Wu, CC BY-NC 4.0 — see NOTICE.md. The 0.70 threshold, the
dotted-acronym pre-pass, the exact-normalized-title gate, and the closed
generic-title set are carried over; identifier normalizers are new.
"""
from __future__ import annotations

import re
import string
from difflib import SequenceMatcher

_PUNCT_TRANSLATION = str.maketrans({c: " " for c in string.punctuation})

# Collapse a run of two-or-more `<letter>.` units at a word boundary
# (`R.A.G.` -> `RAG`) BEFORE punctuation->whitespace, so a dotted acronym and
# its undotted spelling normalize byte-equal. `/`, `&`, and spaced initials
# (`D. H.`) are not dotted runs and stay untouched.
_DOTTED_ACRONYM = re.compile(r"\b(?:[A-Za-z]\.){2,}")

TITLE_SIMILARITY_THRESHOLD = 0.70


def normalize_title(s: str) -> str:
    """Case-insensitive, punctuation stripped to whitespace (token boundaries
    preserved), whitespace runs collapsed."""
    cleaned = s.lower().translate(_PUNCT_TRANSLATION)
    return " ".join(cleaned.split())


def _normalize_title_acronym(s: str) -> str:
    collapsed = _DOTTED_ACRONYM.sub(lambda m: m.group(0).replace(".", ""), s)
    return normalize_title(collapsed)


def similarity(a: str, b: str) -> float:
    """Max over the base and dotted-acronym normalizations — the acronym
    pre-pass can only ever raise the score."""
    a_base, b_base = normalize_title(a), normalize_title(b)
    base = SequenceMatcher(None, a_base, b_base).ratio()
    a_acr, b_acr = _normalize_title_acronym(a), _normalize_title_acronym(b)
    if a_acr == a_base and b_acr == b_base:
        return base
    return max(base, SequenceMatcher(None, a_acr, b_acr).ratio())


def exact_normalized_title(a: str, b: str) -> bool:
    """True iff the titles are byte-equal under EITHER normalization. Both are
    checked so the acronym pass only ever adds matches (`D.H. Lawrence` vs
    `D. H. Lawrence` matches under the base form only)."""
    return (
        normalize_title(a) == normalize_title(b)
        or _normalize_title_acronym(a) == _normalize_title_acronym(b)
    )


# Closed generic/section/type/notice set. Membership is EXACT equality on the
# normalized title, never substring: `Case Report of a Rare Tumor` is content,
# bare `Case Report` is generic. A generic exact-title match without a
# corroborating ID must stay `unresolvable` (it collides across thousands of
# distinct works).
_GENERIC_TITLES = frozenset(
    normalize_title(t)
    for t in (
        "editorial", "guest editorial", "editorial comment", "introduction",
        "preface", "foreword", "letter", "letters", "letter to the editor",
        "letters to the editor", "reply", "comment", "commentary", "response",
        "correspondence", "book review", "book reviews", "review", "news",
        "obituary", "in memoriam", "acknowledgements", "front matter",
        "back matter", "table of contents", "abstracts", "abstract",
        "proceedings", "keynote", "panel discussion", "workshop summary",
        "special issue", "untitled", "note", "notes", "highlights", "errata",
        "erratum", "corrigendum", "addendum", "author correction",
        "publisher correction", "retraction", "expression of concern",
        "short communication", "rapid communication", "brief communication",
        "short report", "brief report", "technical report", "meeting report",
        "conference report", "case report", "case study", "research article",
        "original article", "original research", "short paper", "perspective",
        "perspectives", "viewpoint", "opinion", "discussion", "summary",
        "conclusion", "conclusions", "abstract only", "supplementary material",
    )
)

# Titles carrying a notice-relation prefix must never match the base work:
# `Retraction: X` is a different document from `X`.
_NOTICE_PREFIX = re.compile(
    r"^\s*(retraction|retracted|erratum|corrigendum|correction|"
    r"author correction|publisher correction|expression of concern|"
    r"withdrawal|withdrawn)\s*(:|\bof\b|\bto\b)",
    re.IGNORECASE,
)


def generic_title(title: str) -> bool:
    return normalize_title(title) in _GENERIC_TITLES


def notice_title(title: str) -> bool:
    """True for correction/erratum/retraction-notice titles (notice-relation
    veto: these never count as a match for the underlying work)."""
    return bool(_NOTICE_PREFIX.match(title or ""))


# --- identifier normalizers (new in intensive-research) ---

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", re.IGNORECASE)
_ARXIV_PREFIX = re.compile(
    r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)\s*", re.IGNORECASE
)
_ARXIV_VERSION = re.compile(r"v\d+$")


def normalize_doi(doi: str | None) -> str | None:
    """Lowercase, strip resolver prefixes and surrounding whitespace."""
    if not doi:
        return None
    d = _DOI_PREFIX.sub("", doi.strip()).strip().rstrip(".")
    return d.lower() or None


def normalize_arxiv(arxiv_id: str | None) -> str | None:
    """Strip URL/scheme prefixes, trailing `.pdf`, and the version suffix."""
    if not arxiv_id:
        return None
    a = _ARXIV_PREFIX.sub("", arxiv_id.strip()).strip()
    if a.endswith(".pdf"):
        a = a[: -len(".pdf")]
    a = _ARXIV_VERSION.sub("", a)
    return a or None


def title_year_key(title: str, year: int | None) -> str:
    """Fuzzy dedup fallback key: exact normalized title + year bucket. Callers
    must treat year +/-1 as the same bucket (compare via `title_years_match`)."""
    return f"{normalize_title(title)}"


def title_years_match(year_a: int | None, year_b: int | None) -> bool:
    if year_a is None or year_b is None:
        return True
    return abs(year_a - year_b) <= 1
