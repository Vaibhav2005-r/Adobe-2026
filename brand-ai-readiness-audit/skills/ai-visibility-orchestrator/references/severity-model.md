# Severity model

`severity = f(stage, blast_radius, confidence)` -- deterministic, never
hand-assigned by a detector. A detector reports what it observed
(`stage`, `scope: {checked, affected, page_class}`, `confidence`); this
function turns that into a `Severity`.

## Decision table

| Condition | Severity |
|---|---|
| Blocks stage ① REACH or ② RENDER, site-wide (`page_class` unset or spans the whole sampled corpus) | `critical` |
| Blocks a stage for a whole page class (e.g. all `product` pages), or a `critical`-shaped defect narrowed to one page class | `high` |
| Degrades retrieval/citation quality without blocking a stage outright (partial answers, weak trust, uncredited citation) | `medium` |
| Proactive improvement -- no defect actually found, or a `medium`-shaped defect at `confidence: low` pending falsification | `low` |

**Confidence discounts severity, it never inflates it.** A defect that
would otherwise be `critical` but is only `confidence: low` (single
sample, not yet reproduced by `finding-verification`) is reported as an
`observation`, not a shipped `critical` finding -- see
`references/report-schema.md` on the `observations` array.

## Worked examples from Day 1 field research

These were assigned by hand during field research, before this function
was implemented in code -- they're the worked examples the eventual
`f(stage, blast_radius, confidence)` implementation must reproduce:

- `REACH-001` (nytimes.com, explicit `Disallow: /` for every named AI
  bot): stage=reach, blast_radius=site-wide, confidence=high ->
  `critical`.
- `REACH-002` (stripe.com/pricing empty-body geo-redirect): stage=reach,
  blast_radius=single highest-value page (not literally
  "whole page class", but the *canonical* entry point for the entire
  site's highest-value content) -> `high`.
- `TRUST-001` (SaaS pricing aggregator displacement, reproduced 3-for-3):
  stage=cite, blast_radius=degrades citation credit without blocking
  retrieval, confidence=high (reproduced) -> `medium`.
- `TRUST-002` / `TRUST-003` (single-sample, unverified): confidence=low
  -> demoted to `observations`, not scored as findings at all.
- `TRUST-004` (missing entity-anchoring schema, no citation failure
  observed): blast_radius=structural risk with no observed failure ->
  `low`.

## Status

Implemented since Day 3 as `src/brand_audit/severity.py::compute_severity`
-- every detector across all six stages calls it rather than hand-
assigning a `Severity`, confirmed by grep (no `severity=Severity\.` literal
assignment anywhere outside that one function and its own tests). This
doc was written before that implementation and originally said the `f()`
itself was Day 8 work; corrected on Day 8 while adding the piece that
*was* actually still missing: `finding-verification` (Day 8) re-derives
and recomputes `severity` after a confidence change, via
`verify_findings._infer_blast_radius` -- an inversion of this same
decision table, documented in that function's own docstring, since
`Finding` doesn't persist `blast_radius` directly. See
`skills/finding-verification/scripts/verify_findings.py` and
`docs/progress.md` at the repo root.
