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

- Re-fetch and re-test with a different UA / a second sample of pages --
  does it reproduce?
- Is the artifact still present (URL live, selector resolves, status
  code stable)?
- Does a contradicting signal exist? (E.g. "no JSON-LD" -- but is there
  microdata or RDFa carrying the same facts? Then downgrade, don't
  drop.)
- Is the sample size sufficient for the claimed scope? A defect on 1/1
  page cannot claim site-wide.

Every finding that survives gets `confidence: high|medium|low`,
`verification.reproduced: true|false`, and its `scope: {checked,
affected}` filled in honestly. Findings that fail falsification are
demoted to the report's `observations` array -- shown, never silently
dropped.

This discipline was already applied by hand during Day 1 field research,
before this skill existed: two candidate findings (`TRUST-002`,
`TRUST-003` in `references/taxonomy.md` at the orchestrator) were kept
as explicit single-sample observations rather than shipped as scored
findings, precisely because they hadn't been reproduced. That's the
behavior this skill needs to automate.

## Input / output contract

Reads every `StageResult` from stages ①-⑥. Writes back the same
findings with `verification` populated, plus the `observations` list for
anything demoted -- the orchestrator's `assemble_report.py` merges these
into the final `AuditReport` rather than the raw per-stage findings.

## Status

`Verification`/`Confidence` fields already exist in
`src/brand_audit/models.py`; the falsification logic itself (re-fetch,
contradiction search, sample-adequacy) is not yet implemented -- see
`docs/progress.md` at the repo root.
