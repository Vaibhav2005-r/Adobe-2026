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

- **`EXTRACT-001`** Schema-vs-visible-text contradiction: JSON-LD claims
  one price, the page's visible text shows another. Both sides are
  normalized to a comparable float before comparing -- `"199"` vs.
  `"$199.00"` is the same fact differently formatted, not a
  contradiction.
- **`EXTRACT-002`** Structured data missing properties its own declared
  `@type` requires, checked against a bundled offline schema.org subset
  (`assets/schema-subset.json`).
- **`EXTRACT-003`** Heading hierarchy integrity: zero/multiple `<h1>`,
  or a heading-level skip.
- **`EXTRACT-004`** Numeric-looking facts locked in `alt`-less images,
  narrowly scoped to filenames suggesting fact-bearing content (price
  charts, spec tables) -- not every alt-less image, which would just be
  generic-checklist noise (most alt-less images are decorative).

Not yet implemented: microdata/RDFa contradiction checks (JSON-LD only
for now -- `extruct` parses all three, but the contradiction/
required-property detectors only walk the `json-ld` result), table/`<dl>`
structure checks, and canvas/PDF fact detection (image-filename heuristic
only). See `docs/progress.md` for the honest accounting.

Field research already recorded a **positive control** reused as this
stage's regression check: a Shopify product page whose complete
`ProductGroup`/`Offer` JSON-LD (price, currency, availability, rating)
is present in the raw non-JS HTML -- see the Controls section of
`references/taxonomy.md` at the orchestrator, and
`tests/fixtures/schema-clean-product/` for the synthetic version used in
CI.

## Input / output contract

Reads `corpus_delta` from `crawl-reach-audit` (the raw HTML of every
stage-① survivor) directly, not gated through `render-gap-audit`'s
`corpus_delta`: JSON-LD is overwhelmingly server-rendered even on
otherwise JS-heavy sites, and a page `render-gap-audit` already flagged
as an empty shell simply has nothing for these checks to find either
way -- harmless, not a false negative, since `RENDER-001` already
reported the more fundamental problem for that page. Writes a
`StageResult` with `stage: extract`.

## Status

Implemented in `scripts/extract_detect.py`. All four detectors are
unit-tested against synthetic HTML plus two end-to-end fixtures
(`tests/fixtures/schema-contradiction`, `tests/fixtures/schema-clean-product`)
that are the Day 4 DoD as an executable test: the contradiction detector
flags the defect fixture and stays silent on the clean one.
