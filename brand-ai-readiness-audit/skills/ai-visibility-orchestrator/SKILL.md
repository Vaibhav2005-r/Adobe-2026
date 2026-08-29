---
name: ai-visibility-orchestrator
description: Audits how visible a website is to AI assistants (ChatGPT, Claude, Perplexity, etc.) by simulating the retrieval pipeline they actually run -- reach, render, extract, retrieve, cite, arrive -- and reporting the exact stage where the brand falls out, with artifact-backed evidence for every finding. Use this when the user asks to audit a site's AI/LLM visibility, GEO/AEO readiness, or why a brand isn't being cited by AI assistants.
license: MIT
metadata:
  role: entrypoint
  stage: orchestrator
---

# AI Visibility Orchestrator

This is the one entry point of the `brand-ai-readiness-audit` marketplace. The
other seven skills in this marketplace (`crawl-reach-audit`,
`render-gap-audit`, `extractability-audit`, `retrieval-simulation`,
`trust-corroboration-audit`, `arrival-engagement-audit`,
`finding-verification`) are internal pipeline stages this orchestrator
drives -- they are not meant to be invoked directly.

## The thesis

Don't audit the page. Simulate the pipeline an AI assistant runs to answer
a buyer's question, and report the exact stage where the brand falls out:

```
REACH -> RENDER -> EXTRACT -> RETRIEVE -> CITE -> ARRIVE
```

Every finding is stage-localized and artifact-backed (URL + HTTP status +
selector/byte-offset + the literal extracted strings). No artifact, no
finding.

## Running an audit

```
python scripts/run_audit.py <site> [--max-pages 40] [--out report.json]
```

This crawls the site (robots-respecting, read-only), runs all six
funnel-stage skills plus the cross-cutting falsification pass, and
writes three files from the same validated `AuditReport` (see
`assets/report_schema.json`): `report.json` (the schema-valid contract
-- the source of truth), `report.html` (single-file, self-contained --
funnel diagram with the failing stage highlighted, findings grouped by
stage, the answerability matrix, a prioritized action list -- the demo
surface), and `report.md` (a shorter executive summary a non-expert
reads top to bottom in under a minute). Runtime is hard-capped under 5
minutes by `BudgetManager` (`src/brand_audit/crawl.py`), which degrades
gracefully under an ordered ladder and records every degradation in the
report rather than failing silently.

**Stage coverage:** all six funnel stages (① REACH through ⑥ ARRIVE)
detect; `finding-verification` (cross-cutting) falsifies every finding
before it ships -- re-fetch with a different UA, sample-adequacy check,
a narrow contradiction search -- and demotes anything that fails to the
report's `observations` array rather than dropping it silently.
`assemble_report.dedup_findings` merges known same-root-cause pairs
across stages afterward, and `scripts/proactive.py` derives the
beyond-defect `proactive_recommendations` array from measured
answerability gaps and `llms.txt` absence -- recommendations, never
findings, since they describe what is absent rather than what is
broken. A stage that never runs (budget exhausted, an
optional dependency missing) reports `ai_readiness: skipped`, not
`pass`, so the report never implies a check that didn't happen. See
`docs/progress.md` at the repo root for the day-by-day accounting.

## Composition contract

Every stage skill reads a shared run context and writes a `StageResult`
(`findings`, `artifacts`, `corpus_delta`, `metrics`) back to the run
directory. Stages are gated, not independent: `retrieval-simulation`
only ever sees the `corpus_delta` that survived stages ① and ②. Read
`references/composition.md` before adding a new stage.

## References

- `references/report-schema.md` -- the full report contract (generated
  from `src/brand_audit/models.py`; the JSON Schema itself lives at
  `assets/report_schema.json` -- never hand-edit either, edit the models)
- `references/severity-model.md` -- the deterministic `severity =
  f(stage, blast_radius, confidence)` function
- `references/composition.md` -- how stages gate each other
- `references/taxonomy.md` -- the defect rule pack; every finding must
  map to an entry here
