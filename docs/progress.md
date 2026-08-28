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
**Status:** done

- [x] `crawl-reach-audit` detectors (`skills/crawl-reach-audit/scripts/detect.py`): `REACH-001` (named AI-UA robots block), `REACH-002` (locale-redirect empty body), `REACH-003` (WAF/bot-challenge block) translated directly from Day 1 field evidence; `REACH-004` (soft-404), `REACH-005` (canonical integrity), `REACH-006` (sitemap health) engineering-derived from the build plan's own Day 3 bullet list. All severity-computed via the new `src/brand_audit/severity.py` (the `f(stage, blast_radius, confidence)` function from `severity-model.md` -- implemented for real, not deferred again).
- [x] `render-gap-audit`'s dual-fetch differential (`skills/render-gap-audit/scripts/render_detect.py`): fact-level diff (currency/numeric/date/contact, regex-based -- "entity" extraction deliberately left undone rather than faked, see Notes), noise suppression (today's date, hex/CSRF-looking tokens), primary empty-shell signal plus a secondary per-fact-category signal for partial render gaps.
- [x] **DoD met, as an executable test, not just eyeballed:** `tests/test_render_gap.py` builds a `tests/fixtures/js-only-price` fixture (empty `<div id="app">` shell, JS injects the content on load) and asserts the differ flags it (`RENDER-001`, critical, high confidence) while `tests/fixtures/clean-control` stays silent.
- [x] `run_audit.py` now runs both stages end-to-end; render stage gracefully skips (records `render_stage_skipped_no_playwright` degradation, `ai_readiness.render: skipped`) when playwright isn't installed, never guesses.
- [x] Test suite grown to 14 tests (unit tests for every REACH detector against synthetic fixtures, not just the two end-to-end fixture sites); CI split into two jobs so the base job stays representative of a judge's bare machine (no playwright) while a second job proves the render detector itself works.

**Notes:**

*Real-site validation, not just fixtures:* re-ran the pipeline against nytimes.com and curve.finance -- the two real sites Day 1 used to hand-derive `REACH-001` and `REACH-003` -- to check the automated detectors reproduce the by-hand findings. `REACH-001` caught nytimes.com correctly but initially under-scored it (`medium` instead of `critical`) because the site blocks 11 of 12 named bots, not literally all 12 (it allows plain `Applebot` while blocking `Applebot-Extended` -- Apple's own real distinction between its search-indexing and AI-training bots). Fixed by changing the site-wide threshold from exact-equality to `>=90%`, which is more robust and still doesn't fire on a genuinely partial block. `REACH-003` did **not** reproduce against curve.finance this time -- its WAF let 2 of 3 probe UAs through, unlike Day 1's all-3-blocked result. Investigated rather than dismissed: the detector's own gating (`skip if robots.txt is readable`) correctly stayed silent rather than guessing, and the live inconsistency itself is a useful data point -- WAF/bot-challenge behavior is adaptive and not fully reproducible run-to-run, which is exactly why `finding-verification`'s re-fetch/reproduction check (Day 8) exists. Recorded here rather than treated as a bug to hide.

*A real module-naming bug, caught before it shipped:* both `crawl-reach-audit` and `render-gap-audit` initially had a script named `detect.py`. Since both directories get added to `sys.path` by `run_audit.py`, Python's global module cache would have silently returned whichever one loaded first for both imports -- a real bug that unit tests alone wouldn't have caught (they only import one skill's detectors at a time) but the wired-up `run_audit.py` would have hit immediately. Renamed the render one to `render_detect.py`.

*"Entity" fact extraction, honestly skipped:* the build plan names five fact types for the differential (numeric/currency/date/entity/contact); only four are implemented. A real entity extractor needs an NER model, which conflicts with the project's own "no model weights" constraint, and a naive regex heuristic (e.g. "any capitalized multi-word phrase") would be noisy enough to undermine the "few false positives" goal. Documented as a deliberate gap in `render_detect.py`'s docstring rather than papered over with a bad heuristic.

*Severity function implemented now, not deferred to Day 8:* `severity-model.md` said the `f()` function was Day 8 work, but since Day 3's detectors needed to assign severity to real findings *today*, implementing the already-fully-specified decision table now (rather than hand-assigning severities inconsistently and reconciling later) was strictly less work. `src/brand_audit/severity.py` is the real implementation; Day 8 is now about the *merge/dedup* half of finding-verification, not severity itself.

*Next session should:* start Day 4 (stage ③ EXTRACT: `extruct` parse/validate, schema-vs-visible-text contradiction detection, semantic HTML integrity, facts-locked-in-images). The Allbirds control case from Day 1 field research (complete `ProductGroup`/`Offer` JSON-LD in raw HTML) is a ready-made positive-control fixture candidate.

### Post-Day-3 review pass (full-codebase audit, requested explicitly)

Re-read every file with fresh eyes against CLAUDE.md's hard constraints rather than trusting the code because I'd written it. Found and fixed six real issues, two of them meaningful:

1. **Robots.txt permission was parsed but never enforced (compliance gap).** `RobotsPolicy.allowed()` existed and was correct, but nothing in `run_audit.py` ever called it before fetching a sampled page -- every sampled URL got fetched regardless of `Disallow` rules, which directly violates the "read-only, robots-respecting" hard constraint. Fixed: sampled URLs are now filtered through `robots.allowed()` before any fetch. Verified end-to-end, not just by code inspection: `tests/test_robots_compliance.py` serves a fixture whose sitemap deliberately lists a page robots.txt disallows, then asserts no artifact anywhere in the run directory references that URL. Re-ran against nytimes.com afterward -- it now correctly fetches 0 of its sampled pages (all disallowed) while still detecting and reporting `REACH-001`, since that detection is a robots.txt rule lookup, not a fetch.
2. **The 5-minute watchdog was decorative.** `BudgetManager` was instantiated but `elapsed()`/`over_budget()`/`maybe_degrade()` were never called anywhere -- only the static `--max-pages`/`--max-render-pages` caps offered any real protection, with no adaptive mid-run bailout. Fixed: the REACH and RENDER stages are now wrapped in `asyncio.wait_for(budget.remaining())`; a timeout produces a valid, honestly-degraded report (`degradations: ["*_timed_out_budget_exhausted"]`) rather than running past the cap or crashing. Also added a proactive check (`MIN_RENDER_BUDGET_S`) so RENDER doesn't even start Chromium when there isn't enough budget left to be worth it. Verified with `tests/test_budget.py` (a near-zero budget produces a fast, degraded report, not a hang).
3. **`detect_sitemap_health` (REACH-006) was unreachable dead code.** `discover_sitemap_urls` always falls back to `[base_url]` when nothing is discovered, so the caller's `sitemap_reachable=bool(sitemap_urls)` was always `True` regardless of whether the declared sitemap actually worked -- the detector's condition could never be met. Fixed by having `discover_sitemap_urls` return `(urls, sitemap_fetch_ok)` as two separate signals. Caught with zero prior test coverage on this detector -- added `tests/test_reach_detectors.py::test_sitemap_health_*` while fixing it.
4. **`render_fetch` silently converted a render timeout/failure into `""`**, indistinguishable from "genuinely rendered to nothing." Real risk: a page whose render times out (persistent websockets/analytics never reaching `networkidle` -- curve.finance did exactly this during Day 1 field research) would produce a false *negative* rather than being flagged as unknown, which is backwards for a detector that's supposed to fail toward "flag it," not "miss it." Fixed: `render_fetch` now returns `None` on failure; the caller skips comparison for those pages rather than guessing either direction. Also switched Playwright's wait strategy from `networkidle` (fragile on real sites with persistent connections) to `load` + a short settle delay.
5. **`detect_canonical_issues` used a regex requiring `rel=` before `href=` in source order**, silently missing valid HTML with reversed attribute order. Rewritten using `selectolax` (already a project dependency) for real HTML parsing instead of a hand-rolled regex.
6. **`REACH-001` only ever checked the homepage path**, so a robots.txt rule scoped to a specific path (e.g. `Disallow: /products`) would be invisible to the detector even though it's a genuine, reportable defect. Fixed to check every sampled URL (a robots.txt rule lookup, not a fetch, so this is free) and made the site-wide/degrades classification two-dimensional (bot coverage x page coverage) so a path-scoped block doesn't get miscategorized as site-wide just because it fully blocks bots on that one path.

Smaller, lower-priority items noted but deliberately not fixed this pass (would be diminishing returns right now): `assemble_report`'s headline was picking `findings[0]` by list-concatenation order rather than the most severe finding -- fixed, this one was quick. `pages_crawled` in the run manifest now means "successfully fetched" rather than "attempted" -- also fixed, one-line change. Not fixed: the `today_iso` date-suppression in the fact-diff only matches exact ISO format, so a same-day "generated at" timestamp in a different format wouldn't be suppressed (low impact -- it's already a secondary, medium-confidence signal); render-page selection for `--max-render-pages` has no page-class prioritization yet (acceptable, page classification doesn't exist until later).

All 24 tests pass (10 new this pass); re-validated against docs.python.org (0 findings, clean) and nytimes.com (correctly still flags `REACH-001` critical, now with 0 pages actually fetched); determinism reconfirmed byte-identical. `skills-ref validate`, manifest lint, and schema-drift check all still green. Zip payload (excluding `.venv`/`node_modules`/caches) is ~324 KB, nowhere near the 50 MB cap.

**Plan-alignment assessment:** every hard constraint in CLAUDE.md is now actually enforced in code, not just documented -- the two compliance-critical gaps (robots-respecting, 5-minute watchdog) were real and are the main reason this review was worth doing before Day 4 added more surface area on top of an unenforced foundation. Detection accuracy and composition are on track per the rubric self-check in the build plan; determinism holds; the taxonomy's mechanism-first discipline held up under fresh scrutiny (no entry needed rewriting, only the code implementing REACH-001 needed to actually match what the taxonomy entry already said). No scope or architecture changes -- this was entirely a correctness pass.

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
