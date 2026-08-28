# Composition contract

This is the answer to "is the eight-skill split genuine or padding?" --
it isn't topical (six audit categories that could just as easily be
sections in one report); it's a **pipeline**, where each skill owns one
funnel stage, has one input contract, one output contract, and is
independently runnable and testable against that contract.

## The contract every stage skill implements

```
StageResult(
    stage: Stage,               # which funnel stage this is
    findings: list[Finding],    # artifact-backed, taxonomy-mapped
    artifacts: list[Artifact],
    corpus_delta: list[str],    # URLs this stage adds to / removes from
                                 # the AI-reachable corpus
    metrics: dict,               # stage-specific counters
)
```

Defined in `src/brand_audit/models.py`. A stage skill reads the run
context (site, budget remaining, sample seed, and the upstream
`corpus_delta`) and writes one `StageResult`.

## The gating -- why this is genuine composition, not padding

`retrieval-simulation` (stage ④) **only ever sees the stage ① REACH
survivors, minus any page stage ② RENDER proved is an empty JS-only
shell.** It never reads the raw crawl. (Implementation note: this is
gated on REACH's `corpus_delta` with RENDER-proven-empty pages removed,
not literally RENDER's own `corpus_delta` -- RENDER only dual-fetches a
bounded sample, `--max-render-pages`, for runtime-budget reasons, and a
page RENDER never got to check isn't the same as one it proved empty.
Narrowing to RENDER's sampled subset would shrink the corpus based on a
performance artifact instead of an actual gating failure. See
`ai-visibility-orchestrator/scripts/run_audit.py::run_retrieve_stage`.)
This is deliberate and it's the whole point: the same missing fact
produces a *different* finding depending on where in the funnel it
actually died --

- If a fact is missing because `robots.txt` blocks the page entirely,
  that's a `crawl-reach-audit` finding (`REACH-00x`) -- the fact never
  entered the corpus at all, so `retrieval-simulation` never sees the
  page and can't produce a chunk-level finding about it.
- If the same fact is missing because it only renders after JS
  execution, that's a `render-gap-audit` finding (`RENDER-00x`) -- the
  page *is* in the corpus, but the fact isn't, so a query about it comes
  back `UNGROUNDED` rather than `UNRETRIEVABLE`.
- If the fact is present in both the raw HTML and the render, but its
  subject and value land in different retrieval chunks, that's a
  `retrieval-simulation` finding (`CHUNK-00x`) -- reachable, rendered,
  extractable, and *still* unretrievable because of chunk boundaries.

One root cause, three structurally different findings, each pointing at
a different fix -- because the gating forces each stage to only ever see
what actually survived the stage before it. Breaking this (e.g. letting
`retrieval-simulation` read the raw crawl "just to be safe") would
collapse this distinction and turn the marketplace back into a flat
checklist.

`arrival-engagement-audit` (stage ⑥) extends the same pattern one stage
further: it audits the `citable=True` pages from stage ④'s own
answerability_matrix -- the literal set of pages that actually won a
buyer-intent query -- not a re-derived guess at "pages likely to be
cited." A page a search-engine crawler would treat as important but
that never surfaced an answer to any simulated query is invisible to
this stage, which is correct: it isn't a page an AI-referred visitor
would actually land on. (See
`ai-visibility-orchestrator/scripts/run_audit.py::run_arrive_stage`.)

## Pipeline order and current status

```
① crawl-reach-audit        (implemented: crawl core + 6 detectors)
② render-gap-audit         (implemented: dual-fetch differential)
③ extractability-audit     (implemented: 4 detectors)
④ retrieval-simulation     (implemented: chunking, BM25, answerability matrix, orphan-fact/cross-page-join/boilerplate)
⑤ trust-corroboration-audit (implemented: entity anchoring, staleness, description drift, attribution density)
⑥ arrival-engagement-audit (implemented: answer proximity, orientation, context reset, entry interference, next-step, AI-referral instrumentation, scoped latency)
✗ finding-verification     (cross-cutting, runs after ①-⑥, not yet wired up)
```

`ai-visibility-orchestrator/scripts/run_audit.py` owns the time budget
(`src/brand_audit/crawl.py::BudgetManager`), the degradation policy, and
final report assembly (`scripts/assemble_report.py`). See
`docs/progress.md` at the repo root for what's implemented vs. planned.
