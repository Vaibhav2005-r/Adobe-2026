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
python -m pytest tests/ -v                    # 255 tests, no network needed
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

## How this differs from what already exists

The AI-visibility market as of 2026 splits cleanly into two shapes, and
this audit is deliberately neither:

| | What it answers | Examples | What it can't tell you |
|---|---|---|---|
| **Monitoring platforms** | *Are* you being cited? | Profound, Peec AI (€89–199/mo), AthenaHQ ($295–499/mo), Scrunch AI, Otterly ($29/mo) | *Why not.* They poll live LLMs and track brand mentions — an outcome number, with no causal path back to a fix. Inherently non-reproducible: the same site polled twice gives different answers. |
| **Checklist / radar audits** | Do you *pass these checks*? | Siftly's free AI-crawler audit (7 checks: HTTPS, robots.txt, headers, meta tags, sitemap, SSR, structured data), Igris Radar, AEO Engine, Screaming Frog with a spoofed GPTBot UA | *Whether any of it mattered.* A boolean "SSR: fail" or a 0–100 radar score is a generic assertion — the exact false-positive machine this project's build plan predicted and set out to avoid. |

**This audit is the causal layer between them.** It doesn't report that
you're uncited (monitoring) or that you failed check #4 (checklist) — it
reports *which stage of the retrieval pipeline a specific buyer query
died at, and the byte that killed it.*

Being precise about what's actually novel here, since overclaiming is
the failure mode this project's own discipline exists to prevent:

- **Genuinely unserved.** Per-query **answerability outcomes**
  (`ANSWERABLE`/`PARTIAL`/`UNGROUNDED`/`UNRETRIEVABLE`) computed against
  *your own reachable corpus*, and a **falsification pass** that tries to
  disprove each finding before shipping it. Searching the current
  landscape surfaced no tool in either category that does either.
- **A novel *application*, not a novel idea.** Chunk-boundary and
  orphan-fact analysis. Chunking is thoroughly established in the
  RAG-engineering literature — it is simply not applied by anyone as a
  *website audit dimension*. The insight isn't "chunking matters," it's
  "your public site is already someone else's RAG corpus, so audit it
  like one."
- **Known problem, better instrument.** That AI crawlers largely don't
  execute JavaScript is industry-common knowledge, and Screaming Frog
  can already spoof a GPTBot UA. Our differentiator is not the UA — it's
  the **fact-level differential** between the two extractions
  (currency/numeric/date/contact tokens present in the rendered DOM but
  absent from the raw HTTP response), which turns a boolean into named,
  attributable missing facts.
- **Structurally different by construction.** Every commercial option
  above is a hosted SaaS that queries live models. This runs offline,
  needs no API key, and produces byte-identical reports across runs —
  properties a polling-based architecture cannot have.

Supporting the thesis from the outside: industry diagnostic data reports
that brands with strong organic-search presence routinely score poorly
on AI visibility *because their content is structured for keyword
ranking rather than AI retrieval* — precisely the failure mode a
checklist inherits and a pipeline simulation exposes.

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
bug -- see Limitations.

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

## Relationship to prior research

The academic literature on generative-engine visibility is ahead of this
project in specific, nameable ways. Stating them plainly is more useful
than being caught by them:

- **The literature measures against real engines; this does not.**
  [Citation-absorption work](https://arxiv.org/abs/2604.25707) analysed
  21,143 real citations across 602 prompts on ChatGPT, Gemini and
  Perplexity, separating *citation selection* (the engine picks you) from
  *citation absorption* (your page actually contributes language and
  evidence to the answer). Our rules are reasoned from mechanism and
  validated against fixtures — never against a live generative engine.
  **This is a deliberate constraint trade, not an oversight:** polling
  live models would break determinism *and* require an API key, two of
  this project's hard constraints. The cost is that our BM25 proxy's
  divergence from real retrieval is unmeasured.
- **Evaluation scale.** [E-GEO](https://arxiv.org/abs/2511.20867) builds
  a 13,747-query testbed across five engines with adversarial
  red-teaming. Ours is 9 fixtures and a 6-site sweep.
- **Offline simulation is a named blind spot.** A
  [position paper](https://arxiv.org/abs/2606.12439) identifies exactly
  this gap — that offline laboratory settings diverge from deployed
  system behaviour. It applies to us directly.
- **Off-site may outweigh on-site.**
  [Brand-notability benchmarking](https://arxiv.org/abs/2603.12282)
  reports a systematic bias toward *earned media* over brand-owned
  content. Our audit is almost entirely on-site (the off-site probe was
  cut for determinism reasons), so on-site optimisation has a ceiling we
  cannot measure. `TRUST-001` documents the same effect from field
  research.
- **Chunk quality has validated metrics.** Adaptive Chunking (LREC 2026)
  defines References Completeness, Intrachunk Cohesion and others; our
  orphan-fact detector is a hand-rolled cousin of the first.
- **Standard IR vocabulary exists.** Recall@K, NDCG, MRR, and frameworks
  like RAGAS and ARES. Our four-way outcome taxonomy deviates
  deliberately — the build plan argues outcome-anchored classification
  beats "intermediate proxies like Recall@k" for this audience — but the
  deviation is a choice, not ignorance of the standard.

**Where this project is genuinely unserved by prior work:** a targeted
search found no academic work auditing a *website* for LLM
retrievability with stage localisation (the "audit" literature concerns
auditing LLMs themselves), and the RAG evaluation survey explicitly
notes that corpus-level *retrievability assessment* is underexplored.
The falsification pass has no equivalent in any paper or product found.

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
- **Non-English sites get five stages, not six.** The buyer-intent query
  bank, the BM25 stopword list and `ENGAGE-005`'s CTA phrase list are
  English-language instruments. Pointed at another language they don't
  measure worse, they measure nothing while still producing
  confident-looking output. So when the corpus *declares* a language they
  don't cover (`<html lang>`, majority vote), the answerability probe
  doesn't run, stage ④ reports `skipped`, `ENGAGE-005` is suppressed, and
  the degradation names the language -- the same contract stage ② already
  honours when Playwright is missing. REACH, RENDER, EXTRACT, CITE and
  ARRIVE's other six detectors are language-independent and still run. An
  *undeclared* language is treated as covered, deliberately: acting on an
  absence would skip the crown-jewel stage on the many ordinary English
  sites that never set the attribute. Real multilingual support means a
  query bank, a stopword list and a CTA lexicon per language, plus a
  fixture for each -- not a language-detection call.
- **The stemmer is one rule (trailing `-s`), not a Porter stemmer.** So a
  query token "price" doesn't match a page's "Pricing" heading. A real
  Porter stemmer is deterministic, pure-Python and would collapse both to
  "price", so this is fixable -- it wasn't fixed because there is no
  evidence here that it *helps*: the answerability fixture is 12 data
  points, the one current miss is semantic rather than morphological, and
  this project's own rule is that a change to a detector needs measured
  justification before it ships. Recorded as a known gap rather than
  changed on faith.
- **`ENGAGE-004` matches consent-library signatures in markup, not
  blocking behaviour.** OneTrust/Cookiebot/CookieYes ship on a very large
  share of EU-facing commercial sites, including ones whose banner is a
  small non-blocking footer bar, so this check carries little information
  on such a site. It ships at **low** confidence for exactly that reason
  (downgraded from medium after a 196-site sweep), and its title says a
  consent overlay "may block" first paint rather than that it does.
  Confirming actual occlusion needs a rendered page with computed styles,
  which this stage deliberately doesn't require.
- **Link discovery is one level deep, homepage only.** A site with no
  sitemap is seeded from the links on its own homepage -- enough to give
  the sampler a real corpus instead of a single page, but not a recursive
  crawler. Pages reachable only three clicks in, and pages on sibling
  subdomains, are not discovered. `wikipedia.org` is the honest worst
  case: its portal links all point at `en.wikipedia.org` and friends, so
  the same-host filter leaves one page.
- **`TRUST-008` counts only percentages and currency amounts.** After a
  196-site sweep showed it firing on 101 of 196 sites, "statistic" was
  narrowed to the shapes the KDD study's own strategy refers to. A page
  asserting "12,000 customers in 89 countries" with no source no longer
  fires. That's a deliberate false negative: the alternative counted
  version numbers, ports and process ids as claims someone should have
  cited.
- **`ENGAGE-007` measures latency from the auditing machine.** A slow
  local connection, a VPN or packet loss is attributed to the audited
  site. `httpx`'s `Response.elapsed` is the cheap TTFB-adjacent proxy the
  build plan's cut list explicitly chose over LCP/INP; it has no baseline
  to subtract the client's own network from.
- **No retry or backoff on 429/503.** Each URL is fetched exactly once, so
  a site with aggressive burst limits can have pages recorded as
  unreachable on a first 429. Deliberate to the extent that retries fight
  both the politeness delay and the five-minute cap, but it is a real
  source of under-measurement, not a principled choice.
- **Fixture ports are hardcoded, and the fixtures themselves embed them.**
  Every fixture's `robots.txt`, `sitemap.xml` and internal links carry
  absolute `http://localhost:<port>` URLs, so the test suite fails with
  `Address already in use` if something else holds one of ports
  8123-8135. Moving to ephemeral ports means templating roughly twenty
  fixture files at serve time -- a change to the published eval corpus
  itself, which wasn't worth the regression risk for a local-collision
  annoyance.
- **CI runs on Linux only.** No `windows-latest` in the matrix, so
  Windows-specific path and shell behaviour is untested. Two known
  consequences: PowerShell's default execution policy blocks the
  `npx.ps1` shim used by `skills-ref` (run it as `npx.cmd --yes
  skills-ref validate <dir>`, or via `cmd /c`), and the virtualenv
  activate path is `.venv\Scripts\activate`, not `.venv/bin/activate`.

## Structure

```
marketplace.json              one entrypoint: ai-visibility-orchestrator
LICENSE                        MIT
skills/                        the 8 skills (see Composition above)
src/brand_audit/                shared Pydantic models, crawl core, chunking, BM25, severity function
scripts/eval_fixtures.py        maintainer eval harness -- not a shipped skill
tests/                          255 tests + local fixture sites (no live network needed)
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
