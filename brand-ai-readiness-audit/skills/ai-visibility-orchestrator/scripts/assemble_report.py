"""Merge StageResult objects into a single validated AuditReport.

Dedup/merge across stages (`dedup_findings`, Day 8) collapses exact
duplicates (a safety net -- current detector design shouldn't produce
any) and known same-root-cause cross-stage pairs (currently just
REACH-002/ENGAGE-003 -- a redirect that loses a deep link's specificity
is both a crawler-fetch problem and an arrival-experience problem, and
should ship as one finding with both framings, not two pointing at two
different fixes). `finding-verification` (also Day 8) runs before this
module, in `run_audit.py`, and hands back the already-verified findings
list plus anything it demoted to `observations` -- this module doesn't
call it itself, to keep "detect/verify" and "merge/assemble" as
separate, independently testable responsibilities.
"""

from __future__ import annotations

from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import (  # noqa: E402
    AIReadiness,
    AnswerabilityMatrixEntry,
    AnswerabilityOutcome,
    AnswerabilitySummary,
    AuditReport,
    Finding,
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

_FUNNEL_ORDER = [Stage.REACH, Stage.RENDER, Stage.EXTRACT, Stage.RETRIEVE, Stage.CITE, Stage.ARRIVE]

# (upstream_taxonomy_id, downstream_taxonomy_id): why these two, found on
# the same URL, are the same underlying defect wearing two stages'
# framing. Kept as an explicit, small, mechanism-justified table --
# the same "every rule must state a mechanism" discipline as
# taxonomy.md itself -- rather than a blanket "same URL, different
# stage -> merge" heuristic, which would risk merging genuinely
# distinct defects that just happen to share a page (e.g. a TRUST-005
# and an EXTRACT-002 finding on the same product page are NOT the same
# root cause). Add a pair here only once a real shared mechanism is
# identified, same discipline as adding a taxonomy entry.
_SAME_ROOT_CAUSE_PAIRS: dict[tuple[str, str], str] = {
    ("REACH-002", "ENGAGE-003"): (
        "both fire on an empty-body/context-losing redirect at the same URL -- "
        "REACH-002 is the crawler-fetch framing, ENGAGE-003 is the same "
        "redirect's arrival-experience consequence"
    ),
}


def _dedup_exact(findings: list[Finding]) -> list[Finding]:
    """Collapses findings that share (stage, taxonomy_id, artifact URL
    set) exactly -- a safety net, not expected to trigger given current
    detector design (every detector already emits at most one finding
    per taxonomy_id per distinct artifact set), but cheap and correct
    to have regardless."""
    seen: set[tuple] = set()
    result: list[Finding] = []
    for f in findings:
        key = (f.stage, f.taxonomy_id, tuple(sorted(a.url for a in f.artifacts)))
        if key in seen:
            continue
        seen.add(key)
        result.append(f)
    return result


def _order_by_funnel_stage(a: Finding, b: Finding) -> tuple[Finding, Finding]:
    a_idx = _FUNNEL_ORDER.index(a.stage)
    b_idx = _FUNNEL_ORDER.index(b.stage)
    return (a, b) if a_idx <= b_idx else (b, a)


def _merge_same_root_cause(findings: list[Finding]) -> list[Finding]:
    """For each known same-root-cause pair, merges the two findings
    when they share an overlapping artifact URL: drops the
    downstream-stage finding, and appends a note to the upstream-stage
    finding's evidence. Keeps the *earlier* funnel-stage finding as
    primary regardless of severity -- the whole thesis of this project
    is reporting the stage a brand first falls out at, so the earlier
    stage's framing is the root cause and the later stage's is the
    downstream symptom."""
    by_taxonomy: dict[str, list[Finding]] = {}
    for f in findings:
        by_taxonomy.setdefault(f.taxonomy_id, []).append(f)

    dropped_ids: set[str] = set()
    merge_notes: dict[str, list[str]] = {}

    for (upstream_id, downstream_id), mechanism in _SAME_ROOT_CAUSE_PAIRS.items():
        for upstream in by_taxonomy.get(upstream_id, []):
            if upstream.id in dropped_ids:
                continue
            upstream_urls = {a.url for a in upstream.artifacts}
            for downstream in by_taxonomy.get(downstream_id, []):
                if downstream.id in dropped_ids or downstream.id == upstream.id:
                    continue
                downstream_urls = {a.url for a in downstream.artifacts}
                if not (upstream_urls & downstream_urls):
                    continue
                primary, secondary = _order_by_funnel_stage(upstream, downstream)
                dropped_ids.add(secondary.id)
                merge_notes.setdefault(primary.id, []).append(
                    f"also matches {secondary.taxonomy_id} ({secondary.title}) on the same URL -- {mechanism}"
                )

    result: list[Finding] = []
    for f in findings:
        if f.id in dropped_ids:
            continue
        notes = merge_notes.get(f.id)
        if notes:
            f = f.model_copy(update={"evidence": f.evidence + " | " + "; ".join(notes)})
        result.append(f)
    return result


def dedup_findings(findings: list[Finding]) -> list[Finding]:
    """Exact-duplicate collapse, then known-pair cross-stage merge --
    order matters, since a merge's evidence-note append should only
    ever touch the single surviving copy of a finding, not a duplicate
    that's about to be dropped anyway."""
    return _merge_same_root_cause(_dedup_exact(findings))


def _readiness_for_stage(findings: list[Finding], stage_results: list[StageResult], stage: Stage) -> ReadinessStatus:
    if not any(r.stage == stage for r in stage_results):
        return ReadinessStatus.SKIPPED
    stage_findings = [f for f in findings if f.stage == stage]
    if not stage_findings:
        return ReadinessStatus.PASS
    if any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in stage_findings):
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
    findings: list[Finding] | None = None,
    observations: list = None,
    answerability_matrix: list[AnswerabilityMatrixEntry] = None,
    proactive_recommendations: list = None,
) -> AuditReport:
    """`findings`: the already-verified findings list from
    `finding-verification` (Day 8) -- pass explicitly once that stage
    has run. Falls back to concatenating `stage_results[*].findings`
    directly when omitted (the pre-Day-8 behavior), so a caller that
    hasn't run verification yet (or a test constructing StageResults
    directly) still gets a sensible report. Either way, `dedup_findings`
    always runs before assembly -- this module is where "merge stage
    outputs -> validated report" happens, per its own composition
    contract, so the invariant needs to hold regardless of how the
    caller got here."""
    findings = dedup_findings(findings if findings is not None else [f for r in stage_results for f in r.findings])
    observations = observations or []
    answerability_matrix = answerability_matrix or []
    proactive_recommendations = proactive_recommendations or []

    severity_counts = {s: 0 for s in Severity}
    for f in findings:
        severity_counts[f.severity] += 1

    ai_readiness = AIReadiness(
        **{
            field_name: _readiness_for_stage(findings, stage_results, stage)
            for stage, field_name in _STAGE_TO_READINESS_FIELD.items()
        }
    )

    # The most severe finding, not just the first one by stage-concatenation
    # order -- a report where REACH happens to run before RENDER shouldn't
    # headline a low-severity canonical nit over a critical empty-JS-shell
    # finding just because REACH's findings list came first.
    headline = (
        "No findings on the stages that ran."
        if not findings
        else min(findings, key=lambda f: _SEVERITY_RANK[f.severity]).title
    )

    answerability_counts = {o: 0 for o in AnswerabilityOutcome}
    for entry in answerability_matrix:
        answerability_counts[entry.outcome] += 1

    summary = Summary(
        total_findings=len(findings),
        critical=severity_counts[Severity.CRITICAL],
        high=severity_counts[Severity.HIGH],
        medium=severity_counts[Severity.MEDIUM],
        low=severity_counts[Severity.LOW],
        ai_readiness=ai_readiness,
        answerability=AnswerabilitySummary(
            answerable=answerability_counts[AnswerabilityOutcome.ANSWERABLE],
            partial=answerability_counts[AnswerabilityOutcome.PARTIAL],
            ungrounded=answerability_counts[AnswerabilityOutcome.UNGROUNDED],
            unretrievable=answerability_counts[AnswerabilityOutcome.UNRETRIEVABLE],
        ),
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
        proactive_recommendations=proactive_recommendations,
        answerability_matrix=answerability_matrix,
    )
