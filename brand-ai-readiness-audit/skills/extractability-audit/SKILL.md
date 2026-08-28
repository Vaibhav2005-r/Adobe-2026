---
name: extractability-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 3 EXTRACT -- can a fact be isolated from the page -- via structured-data parsing and validation, schema-vs-visible-text contradiction detection, semantic HTML integrity, and facts-locked-in-images detection.
metadata:
  role: stage
  stage: extract
---

# extractability-audit -- Stage ③ EXTRACT

Answers: **can it isolate the fact?** A page can be fully reachable and
fully rendered and still fail here if the fact isn't structured in a way
an extractor can pull out cleanly.

## Detects

- `JSON-LD` / microdata / RDFa parsing (`extruct`) and validation
  against a bundled schema.org subset.
- Schema-vs-visible-text contradiction (JSON-LD says `price: 199`, the
  page says `$249` -- a high-value, rarely-checked finding).
- Semantic HTML integrity: heading hierarchy, table/`<dl>` structure.
- Facts locked in images: numeric-looking content only present in
  `alt`-less `<img>`/`<canvas>`/embedded PDFs.

Field research already recorded a **positive control** worth reusing as
a regression check once this stage exists: a Shopify product page whose
complete `ProductGroup`/`Offer` JSON-LD (price, currency, availability,
rating) is present in the raw non-JS HTML -- see the Controls section
of `references/taxonomy.md` at the orchestrator.

## Input / output contract

Reads `corpus_delta` from `render-gap-audit` (or `crawl-reach-audit`
directly if stage ② was skipped -- see `references/composition.md`).
Writes a `StageResult` with `stage: extract`.

## Status

Not yet implemented -- see `docs/progress.md` at the repo root.
