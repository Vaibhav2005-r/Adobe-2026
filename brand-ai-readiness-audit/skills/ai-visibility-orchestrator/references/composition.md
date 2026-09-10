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

## The falsification pass and dedup -- one more link in the same chain

`finding-verification` (cross-cutting) runs once, after all six stages'
detection is done, over the flat list of every finding any stage
produced. It's the same composition pattern one level up: instead of
gating *what a stage can see*, it gates *what a finding is allowed to
claim* -- re-fetching each finding's own artifact URL to check it still
resolves, checking whether the claimed severity is actually supported
by how much of the corpus was sampled, and (narrowly, for `EXTRACT-002`)
checking for a contradicting signal. Anything that fails ships as an
`observation`, not a `finding` -- visible, never silently dropped.

`assemble_report.dedup_findings` runs after that, inside
`assemble_report.py` itself: an exact-duplicate safety net, plus a
small, explicit table of known same-root-cause cross-stage pairs
(currently just `REACH-002`/`ENGAGE-003` -- a redirect that loses a
deep link's specificity is both a crawler-fetch problem and an arrival-
experience problem, and should ship as one finding, not two pointing at
two different fixes). The merge always keeps the *earlier* funnel-stage
finding as primary, regardless of severity -- consistent with this
whole document's thesis: the earlier stage's framing is the root cause,
the later stage's is the symptom.

A third pass, `_aggregate_per_page_findings`, then collapses the
*within*-stage case: the same defect found on many pages becomes one
finding scoped across the corpus. Several detectors run per page and
emit per page, which is the right shape for detection and the wrong
shape for a report -- auditing thesouledstore.com produced 26 separate
`EXTRACT-002` findings, one per page, each reading `checked: 1,
affected: 1` and each carrying the identical suggested action, so the
prioritized action list was fourteen consecutive copies of the same
sentence for a single site-wide template defect. Twenty-six findings
claiming `checked: 1` also never add up to the site-wide problem they
are, which starves both the severity function and the sample-adequacy
check of real scope.

Findings are grouped by the *fix* -- stage, taxonomy id, severity,
confidence, and the exact `suggested_action` summary and implementation
steps. That criterion is deliberately reader-facing (two findings that
resolve to identical work are one item to the person acting on the
report) and conservative in the right direction: because
`implementation` is part of the key, `EXTRACT-002` missing `name` never
merges with `EXTRACT-002` missing `logo`, since their implementation
lines name the property. Only groups whose members all report
`checked == 1` are merged, so a detector that already computed a real
corpus-level scope (`RENDER-001`, `TRUST-005`, `TRUST-006`,
`TRUST-008`, `ENGAGE-004`, `ENGAGE-005`) is left alone rather than
having a measured denominator overwritten by a guess. The merged
`checked` comes from the stage's own `pages_examined` metric, so 26 of
40 reads as 26 of 40 rather than as 26 of 26.

## Pipeline order and current status

```
① crawl-reach-audit         (implemented: crawl core + 6 detectors)
② render-gap-audit          (implemented: dual-fetch differential)
③ extractability-audit      (implemented: 4 detectors)
④ retrieval-simulation      (implemented: chunking, BM25, answerability matrix, orphan-fact/cross-page-join/boilerplate)
⑤ trust-corroboration-audit (implemented: entity anchoring, staleness, description drift, attribution density)
⑥ arrival-engagement-audit  (implemented: answer proximity, orientation, context reset, entry interference, next-step, AI-referral instrumentation, scoped latency)
✗ finding-verification      (implemented: re-fetch/reproduction, sample-adequacy, EXTRACT-002 contradiction search, demotion to observations)
```

After assembly, `scripts/proactive.py` derives the beyond-defect layer
from measured output only -- the answerability matrix stage (4) produced
and the `llms.txt` presence stage (1) recorded. It emits
`ProactiveRecommendation`s, never `Finding`s, because these describe
what is *absent* and absence carries no artifact -- the "no artifact, no
finding" rule would otherwise have to be bent to accommodate them.

`ai-visibility-orchestrator/scripts/run_audit.py` owns the time budget
(`src/brand_audit/crawl.py::BudgetManager`), the degradation policy, and
final report assembly (`scripts/assemble_report.py`), which also emits
the single-file HTML report (`scripts/render_html.py`) and the Markdown
executive summary (`scripts/render_markdown.py`) from the same
validated `AuditReport`. See this project's development log for
what's implemented vs. planned.
