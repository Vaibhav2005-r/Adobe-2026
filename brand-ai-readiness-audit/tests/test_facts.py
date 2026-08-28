"""Unit tests for brand_audit.facts -- in particular the date-suppression
fix: the original implementation only discarded an exact ISO-format
match of today's date, so a same-day timestamp written in any other
format the date regex itself supports (US slash, month-name) would slip
through as a spurious "fact". today_variants() must cover every format
_DATE_RE can actually capture.
"""

from __future__ import annotations

from brand_audit.facts import extract_facts, normalize_currency_value, today_variants


def test_today_variants_covers_every_format_the_date_regex_captures():
    variants = today_variants("2026-08-28")
    assert "2026-08-28" in variants
    assert "8/28/2026" in variants
    assert "08/28/2026" in variants
    assert "Aug 28, 2026" in variants


def test_extract_facts_suppresses_today_in_non_iso_format():
    text = "Generated on 08/28/2026 at 12:00pm."
    facts = extract_facts(text, today_iso="2026-08-28")
    assert facts["date"] == set()  # would have leaked through before the fix


def test_extract_facts_suppresses_today_in_month_name_format():
    text = "Last updated: Aug 28, 2026."
    facts = extract_facts(text, today_iso="2026-08-28")
    assert facts["date"] == set()


def test_extract_facts_keeps_other_dates():
    text = "Founded January 15, 2020. Updated 2026-08-28."
    facts = extract_facts(text, today_iso="2026-08-28")
    assert facts["date"] == {"January 15, 2020"}


def test_normalize_currency_value():
    assert normalize_currency_value("$1,049.99") == 1049.99
    assert normalize_currency_value("105") == 105.0
    assert normalize_currency_value("₹24,999") == 24999.0
    assert normalize_currency_value("not a number") is None
