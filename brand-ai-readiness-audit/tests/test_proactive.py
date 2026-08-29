"""The beyond-defect proactive layer: every recommendation must be
derived from something the run actually measured, and must stay silent
when there is no measured gap. These tests pin both halves.
"""

from __future__ import annotations

import proactive
from brand_audit.models import AnswerabilityMatrixEntry, AnswerabilityOutcome


def _entry(intent: str, outcome: AnswerabilityOutcome, query: str = "q") -> AnswerabilityMatrixEntry:
    citable = outcome in (AnswerabilityOutcome.ANSWERABLE, AnswerabilityOutcome.PARTIAL)
    return AnswerabilityMatrixEntry(
        query=f"{query} ({intent})", intent=intent, outcome=outcome,
        top_chunk_url="https://example.com/" if citable else None, citable=citable,
    )


# --- missing intent coverage --------------------------------------------------


def test_intent_class_with_no_answerable_query_is_recommended():
    matrix = [_entry("pricing", AnswerabilityOutcome.UNGROUNDED) for _ in range(3)]
    recs = proactive._recommend_missing_intent_coverage(matrix)
    assert len(recs) == 1
    assert "pricing" in recs[0].title
    # The rationale must cite the measurement, not just assert the gap.
    assert "3 simulated pricing-intent queries" in recs[0].rationale


def test_intent_class_with_one_answerable_query_is_not_recommended():
    matrix = [
        _entry("pricing", AnswerabilityOutcome.ANSWERABLE),
        _entry("pricing", AnswerabilityOutcome.UNGROUNDED),
        _entry("pricing", AnswerabilityOutcome.UNGROUNDED),
    ]
    assert proactive._recommend_missing_intent_coverage(matrix) == []


def test_multiple_missing_intents_are_emitted_in_deterministic_order():
    matrix = [_entry("trust", AnswerabilityOutcome.UNGROUNDED), _entry("pricing", AnswerabilityOutcome.UNGROUNDED)]
    recs = proactive._recommend_missing_intent_coverage(matrix)
    assert [r.title for r in recs] == [
        "No page answers pricing-intent questions",
        "No page answers trust-intent questions",
    ]


def test_empty_matrix_yields_nothing():
    assert proactive._recommend_missing_intent_coverage([]) == []


# --- near-miss upgrades -------------------------------------------------------


def test_partial_outcomes_are_surfaced_as_near_misses():
    matrix = [_entry("capability", AnswerabilityOutcome.PARTIAL)]
    recs = proactive._recommend_near_miss_upgrades(matrix)
    assert len(recs) == 1
    assert "one edit away" in recs[0].title
    assert "capability" in recs[0].rationale


def test_no_partials_means_no_near_miss_recommendation():
    matrix = [_entry("capability", AnswerabilityOutcome.ANSWERABLE)]
    assert proactive._recommend_near_miss_upgrades(matrix) == []


# --- llms.txt -----------------------------------------------------------------


def test_missing_llms_txt_generates_a_proposal_from_the_real_sampled_urls():
    urls = ["https://example.com/", "https://example.com/pricing", "https://example.com/about"]
    recs = proactive._recommend_llms_txt(False, urls, "https://example.com")
    assert len(recs) == 1
    # The build plan's requirement verbatim: generated from the actual
    # site map, not a stub. Every sampled URL must appear in the draft.
    for u in urls:
        assert u in recs[0].rationale
    assert "example.com" in recs[0].rationale


def test_present_llms_txt_is_not_recommended():
    assert proactive._recommend_llms_txt(True, ["https://example.com/"], "https://example.com") == []


def test_llms_txt_not_recommended_when_no_pages_were_crawled():
    # Nothing to build a proposal from -- a generic stub is exactly what
    # this layer is supposed to never emit.
    assert proactive._recommend_llms_txt(False, [], "https://example.com") == []


# --- top-level ----------------------------------------------------------------


def test_clean_site_with_full_coverage_yields_no_recommendations():
    matrix = [_entry(i, AnswerabilityOutcome.ANSWERABLE) for i in ("identity", "pricing", "contact")]
    recs = proactive.derive_proactive_recommendations(
        matrix, ["https://example.com/"], "https://example.com", llms_txt_present=True
    )
    assert recs == []


def test_derivation_is_deterministic():
    matrix = [_entry("pricing", AnswerabilityOutcome.UNGROUNDED), _entry("trust", AnswerabilityOutcome.PARTIAL)]
    urls = ["https://example.com/b", "https://example.com/a"]
    a = proactive.derive_proactive_recommendations(matrix, urls, "https://example.com", llms_txt_present=False)
    b = proactive.derive_proactive_recommendations(matrix, urls, "https://example.com", llms_txt_present=False)
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]
