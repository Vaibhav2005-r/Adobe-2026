---
name: ai-visibility-orchestrator
description: Audits how visible a website is to AI assistants (ChatGPT, Claude, Perplexity, etc.) by simulating the retrieval pipeline they actually run -- reach, render, extract, retrieve, cite, arrive -- and reporting the exact stage where the brand falls out, with artifact-backed evidence for every finding. Use this when the user asks to audit a site's AI/LLM visibility, GEO/AEO readiness, or why a brand isn't being cited by AI assistants.
license: MIT
allowed-tools: Bash, Read, Write
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

## When to use

Use this skill when the user wants to know why a brand is missing,
misrepresented, or ignored by AI assistants, or why visitors who arrive
from one don't engage -- "audit this site's AI visibility", "why isn't
ChatGPT citing us", "is our site AI-readable", "GEO/AEO audit". It is
the only skill in this marketplace meant to be invoked directly.

Do not use it to change anything. This marketplace is recommend-only:
it fetches, reads, and reports. No skill in it writes to the audited
site, authenticates, or performs any action beyond a polite,
robots-respecting read.

## Inputs

A single website: a bare domain (`example.com`) or a full URL
(`https://example.com`). Nothing else is required -- no API key, no
credentials, no site access. Optional flags bound the run:
`--max-pages N` (default 40), `--budget-s N` (default 300),
`--skip-render` (skip stage ② when Playwright isn't installed), and
`--out PATH`.

## Procedure

```
python scripts/run_audit.py <site> [--max-pages 40] [--out report.json]
```

1. **Discover and sample.** Fetch `robots.txt`, discover the sitemap,
   and take a deterministic stratified sample (fixed seed derived from
   the domain, so the same site always yields the same page set).
2. **Run the six funnel stages in order**, each gated on the corpus
   that survived the ones before it: ① `crawl-reach-audit`,
   ② `render-gap-audit`, ③ `extractability-audit`,
   ④ `retrieval-simulation`, ⑤ `trust-corroboration-audit`,
   ⑥ `arrival-engagement-audit`.
3. **Falsify.** `finding-verification` runs across every stage's
   findings and tries to disprove each one before it ships.
4. **Merge.** Collapse same-root-cause findings across stages, and
   collapse per-page findings of one defect into a single
   corpus-scoped finding.
5. **Derive proactive recommendations** from measured answerability
   gaps -- the beyond-defect layer.
6. **Assemble and validate** one `AuditReport`, then write it out.

Every step is deterministic: the same site produces the same report,
modulo `audited_at`.

## Output

Three files, all rendered from one validated `AuditReport` (see
`assets/report_schema.json`): **`report.json`** (the schema-valid
contract -- the source of truth, carrying `site`, `audited_at`, a
counts-by-severity `summary`, and per finding an `id`, `title`,
`severity`, `evidence` and `suggested_action`, plus this project's own
extensions), `report.html` (single-file, self-contained --
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
this project's development log for the day-by-day accounting.

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
