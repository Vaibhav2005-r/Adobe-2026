# Brand AI Readiness Audit

> Every other submission scores your website against a checklist. Ours
> reproduces the pipeline an AI assistant actually runs -- reach, render,
> extract, retrieve, cite, arrive -- tells you the exact stage where your
> brand falls out, proves it with the two extractions side by side, and
> then tries to prove itself wrong before it reports anything.

An Agent Skills marketplace that audits a website's visibility to AI
assistants (ChatGPT, Claude, Perplexity, and the rest). Deterministic,
read-only, robots-respecting, and runs on a bare machine in under five
minutes.

## The eight skills, and what each one does

`ai-visibility-orchestrator` is the **single entrypoint** — the skill you
invoke. It takes a site, drives the other seven in order, and emits one
validated audit report. The other seven are internal pipeline stages and
are not meant to be invoked directly.

| Skill | Stage | What it does |
|---|---|---|
| **`ai-visibility-orchestrator`** | — | **Entrypoint.** Crawls the site (robots-respecting, deterministic stratified sample), runs the seven skills below, owns the time budget and degradation ladder, merges and de-duplicates their findings, derives the proactive recommendations, and writes the single report as JSON + HTML + Markdown. |
| `crawl-reach-audit` | ① REACH | Can a bot fetch the site at all? Probes `robots.txt` with each named AI crawler UA, detects status/soft-404s, canonical breakage, WAF and bot-challenge interstitials, and sitemap health. |
| `render-gap-audit` | ② RENDER | Can it be read without JavaScript? Fetches each page twice — plain HTTP vs. headless Chromium — and diffs at the *fact* level to find prices, dates and contact details that exist only after JS runs. |
| `extractability-audit` | ③ EXTRACT | Can a specific fact be isolated? Parses and validates JSON-LD/microdata, catches structured data that contradicts the visible text, checks heading and table structure, and finds facts locked inside images. |
| `retrieval-simulation` | ④ RETRIEVE | Does the chunk carrying the fact survive retrieval? Chunks the AI-reachable corpus, indexes it with hand-rolled BM25, runs 18 deterministic buyer-intent queries, and classifies each answerable / partial / ungrounded / unretrievable. Also finds orphan facts and cross-page joins. |
| `trust-corroboration-audit` | ⑤ CITE | Is the fact quotable and trusted? Checks entity anchoring (`sameAs`), staleness, description drift across meta/JSON-LD/OpenGraph, and attribution on quantitative claims. |
| `arrival-engagement-audit` | ⑥ ARRIVE | Does the AI-referred visitor stay? Audits the pages that actually won a query, against a persona that arrives deep-linked, mid-task and with zero context: answer proximity, orientation, context-reset redirects, consent interference, next step, referral instrumentation, latency. |
| `finding-verification` | cross-cutting | Tries to **disprove** every finding before it ships — re-fetch with a second UA, sample-adequacy check, contradiction search. Anything that fails is demoted to `observations`, never silently dropped. |

### How the entrypoint composes them

The stages are **gated**, not independent. Each writes a
`StageResult{findings, artifacts, corpus_delta, metrics}`, and the next
stage only ever sees the `corpus_delta` that survived the ones before it:

```
REACH ──corpus_delta──▶ RENDER ──▶ EXTRACT / RETRIEVE / CITE ──▶ ARRIVE
                                                    │
                          finding-verification ◀────┘   (all findings)
                                    │
                     ai-visibility-orchestrator ──▶ one AuditReport
```

`retrieval-simulation` never reads the raw crawl — only the corpus that
survived REACH and RENDER, minus any page RENDER proved is an empty
JS-only shell. `arrival-engagement-audit` goes further and audits only
the pages that actually *won* a buyer-intent query in stage ④. That
gating is why the same missing fact produces a **render** finding on one
site and a **chunking** finding on another, and it's what makes the
split a pipeline rather than eight topical sections. Full contract:
[`skills/ai-visibility-orchestrator/references/composition.md`](skills/ai-visibility-orchestrator/references/composition.md).

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
python -m pytest tests/ -v                    # 265 tests, no network needed
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

## Beyond defects: the proactive layer

A finding requires an artifact proving something is *wrong*. But the most
valuable observation is often that something is **absent** — and absence
has no artifact to point at, which is why these ship in their own
`proactive_recommendations` array rather than as low-severity findings.

The rule that keeps this from becoming a static best-practices list:
**every recommendation is derived from something this run actually
measured.** Three generators, each covering a distinct kind of absence:

- **An entire buyer-intent class nothing answers.** Read from the
  answerability matrix. Distinct from `CHUNK-001`, which measures the
  corpus-wide unanswerable *ratio* — a site can sit comfortably under
  that threshold and still answer nothing at all about, say, comparison,
  which is exactly the gap a competitor's comparison page fills instead.
- **Near-misses.** Queries that resolved only as `PARTIAL` — the facts
  exist but must be assembled. These are the cheapest available wins:
  the content is already written, it is merely badly co-located.
- **No `/llms.txt`** — with a draft **generated from the site's own
  sampled URLs**, not a stub. Raised as a recommendation rather than a
  finding because `llms.txt` is a proposed convention, not a ratified
  standard, and no major AI vendor has publicly committed to honouring
  it. A site without one is not broken; it has skipped a cheap hedge.

## Why the split is a pipeline, not padding

The per-skill table and the gating diagram are above; this is the
argument for *why* that decomposition earns its keep.

The payoff is that the same missing fact produces a *structurally
different* finding depending on where it actually died. Missing because
`robots.txt` blocks the page? `REACH-00x` — fix infrastructure. Missing
because it only renders after JS? `RENDER-001` — fix delivery. Present
in the raw HTML but its subject and value land in different retrieval
chunks? `CHUNK-00x` — fix information architecture. One root cause,
three different findings, three different fixes — because the gating
forces it. A single skill running the same checks could not make that
distinction, because it would never know which corpus each check was
entitled to see.

See
[`references/composition.md`](skills/ai-visibility-orchestrator/references/composition.md)
for the full contract, including the cross-stage merge rule that exists
precisely because two stages can legitimately describe the same root
cause (`REACH-002`/`ENGAGE-003`, a redirect that's both a crawler-fetch
problem and an arrival-experience problem), and the within-stage
aggregation that stops one site-wide template defect from shipping as
twenty-six separate findings.

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
9 fixtures (2 known-defect cases, 6 clean controls, 1 scored separately
-- see below):

| Metric | Value |
|---|---|
| Precision | **1.00** (2/2 flagged findings were real) |
| Recall (on the fixtures' own known-positive cases) | **1.00** (2/2) |
| False-positive rate on clean controls | **0.00** (0/13 certified-clean-stage checks produced a finding) |

`retrieval-answerable` is scored separately (per-query answerability
outcome, not a finding/taxonomy_id): **11/12 (92%)** correct. The one
miss is a known, accepted property of a lexical-only retriever, not a
bug -- see [Limitations](#limitations).

The sixth clean control is **non-English** (`tests/fixtures/non-english`,
a German site built to be genuinely good: `lang="de"`, brand named up top
on every page, JSON-LD, prices in both schema and prose, three German
CTAs). It certifies the four stages where an English-only lexicon would
show up as a false positive. It earns its place -- before the language
guard described under Limitations, this fixture produced a `CHUNK-001`
finding, an `ENGAGE-005` finding, a false headline claiming 15 of 18
buyer-intent queries were unanswerable, and five false "no page answers
X-intent questions" recommendations. Its pricing page says
`Der Bergquell A1 Aktivkohlefilter kostet 149,00 EUR`; the probe called
that UNGROUNDED.

**Wild-corpus sweep**, run through the real, current pipeline (not just
hand-diagnosed, as Day 1's original 12-site field research was): a
Shopify store, a static docs site, a SaaS marketing/legal site, a
single-page portfolio, a news publisher, and a non-English retail
site. Every finding was spot-checked by hand for plausibility, not just
"the process didn't crash." The sweep found and fixed two real bugs
before this evaluation number was final: a false positive (`REACH-001`
flagging an ordinary `User-agent: *` page exclusion as if it were
AI-specific discrimination) and a crash (a `Finding` constructed with
zero artifacts when an entire crawl came back empty). Full accounting, including what was tried
and reverted, lives in this project's development log (kept in the source
repository, outside this submitted marketplace).

## Limitations

Stated in full, with reasoning, in [`NOTES.md`](NOTES.md#limitations-stated-honestly).
The ones most likely to matter to a reader of a report:

- **Playwright is optional.** Without it, stage ② RENDER is skipped and
  every `RENDER-*` finding is suppressed rather than guessed at — the
  skip is recorded in the report's `degradations`.
- **Retrieval is lexical (BM25), not semantic.** A query about "customer
  support" won't match a page that only says "reach us". Deliberate: an
  embedding backend needs model weights or an API key, and neither is
  allowed here.
- **Non-English sites get five stages, not six.** The query bank and CTA
  lexicon are English, so when a corpus *declares* a language they don't
  cover, the answerability probe doesn't run and says so.
- **No live name-collision search.** On-site entity anchoring only — a
  live web search would break determinism and offline portability.
- **Link discovery is one level deep** (homepage only) for sites with no
  sitemap, and the sample is stratified but shallow.

## Structure

```
marketplace.json              one entrypoint: ai-visibility-orchestrator
NOTES.md                       competitive positioning, prior research, full limitations
LICENSE                        MIT
skills/                        the 8 skills (see Composition above)
src/brand_audit/                shared Pydantic models, crawl core, chunking, BM25, severity function
scripts/eval_fixtures.py        maintainer eval harness -- not a shipped skill
tests/                          265 tests + local fixture sites (no live network needed)
```

See `skills/ai-visibility-orchestrator/SKILL.md` for the full CLI and
the composition contract in more detail; every skill's own `SKILL.md`
documents its detectors, input/output contract, and current status.

**A note on the manifest.** The handout is explicit that the multi-skill
marketplace format is the contest's own convention, not an external
standard: agentskills.io defines the single-skill `SKILL.md` format and
nothing above it. So `marketplace.json` is the handout's example shape
verbatim — `name`, `version`, and a `skills` array of
`{id, path, entrypoint}` — with exactly one skill carrying
`entrypoint: true`. `skills/ai-visibility-orchestrator/scripts/lint_marketplace.py`
enforces that shape in CI: every listed path resolves inside the
marketplace root and contains a `SKILL.md`, no skill folder on disk is
missing from the manifest, exactly one entrypoint, and no key the
handout's manifest doesn't define.
