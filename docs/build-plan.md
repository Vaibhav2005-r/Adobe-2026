# Round 3 — Agent Skill Marketplace: Build Plan

**Adobe University Hackathon 2026 · 10-day take-home (Fri 28 Aug → Sun 6 Sep)**

---

## Part 0 — What the brief is actually testing

Read the rubric carefully. It does **not** say "find the most problems." It says:

| Rubric line | What it really rewards |
|---|---|
| Detection accuracy | "evidence-backed… **few false positives**" — precision is scored, not just recall |
| Suggested-action quality | "**mechanism-sound**" — the fix must follow from *how retrieval works*, not from a best-practices list |
| Output design | "**a non-expert could act on**" — the report is a product surface, not a debug dump |
| Skill-format hygiene | "**deterministic; safe**" — same site in, same report out |
| Marketplace composition | "genuine separation of concerns… **not padding**" |
| Generalization | tested by construction — you never see the graded sites |

Three of six criteria are about *epistemics and engineering*, not about how many checks you have. That is the opening.

**The trap:** the obvious build is a crawler that runs 40 boolean checks (llms.txt? JSON-LD? alt text? robots.txt?) and emits a score. Every commercial GEO/AEO tool on the market today does exactly this — GEO Optimizer (47 "research-backed methods"), HubSpot AEO Grader, the Chrome AEO extensions, AthenaHQ, Peec. It is a solved, commoditised shape. If your submission is shaped like those tools, the judges have already seen it four times before lunch, and every finding you emit is a generic assertion ("you're missing FAQPage schema") that can't be defended against a site where it wasn't actually a problem — i.e. a false positive machine.

---

## Part 1 — The differentiating thesis

> **Don't audit the page. Simulate the pipeline, and report the stage where the brand falls out.**

An AI assistant answering "what does Brand X charge for Y?" runs a funnel. Every stage can drop the brand, and each stage failing produces a *completely different fix*:

```
① REACH     Can a bot fetch it?          robots, status codes, WAF, sitemap, canonicals
      ↓                                   ✗ → fix infrastructure
② RENDER    Can it read it without JS?   HTML-only vs headless-rendered text delta
      ↓                                   ✗ → fix delivery (SSR/no-JS fallback)
③ EXTRACT   Can it isolate the fact?     semantic HTML, JSON-LD, text-vs-image facts
      ↓                                   ✗ → fix markup
④ RETRIEVE  Does the chunk survive?      chunk boundaries, orphan facts, boilerplate ratio
      ↓                                   ✗ → fix information architecture
⑤ CITE      Is it quotable & trusted?    attribution, stats, freshness, corroboration, entity ID
      ↓                                   ✗ → fix content & off-site presence
⑥ ARRIVE    Does the visitor stay?       mid-task orientation, answer-above-fold, next step
                                          ✗ → fix landing experience
```

Checklist tools score signals. **We localise failures.** The unit of output isn't "you scored 62/100" — it's *"the query 'X pricing' dies at stage ②: the price string exists only in the rendered DOM; here is the exact HTML-only extraction proving it, and here are the three lines of SSR that fix it."*

Three consequences that map straight onto the rubric:

1. **Generalisation is structural, not learned.** The funnel is how *every* retrieval system works. It does not encode any site's idiosyncrasies, so it cannot overfit to your field-research sites.
2. **False positives collapse.** A checklist says "missing FAQPage schema" on a site where nobody asks questions. We only raise a finding when a *simulated query actually fails* and we can point at the byte that caused it.
3. **Fixes are mechanism-sound by construction.** The fix is determined by which stage broke. You cannot recommend "add schema" for a problem that is actually a robots.txt block.

---

## Part 2 — Eight innovations no competing submission will have

These are the things to build. Ranked by judge-impact per hour of work.

### ① The Dual-Fetch Differential ("AI blind-spot diff") — *highest ROI, build first*

Fetch every sampled page **twice**: (a) plain HTTP GET with an AI-crawler User-Agent and no JavaScript, (b) headless Chromium, fully rendered. Extract main content from both. Diff at the **fact level**, not the character level.

The delta *is* the set of facts invisible to AI assistants. Output reads:

> `RENDER-001 · critical` — 7 of 12 product pages deliver their price only after JS execution. HTML-only extraction of `/products/atlas` yields 431 chars with no currency token; rendered extraction yields 3,847 chars containing `₹24,999`. Evidence: [both extractions attached, SHA-256 hashed].

Nobody ships this because it needs two fetch paths and a diff engine. It is *devastating* evidence in a report — irrefutable, specific, and it explains a whole class of "we're invisible and we don't know why."

**Why it's mechanism-sound:** major AI crawlers are documented as executing JavaScript inconsistently or not at all, unlike Googlebot which has rendered for a decade. Sites built on client-side frameworks pass every SEO audit and are still blank to an AI fetcher.

### ② The Answerability Probe (the crown jewel)

Instead of asking "does this page have good content," ask **"can a machine answer the questions a buyer would ask, using only what it can actually reach and read?"**

Pipeline:
1. Derive the brand's entity + category from the site itself (JSON-LD `Organization`, title, H1, nav).
2. Generate a deterministic query set from a **bundled template bank** in `assets/` — 6 intent classes × the detected vertical: *identity* ("what is X"), *pricing*, *comparison*, *capability/spec*, *trust/proof*, *contact/logistics*. Templates, not free-form LLM generation, so the query set is reproducible.
3. Chunk **only the AI-reachable corpus** (the stage-① and ② survivors), 400–600 tokens with overlap, boilerplate-stripped.
4. Retrieve with **BM25** (deterministic, zero-dependency, no model weights — see stack notes).
5. For each query, classify the outcome:
   - `ANSWERABLE` — a retrieved chunk contains a verbatim, attributable answer
   - `PARTIAL` — answer must be assembled across chunks/pages (fragile under real retrieval)
   - `UNGROUNDED` — top chunks are topically close but contain no fact
   - `UNRETRIEVABLE` — nothing relevant surfaces at all

Findings are then *outcome-anchored*: "5 of 18 buyer-intent queries are UNANSWERABLE from your machine-readable surface." That is the metric the industry actually cares about (answer visibility / citation frequency), not intermediate proxies like Recall@k.

**This single feature is the submission's identity.** It's the thing a judge repeats to another judge.

### ③ Chunk-Boundary & Orphan-Fact Analysis

Retrieval operates on chunks, not pages. A fact whose *subject* and *value* land in different chunks is unretrievable even though the page "has" it. Concretely:

- **Orphan fact** — a `<td>₹24,999</td>` whose product name is 40 DOM nodes upstream in an `<h1>`, so the chunk containing the price never says what it prices.
- **Cross-page join** — the answer needs page A's spec plus page B's price. Real assistants rarely do this join.
- **Boilerplate dominance** — chunks that are >60% nav/footer/cookie text have their signal diluted below the retrieval threshold.

No commercial tool checks this. It's genuinely novel, it's trivially explainable to a judge ("the price is on the page but the chunk containing it doesn't say what it's the price *of*"), and the fix is concrete (co-locate subject and value, add a summary sentence per section, use `<dl>`/table headers).

### ④ The Falsification Pass (the anti-false-positive weapon)

The rubric explicitly rewards "few false positives." Build a dedicated **verification skill** that runs *after* detection and tries to **disprove every finding** before it ships:

- Re-fetch and re-test with a different UA / a second sample of pages — does it reproduce?
- Is the artifact still present (URL live, selector resolves, status code stable)?
- Does a contradicting signal exist? (e.g. "no JSON-LD" — but is there microdata or RDFa carrying the same facts? Then downgrade, don't drop.)
- Is the sample size sufficient for the claimed scope? A defect on 1/1 page cannot claim "site-wide."

Every finding carries `confidence: high|medium|low`, `reproduced: true|false`, and `sample: {checked: 12, affected: 7}`. Findings that fail falsification are **demoted to an `observations` array**, not silently dropped — which itself demonstrates epistemic discipline to a judge.

Add a hard rule: **no artifact, no finding.** Every finding must carry a machine-checkable artifact (URL + HTTP status + selector/XPath or byte-offset + the literal extracted strings). This makes it structurally impossible to emit hand-wavy assertions.

### ⑤ Mid-Task Arrival Model (the engagement half, done properly)

Most teams will do engagement as Core Web Vitals + "add a CTA." That's a generic UX audit and scores nothing.

Mechanism-sound framing: **an AI-referred visitor is fundamentally different from a search visitor.** They arrive (a) deep-linked, never the homepage, (b) mid-task with a specific question already formed, (c) having already been given a partial answer by the assistant, (d) with zero context about who you are. So audit the pages *most likely to be cited* (the stage-⑤ survivors) against that persona:

- **Answer proximity** — is the answer the assistant would have cited present in text above the fold, or buried below three hero sections?
- **Orientation** — can a cold arrival tell what this company is and what this page is, from this page alone, without the nav?
- **Context reset** — do deep links redirect to `/` or a region/locale selector? (An outright killer: the assistant's citation lands nowhere.)
- **Entry interference** — consent walls, modals, chat popups, age gates blocking first meaningful paint.
- **Next-step availability** — is the natural next action present *on the landing page*, or does it require a navigation hunt?
- **AI-referral blindness** — is the site even instrumented to detect referrals from `chatgpt.com`, `perplexity.ai`, `claude.ai`? Most brands cannot see this traffic at all, so they can't tell it's failing.
- **Performance, scoped** — LCP/INP measured on the *citable page set*, not the homepage.

The "context retention" phrase in the brief is a direct hint at this. Nail it.

### ⑥ Corroboration & Entity-Collision Graph (off-site, per Appendix D)

Recommend-only and read-only, but off-site signals matter:

- **Entity anchoring** — does `Organization` JSON-LD carry `sameAs` to authoritative profiles? Is there a Wikidata/Wikipedia anchor? Is the name/address/contact consistent across the site's own footers?
- **Name collision detection** — search the brand token; if the top results are dominated by a different entity of the same name, that's `TRUST-002 Entity Collision` and it explains misrepresentation, not just invisibility. Fix: disambiguating descriptor + `sameAs` + consistent one-line boilerplate.
- **Single-source fragility** — claims that appear only on the brand's own domain. Fix: seed the claim into profiles/directories/press so it corroborates.
- **Description drift** — is the brand's one-line self-description consistent across `<title>`, meta description, JSON-LD, OG tags, and footer? Drift = a system can't converge on a canonical framing.

### ⑦ Grounded Prioritisation (not invented scores)

Every suggested action gets `{impact, effort, confidence, stage_unblocked}`. Impact is **derived from the funnel**, not asserted: unblocking stage ① for the whole site outranks a stage-⑤ polish on one page, because everything downstream is gated on it. Cite the published effect sizes where relevant — the KDD 2024 GEO study found source citations, statistics addition and quotations each moved visibility materially (~+20–40% relative on their metrics) while keyword stuffing did essentially nothing. That lets us say "add attributed statistics to your claims pages" and defend *why*, with a reference, instead of vibes.

Ship an explicit `severity` function so it's deterministic:

```
severity = f(stage, blast_radius, confidence)
  critical : blocks stage ① or ② site-wide           (nothing downstream can work)
  high     : blocks a stage for a whole page class    (e.g. all product pages)
  medium   : degrades retrieval/citation quality      (partial answers, weak trust)
  low      : proactive improvement, no defect found
```

### ⑧ Beyond-Defect Proactive Layer

The rubric explicitly rewards suggestions "even where no explicit defect was found," and calls out "relevant and **non-obvious**." Reserve a `proactive_recommendations` array, generated from *gaps in the answerability matrix* rather than from a static list:

- Query intents with no dedicated page at all → "you have no page that answers comparison-intent queries; assistants will cite a competitor's comparison page instead."
- A `/llms.txt` proposal **generated from the actual site map**, not a stub.
- Fact-density upgrades on the pages closest to being citable (near-misses in the probe).
- Corroboration plan: the three specific claims most worth getting a third party to repeat.
- Instrumentation plan for AI-referral attribution.

Non-obvious, site-specific, and directly traceable to measurements. That's the difference between "add an FAQ" and a real recommendation.

---

## Part 3 — Marketplace architecture

Decomposition mirrors the **funnel stages**. This is the argument that wins the composition criterion: the split isn't topical padding, it's a pipeline where each skill owns one stage, has one input contract, one output contract, and is independently runnable and testable.

```
brand-ai-readiness-audit/            <- zip this
├── marketplace.json                 <- manifest, exactly one entrypoint
├── README.md                        <- what each skill does + composition story
├── LICENSE
└── skills/
    ├── ai-visibility-orchestrator/  ★ ENTRYPOINT
    │   ├── SKILL.md                 <- composition contract, budget mgr, report assembly
    │   ├── scripts/
    │   │   ├── run_audit.py         <- pipeline driver, stage gating, time budget
    │   │   ├── assemble_report.py   <- merge stage outputs → validated report
    │   │   └── render_html.py       <- single-file HTML report (demo surface)
    │   ├── references/
    │   │   ├── report-schema.md     <- the full JSON contract
    │   │   ├── severity-model.md    <- deterministic severity + priority function
    │   │   └── composition.md       <- how stages gate each other
    │   └── assets/report_schema.json
    │
    ├── crawl-reach-audit/           ① REACH
    │   └── robots/AI-UA probes, sitemap health, status/soft-404, canonical integrity,
    │      WAF & interstitial detection, deterministic page sampling + crawl budget
    │
    ├── render-gap-audit/            ② RENDER
    │   └── dual-fetch differential, fact-level diff, non-text fact detection
    │      (image/canvas/PDF-only facts), interaction-gated content
    │
    ├── extractability-audit/        ③ EXTRACT
    │   └── JSON-LD/microdata/RDFa parse + validate, schema↔visible-text contradiction,
    │      semantic HTML integrity, table/heading structure, fact-density scoring
    │
    ├── retrieval-simulation/        ④ RETRIEVE  ← crown jewel
    │   └── chunking, BM25 index, query-template expansion, answerability matrix,
    │      orphan-fact & chunk-boundary analysis, boilerplate ratio
    │
    ├── trust-corroboration-audit/   ⑤ CITE
    │   └── entity anchoring & sameAs, name-collision, freshness/staleness,
    │      attribution & statistic density, description drift
    │
    ├── arrival-engagement-audit/    ⑥ ARRIVE
    │   └── mid-task arrival model, answer proximity, orientation, context reset,
    │      entry interference, next-step, AI-referral instrumentation, scoped CWV
    │
    └── finding-verification/        ✗ FALSIFICATION (cross-cutting)
        └── reproduce, re-fetch, contradiction search, sample-adequacy,
           confidence assignment, demotion to observations
```

**Composition contract** (this is what the entrypoint's SKILL.md documents, and what judges will look for): every stage skill reads a shared `run_context` and writes a `StageResult{findings[], artifacts[], corpus_delta, metrics}` to a run directory. Stages are **gated** — `retrieval-simulation` consumes only the corpus that survived ① and ②, which is precisely why the same missing fact produces a *render* finding on one site and a *chunking* finding on another. `finding-verification` runs across all stages before assembly. The orchestrator owns the time budget, degradation policy, and the single validated report.

That gating story is the whole answer to "is the decomposition genuine or padding?" Write it down explicitly in the README.

---

## Part 4 — Tech stack

Constraints that drive every choice: **≤50 MB zip, no model weights, <5 min runtime, deterministic, read-only, portable, provider-neutral.**

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | matches `skills-ref`'s own requirement; universally available |
| Deps | `pyproject.toml` + `uv`, but **stdlib-first fallbacks everywhere** | a judge running on a bare machine must still get a report |
| HTTP | `httpx` (async, HTTP/2, per-host limits) | needed for the dual-fetch and to hit the 5-min budget |
| robots.txt | `protego` | handles wildcards/`Allow` precedence correctly; `urllib.robotparser` gets AI-UA rules wrong |
| Rendering | `playwright` (chromium, headless) | stage ②. **Optional dependency** — if absent, emit `render_check: skipped` and *suppress* all RENDER findings rather than guessing |
| HTML parse | `selectolax` (lexbor) w/ `lxml` fallback | 5–10× faster than bs4; matters for the time budget |
| Main-content extraction | `trafilatura` | best-in-class boilerplate removal + date extraction; used identically on both fetch paths so the diff is apples-to-apples |
| Structured data | `extruct` | JSON-LD + microdata + RDFa + OpenGraph in one pass |
| Schema validation | bundled schema.org subset in `assets/` | offline, deterministic, no network dependency |
| Tokenising | `tiktoken` (fallback: regex word-count approximation) | chunk boundaries must match real retrieval |
| Retrieval | **BM25, hand-rolled (~120 LOC)** | ⚠️ deliberate: embeddings would need model weights (banned) or an API key (non-portable, non-deterministic). BM25 is the lexical half of every production hybrid retriever, is fully reproducible, and is *defensible in the README* as a conservative floor. Leave a pluggable `Retriever` interface so an embedding backend can be enabled if an API key is present. |
| Perf metrics | Playwright CDP → LCP/CLS, TTFB from `httpx` | scoped to the citable page set only |
| Models | pydantic v2 → JSON Schema | schema is generated *from* the models, so report and contract can never drift |
| Report out | JSON (required) + single-file HTML + Markdown exec summary | HTML is the demo surface; zero external assets |
| CI | GitHub Actions: `skills-ref validate` on every skill folder + manifest lint + eval harness | proves hygiene, and it's a screenshot for the README |

**Any LLM usage is confined to two places**, both schema-constrained, temperature 0, with a deterministic pre-filter and a deterministic fallback: (1) classifying answerability outcomes, (2) drafting suggested-action prose from a structured finding. Everything else is deterministic code. Say this explicitly in the README — "the audit is deterministic; the LLM writes prose, it does not decide findings" is a strong line.

**Runtime budget** (hard-enforced by the orchestrator): default 40 pages, stratified deterministic sample — home, top nav L1, pricing/plans, product/service class ×N, about, contact, docs/help, most-recent blog. Fixed seed, sitemap-first ordering, URL-hash tie-break. Concurrency 8 with per-host politeness delay. Global watchdog degrades gracefully: drops stage ⑥ perf first, then render sample size, then page count — and **records the degradation in the report** rather than silently producing a thinner audit.

---

## Part 5 — Report schema (superset of the required floor)

Keep every required field exactly as specified, then extend. Required floor: `site`, `audited_at`, counts-by-severity `summary`, and per-finding `id`, `title`, `severity`, `evidence`, `suggested_action`.

```jsonc
{
  "site": "example.com",
  "audited_at": "2026-09-06T14:32:00Z",
  "schema_version": "1.0.0",
  "run_manifest": {                          // determinism proof
    "marketplace_version": "1.0.0",
    "rule_pack_version": "2026.09.1",
    "pages_crawled": 38, "pages_rendered": 12,
    "sample_seed": "sha256:...", "duration_s": 214,
    "stages_completed": ["reach","render","extract","retrieve","trust","arrive","verify"],
    "degradations": []
  },
  "summary": {
    "total_findings": 11, "critical": 1, "high": 3, "medium": 5, "low": 2,
    "ai_readiness": {                         // the headline a non-expert reads
      "reach": "pass", "render": "fail", "extract": "partial",
      "retrieve": "fail", "cite": "partial", "arrive": "pass"
    },
    "answerability": { "answerable": 9, "partial": 4, "ungrounded": 3, "unretrievable": 2 },
    "headline": "Prices and specs are invisible to AI crawlers because they render client-side."
  },
  "findings": [{
    "id": "F-001",
    "title": "Product prices delivered only after JavaScript execution",
    "severity": "critical",
    "stage": "render",
    "taxonomy_id": "RENDER-001",
    "scope": { "checked": 12, "affected": 7, "page_class": "product" },
    "evidence": "HTML-only fetch (UA: GPTBot) of /products/atlas returns 431 chars of main content with no currency token. Headless-rendered fetch returns 3,847 chars including '₹24,999'. Reproduced on 7/12 sampled product pages.",
    "artifacts": [{
      "url": "https://example.com/products/atlas",
      "http_status": 200,
      "selector": "div[data-testid='price-block']",
      "html_only_extract": "…", "rendered_extract": "…",
      "sha256": "…"
    }],
    "confidence": "high",
    "verification": { "reproduced": true, "method": "second-UA refetch + 3-page resample", "contradicting_signals": [] },
    "impact_mechanism": "Major AI crawlers do not reliably execute JavaScript. A price absent from the HTTP response cannot enter the retrieval corpus, so no pricing query can ever cite this page.",
    "affected_queries": ["what does Atlas cost", "Atlas vs competitor pricing"],
    "suggested_action": {
      "summary": "Server-render the price block, or emit it as text in the initial HTML response.",
      "priority": "critical",
      "impact": "high", "effort": "medium", "confidence": "high",
      "stage_unblocked": "render",
      "implementation": ["…concrete, framework-aware steps…"],
      "verification_step": "curl -A 'GPTBot' <url> | grep '₹' — must match before and after JS.",
      "rationale_ref": "references/mechanisms.md#js-render-gap"
    }
  }],
  "observations": [ /* findings that failed falsification — shown, not hidden */ ],
  "proactive_recommendations": [ /* the beyond-defect layer */ ],
  "answerability_matrix": [ /* per-query: intent, outcome, top chunk, citable? */ ]
}
```

The `impact_mechanism`, `affected_queries` and `verification_step` fields are what make this actionable for a non-expert. `verification_step` in particular — giving the user a one-liner to confirm the fix worked — is a small touch that reads as extremely professional.

---

## Part 6 — Proving generalisation without test sites

You can't test on the graded sites. So **build the evidence that you generalise** and put it in the README. This is the single most underrated move available.

**Two-track validation:**

1. **Synthetic fixture corpus** (`tests/fixtures/`) — ~10 tiny local sites served from `python -m http.server`, each with **deliberately injected, known defects**: a JS-only-price site, a robots-blocked site, a schema-contradicts-text site, an orphan-fact site, a consent-wall site, and — critically — **two clean control sites with no defects at all.** Compute precision, recall and **false-positive rate on the controls**. Publish the confusion matrix in the README. Nobody else will do this, and it speaks directly to two rubric lines at once.

2. **Wild diversity sweep** (the brief's field research) — run against a deliberately heterogeneous set: a static docs site, a Next.js SaaS marketing site, a Shopify store, a WordPress local business, a single-page portfolio, a news publisher, a non-English site. You're not tuning to them; you're checking the auditor **doesn't crash, doesn't stall, and doesn't emit nonsense** on shapes it hasn't seen. Log every crash and every finding you judge wrong, and fix the *rule*, never the *site*.

**Discipline rule for the whole 10 days:** if a fix only helps one site, it's overfitting — delete it. Every rule must state the mechanism it's testing before it's allowed into the rule pack.

---

## Part 7 — The 10-day plan

Each day has a **definition of done**. If a day's DoD isn't met, cut scope from the *next* day's stretch items, never from the core.

### Day 1 — Fri 28 Aug · Field research + taxonomy
- Assemble the wild corpus (10–15 sites, deliberately diverse; include sites you *know* AI assistants cite well and ones they ignore).
- For each: ask a live assistant a buyer question about the brand, record whether it's cited, misrepresented or absent. **Then** manually find why. This is the reverse-engineering the brief is asking for.
- Freeze the **defect taxonomy** as `references/taxonomy.md` — ~30 defect IDs across the six stages (`REACH-00x`, `RENDER-00x`, `EXTRACT-00x`, `CHUNK-00x`, `TRUST-00x`, `ENGAGE-00x`), each with: mechanism, detection method, evidence artifact, severity default, fix pattern.
- **DoD:** taxonomy frozen; every entry has a stated *mechanism*, not just a symptom.

### Day 2 — Sat 29 Aug · Contracts + scaffolding
- Repo, `marketplace.json`, all 8 skill folders with valid stub `SKILL.md` (name matches folder, frontmatter uses only the 6 legal keys).
- `skills-ref validate` green on all 8 + CI wired.
- Pydantic models for `Finding`, `Artifact`, `StageResult`, `AuditReport`; generate `report_schema.json` from them.
- Crawl core: robots/`protego`, sitemap parse, deterministic sampler, budget manager, artifact store.
- **DoD:** `run_audit.py` crawls a site, emits a schema-valid report with zero findings. The skeleton is end-to-end before any detector exists.

### Day 3 — Sun 30 Aug · Stage ① REACH + Stage ② RENDER
- `crawl-reach-audit`: AI-UA probes across the documented bot list (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-SearchBot, Claude-User, PerplexityBot, Google-Extended, CCBot, Bytespider, Applebot…), status/soft-404 detection, canonical integrity, WAF/interstitial detection, sitemap health.
- `render-gap-audit`: **the dual-fetch differential.** Build the fact-level differ, not a text differ — tokenise both extractions, classify the delta by fact type (numeric/currency/date/entity/contact), suppress noise (nav, timestamps, CSRF tokens, personalisation).
- **DoD:** the differ correctly flags the JS-only-price fixture and stays *silent* on the clean control.

### Day 4 — Mon 31 Aug · Stage ③ EXTRACT
- `extractability-audit`: `extruct` parse; validate against the bundled schema.org subset; **schema↔visible-text contradiction detection** (JSON-LD says `price: 199`, page says `₹24,999` — a high-value, rarely-checked finding); semantic HTML integrity; heading hierarchy; table/`<dl>` structure; facts-locked-in-images detection (numeric-looking content only present in `alt`-less `<img>`/`<canvas>`/embedded PDF).
- **DoD:** stage ③ passes fixtures; contradiction detector has zero false positives on controls.

### Day 5 — Tue 1 Sep · Stage ④ RETRIEVE (crown jewel, part 1)
- Chunker (400–600 tokens, overlap, boilerplate-stripped, provenance-tracked back to URL + DOM position).
- BM25 index + `Retriever` interface.
- Query template bank in `assets/` — 6 intent classes, vertical-aware, deterministic expansion from the detected entity.
- **DoD:** given a fixture site, produces a reproducible answerability matrix. Two runs, byte-identical output.

### Day 6 — Wed 2 Sep · Stage ④ part 2 + Stage ⑤ CITE
- Orphan-fact detector (subject/value co-location within chunk), cross-page-join detector, boilerplate-ratio scoring.
- `trust-corroboration-audit`: entity anchoring/`sameAs`, name-collision probe, freshness (`dateModified` vs. content-derived dates vs. contradictions), attribution & statistic density, description drift across title/meta/JSON-LD/OG/footer.
- **DoD:** all detection stages complete. Full pipeline runs end-to-end on the wild corpus without crashing.

### Day 7 — Thu 3 Sep · Stage ⑥ ARRIVE
- `arrival-engagement-audit`: answer proximity (is the citable answer above the fold in text?), orientation check, context-reset detection (deep link → redirect/locale gate), entry interference (consent/modal/chat blocking first paint), next-step availability, AI-referral instrumentation detection, LCP/INP scoped to the citable page set.
- **DoD:** engagement stage produces findings that are visibly *about AI-referred arrivals*, not a generic UX audit. If a finding would be identical for a Google visitor, rewrite it or drop it.

### Day 8 — Fri 4 Sep · Orchestration, falsification, output
- `finding-verification`: reproduction, re-fetch, contradiction search, sample-adequacy, confidence assignment, demotion to `observations`.
- Deterministic severity + priority function; dedup/merge across stages (one root cause must not emit six findings).
- Report assembly + validation; **single-file HTML report** — funnel diagram with the failing stage highlighted, findings grouped by stage, answerability matrix, prioritised action list. This is the demo.
- **DoD:** one command → JSON + HTML + Markdown summary, schema-valid, under 5 minutes.

### Day 9 — Sat 5 Sep · Evaluation & precision hardening
- Run the full fixture suite; compute precision/recall/**FP-rate on controls**; publish the confusion matrix.
- Run the wild diversity sweep. Triage every false positive. **Fix rules, not sites.**
- Degradation testing: no Playwright, no network mid-run, robots-blocked, JS-heavy SPA, 5,000-page site, non-English site, site with no sitemap.
- Determinism test: three runs of the same site → identical reports modulo `audited_at`.
- Prune the rule pack: any rule with FP-rate above threshold on controls gets demoted to `observations` or deleted. **Deleting a mediocre rule raises your score.**
- **DoD:** FP-rate on clean controls ≈ 0; three identical runs; no crashes on the sweep.

### Day 10 — Sun 6 Sep · Package & narrative
- README: the funnel thesis, the composition contract (how stages gate each other and why the split is genuine), the eval results with the confusion matrix, the "deterministic detection, LLM only writes prose" statement, limitations stated honestly.
- Each `SKILL.md` trimmed under 500 lines with detail pushed to `references/` — progressive disclosure is explicitly in the spec and it's free rubric points on hygiene.
- Verify: `skills-ref validate` on all 8 · manifest has exactly one entrypoint · every `name` matches its folder · no illegal frontmatter keys · **no `<` or `>` anywhere in frontmatter** · no weights · zip ≤50 MB · runtime <5 min.
- A sample report from a real site, committed. Buffer for everything that slipped.
- **DoD:** zip built, unzipped in a clean container, run end-to-end from the README instructions alone.

---

## Part 8 — Risks and the cut list

| Risk | Mitigation |
|---|---|
| Playwright unavailable / too slow on judge's machine | Optional dep. Absent → skip stage ② and **suppress** RENDER findings + record degradation. Never guess. |
| 5-min budget blown on large sites | Hard page cap + watchdog with an ordered degradation ladder, recorded in the report. |
| Retrieval simulation slips | Ship it BM25-only. It's the differentiator; protect its schedule at all costs. Days 5–6 are non-negotiable. |
| False positives tank detection score | Falsification pass (Day 8) + control fixtures (Day 9) + willingness to delete rules. |
| Over-engineering, nothing finishes | Skeleton is end-to-end on Day 2. Every subsequent day adds a stage that the skeleton already knows how to run. You always have a shippable artifact. |
| Non-determinism from LLM calls | LLM confined to classification (schema-constrained, temp 0) and prose. Deterministic fallback for both. |

**If you're behind, cut in this order** (top = cut first):
1. LCP/INP measurement (keep TTFB — cheap and adequate)
2. Name-collision web probe (keep on-site entity anchoring)
3. Markdown exec summary (JSON + HTML suffice)
4. Cross-page-join detector
5. Reduce fixtures from 10 to 6, keeping **both controls**

**Never cut:** dual-fetch differential · answerability probe · falsification pass · schema validity · determinism · the README composition story.

---

## Part 9 — Rubric self-check

Score yourself against this before you zip. Anything not green gets Day 10's buffer.

| Criterion | Our evidence |
|---|---|
| Detection accuracy | Stage-localised findings, every one artifact-backed; falsification pass; published FP-rate on clean controls |
| Suggested-action quality | Fix determined by which stage broke, so it's mechanism-sound by construction; `impact_mechanism` + `verification_step` per action; proactive layer derived from measured answerability gaps |
| Output design | Funnel status a non-expert reads at a glance; headline sentence; prioritised actions with impact/effort; single-file HTML |
| Format & hygiene | 8 spec-compliant skills, CI-validated; one entrypoint; deterministic (3 identical runs); read-only, robots-respecting, no auth, no writes |
| Composition | Split follows the retrieval funnel; stages gate each other via a documented `StageResult` contract; cross-cutting verification skill; the gating story is *why* it isn't padding |
| Generalisation | Zero site-specific rules; every rule states a mechanism; fixture + wild-sweep validation published |

---

## Part 10 — The one-sentence pitch

> **Every other submission scores your website against a checklist. Ours reproduces the pipeline an AI assistant actually runs — reach, render, extract, retrieve, cite, arrive — tells you the exact stage where your brand falls out, proves it with the two extractions side by side, and then tries to prove itself wrong before it reports anything.**

Put that in the README's first paragraph. It is the whole submission in one line, and it's the line a judge repeats to another judge.
