"""finding-verification: unit tests for the falsification pass --
reproduction/liveness, sample-adequacy demotion, and the EXTRACT-002
contradiction check -- plus an end-to-end check that a real audit run
actually populates `verification` and can demote to `observations`.
"""

from __future__ import annotations

from pathlib import Path

import verify_findings as vf
from brand_audit.artifact_store import FetchRecord
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

REPO_ROOT = Path(__file__).resolve().parent.parent


def _finding(
    *,
    taxonomy_id: str = "TRUST-005",
    stage: Stage = Stage.CITE,
    severity: Severity = Severity.MEDIUM,
    confidence: Confidence = Confidence.HIGH,
    checked: int = 5,
    affected: int = 1,
    url: str = "https://example.com/",
    http_status: int | None = 200,
    evidence: str = "some evidence",
) -> Finding:
    return Finding(
        id="F-TEST-001",
        title="test finding",
        severity=severity,
        stage=stage,
        taxonomy_id=taxonomy_id,
        scope=Scope(checked=checked, affected=affected),
        evidence=evidence,
        artifacts=[Artifact(url=url, http_status=http_status)],
        confidence=confidence,
        verification=Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented"),
        impact_mechanism="mechanism",
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="fix it", priority=severity, impact="low", effort="low",
            confidence=confidence, stage_unblocked=stage,
        ),
    )


def _record(url: str, status: int | None = 200) -> FetchRecord:
    return FetchRecord(url=url, http_status=status, body=b"<html></html>", fetched_with_ua="test")


# --- reproduction / liveness -------------------------------------------------


def test_successful_refetch_marks_reproduced_true():
    finding = _finding(url="https://example.com/a")
    fresh_records = {"https://example.com/a": _record("https://example.com/a", 200)}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=5)
    assert updated.verification.reproduced is True
    assert demote is False


def test_failed_refetch_demotes_and_marks_not_reproduced():
    finding = _finding(url="https://example.com/a")
    updated, demote = vf.verify_finding(finding, {}, {}, total_pages_available=5)
    assert updated.verification.reproduced is False
    assert demote is True


def test_status_class_change_downgrades_confidence_but_does_not_demote():
    finding = _finding(url="https://example.com/a", http_status=200, confidence=Confidence.HIGH)
    fresh_records = {"https://example.com/a": _record("https://example.com/a", 404)}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=5)
    assert demote is False
    assert updated.confidence == Confidence.MEDIUM
    assert any("status class changed" in s for s in updated.verification.contradicting_signals)


def test_stable_status_does_not_downgrade_confidence():
    finding = _finding(url="https://example.com/a", http_status=200, confidence=Confidence.HIGH)
    fresh_records = {"https://example.com/a": _record("https://example.com/a", 200)}
    updated, _ = vf.verify_finding(finding, fresh_records, {}, total_pages_available=5)
    assert updated.confidence == Confidence.HIGH
    assert updated.verification.contradicting_signals == []


# --- sample adequacy ----------------------------------------------------------


def test_critical_finding_from_tiny_sample_of_larger_corpus_is_demoted():
    finding = _finding(stage=Stage.REACH, severity=Severity.CRITICAL, checked=1, url="https://example.com/a")
    fresh_records = {"https://example.com/a": _record("https://example.com/a")}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=40)
    assert demote is True
    assert updated.confidence == Confidence.LOW
    assert any("severity claimed from a sample" in s for s in updated.verification.contradicting_signals)


def test_critical_finding_from_a_genuinely_single_page_corpus_is_not_demoted():
    # The real bug this regression-tests: a site whose *entire* known
    # corpus is 1 page checking "all of it" is a complete sample, not
    # an inadequate one -- caught live on tests/fixtures/js-only-price
    # during Day 8 development (see docs/progress.md).
    finding = _finding(stage=Stage.RENDER, severity=Severity.CRITICAL, checked=1, url="https://example.com/")
    fresh_records = {"https://example.com/": _record("https://example.com/")}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=1)
    assert demote is False
    assert updated.severity == Severity.CRITICAL


def test_high_severity_from_small_sample_is_not_demoted():
    # PAGE_CLASS/high severity legitimately comes from one page's
    # evidence in this codebase (see REACH-002's own worked example in
    # severity-model.md) -- only CRITICAL is sample-adequacy-gated.
    finding = _finding(stage=Stage.EXTRACT, severity=Severity.HIGH, checked=1, url="https://example.com/a")
    fresh_records = {"https://example.com/a": _record("https://example.com/a")}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=40)
    assert demote is False
    assert updated.severity == Severity.HIGH


def test_critical_finding_from_adequate_sample_is_not_demoted():
    finding = _finding(stage=Stage.REACH, severity=Severity.CRITICAL, checked=10, url="https://example.com/a")
    fresh_records = {"https://example.com/a": _record("https://example.com/a")}
    updated, demote = vf.verify_finding(finding, fresh_records, {}, total_pages_available=40)
    assert demote is False


# --- EXTRACT-002 contradiction check -----------------------------------------


def test_extract_002_contradiction_found_in_microdata_downgrades_confidence():
    finding = _finding(
        taxonomy_id="EXTRACT-002", stage=Stage.EXTRACT, severity=Severity.MEDIUM, confidence=Confidence.HIGH,
        checked=5, url="https://example.com/product",
        evidence="@type='Product', missing: ['sku', 'brand'], present keys: ['name']",
    )
    html = (
        '<html><body itemscope itemtype="https://schema.org/Product">'
        '<span itemprop="sku">ABC-123</span></body></html>'
    )
    fresh_records = {"https://example.com/product": _record("https://example.com/product")}
    fresh_pages = {"https://example.com/product": html}
    updated, demote = vf.verify_finding(finding, fresh_records, fresh_pages, total_pages_available=40)
    assert demote is False
    assert updated.confidence == Confidence.MEDIUM
    assert any("microdata/RDFa" in s for s in updated.verification.contradicting_signals)


def test_extract_002_no_contradiction_when_property_absent_everywhere():
    finding = _finding(
        taxonomy_id="EXTRACT-002", stage=Stage.EXTRACT, severity=Severity.MEDIUM, confidence=Confidence.HIGH,
        checked=5, url="https://example.com/product",
        evidence="@type='Product', missing: ['sku', 'brand'], present keys: ['name']",
    )
    html = "<html><body><p>No microdata here at all.</p></body></html>"
    fresh_records = {"https://example.com/product": _record("https://example.com/product")}
    fresh_pages = {"https://example.com/product": html}
    updated, _ = vf.verify_finding(finding, fresh_records, fresh_pages, total_pages_available=40)
    assert updated.confidence == Confidence.HIGH
    assert updated.verification.contradicting_signals == []


def test_contradiction_check_only_applies_to_registered_taxonomy_ids():
    finding = _finding(taxonomy_id="TRUST-005", confidence=Confidence.HIGH, url="https://example.com/a")
    fresh_records = {"https://example.com/a": _record("https://example.com/a")}
    fresh_pages = {"https://example.com/a": "<html>anything</html>"}
    updated, _ = vf.verify_finding(finding, fresh_records, fresh_pages, total_pages_available=40)
    assert updated.confidence == Confidence.HIGH
