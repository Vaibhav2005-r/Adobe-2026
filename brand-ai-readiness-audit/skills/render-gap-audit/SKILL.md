---
name: render-gap-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 2 RENDER -- the dual-fetch differential -- fetching each page twice (plain HTTP GET vs. headless-rendered) and diffing at the fact level to find content that only exists after JavaScript execution.
metadata:
  role: stage
  stage: render
---

# render-gap-audit -- Stage ② RENDER

Answers: **can it read it without JS?** The highest-ROI mechanism in this
audit -- major AI crawlers are documented as executing JavaScript
inconsistently or not at all, so a page that passes every SEO check can
still be blank to an AI fetcher.

## Detects

- Fact-level (not character-level) delta between a plain HTTP GET and a
  headless-Chromium render of the same URL, classified by fact type
  (numeric/currency/date/entity/contact), noise-suppressed (nav,
  timestamps, CSRF tokens, personalization).
- Non-text facts locked in images/canvas/embedded PDFs.
- Interaction-gated content (facts that only appear after a click, e.g.
  behind a tab or accordion).

Confirmed via field research: an empty `<div id="app">`/`<div
id="root">` root container in the raw HTTP response, with all content
injected by JS, is the textbook pattern -- see `RENDER-001` in
`references/taxonomy.md` at the orchestrator for two real, evidence-complete
examples (a JS-only docs generator, a DeFi trading app shell) including the
citation consequence: the render gap didn't just hide content, it handed
the citation to a different domain entirely.

## Input / output contract

Reads `corpus_delta` from `crawl-reach-audit` (only pages that survived
stage ① are dual-fetched -- this is the composition gating in
`references/composition.md`). Writes a `StageResult` with `stage:
render`; `corpus_delta` passes through only the facts confirmed present
in the non-JS fetch.

## Optional dependency

Uses `playwright` (chromium, headless) for the rendered half of the
diff. If unavailable, this stage is **skipped entirely** and every
RENDER finding is suppressed -- never guessed at -- with the skip
recorded in `run_manifest.degradations`.

## Status

Implemented in `scripts/render_detect.py`: fact-level diff (currency,
numeric, date, contact -- "entity" extraction deliberately left out
rather than faked with a noisy heuristic, since a real NER model would
itself need weights the project's constraints rule out), noise
suppression (today's date, hex/CSRF-looking tokens), and the primary
empty-shell signal that matches the two field-verified `RENDER-001`
cases exactly. Confirmed against `tests/fixtures/js-only-price` (flags
correctly) and `tests/fixtures/clean-control` (stays silent) -- see
`tests/test_render_gap.py`, which is the Day 3 DoD as an executable
test.
