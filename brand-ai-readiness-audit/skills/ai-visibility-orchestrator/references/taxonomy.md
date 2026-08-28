# Defect Taxonomy

The rule pack. Every finding emitted by any stage skill must map to an entry here. Entries are added only after field research surfaces a real, reproducible failure — never invented from a best-practices checklist.

**Admission rule (non-negotiable):** an entry must state a *mechanism* — how the retrieval pipeline actually breaks — not just a symptom. "Missing FAQPage schema" is a symptom. "Assistants that rely on FAQPage JSON-LD to extract Q&A pairs skip freeform prose, so the answer never enters the corpus" is a mechanism. If a candidate rule only helps one site in the wild corpus, it's overfitting — cut it, don't add it.

**Falsification discipline (applied from Day 1, not bolted on at Day 8):** an entry backed by only one query/one sample is not a shipped finding — it's an **observation**, carried forward until a second, independent probe reproduces it or contradicts it. Confidence is stated explicitly on every entry.

## Entry format

```
### <ID> — <short title>
- **Stage:** reach | render | extract | chunk | trust | engage
- **Mechanism:** why this actually breaks retrieval/citation (not a symptom)
- **Detection method:** how the detector identifies it, deterministically
- **Evidence artifact:** what gets captured to prove it (URL, selector/byte-offset, extracted strings, hashes)
- **Severity default:** critical | high | medium | low (per severity-model.md — blast radius × stage × confidence)
- **Confidence:** high | medium | low — and why
- **Fix pattern:** the mechanism-sound remediation
- **Source:** which wild-corpus site(s) surfaced this, and the query that failed
```

---

## REACH-00x

### REACH-001 — Explicit AI-crawler block, site-wide
- **Stage:** reach
- **Mechanism:** `robots.txt` carries explicit `Disallow: /` rules for every major documented AI crawler by name (`GPTBot`, `ChatGPT-User`, `anthropic-ai`, `ClaudeBot`, `Google-Extended`, `PerplexityBot`, `CCBot`, `Bytespider`, `Applebot-Extended`). A robots-respecting AI crawler never fetches a single byte of the site, so the brand can only ever appear in an assistant's answer via third-party syndication or licensing — never a first-party citation.
- **Detection method:** parse `robots.txt` with `protego`; for each named AI-UA in the documented bot list, check for a `Disallow: /` (or equivalent broad disallow) rule; flag if the named-AI-UA rule set is more restrictive than `User-agent: *`.
- **Evidence artifact:** the raw `robots.txt` block per UA (URL + full matched rule text).
- **Severity default:** critical (blocks stage ① site-wide — nothing downstream can work).
- **Confidence:** high — directly observed in the fetched `robots.txt`, and independently corroborated by a live-assistant citation test returning zero first-party URLs.
- **Fix pattern:** none within the audit's own scope (recommend-only, per the "no writes to the audited site" constraint) — surface the tradeoff explicitly: the brand is choosing licensing/opt-out over AI-assistant visibility, and should confirm that's intentional.
- **Source:** nytimes.com; live query "is New York Times free to read or subscription required" → 0/9 returned links were nytimes.com; robots.txt confirmed `Disallow: /` for 9 named AI bots including GPTBot and ClaudeBot.

### REACH-002 — Geo/locale redirect returns an empty body at the canonical marketing URL
- **Stage:** reach
- **Mechanism:** the most commonly linked/canonical path for a high-value page (e.g. `/pricing`) responds with an HTTP 3xx and **zero bytes of body** (`content-length: 0`), redirecting to a locale-prefixed variant (e.g. `/in/pricing`) chosen by server-side geo-detection of the requester's IP. A stateless AI crawler with no persistent session/cookie and no reason to prefer one locale over another either (a) doesn't follow the redirect, or (b) follows it to whatever locale variant its egress IP maps to — meaning the "citable" URL a person would naturally link to carries no content of its own, and different crawls of the same nominal URL can resolve to different regional copy.
- **Detection method:** fetch canonical high-value paths (pricing, product, docs index) with no cookies and a neutral/rotating egress; flag any 3xx response with `content-length: 0` whose `Location` is the same path prefixed with a locale/region segment.
- **Evidence artifact:** response headers showing status code, `content-length: 0`, and `Location` header; reproduced across two different UA strings to rule out a UA-specific block.
- **Severity default:** high (blocks stage ① for the single highest-value page on the site, though the destination locale variant does carry real content).
- **Confidence:** high — reproduced identically with `Mozilla/5.0 (compatible; GPTBot/1.0)` and a bare `GPTBot` UA string.
- **Fix pattern:** serve canonical, locale-neutral pricing content directly at the un-prefixed path (e.g. USD default), and reserve geo-redirects for browser sessions carrying explicit locale signals (`Accept-Language`, prior cookie) rather than IP alone.
- **Source:** stripe.com/pricing; query "Stripe payment processing fees for small business 2026" — `curl -I -A GPTBot https://stripe.com/pricing` → `HTTP/2 307`, `content-length: 0`, `location: https://stripe.com/in/pricing`.

## RENDER-00x

_(No confirmed defect this pass — see Day 1 notes in `docs/progress.md`. Four JS-heavy marketing sites screened — framer.com, webflow.com, figma.com, linear.app/pricing — all returned substantial fact-bearing text in the raw, non-JS HTTP response; none showed the JS-only-content pattern. Kept open, not deleted: this is exactly the "highest-ROI" mechanism per the build plan, and modern marketing sites skewing SSR-by-default doesn't mean product/app-shell pages do. Retarget at dashboard/logged-in-adjacent surfaces and older CSR-era sites next pass, per the mechanism, not by re-testing the same site shape.)_

## EXTRACT-00x

_(No confirmed defect this pass. Positive control recorded below under Controls.)_

## CHUNK-00x

_(Not yet testable — requires the stage ①/② corpus-gating pipeline, built Day 5–6. No entries expected until then.)_

## TRUST-00x

### TRUST-001 — Third-party aggregator content displaces the brand's own page for "cost/pricing" intent queries
- **Stage:** trust (cite)
- **Mechanism:** "how much does X cost" is a well-established content genre that third-party sites (pricing round-ups, fee calculators, "hidden costs" explainers) purpose-build to rank for the buyer's exact phrasing, restating the vendor's published number in a terser, more directly-answer-shaped format than the vendor's own marketing page. This happens **even when the vendor's page is technically reachable and fact-dense** — the failure isn't extractability, it's that the aggregator's content is structured *as an answer*, while the vendor's page is structured *as a sales pitch*, and retrieval favors the shape that matches the query.
- **Detection method:** run the templated pricing-intent query for the brand; check whether any returned source URL matches a registered brand domain; if zero across the sample, flag with `scope: {checked: N, affected: N}`.
- **Evidence artifact:** the full source-link list per query, annotated brand-domain / third-party.
- **Severity default:** medium (degrades stage ⑤ citation quality — the fact is correct and retrievable, just uncredited to the brand, so the brand loses framing control and the "cited by name" signal).
- **Confidence:** high — reproduced identically on 3 of 3 independent SaaS brands tested (Stripe, Linear, Notion): 0 of 24 total source links across the three queries pointed to the brand's own domain, despite Linear's raw HTML confirming its `$10`/`$16` prices are present without JS.
- **Fix pattern:** publish a plainly-labeled, FAQ/QAPage-schema-marked pricing answer in the exact phrasing buyers search ("Stripe charges 2.9% + 30¢ per transaction") as a direct, front-loaded answer rather than embedding the number in marketing narrative; pursue corroboration by seeding the same fact into high-authority third-party comparison sources rather than relying solely on the owned page.
- **Source:** stripe.com (query: "Stripe payment processing fees for small business 2026"), linear.app (query: "Linear app pricing cost per user 10 person engineering team"), notion.so (query: "Notion pricing plans for small team features included").

### TRUST-002 — [Observation, unverified] Named-entity query fails to surface the entity's own domain despite an open REACH stage
- **Stage:** trust (cite) — mechanism not yet localized to a specific downstream stage
- **Mechanism (tentative):** a query that directly names the brand and asks about content the brand indisputably published ("The Verge review iPhone 17") returned zero results from the brand's own domain, and the assistant's own response acknowledged the gap explicitly. `robots.txt` confirms `GPTBot: Allow: /` — so this is not a REACH block. Candidate mechanisms not yet distinguished: (a) general web-search index coverage gap unrelated to the site itself, (b) the review is delivered via a format that resists chunking (long paywall-adjacent article, video-led format with the verdict off-page), (c) something render/extract-stage specific not yet inspected.
- **Why this is an observation, not a finding:** single query, single sample — fails the "reproduced" bar (`references/composition.md` / falsification pass rule: a defect on 1/1 cannot claim anything). Needs a second, differently-phrased query and a direct page-level render/extract inspection of an actual review URL before it can ship as a scored finding.
- **Evidence artifact:** WebSearch result set (9 links, 0 theverge.com) + robots.txt `Allow: /` for GPTBot.
- **Confidence:** low.
- **Source:** theverge.com; query "The Verge review iPhone 17".

### TRUST-003 — [Observation, unverified] Query-language / content-language mismatch cedes citation to translated third-party summaries
- **Stage:** trust (cite)
- **Mechanism (tentative):** an English-language buyer query about a policy the brand publishes authoritatively in its primary market language returns zero brand-domain results, with the entire result set being English-language third-party explainer sites — consistent with retrieval preferring content already in the query's language over a correct-but-untranslated primary source, even when that source is reachable (`robots.txt` empty/unblocked, homepage resolves 200).
- **Why this is an observation, not a finding:** single query, no control run in the brand's native language, no check for an official English-market subdomain — needs both before it can ship as a scored finding.
- **Evidence artifact:** WebSearch result set (7 links, 0 zalando.de/zalando.com); `zalando.de/robots.txt` empty; `zalando.com` → 200; `zalando.co.uk` → 403.
- **Confidence:** low.
- **Source:** zalando.de; query "Zalando return policy online orders".

### TRUST-004 — [Low severity / proactive] Missing entity-anchoring structured data + identity fragmented across versioned subdomains
- **Stage:** trust
- **Mechanism:** the site's raw HTML contains zero `application/ld+json` blocks — no `Person` schema, no `sameAs` linking the nav's GitHub/LinkedIn/CodePen profiles to a canonical identity — so there's no machine-verifiable anchor tying the page's prose bio to those profiles. Separately, a live citation query surfaced four distinct indexed domains for the same person (current domain plus `v2.` and `v4.` version subdomains and a GitHub Pages mirror), meaning identity signal is split across four crawlable origins rather than consolidated on one canonical entity.
- **Why this is low severity, not higher:** the live citation test still succeeded well (4 of 9 results were the person's own domains) — this is a structural risk (single point of drift if any variant goes stale or diverges), not an observed failure.
- **Evidence artifact:** raw HTML fetch of the homepage showing 0 `<script type="application/ld+json">` blocks despite 4,789 chars of bio/nav text being present without JS (so this is not a RENDER problem); WebSearch result set showing 4 distinct domains for one identity.
- **Severity default:** low.
- **Confidence:** high (directly observed, not a citation-outcome inference).
- **Fix pattern:** add `Person` JSON-LD with `sameAs` to the canonical profiles; 301-redirect legacy version subdomains to the current canonical domain.
- **Source:** brittanychiang.com; query "Brittany Chiang frontend engineer portfolio background".

## ENGAGE-00x

_(Not yet testable — requires the stage ⑤ citable-page-set gating built Day 6–7. No entries expected until then. Note: REACH-002's redirect-to-locale behavior is adjacent to the "context reset" ENGAGE mechanism the build plan names — revisit whether it also deserves an ENGAGE-side entry once stage ⑥ is built and can test it as a *deep-link arrival* problem, not just a *crawler-fetch* problem.)_

---

## Controls (no defect — recorded because a negative result is evidence too)

- **docs.python.org** — official docs and `pip.pypa.io` (an official project domain) both appear directly in citation results for a how-to query; `robots.txt` disallows only `/dev`, `/release`, and EOL version paths, current docs stay fully open. Baseline "everything working" case.
- **allbirds.com** — product page carries a complete `ProductGroup`/`Offer` JSON-LD block (price, currency, availability, rating) in the raw non-JS HTML. For a narrowly-scoped product-spec query, 6 of 10 returned links were allbirds.com pages — the brand's own domain dominated the result set. Recorded specifically as a **contrast case against TRUST-001**: good EXTRACT hygiene correlates with strong citation on product-spec queries, but did *not* help Stripe/Linear/Notion on pricing-genre queries — suggesting TRUST-001's mechanism is query-genre-specific (comparison/calculator content has its own gravity), not a general EXTRACT failure. This distinction is what keeps TRUST-001 from being overfit advice ("just add schema").

---

**Status:** Day 1 pass — 2 shipped findings (REACH-001, REACH-002), 1 high-confidence cross-site pattern (TRUST-001, 3-for-3 reproduced), 2 explicit observations pending falsification (TRUST-002, TRUST-003), 1 low-severity structural note (TRUST-004), 2 positive controls. Deliberately not padded to ~30 — RENDER/CHUNK/ENGAGE are honestly empty pending later stages' tooling and further corpus breadth; see `docs/progress.md` for what's next.
