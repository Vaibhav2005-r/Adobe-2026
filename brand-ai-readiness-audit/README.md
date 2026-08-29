# Brand AI Readiness Audit

> Every other submission scores your website against a checklist. Ours
> reproduces the pipeline an AI assistant actually runs -- reach, render,
> extract, retrieve, cite, arrive -- tells you the exact stage where your
> brand falls out, proves it with the two extractions side by side, and
> then tries to prove itself wrong before it reports anything.

A Claude Skills marketplace that audits a website's visibility to AI
assistants (ChatGPT, Claude, Perplexity, and the rest). Deterministic,
read-only, robots-respecting, and runs on a bare machine in under five
minutes.

## Quickstart

```bash
pip install -e .
python skills/ai-visibility-orchestrator/scripts/run_audit.py example.com
```

Writes `runs/example.com/report.json` (the schema-valid contract),
`report.html` (a single-file, self-contained report -- open it directly
in a browser), and `report.md` (a short executive summary). Runtime is
hard-capped under five minutes, with a degradation ladder that's
recorded in the report, never silent.

Optional: `pip install -e ".[render,tokenize]"` adds Playwright (stage ②
RENDER's dual-fetch differential) and `tiktoken` (exact chunk-token
counts). Both are gracefully skipped, not guessed at, when absent --
see [Limitations](#limitations).

A real report, committed and ready to open: [`sample-report/`](sample-report/)
(allbirds.com, `report.html` is the one to open in a browser).

```bash
python -m pytest tests/ -v                    # 161 tests, no network needed
python scripts/eval_fixtures.py                # fixture confusion matrix
```

## The thesis

An AI assistant answering a buyer's question runs a funnel. Every stage
can drop the brand, and each stage failing produces a *different fix*:

```
① REACH     Can a bot fetch it?          robots.txt, status codes, WAF, sitemap
② RENDER    Can it read it without JS?   HTML-only vs. headless-rendered diff
③ EXTRACT   Can it isolate the fact?     semantic HTML, JSON-LD, image-locked facts
④ RETRIEVE  Does the chunk survive?      chunk boundaries, orphan facts, boilerplate
⑤ CITE      Is it quotable & trusted?    entity anchoring, freshness, attribution
⑥ ARRIVE    Does the visitor stay?       answer proximity, orientation, next step
```

A checklist tool scores signals ("you're missing FAQPage schema").
This audit **localizes failures**: the unit of output isn't a score,
it's *"the query 'X pricing' dies at stage ②: the price string exists
only in the rendered DOM; here is the exact HTML-only extraction
proving it, and here are the three lines of SSR that fix it."* Every
finding carries a `taxonomy_id`, a stated mechanism (not a symptom),
and at least one machine-checkable artifact -- enforced at the Pydantic
model level (`Finding.artifacts` requires ≥1 entry). No artifact, no
finding.

## Composition: eight skills, one pipeline

```
marketplace.json                    exactly one entrypoint
skills/
  ai-visibility-orchestrator/       ENTRYPOINT -- budget, report assembly, HTML/MD render
  crawl-reach-audit/                ① REACH
  render-gap-audit/                 ② RENDER  -- the dual-fetch differential
  extractability-audit/             ③ EXTRACT
  retrieval-simulation/             ④ RETRIEVE -- the answerability probe (crown jewel)
  trust-corroboration-audit/        ⑤ CITE
  arrival-engagement-audit/         ⑥ ARRIVE
  finding-verification/             cross-cutting falsification pass
src/brand_audit/                    shared models, crawl core, chunking, BM25 -- imported by every skill above
scripts/eval_fixtures.py            maintainer eval harness (not a shipped skill)
```

This isn't eight topical sections that could just as easily be one
report -- it's a pipeline where each stage reads a shared `run_context`
and writes a `StageResult{findings, artifacts, corpus_delta, metrics}`,
and later stages only ever see what survived the stages before them.
Concretely: `retrieval-simulation` never reads the raw crawl -- it only
sees the corpus that survived REACH and RENDER, minus any page RENDER
proved is an empty JS-only shell. `arrival-engagement-audit` goes one
step further and only audits the pages that actually *won* a
buyer-intent query in stage ④'s own answerability matrix, not a
re-derived guess at "pages likely to be cited."

The payoff: the same missing fact produces a *structurally different*
finding depending on where it actually died. Missing because
`robots.txt` blocks the page? `REACH-00x` -- fix infrastructure. Missing
because it only renders after JS? `RENDER-001` -- fix delivery. Present
in the raw HTML but its subject and value land in different retrieval
chunks? `CHUNK-00x` -- fix information architecture. One root cause,
three different findings, three different fixes -- because the gating
forces it. See
[`references/composition.md`](skills/ai-visibility-orchestrator/references/composition.md)
for the full contract, including the one cross-stage merge rule that
exists precisely because two stages can legitimately describe the same
root cause (`REACH-002`/`ENGAGE-003`, a redirect that's both a
crawler-fetch problem and an arrival-experience problem).

## Deterministic, not LLM-driven

The build plan's own tech-stack section reserved two schema-constrained
LLM touchpoints (answerability classification, suggested-action prose)
with deterministic fallbacks. In the actual implementation, **neither
touchpoint uses an LLM call at all** -- answerability classification is
a hand-rolled BM25 retriever plus a term-coverage threshold
(`src/brand_audit/retrieval.py`, ~120 lines, zero model weights), and
suggested-action prose is written directly by each detector from the
concrete facts it found, not generated. There is no API key anywhere in
this codebase (`grep -rn "api_key\|anthropic\.\|openai\." src/ skills/`
returns nothing but two crawler User-Agent strings). This wasn't a
fallback path taken because something else failed -- it was simpler and
strictly better for this project's own hard constraints (deterministic,
portable, no bundled weights, no network dependency beyond the audited
site itself) to just not need one for a task this well-suited to
lexical matching. Every finding, every severity, and every action in
this report is produced by code you can read start to finish.

## Evaluation

Published confusion matrix (`python scripts/eval_fixtures.py`), against
8 fixtures (2 known-defect cases, 5 clean controls, 1 scored separately
-- see below):

| Metric | Value |
|---|---|
| Precision | **1.00** (2/2 flagged findings were real) |
| Recall (on the fixtures' own known-positive cases) | **1.00** (2/2) |
| False-positive rate on clean controls | **0.00** (0/9 certified-clean-stage checks produced a finding) |

`retrieval-answerable` is scored separately (per-query answerability
outcome, not a finding/taxonomy_id): **11/12 (92%)** correct. The one
miss is a known, accepted property of a lexical-only retriever, not a
bug -- see Limitations.

**Wild-corpus sweep**, run through the real, current pipeline (not just
hand-diagnosed, as Day 1's original 12-site field research was): a
Shopify store, a static docs site, a SaaS marketing/legal site, a
single-page portfolio, a news publisher, and a non-English retail
site. Every finding was spot-checked by hand for plausibility, not just
"the process didn't crash." The sweep found and fixed two real bugs
before this evaluation number was final: a false positive (`REACH-001`
flagging an ordinary `User-agent: *` page exclusion as if it were
AI-specific discrimination) and a crash (a `Finding` constructed with
zero artifacts when an entire crawl came back empty). Full accounting,
including what was tried and reverted, in
[`docs/progress.md`](../docs/progress.md)'s Day 9 entry.

## Limitations, stated honestly

- **No live name-collision search.** The build plan's own cut list names
  this first-to-cut if behind schedule; it's also a real conflict with
  this project's determinism and portability constraints (a live web
  search returns different results over time and needs network access
  a judge's bare machine can't be assumed to have). On-site entity
  anchoring (`sameAs` in JSON-LD) is implemented instead.
- **No real NER.** "Entity" as a fact type (build plan Part 4) isn't
  implemented -- a real named-entity extractor needs model weights,
  which this project's own constraints rule out, and a regex heuristic
  would be too noisy to hold the "few false positives" bar. Four of the
  five named fact types (currency, numeric, date, contact) are
  implemented.
- **`finding-verification`'s contradiction search covers one taxonomy
  family.** Only `EXTRACT-002` (missing JSON-LD properties) is checked
  against a contradicting microdata/RDFa signal. A generic "does some
  alternate signal carry the same fact" check isn't well-defined enough
  across mechanisms as different as a redirect and a staleness date to
  build honestly within the project's timeline.
- **No re-derivation against a second, independent page sample.**
  Verification re-fetches each finding's own artifact URL to confirm it
  still resolves; it doesn't re-run a detector's full logic against
  fresh pages to independently reproduce the underlying *pattern*. That
  would need a per-taxonomy_id dispatch table this project didn't build.
- **`ENGAGE-001`/`ENGAGE-003`/`ENGAGE-007` are unit-tested but not yet
  observed firing on a live site** in this project's own wild-corpus
  sweeps -- the mechanisms (buried answers, context-reset redirects,
  slow citable pages) are real and covered by fixtures, but haven't yet
  had a field-verified example the way `REACH-007` or `TRUST-001` have.
- **Description drift (`TRUST-007`) checks three of five named fields**
  (meta description, JSON-LD, OpenGraph) -- `<title>` and footer
  consistency aren't included yet.
- **Playwright is optional, by design** -- if it's not installed, stage
  ② RENDER is skipped and every `RENDER-*` finding is suppressed, not
  guessed at. A judge on a bare machine with no Playwright still gets a
  complete, honest report for the other five stages; the report's own
  `degradations` array says exactly what didn't run and why.
- **The wild-corpus sweep never included a WordPress-powered local
  business site**, one of the shapes the build plan explicitly names.
  Not chased further given the rest of the diversity already covered
  (SaaS, Shopify, docs, portfolio, news, non-English) and higher-value
  uses of the remaining time (two real bugs, found and fixed).
- **The lexical-only retriever misses semantically-equivalent, lexically
  -different phrasing.** A query asking about "customer support" against
  a page that only says "reach us" won't hit the coverage threshold --
  this is the deliberate, accepted tradeoff of using BM25 (deterministic,
  no model weights, no API key) instead of an embedding-based retriever.
  Confirmed directly on Day 9: rewording the query template to a
  different synonym set didn't fix this, it just relocated the same
  miss to a different query on the same fixture -- a real, structural
  property of lexical matching, not a fixable bug.

## Structure

```
marketplace.json              one entrypoint: ai-visibility-orchestrator
LICENSE                        MIT
skills/                        the 8 skills (see Composition above)
src/brand_audit/                shared Pydantic models, crawl core, chunking, BM25, severity function
scripts/eval_fixtures.py        maintainer eval harness -- not a shipped skill
tests/                          161 tests + local fixture sites (no live network needed)
docs/build-plan.md              the full 10-day plan this was built against
docs/progress.md                the honest day-by-day accounting, including every bug found and fixed
```

See `skills/ai-visibility-orchestrator/SKILL.md` for the full CLI and
the composition contract in more detail; every skill's own `SKILL.md`
documents its detectors, input/output contract, and current status.
