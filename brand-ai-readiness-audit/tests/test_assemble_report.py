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


def test_same_taxonomy_different_urls_are_not_collapsed_by_the_exact_pass():
    # Tests `_dedup_exact` directly rather than through `dedup_findings`.
    # The exact pass keys on the artifact URL set, so two findings on two
    # pages are not the same finding to it -- that property is unchanged.
    # What did change is the public wrapper: `dedup_findings` now runs a
    # per-page aggregation afterwards, which merges exactly this pair on
    # purpose (see the aggregation tests below). Asserting the old count
    # through the wrapper was asserting the absence of a feature that has
    # since been added deliberately.
    a = _finding("F-1", "TRUST-005", Stage.CITE, urls=["https://example.com/a"])
    b = _finding("F-2", "TRUST-005", Stage.CITE, urls=["https://example.com/b"])
    assert len(ar._dedup_exact([a, b])) == 2


# --- per-page aggregation within a stage --------------------------------------


def test_the_same_defect_on_many_pages_becomes_one_finding():
    # Regression for a real report: auditing thesouledstore.com produced
    # 26 separate EXTRACT-002 findings, one per page, each reading
    # checked=1/affected=1 and each carrying the identical suggested
    # action -- so the prioritized action list was fourteen consecutive
    # copies of the same sentence for one site-wide template defect.
    findings = [
        _finding(f"F-{i}", "EXTRACT-002", Stage.EXTRACT, urls=[f"https://example.com/p{i}"])
        for i in range(26)
    ]
    result = ar.dedup_findings(findings, {Stage.EXTRACT: 40})
    assert len(result) == 1
    merged = result[0]
    # The honest denominator is what the stage examined, not the group size.
    assert (merged.scope.checked, merged.scope.affected) == (40, 26)
    assert merged.title.startswith("26 of 40 page(s):")
    assert merged.artifacts, "no artifact, no finding -- still holds after merging"


def test_merged_evidence_names_the_pages_it_came_from():
    findings = [
        _finding(f"F-{i}", "EXTRACT-002", Stage.EXTRACT, urls=[f"https://example.com/p{i}"])
        for i in range(3)
    ]
    merged = ar.dedup_findings(findings, {Stage.EXTRACT: 10})[0]
    # Each member's evidence is page-local and doesn't name its own URL,
    # so the merge has to pair them or it says what is wrong without where.
    for i in range(3):
        assert f"https://example.com/p{i}" in merged.evidence


def test_findings_with_different_fixes_do_not_merge():
    # EXTRACT-002 missing 'name' and EXTRACT-002 missing 'logo' are two
    # separate pieces of work, and their implementation lines say so.
    a = _finding("F-1", "EXTRACT-002", Stage.EXTRACT, urls=["https://example.com/a"])
    b = _finding("F-2", "EXTRACT-002", Stage.EXTRACT, urls=["https://example.com/b"])
    b = b.model_copy(
        update={"suggested_action": b.suggested_action.model_copy(update={"implementation": ["add logo"]})}
    )
    assert len(ar.dedup_findings([a, b], {Stage.EXTRACT: 10})) == 2


def test_a_detector_that_already_aggregates_is_left_alone():
    # TRUST-008/ENGAGE-005/RENDER-001 compute a real corpus-level scope.
    # Re-merging them would overwrite a measured `checked` with a guess.
    a = _finding("F-1", "TRUST-008", Stage.CITE, urls=["https://example.com/a"])
    a = a.model_copy(update={"scope": Scope(checked=40, affected=40)})
    b = _finding("F-2", "TRUST-008", Stage.CITE, urls=["https://example.com/b"])
    b = b.model_copy(update={"scope": Scope(checked=40, affected=40)})
    result = ar.dedup_findings([a, b], {Stage.CITE: 40})
    assert len(result) == 2
    assert all(f.scope.checked == 40 for f in result)


def test_a_single_page_finding_is_not_rewritten():
    a = _finding("F-1", "EXTRACT-002", Stage.EXTRACT, urls=["https://example.com/a"])
    result = ar.dedup_findings([a], {Stage.EXTRACT: 40})
    assert len(result) == 1
    assert result[0].title == a.title, "a lone finding must not gain a '1 of 40' prefix"
    assert result[0].scope.checked == 1


def test_aggregation_preserves_report_order_and_is_deterministic():
    other = _finding("F-0", "EXTRACT-004", Stage.EXTRACT, urls=["https://example.com/z"])
    group = [
        _finding(f"F-{i}", "EXTRACT-002", Stage.EXTRACT, urls=[f"https://example.com/p{i}"])
        for i in range(1, 4)
    ]
    a = ar.dedup_findings([other, *group], {Stage.EXTRACT: 9})
    b = ar.dedup_findings([other, *group], {Stage.EXTRACT: 9})
    assert [f.id for f in a] == [f.id for f in b] == ["F-0", "F-1"]


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
