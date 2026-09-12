# Supporting notes

Background for [`README.md`](README.md), kept separate so the README can
stay focused on what each skill does and how the entrypoint composes
them. Nothing here is needed to run or evaluate the marketplace.

- [How this differs from what already exists](#how-this-differs-from-what-already-exists)
- [Relationship to prior research](#relationship-to-prior-research)
- [Limitations, stated honestly](#limitations-stated-honestly)

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
- **The sample is stratified, but shallowly.** The homepage and one page
  from each of pricing / contact / about / docs / product get a
  guaranteed slot; the rest is seeded URL-hash rank. A site whose pricing
  lives at a path none of those patterns match (`/plans-and-billing/`
  matches, `/how-much/` doesn't) still relies on the hash draw.
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

