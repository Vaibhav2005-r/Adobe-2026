---
name: retrieval-simulation
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 4 RETRIEVE, the crown-jewel answerability probe -- chunks the AI-reachable corpus, indexes it with hand-rolled BM25, expands a deterministic buyer-intent query set, and classifies each query as answerable, partial, ungrounded, or unretrievable. Also runs orphan-fact and chunk-boundary analysis.
license: MIT
allowed-tools: Bash, Read
metadata:
  role: stage
  stage: retrieve
---

# retrieval-simulation -- Stage ④ RETRIEVE (crown jewel)

Answers: **can a machine answer the questions a buyer would ask, using
only what it can actually reach and read?** Not "does this page have
good content" -- an outcome-anchored, reproducible probe.

## When to use

Not directly. This skill is an internal pipeline stage of the
`brand-ai-readiness-audit` marketplace, owning stage ④ RETRIEVE -- *does the
chunk carrying the fact survive retrieval?*
`ai-visibility-orchestrator` is the marketplace's single entrypoint and
drives this stage as one step of its own procedure, handing it the corpus
that survived the stages before it. Invoking it on its own gives you one
stage's `StageResult`, not an audit report.

Read-only and recommend-only, like every skill here: it fetches and reads,
and never writes to, authenticates against, or otherwise alters the audited
site.

## Procedure

1. Derive the brand's entity + category from the site itself: JSON-LD
   `Organization` first, then the homepage's own `<title>`/`<h1>`, then
   (Day 7) a domain-derived name as the last-resort floor -- not a
   guess from some other sampled page's title, which a real Day 7 wild-
   corpus check found could be hijacked by an unrelated page (see
   Status).
2. Expand a deterministic query set from a bundled template bank -- 6
   intent classes (identity, pricing, comparison, capability/spec,
   trust/proof, contact/logistics) x the detected vertical.
3. Chunk **only the AI-reachable corpus** (the stage ①/② survivors),
   400-600 tokens with overlap, boilerplate-stripped, provenance-tracked
   back to URL + DOM position.
4. Retrieve with hand-rolled BM25 (deterministic, zero model weights, no
   API key -- see `pyproject.toml` and the stack rationale in
   the project's build plan, Part 4). A pluggable `Retriever` interface
   leaves room for an embedding backend if an API key is ever present.
5. Classify each query: `ANSWERABLE` / `PARTIAL` / `UNGROUNDED` /
   `UNRETRIEVABLE`.

Also runs, as of Day 6: orphan-fact detection (`CHUNK-002` -- a fact's
subject and value land in the same chunk or they don't), cross-page-join
reliance (`CHUNK-003` -- a `PARTIAL` answer that only resolves by
combining chunks from different pages, not just different sections of
one page), and boilerplate-ratio scoring (`CHUNK-004`).

Field research already surfaced a genre-specific citation-displacement
pattern worth probing for here in a later pass: three well-optimized
SaaS pricing pages went 0-for-24 on brand-domain live citations against
third-party comparison content, despite the facts being extractable --
see `TRUST-001` in `references/taxonomy.md` at the orchestrator.
Whether that shows up as an `UNGROUNDED`/`UNRETRIEVABLE` outcome here or
is purely a stage ⑤ CITE phenomenon is still an open question.

## Inputs

Consumes the stage ① REACH survivors, minus any page stage ② RENDER
proved is an empty JS-only shell (a `RENDER-001` finding at `critical`
severity) -- not gated on stage ②'s own `corpus_delta` directly, since
that's bounded by `--max-render-pages` for performance and a page RENDER
never got to check isn't the same as one it proved empty; see
`ai-visibility-orchestrator/scripts/run_audit.py::run_retrieve_stage`
for the exact logic and `references/composition.md` for the reasoning.

## Output

Writes a `StageResult` with `stage: retrieve`, a single aggregate
`CHUNK-001` finding when >=25% of the 18 queries are unanswerable (never
one finding per query), and the full `answerability_matrix` passed
through to the report's top level.

## Language scope

The query bank and the BM25 stopword list are English. When the caller
reports that the corpus declares a language they don't cover, it passes
`probe_enabled=False`: entity detection still runs (it reads a JSON-LD
`name`, a `<title>` and an `<h1>`, none of which depend on the query
bank, and stage 6 needs the entity name), and the probe stops there --
no queries, no matrix, no findings. The orchestrator then reports this
stage `skipped` and records a degradation naming the language.

This is not defensive coding. A deliberately well-built German fixture
(`tests/fixtures/non-english`) scored 15 of 18 queries unanswerable, with
a pricing page whose own sentence reads `Der Bergquell A1
Aktivkohlefilter kostet 149,00 EUR`. Only the three identity queries
passed, and only because a brand name is the one token that survives
translation. Same contract as a missing Playwright in stage 2: skip the
measurement, suppress the findings, record the degradation, never guess.

## Entity detection is homepage-first

Every one of the 18 buyer-intent queries is built from the detected brand
name, so a wrong name does not degrade the probe -- it invalidates it.
Precedence is therefore homepage-first throughout: the homepage's own
JSON-LD `Organization` name, then its `<title>`, then its `<h1>`, then an
`Organization` name from any other sampled page, then a domain-derived
floor.

Two real hijacks motivated that ordering, arriving through different
doors. `allbirds.com` (Day 6) never sampled `/` at all, and falling back
to "whichever sampled page sorts first" landed on a page whose `<title>`
is literally "Design System". `ghost.org` (later) publishes no
`Organization` JSON-LD on its homepage but does on `/resources/`, where it
names itself **"Ghost Resources"** -- so a live audit asked "How much does
Ghost Resources cost?" eighteen times over. Both are legitimate pages
being read as the brand.

## Status

Implemented in `scripts/retrieve_detect.py`, with chunking (`Chunk`,
`chunk_page`), BM25 (`BM25Retriever`, the `Retriever` protocol), and
homepage resolution (`find_homepage_url`, shared with
`trust-corroboration-audit`) in `src/brand_audit/chunk.py` /
`retrieval.py` / `crawl.py` since all three are generic, reusable
primitives, not retrieval-simulation-specific. The Day 5 DoD -- "given a
fixture site, produces a reproducible answerability matrix. Two runs,
byte-identical output" -- is an executable test
(`tests/test_retrieve_stage.py`), verified against
`tests/fixtures/retrieval-answerable`, a fixture built so some intents
(identity/pricing/contact) come back genuinely answerable and others
(comparison/trust) come back honestly ungrounded, rather than uniformly
one or the other. `CHUNK-002`/`003`/`004` (Day 6) are also implemented
and tested, `CHUNK-003` confirmed firing on real sites (stripe.com,
notion.com) during the Day 6 wild-corpus sweep. Not implemented:
"entity" as a fact type (regex-based NER would be too noisy -- see
`render-gap-audit`'s equivalent note). `detect_entity`'s fallback chain
was tightened on Day 7: guessing a brand name from *some other* sampled
page's title/h1 when the homepage itself wasn't in the crawl sample
(the previous behavior) was found -- via the Day 7 wild-corpus sweep of
`arrival-engagement-audit`, not this stage's own tests -- to be
hijackable by an unrelated page (a real allbirds.com crawl sample never
included its own homepage and instead named the site "Design System"
after a legitimate but unrelated page's `<title>`); replaced with a
domain-derived name as the floor. The development log records the full
accounting, including a cluster of real bugs this stage's build
surfaced and fixed -- several in code that had already shipped on
earlier days.
