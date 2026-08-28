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

This crawls the site (robots-respecting, read-only), runs whichever
stages are wired up, and writes a schema-valid `AuditReport` (see
`assets/report_schema.json`). Runtime is hard-capped under 5 minutes by
`BudgetManager` (`src/brand_audit/crawl.py`), which degrades gracefully
under an ordered ladder and records every degradation in the report
rather than failing silently.

**Current stage coverage:** ① REACH only (crawl core: robots/AI-UA
policy, sitemap discovery, deterministic sampling, fetch). Stages ②-⑥ are
not wired up yet -- their `ai_readiness` field reports `skipped`, not
`pass`, so the report never implies a check that didn't happen. See
`docs/progress.md` at the repo root for what's done and what's next.

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
