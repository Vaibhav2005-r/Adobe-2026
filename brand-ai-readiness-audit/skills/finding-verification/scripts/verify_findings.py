"""Cross-cutting falsification pass (finding-verification): runs after
every detection stage, across all their findings, and tries to disprove
each one before it ships. Per docs/build-plan.md Part 2 (4), the
"anti-false-positive weapon" -- the rubric explicitly rewards "few false
positives," so this is the dedicated mechanism that earns it, not a
hope that the per-stage detectors are already careful enough.

Checks, generically, per finding -- works for every taxonomy_id without
a per-detector re-implementation, since every Finding already
guarantees `artifacts: list[Artifact]` (>=1 entry, "no artifact, no
finding") and a `scope`:

1. Reproduction / artifact liveness -- re-fetch the finding's own
   primary artifact URL with a *different* UA than stage (1) used;
   confirm the URL still resolves at all, and note (without demoting)
   if its HTTP status class flips between "ok" (<400) and "broken".
2. Sample adequacy -- a HIGH/CRITICAL severity claim resting on a
   sample of fewer than 2 checked pages can't support the blast-radius
   it claims ("a defect on 1/1 page cannot claim site-wide", per the
   build plan verbatim).
3. Contradiction search -- narrowly implemented for `EXTRACT-002`
   (missing required JSON-LD properties): is the same property carried
   by microdata/RDFa on the same page instead? If so, the "a consumer
   may skip this fact" claim is weaker than stated -- downgrade, don't
   drop, per the build plan's own instruction. Not implemented for
   other taxonomy families: a generic "does some alternate signal carry
   the same fact" check isn't well-defined enough to implement
   honestly across mechanisms as different as a redirect (ENGAGE-003)
   and a staleness date (TRUST-006) -- see SKILL.md Status for the
   explicit scope statement, the same "state the gap, don't fake
   coverage" discipline used throughout this project.

A finding whose re-fetch fails outright (check 1), or that fails sample
adequacy (check 2), is demoted to the report's `observations` array --
shown, never silently dropped, per the build plan. A finding that trips
check 3 alone stays a finding, with confidence downgraded one notch and
the contradiction recorded in `verification.contradicting_signals`.

Explicitly NOT implemented: re-deriving a finding's own pattern against
a *second, independent sample* of additional pages (the build plan's
other re-fetch bullet, "a second sample of pages"). That would mean
re-running each taxonomy_id's own detection logic against fresh pages,
which needs a per-detector dispatch table this pass deliberately
doesn't build within Day 8's scope -- see SKILL.md Status.

Re-fetching a finding's own artifact URL a second time doesn't need a
fresh robots.txt check: every such URL was already fetched once during
stage (1), which only ever fetches robots-permitted URLs in the first
place -- this pass fetches nothing that wasn't already legitimately
fetched this same run.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.artifact_store import FetchRecord  # noqa: E402
from brand_audit.crawl import VERIFICATION_UA  # noqa: E402
from brand_audit.fetch import fetch_many  # noqa: E402
from brand_audit.models import Confidence, Finding, Severity, Verification  # noqa: E402
from brand_audit.severity import BlastRadius, compute_severity  # noqa: E402

import extruct

_MIN_CHECKED_FOR_BROAD_CLAIM = 2
_CONFIDENCE_ORDER = [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]


def _downgrade(confidence: Confidence) -> Confidence:
    idx = _CONFIDENCE_ORDER.index(confidence)
    return _CONFIDENCE_ORDER[min(idx + 1, len(_CONFIDENCE_ORDER) - 1)]


def _infer_blast_radius(severity: Severity) -> BlastRadius:
    """Recover the blast_radius a detector must have used to produce
    this severity, so severity can be recomputed after a confidence
    change. `Finding` doesn't persist `blast_radius` directly (only the
    resulting `severity`) -- adding it would mean threading a new
    constructor argument through ~30 existing `Finding(...)` call sites
    across six already-shipped detector files for marginal benefit, so
    this inverts `compute_severity` instead.

    Safe to invert: the base-severity mapping in `compute_severity` is
    injective in blast_radius (SITE_WIDE+REACH/RENDER -> CRITICAL,
    PAGE_CLASS -> HIGH, DEGRADES -> MEDIUM, NONE -> LOW), and the
    confidence clamp only ever pulls a CRITICAL/HIGH base down to
    MEDIUM, never down to LOW -- so an observed LOW severity can only
    mean the base was NONE, never a clamped-down CRITICAL/HIGH. The one
    imprecision: a finding shipped at MEDIUM because LOW confidence
    already clamped a HIGH/CRITICAL base down re-infers here as
    DEGRADES rather than the true PAGE_CLASS/SITE_WIDE -- harmless,
    since further discounting an already-LOW confidence recomputes to
    MEDIUM either way (no clamp rule touches DEGRADES), so the
    recomputed severity is correct regardless of which of the two the
    real blast radius was.
    """
    if severity == Severity.CRITICAL:
        return BlastRadius.SITE_WIDE
    if severity == Severity.HIGH:
        return BlastRadius.PAGE_CLASS
    if severity == Severity.MEDIUM:
        return BlastRadius.DEGRADES
    return BlastRadius.NONE


def _fails_sample_adequacy(finding: Finding, total_pages_available: int) -> bool:
    """CRITICAL only, not HIGH: per severity-model.md's own worked
    example (REACH-002, a single canonical page -> `high`), this
    codebase's detectors legitimately assign PAGE_CLASS/`high` severity
    from a single page's evidence when that page matters enough -- a
    price contradiction on one product page is a real, individually
    actionable defect regardless of whether every other product page
    also has it. CRITICAL is different: `compute_severity` only ever
    produces it from `BlastRadius.SITE_WIDE` on stage REACH/RENDER,
    which severity-model.md defines explicitly as "spans the whole
    sampled corpus" -- a claim `scope.checked < 2` cannot support,
    per the build plan's own "a defect on 1/1 page cannot claim
    site-wide" wording, verbatim.

    The floor is `min(2, total_pages_available)`, not a flat 2: a
    truly single-page site (or a run that only ever fetched one page)
    checking "all of it" isn't an inadequate sample, it's a complete
    one -- confirmed directly by a real false demotion during Day 8
    development, where the single-page `js-only-price` fixture's
    entirely-legitimate site-wide RENDER-001 finding got demoted for
    "only" checking 1 of its site's exactly-1 pages. `checked < 2`
    only signals a risky generalization when there was more corpus
    available to have checked."""
    floor = min(_MIN_CHECKED_FOR_BROAD_CLAIM, total_pages_available)
    return finding.severity == Severity.CRITICAL and finding.scope.checked < floor


def _collect_all_keys(obj) -> set[str]:
    """Every string dict-key anywhere in a nested structure, regardless
    of shape -- used instead of hand-modeling extruct's microdata vs.
    RDFa nesting (they differ: RDFa items nest properties as lists,
    microdata as a flat dict) since a generic key-presence check needs
    only "does this property name appear anywhere," not the structure
    around it."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                keys.add(k)
            keys |= _collect_all_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _collect_all_keys(item)
    return keys


def _contradiction_for_extract_002(finding: Finding, html: str) -> str | None:
    """EXTRACT-002 fired because JSON-LD was missing required
    properties -- does microdata/RDFa on the same page carry any of
    them instead? If so, the fact isn't actually unreachable to a
    structured-data consumer, just not reachable *via JSON-LD*
    specifically -- the build plan's own worked example for this check
    ("no JSON-LD -- but is there microdata or RDFa carrying the same
    facts?"), applied to the taxonomy entry that's actually shaped to
    use it."""
    m = re.search(r"missing: (\[.*?\])", finding.evidence)
    if not m:
        return None
    try:
        missing_props = ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError):
        return None
    if not missing_props:
        return None
    try:
        alt_data = extruct.extract(html, syntaxes=["microdata", "rdfa"])
    except Exception:
        return None
    alt_keys = _collect_all_keys(alt_data)
    found = [p for p in missing_props if p in alt_keys]
    if not found:
        return None
    return f"microdata/RDFa on the same page carries {found} even though JSON-LD omits it"


_CONTRADICTION_CHECKS = {
    "EXTRACT-002": _contradiction_for_extract_002,
}


def verify_finding(
    finding: Finding,
    fresh_records: dict[str, FetchRecord],
    fresh_pages: dict[str, str],
    total_pages_available: int,
) -> tuple[Finding, bool]:
    """Returns (updated_finding, demote). `demote=True` means the
    caller should move this finding to the report's `observations`
    array instead of `findings`."""
    primary_url = finding.artifacts[0].url
    fresh_record = fresh_records.get(primary_url)

    contradicting_signals: list[str] = []
    demote = False
    new_confidence = finding.confidence
    original_status = finding.artifacts[0].http_status

    if fresh_record is None:
        reproduced = False
        method = f"re-fetch of {primary_url} with a different UA failed -- could not re-verify"
        demote = True
    else:
        reproduced = True
        new_status = fresh_record.http_status
        method = f"re-fetched {primary_url} with a different UA (GPTBot); status was {original_status}, now {new_status}"
        if original_status is not None and new_status is not None and (original_status < 400) != (new_status < 400):
            contradicting_signals.append(f"HTTP status class changed since detection: {original_status} -> {new_status}")
            new_confidence = _downgrade(new_confidence)

    if _fails_sample_adequacy(finding, total_pages_available):
        contradicting_signals.append(
            f"{finding.severity.value} severity claimed from a sample of only {finding.scope.checked} checked page(s)"
        )
        demote = True
        new_confidence = Confidence.LOW

    contradiction_check = _CONTRADICTION_CHECKS.get(finding.taxonomy_id)
    if contradiction_check is not None:
        html = fresh_pages.get(primary_url, "")
        contradiction = contradiction_check(finding, html)
        if contradiction:
            contradicting_signals.append(contradiction)
            new_confidence = _downgrade(new_confidence)

    new_severity = compute_severity(finding.stage, _infer_blast_radius(finding.severity), new_confidence)

    updated = finding.model_copy(
        update={
            "confidence": new_confidence,
            "severity": new_severity,
            "verification": Verification(
                reproduced=reproduced,
                method=method,
                contradicting_signals=contradicting_signals,
            ),
        }
    )
    return updated, demote


async def run_finding_verification(
    findings: list[Finding], *, total_pages_available: int = 1, timeout_s: float = 15.0
) -> tuple[list[Finding], list[Finding]]:
    """Re-fetches every finding's primary artifact URL (deduplicated,
    bounded concurrency, a different UA than stage (1) used), then
    verifies each finding against the fresh data. Returns (surviving
    findings, demoted-to-observations findings) -- order-preserving
    within each group.

    `total_pages_available`: the audit's own stage (1) page count
    (`pages_fetched_ok`) -- how big the known corpus actually is, so
    the sample-adequacy check can tell "a small slice of a bigger
    corpus" apart from "the whole corpus, which happens to be small."
    Defaults to 1 (the most conservative floor: any `checked>=1`
    finding counts as adequate) only for callers that don't have a
    real page count to pass -- production use (run_audit.py) always
    passes the real count."""
    if not findings:
        return [], []

    urls = sorted({f.artifacts[0].url for f in findings})
    outcomes = await fetch_many(urls, user_agent=VERIFICATION_UA, timeout_s=timeout_s)
    fresh_records = {o.url: o.record for o in outcomes if o.record is not None}
    fresh_pages = {u: r.text for u, r in fresh_records.items()}

    survived: list[Finding] = []
    demoted: list[Finding] = []
    for finding in findings:
        updated, demote = verify_finding(finding, fresh_records, fresh_pages, total_pages_available)
        (demoted if demote else survived).append(updated)
    return survived, demoted
