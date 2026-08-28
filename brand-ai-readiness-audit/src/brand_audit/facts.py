"""Shared fact extraction: pulls currency/numeric/date/contact facts out
of plain text via regex, deliberately not a real NER model (see
render-gap-audit/scripts/render_detect.py's module docstring for why).

Used by stage (2) render-gap-audit (raw-vs-rendered fact diff) and stage
(3) extractability-audit (schema-vs-visible-text contradiction) -- both
need the same "what facts does this text actually contain" primitive, so
it lives here once rather than being duplicated per stage.
"""

from __future__ import annotations

import re
from datetime import date

_CURRENCY_RE = re.compile(r"[$€£₹]\s?\d[\d,]*(?:\.\d+)?")
_NUMERIC_RE = re.compile(r"\b\d{2,}(?:\.\d+)?%?\b")
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b"
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")

# Noise: hex-looking (or long numeric-only) tokens -- hashes, CSRF
# tokens, session ids -- that a naive numeric regex would otherwise pick
# up as a "fact".
_HEX_NOISE_RE = re.compile(r"^[a-f0-9]{12,}$", re.IGNORECASE)

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def today_variants(today_iso: str) -> set[str]:
    """Every string form of `today_iso` that `_DATE_RE` could plausibly
    capture, so "generated at" timestamps get suppressed regardless of
    which of the regex's supported formats a template happens to use --
    matching only the exact ISO string (the original implementation)
    missed a same-day date written as "08/28/2026" or "Aug 28, 2026"."""
    d = date.fromisoformat(today_iso)
    month = _MONTH_NAMES[d.month - 1]
    return {
        d.isoformat(),  # 2026-08-28
        f"{d.month}/{d.day}/{d.year}",  # 8/28/2026
        f"{d.month:02d}/{d.day:02d}/{d.year}",  # 08/28/2026
        f"{month} {d.day}, {d.year}",  # Aug 28, 2026
        f"{month}. {d.day}, {d.year}",  # Aug. 28, 2026
    }


def extract_facts(text: str, *, today_iso: str | None = None) -> dict[str, set[str]]:
    facts = {
        "currency": set(_CURRENCY_RE.findall(text)),
        "numeric": {n for n in _NUMERIC_RE.findall(text) if not _HEX_NOISE_RE.match(n)},
        "date": set(_DATE_RE.findall(text)),
        "contact": set(_EMAIL_RE.findall(text)) | set(_PHONE_RE.findall(text)),
    }
    if today_iso:
        facts["date"] -= today_variants(today_iso)  # suppress "generated at" timestamps, not content dates
    # numeric facts that are substrings of an already-captured currency
    # fact aren't a separate finding (e.g. "$49" also matching \d{2,})
    currency_digits = {re.sub(r"[^\d.]", "", c) for c in facts["currency"]}
    facts["numeric"] = {n for n in facts["numeric"] if n not in currency_digits}
    return facts


def normalize_currency_value(value: str) -> float | None:
    """'$1,049.99' / '1049.99' / 1049 -> 1049.99. Returns None if it
    doesn't parse as a number at all (used to compare a JSON-LD price
    field against text-extracted currency facts without formatting
    differences -- '$105' vs '105.00' -- causing a false contradiction)."""
    stripped = re.sub(r"[^\d.]", "", str(value))
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None
