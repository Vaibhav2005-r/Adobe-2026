# Progress Log

Tracks DoD completion against `docs/build-plan.md` Part 7, one entry per day. Update as each day's DoD is met so a fresh session can pick up where the last one left off.

## Day 1 — Fri 28 Aug · Field research + taxonomy
**Status:** core pass done; corpus breadth is the open item

- [x] Wild corpus assembled — 9 sites given the full treatment (live-assistant query + technical diagnosis), 3 more screened for RENDER only. Short of the 10–15 floor; see Notes.
- [x] Each of the 9: asked a live assistant (Claude's web search, used as the "live assistant" proxy — see Notes) a buyer question about the brand, recorded cited/misrepresented/absent, then manually diagnosed why via `curl` (robots.txt, raw HTML, headers, JSON-LD) and cross-checked with a second UA where the result was surprising
- [x] Defect taxonomy started at `brand-ai-readiness-audit/skills/ai-visibility-orchestrator/references/taxonomy.md` — 2 shipped findings, 1 reproduced cross-site pattern, 2 explicit observations pending falsification, 1 low-severity note, 2 positive controls. **Not** frozen at ~30 — see Notes on why padding was rejected.
- [x] Every taxonomy entry states a mechanism, not just a symptom (self-checked against the admission rule while writing each one)

**DoD status:** partially met. The mechanism-first discipline is met for every entry that exists. The ~30-entry / 10–15-site targets are not met — carrying forward as the first item of Day 2's buffer rather than padding today's taxonomy with unverified entries.

**Notes:**

*Methodology:* used Claude's own web-search tool as the "live assistant" being probed (rather than separately driving ChatGPT/Perplexity UIs, which would have needed logins/rate-limit handling out of scope for a non-interactive session) — reasonable as a first-pass proxy since it's a real retrieval-and-cite pipeline, not a simulation, but worth re-running key queries through 1–2 other assistants before the taxonomy is trusted as generalizing across assistants, not just this one's retrieval quirks.

*Corpus (9 fully diagnosed):* stripe.com (SaaS/fintech), linear.app (Next.js SaaS), allbirds.com (Shopify DTC), nytimes.com (news, explicit AI-bot blocker), notion.so→notion.com (JS-heavy PaaS), docs.python.org (static docs, control), brittanychiang.com (single-page portfolio, Next.js SSG), theverge.com (news/tech, open robots but citation gap), zalando.de (non-English/German retailer). Plus 3 screened for the RENDER differential only (framer.com, webflow.com, figma.com — all SSR-clean, no defect).

*Why not 10–15:* ran out of session budget verifying findings properly (each diagnosed site took several `curl` round-trips to avoid guessing) rather than rushing shallow passes on more sites. Given the taxonomy's own "if it only helps one site, delete it" discipline, 9 well-diagnosed sites that produced one reproduced 3-for-3 pattern felt like better use of the time than 15 shallow ones that produced 15 single-sample guesses.

*Why not ~30 entries:* the same reasoning — TRUST-002 and TRUST-003 are explicitly marked as unverified single-sample observations rather than promoted to scored findings, per the taxonomy's own falsification discipline (which the build plan otherwise schedules for Day 8). RENDER-00x, CHUNK-00x, and ENGAGE-00x are honestly empty: no JS-only-content site was found in this pass (worth noting — modern marketing sites skew SSR by default; the render-gap mechanism may show up more on app/dashboard surfaces than marketing pages), and CHUNK/ENGAGE aren't testable at all until the stage ①/②/⑤ pipelines exist (Day 5–7).

*Biggest surprise:* TRUST-001 (SaaS pricing aggregator displacement) — three well-optimized, technically reachable SaaS sites (Stripe, Linear, Notion) were **zero-for-24** on brand-domain citations for their own pricing, entirely displaced by third-party pricing round-ups/calculators, while Allbirds (e-commerce, product-spec query) was 6-for-10 brand-domain. This is a genuinely new mechanism not in the build plan's original list and is query-genre-specific, not a general extractability problem — the contrast with Allbirds is what proves that (see taxonomy Controls section).

*Next session should:* (1) extend the corpus toward 12–15 sites, prioritizing categories not yet covered (non-English site with a native-language control query, a confirmed WordPress-powered small/local business, a genuine JS-only-content example); (2) re-run TRUST-002 and TRUST-003 with a second query each to either promote them to findings or drop them; (3) start Day 2 scaffolding once taxonomy coverage feels sufficient, rather than blocking Day 2 entirely on hitting 30.

---

## Day 2 — Sat 29 Aug · Contracts + scaffolding
**Status:** not started

**DoD:** `run_audit.py` crawls a site, emits a schema-valid report with zero findings. Skeleton end-to-end before any detector exists.

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
