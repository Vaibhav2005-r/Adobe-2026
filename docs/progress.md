# Progress Log

Tracks DoD completion against `docs/build-plan.md` Part 7, one entry per day. Update as each day's DoD is met so a fresh session can pick up where the last one left off.

## Day 1 — Fri 28 Aug · Field research + taxonomy
**Status:** core pass done across 2 sessions; corpus breadth is the remaining open item

- [x] Wild corpus assembled — 12 sites given the full treatment (live-assistant query + technical diagnosis), 3 more screened for RENDER only and found clean. Close to, still just under, the 10–15 floor; see Notes.
- [x] Each site: asked a live assistant (Claude's web search, used as the "live assistant" proxy — see Notes) a buyer question about the brand, recorded cited/misrepresented/absent, then manually diagnosed why via `curl` (robots.txt, raw HTML, headers, JSON-LD) plus a real headless-browser render for the two confirmed RENDER cases
- [x] Defect taxonomy at `brand-ai-readiness-audit/skills/ai-visibility-orchestrator/references/taxonomy.md` — 5 shipped findings (3 REACH, 1 RENDER, 1 cross-site TRUST pattern), 2 explicit observations pending falsification, 1 low-severity note, 3 positive controls. **Not** frozen at ~30 — see Notes on why padding was rejected.
- [x] Every taxonomy entry states a mechanism, not just a symptom (self-checked against the admission rule while writing each one)

**DoD status:** substantially met. Mechanism-first discipline holds for every entry. RENDER-00x — previously the biggest gap — now has two confirmed, evidence-complete cases with a full dual-fetch (curl-raw vs. headless-rendered) comparison. Site count (12) and entry count (8, not ~30) are still short of the plan's targets but each entry is load-bearing, not padding.

**Notes:**

*Methodology:* used Claude's own web-search tool as the "live assistant" being probed (rather than separately driving ChatGPT/Perplexity UIs, which would have needed logins/rate-limit handling out of scope for a non-interactive session) — reasonable as a first-pass proxy since it's a real retrieval-and-cite pipeline, not a simulation, but worth re-running key queries through 1–2 other assistants before the taxonomy is trusted as generalizing across assistants, not just this one's retrieval quirks.

*Corpus (12 fully diagnosed):* stripe.com (SaaS/fintech), linear.app (Next.js SaaS), allbirds.com (Shopify DTC), nytimes.com (news, explicit AI-bot blocker), notion.so→notion.com (JS-heavy PaaS), docs.python.org (static docs, control), brittanychiang.com (single-page portfolio, Next.js SSG), theverge.com (news/tech, open robots but citation gap), zalando.de (non-English/German retailer), **docsify.js.org** (JS-only docs generator — confirmed RENDER case), **app.uniswap.org** (JS-only DeFi app shell — confirmed RENDER case), **curve.finance** (WAF/bot-challenge block found while chasing the RENDER lead — confirmed REACH case). Plus 3 screened for RENDER only and found SSR-clean (framer.com, webflow.com, figma.com).

*Finding the RENDER cases:* the first pass tested big-brand marketing sites (Framer, Webflow, Figma, Linear) and found all of them SSR-clean — a real negative result, not a miss, but it left the plan's highest-ROI feature (dual-fetch differential) without a positive example. Redirecting the search toward **framework-driven doc generators that are explicitly client-side-only by design** (docsify) and **application shells never built with crawlability in mind** (a DeFi trading UI, Uniswap) found two textbook cases on the first two tries: both ship a literal empty `<div id="app">`/`<div id="root">` in the raw HTTP response. The lesson for the detector: targeting matters more than volume — "is this a marketing site" is the wrong filter; "is this a JS-framework app-shell with no build/SSG step" is closer to the real signal.

*Why not 10–15 sites / ~30 entries yet:* same discipline as the first session — quality of diagnosis over site count. Each RENDER case required a curl-raw fetch *and* a real headless-browser render of the *same URL* to make the before/after comparison airtight, which is slower than a single probe. TRUST-002 and TRUST-003 remain explicit single-sample observations, not promoted to findings.

*Biggest surprises this session:* (1) both RENDER cases had a clean **citation consequence**, not just a technical gap — docsify.js.org's own render gap handed its citation to `github.com/docsifyjs/docsify` (GitHub server-renders the README) instead, and Uniswap's gap was partly absorbed by its own render-friendly sibling subdomains (`support.`, `developers.`) rather than the app itself. This is exactly the "artifact-backed, stage-localized" story the audit is meant to tell. (2) curve.finance turned up by accident while chasing a RENDER lead: its WAF blocks *all* UAs including a plain browser string, and even blocks `/robots.txt` itself — a stronger failure than REACH-001's explicit `Disallow`, because the crawler can't even learn what's permitted. Worth remembering as a lesson: some of the best findings come from following a technical trail, not from working strictly one query at a time down a fixed list.

*Next session should:* (1) push corpus to 15 with categories still uncovered (a confirmed WordPress-powered local business; a native-language control query for the Zalando language-mismatch observation); (2) re-run TRUST-002 and TRUST-003 with a second query each to either promote or drop them; (3) run a live-citation query for curve.finance (REACH-003 currently has no citation-test corroboration, unlike every other finding); (4) start Day 2 scaffolding once corpus/taxonomy coverage feels sufficient, rather than blocking Day 2 entirely on hitting 30.

---

## Day 2 — Sat 29 Aug · Contracts + scaffolding
**Status:** done

- [x] `marketplace.json` with exactly one entrypoint (`ai-visibility-orchestrator`); all 8 skill folders with valid stub `SKILL.md` (name matches folder, only legal frontmatter keys used -- confirmed against the actual `skills-ref` validator source, not guessed: `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`)
- [x] `skills-ref validate` green on all 8 (via `npx skills-ref`, real Anthropic package, not a stand-in)
- [x] Pydantic v2 models (`src/brand_audit/models.py`): `Finding`, `Artifact`, `StageResult`, `AuditReport`, plus `Scope`/`Verification`/`SuggestedAction`/`RunManifest`/`Summary`/etc.; `report_schema.json` generated from them via `scripts/gen_schema.py` (CI checks for drift)
- [x] Crawl core (`src/brand_audit/crawl.py`, `fetch.py`, `artifact_store.py`): `protego`-based robots/AI-UA policy, sitemap discovery (index + urlset), deterministic stratified sampler (seeded by `sha256(domain)`, time-independent), `BudgetManager` with an ordered degradation ladder, concurrent polite fetch, artifact persistence to `runs/<domain>/artifacts/`
- [x] CI wired (`.github/workflows/ci.yml` at the repo root): `skills-ref validate` x8, manifest lint, schema-drift check, pytest smoke suite -- all run against a local fixture server, no live network dependency
- [x] **DoD met:** `run_audit.py` crawls a real site (tested against docs.python.org and a local fixture) and emits a schema-valid report with zero findings. Confirmed deterministic: two runs, byte-identical modulo `audited_at`/`duration_s` (`tests/test_smoke.py::test_determinism_across_runs`).

**Notes:**

*skills-ref, for real:* rather than guess at the "6 legal frontmatter keys" CLAUDE.md mentions, read the actual validator source (`npx skills-ref` pulls the real `skills-ref` npm package) at `validator.js` -- confirmed the allowed set, the name-format rules (lowercase, <=64 chars, no leading/trailing/double hyphens, must match directory name after NFKC normalization), and the description length cap (<=1024 chars). This is why every SKILL.md passed validation on the first real run, not after several rounds of guessing.

*marketplace.json format assumption, flagged explicitly:* `skills-ref` has no marketplace-level schema of its own -- "marketplace.json, exactly one entrypoint" is the hackathon brief's own convention, and the original brief document isn't available in this session, only CLAUDE.md's summary of it. Modeled the file on Anthropic's own real `.claude-plugin/marketplace.json` (fetched from `anthropics/skills` on GitHub) -- `name`/`owner`/`metadata`/`plugins[].skills`. "Exactly one entrypoint" is expressed two ways: (1) a custom `metadata.entrypoint` field naming `ai-visibility-orchestrator`, checked by `lint_marketplace.py`; (2) every other skill's `description` is worded as "internal pipeline stage ... not meant to be invoked directly" so it wouldn't get triggered by a generic user request even though it's a technically valid, independently-invocable skill. Worth double-checking against the actual brief if it turns up.

*Where shared code lives:* the build plan's file tree only shows `scripts/` explicitly under `ai-visibility-orchestrator/`; it doesn't say where cross-stage code (Pydantic models, crawl core) should live. Put it in `src/brand_audit/` as a proper installable package (`pyproject.toml` + `pip install -e .`) rather than duplicating models across 8 skill folders -- every stage's future `scripts/` imports from it. This keeps each skill's own `scripts/` thin and stage-specific, which is what the composition story needs (see `references/composition.md`).

*Determinism bug caught by the smoke test:* first local-fixture run showed `0/1 sampled pages reachable` -- turned out `run_audit.py`'s site-normalization always prepends `https://` when no scheme is given, which silently broke against the plain-HTTP local fixture server. Not a real bug for actual audit targets (real sites serve HTTPS), but worth remembering: `run_audit.py http://localhost:PORT` needs the explicit scheme for local/test use.

*Next session should:* start Day 3 (stage ① REACH detectors + stage ② RENDER dual-fetch differential). The REACH detector layer has real material to work from already -- `REACH-001`/`REACH-002`/`REACH-003` in `references/taxonomy.md` are three field-verified mechanisms ready to become actual `Finding`-emitting code, not hypothetical rules. Same for `RENDER-001`. This should make Day 3 mostly translation (taxonomy entry -> detector) rather than fresh discovery.

## Day 3 — Sun 30 Aug · Stage ① REACH + Stage ② RENDER
**Status:** not started

**DoD:** the differ correctly flags the JS-only-price fixture and stays silent on the clean control.

## Day 4 — Mon 31 Aug · Stage ③ EXTRACT
**Status:** not started

**DoD:** stage ③ passes fixtures; contradiction detector has zero false positives on controls.

## Day 5 — Tue 1 Sep · Stage ④ RETRIEVE (part 1)
**Status:** not started

**DoD:** given a fixture site, produces a reproducible answerability matrix. Two runs, byte-identical output.

## Day 6 — Wed 2 Sep · Stage ④ part 2 + Stage ⑤ CITE
**Status:** not started

**DoD:** all detection stages complete. Full pipeline runs end-to-end on the wild corpus without crashing.

## Day 7 — Thu 3 Sep · Stage ⑥ ARRIVE
**Status:** not started

**DoD:** engagement stage produces findings visibly about AI-referred arrivals, not a generic UX audit.

## Day 8 — Fri 4 Sep · Orchestration, falsification, output
**Status:** not started

**DoD:** one command → JSON + HTML + Markdown summary, schema-valid, under 5 minutes.

## Day 9 — Sat 5 Sep · Evaluation & precision hardening
**Status:** not started

**DoD:** FP-rate on clean controls ≈ 0; three identical runs; no crashes on the sweep.

## Day 10 — Sun 6 Sep · Package & narrative
**Status:** not started

**DoD:** zip built, unzipped in a clean container, run end-to-end from the README instructions alone.
