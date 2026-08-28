"""Merge StageResult objects into a single validated AuditReport.

Deduping/merging findings across stages (so one root cause doesn't emit
six findings) and the deterministic severity function are Day 8 work --
see docs/progress.md. For now this does the honest minimum: concatenate
findings, count them by severity, and compute the ai_readiness/
answerability summaries from whatever stages actually ran.
"""

from __future__ import annotations

from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import (  # noqa: E402
    AIReadiness,
    AnswerabilitySummary,
    AuditReport,
    ReadinessStatus,
    RunManifest,
    Severity,
    Stage,
    StageResult,
    Summary,
)

MARKETPLACE_VERSION = "0.1.0"
RULE_PACK_VERSION = "2026.08.28"  # bump when references/taxonomy.md gains/loses entries

# Every stage's readiness defaults to "skipped" until that stage actually
# runs -- an honest report says what it didn't check, rather than implying
# a pass.
_STAGE_TO_READINESS_FIELD = {
    Stage.REACH: "reach",
    Stage.RENDER: "render",
    Stage.EXTRACT: "extract",
    Stage.RETRIEVE: "retrieve",
    Stage.CITE: "cite",
    Stage.ARRIVE: "arrive",
}

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def _readiness_for_stage(stage_results: list[StageResult], stage: Stage) -> ReadinessStatus:
    matching = [r for r in stage_results if r.stage == stage]
    if not matching:
        return ReadinessStatus.SKIPPED
    findings = [f for r in matching for f in r.findings]
    if not findings:
        return ReadinessStatus.PASS
    if any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in findings):
        return ReadinessStatus.FAIL
    return ReadinessStatus.PARTIAL


def assemble_report(
    *,
    site: str,
    stage_results: list[StageResult],
    duration_s: float,
    sample_seed: str,
    pages_crawled: int,
    pages_rendered: int,
    degradations: list[str],
    observations: list = None,
) -> AuditReport:
    findings = [f for r in stage_results for f in r.findings]
    observations = observations or []

    severity_counts = {s: 0 for s in Severity}
    for f in findings:
        severity_counts[f.severity] += 1

    ai_readiness = AIReadiness(
        **{
            field_name: _readiness_for_stage(stage_results, stage)
            for stage, field_name in _STAGE_TO_READINESS_FIELD.items()
        }
    )

    # The most severe finding, not just the first one by stage-concatenation
    # order -- a report where REACH happens to run before RENDER shouldn't
    # headline a low-severity canonical nit over a critical empty-JS-shell
    # finding just because REACH's findings list came first.
    headline = (
        "No findings on the stages that ran -- audit skeleton only, detectors not yet wired up."
        if not findings
        else min(findings, key=lambda f: _SEVERITY_RANK[f.severity]).title
    )

    summary = Summary(
        total_findings=len(findings),
        critical=severity_counts[Severity.CRITICAL],
        high=severity_counts[Severity.HIGH],
        medium=severity_counts[Severity.MEDIUM],
        low=severity_counts[Severity.LOW],
        ai_readiness=ai_readiness,
        answerability=AnswerabilitySummary(),
        headline=headline,
    )

    run_manifest = RunManifest(
        marketplace_version=MARKETPLACE_VERSION,
        rule_pack_version=RULE_PACK_VERSION,
        pages_crawled=pages_crawled,
        pages_rendered=pages_rendered,
        sample_seed=sample_seed,
        duration_s=duration_s,
        stages_completed=[r.stage for r in stage_results],
        degradations=degradations,
    )

    return AuditReport(
        site=site,
        audited_at=datetime.now(timezone.utc),
        run_manifest=run_manifest,
        summary=summary,
        findings=findings,
        observations=observations,
        proactive_recommendations=[],
        answerability_matrix=[],
    )
