"""assemble_report: unit tests for dedup/merge across stages -- exact-
duplicate collapse (a safety net) and the known REACH-002/ENGAGE-003
same-root-cause merge -- plus a check that unrelated findings sharing a
URL are never merged just because they're on the same page.
"""

from __future__ import annotations

import assemble_report as ar
from brand_audit.models import (
    Artifact,
    Confidence,
    Finding,
    Scope,
    Severity,
    Stage,
    SuggestedAction,
    Verification,
)


def _finding(
    id: str,
    taxonomy_id: str,
    stage: Stage,
    *,
    severity: Severity = Severity.MEDIUM,
    urls: list[str] = None,
) -> Finding:
    urls = urls or ["https://example.com/a"]
    return Finding(
        id=id,
        title=f"{taxonomy_id} finding",
        severity=severity,
        stage=stage,
        taxonomy_id=taxonomy_id,
        scope=Scope(checked=1, affected=1),
        evidence="original evidence",
        artifacts=[Artifact(url=u) for u in urls],
        confidence=Confidence.HIGH,
        verification=Verification(reproduced=True, method="test"),
        impact_mechanism="mechanism",
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="fix it", priority=severity, impact="low", effort="low",
            confidence=Confidence.HIGH, stage_unblocked=stage,
        ),
    )


# --- exact-duplicate collapse -------------------------------------------------


def test_exact_duplicate_findings_collapse_to_one():
    a = _finding("F-1", "TRUST-005", Stage.CITE)
    b = _finding("F-2", "TRUST-005", Stage.CITE)  # same taxonomy_id, same stage, same artifact URL
    result = ar.dedup_findings([a, b])
    assert len(result) == 1


def test_same_taxonomy_different_urls_are_not_collapsed():
    a = _finding("F-1", "TRUST-005", Stage.CITE, urls=["https://example.com/a"])
    b = _finding("F-2", "TRUST-005", Stage.CITE, urls=["https://example.com/b"])
    result = ar.dedup_findings([a, b])
    assert len(result) == 2


# --- known same-root-cause merge (REACH-002 / ENGAGE-003) --------------------


def test_reach_002_and_engage_003_on_same_url_merge_keeping_earlier_stage():
    reach = _finding("F-1", "REACH-002", Stage.REACH, severity=Severity.HIGH, urls=["https://example.com/pricing"])
    engage = _finding("F-2", "ENGAGE-003", Stage.ARRIVE, severity=Severity.HIGH, urls=["https://example.com/pricing"])
    result = ar.dedup_findings([reach, engage])
    assert len(result) == 1
    survivor = result[0]
    assert survivor.taxonomy_id == "REACH-002"  # earlier funnel stage wins, not severity
    assert "ENGAGE-003" in survivor.evidence  # merge note appended, not silently dropped


def test_merge_is_order_independent():
    # Same pair, findings passed in the opposite order -- the earlier
    # funnel stage must still win regardless of list order.
    engage = _finding("F-1", "ENGAGE-003", Stage.ARRIVE, severity=Severity.HIGH, urls=["https://example.com/pricing"])
    reach = _finding("F-2", "REACH-002", Stage.REACH, severity=Severity.HIGH, urls=["https://example.com/pricing"])
    result = ar.dedup_findings([engage, reach])
    assert len(result) == 1
    assert result[0].taxonomy_id == "REACH-002"


def test_reach_002_and_engage_003_on_different_urls_do_not_merge():
    reach = _finding("F-1", "REACH-002", Stage.REACH, urls=["https://example.com/pricing"])
    engage = _finding("F-2", "ENGAGE-003", Stage.ARRIVE, urls=["https://example.com/contact"])
    result = ar.dedup_findings([reach, engage])
    assert len(result) == 2


def test_unrelated_taxonomy_pair_on_same_url_is_never_merged():
    # TRUST-005 and EXTRACT-002 sharing a page is a coincidence, not a
    # shared root cause -- only pairs in the explicit table merge.
    trust = _finding("F-1", "TRUST-005", Stage.CITE, urls=["https://example.com/product"])
    extract = _finding("F-2", "EXTRACT-002", Stage.EXTRACT, urls=["https://example.com/product"])
    result = ar.dedup_findings([trust, extract])
    assert len(result) == 2


# --- assemble_report's findings= override -------------------------------------


def test_assemble_report_uses_explicit_findings_not_stage_results_when_given():
    from brand_audit.models import StageResult

    stage_result = StageResult(stage=Stage.CITE, findings=[_finding("F-1", "TRUST-005", Stage.CITE)], corpus_delta=[])
    report = ar.assemble_report(
        site="example.com",
        stage_results=[stage_result],
        findings=[],  # explicitly override to empty, even though stage_results has one
        duration_s=1.0,
        sample_seed="sha256:x",
        pages_crawled=1,
        pages_rendered=0,
        degradations=[],
    )
    assert report.findings == []
    assert report.summary.ai_readiness.cite == "pass"  # stage ran (per stage_results), just produced no findings


def test_assemble_report_falls_back_to_stage_results_when_findings_omitted():
    from brand_audit.models import StageResult

    stage_result = StageResult(stage=Stage.CITE, findings=[_finding("F-1", "TRUST-005", Stage.CITE)], corpus_delta=[])
    report = ar.assemble_report(
        site="example.com",
        stage_results=[stage_result],
        duration_s=1.0,
        sample_seed="sha256:x",
        pages_crawled=1,
        pages_rendered=0,
        degradations=[],
    )
    assert len(report.findings) == 1
