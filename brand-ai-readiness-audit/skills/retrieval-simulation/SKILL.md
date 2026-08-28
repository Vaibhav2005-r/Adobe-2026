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

Also runs orphan-fact detection (a fact's subject and value land in
different chunks, so the chunk that has the price never says what it
prices) and chunk-boundary / boilerplate-ratio analysis.

Field research already surfaced a genre-specific citation-displacement
pattern worth probing for here once real retrieval exists: three
well-optimized SaaS pricing pages went 0-for-24 on brand-domain live
citations against third-party comparison content, despite the facts
being extractable -- see `TRUST-001` in `references/taxonomy.md` at the
orchestrator. Whether that shows up as an `UNGROUNDED`/`UNRETRIEVABLE`
outcome here or is purely a stage ⑤ CITE phenomenon is an open question
for when this stage is built.

## Input / output contract

Consumes **only** the `corpus_delta` gated through stages ① and ②
(never the raw crawl -- this is the composition story, see
`references/composition.md`). Writes a `StageResult` with `stage:
retrieve` plus the `answerability_matrix` entries that feed the report's
top-level summary.

## Status

Not yet implemented -- see `docs/progress.md` at the repo root.
