---
name: finding-verification
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Cross-cutting falsification pass that runs after all detection stages and tries to disprove every finding before it ships -- re-fetch, reproducibility check, contradiction search, sample-adequacy check, confidence assignment, and demotion to observations for anything that fails.
metadata:
  role: stage
  stage: verify
---

# finding-verification -- the anti-false-positive weapon

Runs after every other stage, across all their findings. The rubric
rewards "few false positives" -- this is the dedicated skill that earns
that, not a hope that the detectors are already careful enough.

## Checks, per finding

- **Reproduction / artifact liveness.** Re-fetch the finding's primary
  artifact URL with a *different* UA (`GPTBot`) than stage ① used --
  confirm the URL still resolves at all (not reproduced, demoted, if
  the fetch fails outright), and note (without demoting) if its HTTP
  status class flips between "ok" and "broken" since detection.
- **Sample adequacy.** A `CRITICAL` severity claim resting on a sample
  smaller than the audit's own known page count can't support the
  site-wide blast radius it makes -- "a defect on 1/1 page cannot claim
  site-wide," except when the corpus genuinely only has 1 page, in
  which case checking all of it *is* adequate (see the module
  docstring's worked example, a real false-demotion this caught during
  Day 8 development). Deliberately not applied to `HIGH`: this
  codebase's own detectors legitimately assign page-class/`high`
  severity from a single page's evidence when that page matters enough
  (`REACH-002`'s own worked example in `references/severity-model.md`).
- **Contradiction search.** Narrowly implemented for `EXTRACT-002`
  (missing required JSON-LD properties): is the same property carried
  by microdata/RDFa on the same page instead? If so, downgrade
  confidence one notch and record it -- don't drop the finding. Not
  implemented for other taxonomy families; see the module docstring
  for why a generic version isn't well-defined enough to build
  honestly.

Every finding that survives gets `confidence` and `severity`
recomputed (via `compute_severity`, re-deriving `blast_radius` from the
original severity -- `Finding` doesn't persist `blast_radius` itself),
plus `verification.reproduced` and `verification.contradicting_signals`
filled in honestly. Findings that fail reproduction or sample adequacy
are demoted to the report's `observations` array -- shown, never
silently dropped.

This discipline was already applied by hand during Day 1 field research,
before this skill existed: two candidate findings (`TRUST-002`,
`TRUST-003` in `references/taxonomy.md` at the orchestrator) were kept
as explicit single-sample observations rather than shipped as scored
findings, precisely because they hadn't been reproduced.

Explicitly **not** implemented: re-deriving a finding's own pattern
against a second, independent sample of *additional* pages (the build
plan's other re-fetch bullet). That would need a per-taxonomy_id
dispatch table re-running each detector's own logic, which this skill
deliberately doesn't build -- see Status.

## Input / output contract

Reads the flat list of findings collected across stages ①-⑥ (assembled
by `run_audit.py`'s `main_async`, after all six stages have run).
Writes back `(surviving_findings, demoted_findings)` -- the
orchestrator passes both into `assemble_report.py`, which merges
surviving findings across stages (`dedup_findings`, e.g. collapsing
`REACH-002`/`ENGAGE-003` when they fire on the same redirect) and
carries the demoted list through as `observations`, rather than reading
the raw per-stage findings directly.

## Status

Implemented in `scripts/verify_findings.py`. Unit-tested against both
positive and negative cases for every check (`tests/test_finding_verification.py`)
-- reproduction success/failure, sample-adequacy demotion (including
the genuinely-tiny-corpus non-demotion case), and the EXTRACT-002
contradiction check. Confirmed running for real against live sites
during Day 8 development (allbirds.com, docs.python.org): every finding
came back `reproduced: true` with no demotions needed on those runs, and
a real demotion was independently confirmed against a synthetic
single-page fixture case (see `docs/progress.md`).
