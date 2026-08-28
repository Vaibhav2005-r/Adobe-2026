---
name: retrieval-simulation
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 4 RETRIEVE, the crown-jewel answerability probe -- chunks the AI-reachable corpus, indexes it with hand-rolled BM25, expands a deterministic buyer-intent query set, and classifies each query as answerable, partial, ungrounded, or unretrievable. Also runs orphan-fact and chunk-boundary analysis.
metadata:
  role: stage
  stage: retrieve
---

# retrieval-simulation -- Stage ④ RETRIEVE (crown jewel)

Answers: **can a machine answer the questions a buyer would ask, using
only what it can actually reach and read?** Not "does this page have
good content" -- an outcome-anchored, reproducible probe.

## Pipeline

1. Derive the brand's entity + category from the site itself (JSON-LD
   `Organization`, title, H1, nav).
2. Expand a deterministic query set from a bundled template bank -- 6
   intent classes (identity, pricing, comparison, capability/spec,
   trust/proof, contact/logistics) x the detected vertical.
3. Chunk **only the AI-reachable corpus** (the stage ①/② survivors),
   400-600 tokens with overlap, boilerplate-stripped, provenance-tracked
   back to URL + DOM position.
4. Retrieve with hand-rolled BM25 (deterministic, zero model weights, no
   API key -- see `pyproject.toml` and the stack rationale in
   `docs/build-plan.md` Part 4). A pluggable `Retriever` interface
   leaves room for an embedding backend if an API key is ever present.
5. Classify each query: `ANSWERABLE` / `PARTIAL` / `UNGROUNDED` /
   `UNRETRIEVABLE`.

Orphan-fact detection (a fact's subject and value land in different
chunks) and boilerplate-ratio analysis are Day 6 work, not yet
implemented -- see Status below.

Field research already surfaced a genre-specific citation-displacement
pattern worth probing for here in a later pass: three well-optimized
SaaS pricing pages went 0-for-24 on brand-domain live citations against
third-party comparison content, despite the facts being extractable --
see `TRUST-001` in `references/taxonomy.md` at the orchestrator.
Whether that shows up as an `UNGROUNDED`/`UNRETRIEVABLE` outcome here or
is purely a stage ⑤ CITE phenomenon is still an open question.

## Input / output contract

Consumes the stage ① REACH survivors, minus any page stage ② RENDER
proved is an empty JS-only shell (a `RENDER-001` finding at `critical`
severity) -- not gated on stage ②'s own `corpus_delta` directly, since
that's bounded by `--max-render-pages` for performance and a page RENDER
never got to check isn't the same as one it proved empty; see
`ai-visibility-orchestrator/scripts/run_audit.py::run_retrieve_stage`
for the exact logic and `references/composition.md` for the reasoning.
Writes a `StageResult` with `stage: retrieve`, a single aggregate
`CHUNK-001` finding when >=25% of the 18 queries are unanswerable (never
one finding per query), and the full `answerability_matrix` passed
through to the report's top level.

## Status

Implemented in `scripts/retrieve_detect.py`, with chunking (`Chunk`,
`chunk_page`) and BM25 (`BM25Retriever`, the `Retriever` protocol) in
`src/brand_audit/chunk.py` / `retrieval.py` since both are generic,
reusable primitives, not retrieval-simulation-specific. The Day 5 DoD --
"given a fixture site, produces a reproducible answerability matrix. Two
runs, byte-identical output" -- is an executable test
(`tests/test_retrieve_stage.py`), verified against
`tests/fixtures/retrieval-answerable`, a fixture built so some intents
(identity/pricing/contact) come back genuinely answerable and others
(comparison/trust) come back honestly ungrounded, rather than uniformly
one or the other. Not implemented yet: orphan-fact detection,
cross-page-join detection, boilerplate-ratio scoring (all Day 6), and
"entity" as a fact type (regex-based NER would be too noisy -- see
`render-gap-audit`'s equivalent note). See `docs/progress.md` for the
full accounting, including a cluster of real bugs this stage's build
surfaced and fixed -- several in code that had already shipped on
earlier days.
