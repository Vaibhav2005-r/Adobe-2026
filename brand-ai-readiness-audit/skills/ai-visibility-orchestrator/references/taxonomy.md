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
- **Detection method:** parse `robots.txt` with `protego`; for every sampled URL, check each named AI-UA for a `Disallow` rule; a URL only counts if the exclusion is AI-*specific* — a generic, unnamed crawler (`GENERIC_CRAWLER_UA`, a real Googlebot string) must still be allowed there, or the rule is a blanket `User-agent: *` exclusion that would catch any crawler equally (a staff directory, an admin panel), not the "brand deliberately disallows named AI crawlers" mechanism this entry is about. Blast radius is two-dimensional (bot coverage × page coverage, ≥90% each for site-wide, per `severity-model.md`'s REACH-002 worked example on why a single high-value page can still warrant `high` even when not literally site-wide).
- **Evidence artifact:** the raw `robots.txt` block per UA (URL + full matched rule text), plus the affected-page fraction stated in the finding's own title.
- **Severity default:** critical (blocks stage ① site-wide — nothing downstream can work), `medium` when the pattern doesn't clear the site-wide threshold.
- **Confidence:** high — directly observed in the fetched `robots.txt`, and independently corroborated by a live-assistant citation test returning zero first-party URLs.
- **Fix pattern:** none within the audit's own scope (recommend-only, per the "no writes to the audited site" constraint) — surface the tradeoff explicitly: the brand is choosing licensing/opt-out over AI-assistant visibility, and should confirm that's intentional.
- **Source:** nytimes.com; live query "is New York Times free to read or subscription required" → 0/9 returned links were nytimes.com; robots.txt confirmed `Disallow: /` for 9 named AI bots including GPTBot and ClaudeBot. The AI-specific-targeting check was added Day 9 after the automated detector false-positived on a compliance fixture's ordinary `User-agent: *` page exclusion — see `docs/progress.md`.

### REACH-002 — Geo/locale redirect returns an empty body at the canonical marketing URL
- **Stage:** reach
- **Mechanism:** the most commonly linked/canonical path for a high-value page (e.g. `/pricing`) responds with an HTTP 3xx and **zero bytes of body** (`content-length: 0`), redirecting to a locale-prefixed variant (e.g. `/in/pricing`) chosen by server-side geo-detection of the requester's IP. A stateless AI crawler with no persistent session/cookie and no reason to prefer one locale over another either (a) doesn't follow the redirect, or (b) follows it to whatever locale variant its egress IP maps to — meaning the "citable" URL a person would naturally link to carries no content of its own, and different crawls of the same nominal URL can resolve to different regional copy.
- **Detection method:** fetch canonical high-value paths (pricing, product, docs index) with no cookies and a neutral/rotating egress; flag any 3xx response with `content-length: 0` whose `Location` is the same path prefixed with a locale/region segment.
- **Evidence artifact:** response headers showing status code, `content-length: 0`, and `Location` header; reproduced across two different UA strings to rule out a UA-specific block.
- **Severity default:** high (blocks stage ① for the single highest-value page on the site, though the destination locale variant does carry real content).
- **Confidence:** high — reproduced identically with `Mozilla/5.0 (compatible; GPTBot/1.0)` and a bare `GPTBot` UA string.
- **Fix pattern:** serve canonical, locale-neutral pricing content directly at the un-prefixed path (e.g. USD default), and reserve geo-redirects for browser sessions carrying explicit locale signals (`Accept-Language`, prior cookie) rather than IP alone.
- **Source:** stripe.com/pricing; query "Stripe payment processing fees for small business 2026" — `curl -I -A GPTBot https://stripe.com/pricing` → `HTTP/2 307`, `content-length: 0`, `location: https://stripe.com/in/pricing`.

### REACH-003 — WAF/bot-challenge blocks the canonical domain outright, independent of robots.txt policy
- **Stage:** reach
- **Mechanism:** the canonical domain returns a block or an infinite redirect-into-challenge loop for any non-interactive HTTP client — reproduced identically across a bare `GPTBot` UA, a `Mozilla/5.0 (compatible; GPTBot/1.0)` UA, and a full desktop-Chrome UA string carrying no bot signature at all. This rules out a UA-based robots.txt-style policy decision: `robots.txt` itself was unreachable, redirected into the same challenge loop, so the file that's supposed to declare crawl permissions can't even be read. This is an infrastructure-level bot-management layer (Cloudflare-style JS challenge), not a declared policy — meaning a fully honest, robots-compliant AI crawler gets nothing, with no way to even discover whether it would have been allowed.
- **Detection method:** fetch the canonical domain and its `/robots.txt` with 3 UA variants (a declared AI bot, a generic bot-like string, and a full browser string with no bot hint); flag if all three receive a challenge/block/redirect-loop response instead of content.
- **Evidence artifact:** `curl -I https://curve.finance/` returned `403` body `"Your request was blocked."` on first probe; repeat probes across all 3 UAs returned a `307` redirect loop; the `robots.txt` fetch redirected into the same loop rather than returning rules. Cross-checked with a real headless browser (full JS execution): the rendered page showed only `"Curve"` (5 characters) with the nav present but the swap widget and stat placeholders (`Total Deposits: -`, `Daily Volume: -`, `Crypto Volume Share: -`) never resolving.
- **Severity default:** critical (blocks stage ① site-wide, and worse than an explicit `Disallow` — the crawler can't even read the policy meant to inform it).
- **Confidence:** high — reproduced across 3 distinct UA strings, and independently corroborated with a real headless-browser render showing the same near-empty result.
- **Fix pattern:** exempt documented AI-crawler UAs from the JS-challenge gate, or at minimum always serve `/robots.txt` unchallenged — most bot-management vendors document this as a best practice already.
- **Source:** curve.finance (discovered while screening curve.fi to curve.finance for the RENDER differential; no live-assistant query run yet — flagged for a follow-up citation probe).

### REACH-004 — Soft-404: HTTP 200 on a page that reads as missing
- **Stage:** reach
- **Mechanism:** a page returns HTTP 200 (a healthy status code) but its actual content says the thing isn't there ("page not found", "no longer available", etc.), combined with unusually short content. A crawler that trusts the status code — which is the normal, correct thing to do — treats this as valid, citable content; an assistant could cite a URL whose actual text tells a reader nothing is there.
- **Detection method:** for each fetched page, if `http_status == 200` and the stripped text is short (<300 chars) *and* matches a not-found phrase pattern, flag it. Both conditions are required — a real page that happens to mention "page not found" as a topic (e.g. an article about broken links) won't false-positive on the phrase match alone, because it won't also be a near-empty page.
- **Evidence artifact:** the URL, its HTTP status, and the stripped content that triggered the phrase match.
- **Severity default:** high (a single page returning wrong status is `page_class`-scoped, not site-wide).
- **Confidence:** medium — a keyword+length heuristic, not a certainty; a legitimately short page containing one of the trigger phrases in an unrelated context is possible, if unlikely given both conditions must hold.
- **Fix pattern:** return a real 404 (or 410) status for content that's actually gone.
- **Source:** engineering-derived from the build plan's Day 3 requirement ("status/soft-404 detection"), not yet observed on a real site during field research — implemented and unit-tested (`tests/test_reach_detectors.py`) against synthetic fixtures, not yet run against a live soft-404 in the wild. Flagged here so that gap is visible, not papered over.

### REACH-005 — Ambiguous or cross-domain `rel=canonical`
- **Stage:** reach
- **Mechanism:** either (a) a page emits two or more distinct `rel=canonical` hrefs, leaving a crawler unable to determine which URL should receive citation credit, or (b) a page canonicalizes to a different domain entirely, which — if unintentional (a staging/CDN template artifact is the common real-world cause) — means the brand's own domain never accrues citation authority for content it actually published. Deliberately does **not** flag a *missing* canonical tag: that's normal and common, not a defect, and flagging it would be exactly the kind of generic-checklist noise this project is trying to avoid.
- **Detection method:** parse `<link rel="canonical">` tags per page; flag if count > 1 with differing hrefs, or if the single href's domain differs from the page's own domain.
- **Evidence artifact:** the page URL and the canonical href(s) found.
- **Severity default:** medium (degrades citation-credit consolidation without blocking a stage outright).
- **Confidence:** medium — the pattern is unambiguous once matched, but whether a given cross-domain canonical is a real misconfiguration or an intentional syndication setup needs a human (or `finding-verification`) to confirm.
- **Fix pattern:** emit exactly one `rel=canonical` tag per page, self-referential unless cross-domain syndication is genuinely intended.
- **Source:** engineering-derived from the build plan's Day 3 requirement ("canonical integrity"); unit-tested against synthetic fixtures, not yet observed on a real site.

### REACH-006 — Declared sitemap is unreachable
- **Stage:** reach
- **Mechanism:** `robots.txt` declares a `Sitemap:` URL, but fetching it fails. Sitemap-first discovery — the fastest, most reliable way a crawler finds a site's pages — gets nothing, and the crawler falls back to slower internal-link discovery, which may miss pages entirely under a crawl-budget cap.
- **Detection method:** if `robots.txt` declares one or more sitemap URLs and none of them are fetchable, flag it.
- **Evidence artifact:** the declared sitemap URL(s).
- **Severity default:** medium (degrades discovery completeness without blocking the site outright — internal-link discovery is a fallback, not nothing).
- **Confidence:** high — directly observed (the URL either resolves or it doesn't).
- **Fix pattern:** fix or remove the declared sitemap URL.
- **Source:** engineering-derived from the build plan's Day 3 requirement ("sitemap health"); unit-tested, not yet observed on a real site.

### REACH-007 — WAF blocks a fetch even though robots.txt explicitly allows it
- **Stage:** reach
- **Mechanism:** `robots.txt` declares no `Disallow` covering these paths — they pass the crawler's own permission check before being fetched at all — but fetching them still returns a block-shaped status (403/429/503). An infrastructure layer (WAF/bot-management) is contradicting the site's own declared policy: robots.txt says "you're welcome here," and the site's actual behavior says otherwise. Distinct from `REACH-003`, which requires `robots.txt` itself to be unreadable; this is the more common real-world shape, where the declared policy is perfectly normal and permissive but doesn't reflect what the infrastructure layer actually does.
- **Detection method:** among sampled URLs that passed the robots-permission check, if ≥80% return a block-shaped status (403/429/503), flag it. The 80% threshold (not "any") is deliberate — a handful of isolated 403s (a genuinely gone page, a rate-limit blip) isn't a policy contradiction; the *majority* of an explicitly-allowed sample being blocked is.
- **Evidence artifact:** up to 5 `url -> status` pairs from the blocked subset.
- **Severity default:** critical (site-wide — the same infrastructure gate applies regardless of which allowed path a crawler requests).
- **Confidence:** high — directly observed status codes against paths that independently passed the robots-permission check.
- **Fix pattern:** align the WAF/bot-management allowlist with the declared robots.txt policy, or add explicit `Disallow` rules for what's actually blocked so crawlers don't waste budget discovering the contradiction themselves.
- **Source:** found on a real site during Day 6's wild-corpus validation sweep, not hypothesized first and confirmed later: allbirds.com's `robots.txt` is a standard, permissive Shopify robots.txt with no rule blocking the 8 sampled product/page URLs, yet every one of them returned HTTP 403 for this project's own declared crawler UA. Implemented and shipped the same day it was found.

## RENDER-00x

### RENDER-001 — Client-side-only rendering leaves an empty content shell for non-JS fetchers
- **Stage:** render
- **Mechanism:** the page ships an empty root container (`<div id="app"></div>` / `<div id="root"></div>`) with zero content in the initial HTTP response; every fact on the page is injected by JavaScript after load. A crawler that doesn't execute JS receives a page with nothing to extract, index, or cite, no matter how good the eventually-rendered content is. The failure isn't partial (some facts missing); it's total (zero facts present at the HTTP layer). **Empirically grounded, not assumed:** Vercel's crawler study found no evidence of JavaScript execution across 500M+ GPTBot fetches, measuring GPTBot downloading JS files in ~11.5% of requests and ClaudeBot in ~23.8% *without ever executing them*. **Two documented exceptions are deliberately excluded from this finding's claim** (corrected post-Day-10 after checking the evidence — the earlier wording implied all 12 probed UAs were JS-blind, which overclaims): Applebot uses a browser-based crawler that does render, and Gemini rides Googlebot's rendering infrastructure (`Google-Extended` is not a fetching crawler at all — it is a training-usage control token). The finding is therefore scoped to the fetch-only majority: GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-SearchBot, Claude-User, PerplexityBot, CCBot, Bytespider, anthropic-ai. See `brand_audit.crawl.JS_RENDERING_OR_NON_FETCHING_UAS`.
- **Detection method:** dual-fetch differential — plain HTTP GET vs. headless-rendered fetch of the same URL; diff extracted main-content text length; flag when the raw-fetch stripped text is near-zero (e.g. under ~50 chars, or just a `<title>`) while the rendered text is substantial.
- **Evidence artifact:**
  - `docsify.js.org` — raw HTML: `<div id="app"></div>` with **7 characters** of text on the page (`docsify`, from the title). Headless-rendered: **~800 characters**, including the full "What it is / Features / Examples / Donate / Community" sections.
  - `app.uniswap.org` — raw HTML: `<div id="root"></div>` with **64 characters** (`"Uniswap Interface You need to enable JavaScript to run this app."`). Headless-rendered: full swap-interface text including the buyer-relevant fact "Buy and sell crypto with zero app fees on 21+ networks including Ethereum, Unichain, and Base."
- **Severity default:** critical for a content-first site where the render gap covers effectively the entire page (docsify.js.org — the site's entire purpose is the missing content); high for an application shell (app.uniswap.org — content-bearing but not the site's sole purpose).
- **Confidence:** high — directly observed via matching-URL before/after comparison (curl vs. headless browser), reproduced identically on 2 independent sites built on different frameworks, and corroborated by the live-citation consequence below.
- **Citation consequence (why this matters beyond "the page is technically incomplete"):** for docsify.js.org, a live-assistant query ("what is docsify documentation generator how does it work") returned **zero citations of docsify.js.org** across 8 sources — the top result was `github.com/docsifyjs/docsify` (GitHub server-renders README markdown) instead, with the rest third-party blog explainers. The render gap didn't just hide content, it handed the citation to a different domain entirely. For Uniswap, the query ("does Uniswap charge fees to swap crypto tokens") again returned zero `app.uniswap.org` citations, but did surface `support.uniswap.org` and `developers.uniswap.org` — render-friendly sibling subdomains (Zendesk-style help center, docs site) that happened to compensate, alongside third-party crypto-news coverage.
- **Fix pattern:** server-render or statically pre-render at least the primary content/marketing surface — for a docs generator, an SSG build step; for an app shell, a lightweight prerendered snapshot (or a dedicated server-rendered landing/about page) served regardless of JS execution.
- **Source:** docsify.js.org (query: "what is docsify documentation generator how does it work"); app.uniswap.org (query: "does Uniswap charge fees to swap crypto tokens").

**Negative-result controls kept from the first pass:** framer.com, webflow.com, figma.com, linear.app/pricing — all returned substantial fact-bearing text in the raw, non-JS HTTP response; none showed this pattern. Combined with the two confirmed cases above, this narrows the mechanism usefully: **major-brand marketing sites skew SSR by default in 2026; the JS-only-shell pattern shows up on framework-driven docs generators (docsify) and application shells (DeFi/trading UIs) that were never built with SEO/crawl in mind** — a more precise targeting rule for the detector than "check everything."

## EXTRACT-00x

### EXTRACT-001 — Structured data contradicts visible text
- **Stage:** extract
- **Mechanism:** JSON-LD claims one value for a fact (e.g. `offers.price: 199`) while the page's actual visible text shows a different one (e.g. "$249"). Structured data is a shortcut extraction systems prefer over parsing prose -- it's faster and (nominally) more reliable -- so when it disagrees with what a human reader would see, an assistant relying on the structured data cites the *wrong* fact with high confidence, and it's a defect a normal manual read-through of the page would never catch (the human reads the correct visible price and never looks at the JSON-LD). This typically happens when structured data is generated by a different system/pipeline than the visible template and the two fall out of sync (price updated in the CMS, a separately-cached schema block wasn't).
- **Detection method:** parse JSON-LD via `extruct`; for price-bearing properties (`offers.price`), normalize both the claimed value and every currency fact extracted from the page's visible text (`trafilatura` main-content extraction, same fact-extraction primitive `render-gap-audit` uses) to a comparable float; flag if the claimed value doesn't match any visible-text currency fact. Normalizing before comparing is load-bearing -- naive string equality would treat `"199"` (JSON-LD) vs `"$199.00"` (text) as a contradiction when they're the same fact in different formatting, which would make this detector fail its own "zero false positives on controls" bar immediately.
- **Evidence artifact:** the JSON-LD block (or the specific property), the extracted visible-text currency facts, and the page URL.
- **Severity default:** high (a page-class-scoped defect that actively misinforms rather than merely hiding a fact).
- **Confidence:** high — both sides are directly extracted, not inferred; the only judgment call is the normalization itself, which is unit-tested.
- **Fix pattern:** regenerate structured data from the same source of truth as the visible template, or remove the stale JSON-LD property rather than leave it contradicting the page.
- **Source:** engineering-derived from the build plan's Day 4 requirement (a named example: "JSON-LD says `price: 199`, page says `₹24,999`"); not yet observed on a real site during field research.

### EXTRACT-002 — Structured data missing required properties
- **Stage:** extract
- **Mechanism:** a JSON-LD block declares a schema.org type (`Product`, `Offer`, `Organization`) but omits properties that type requires to be useful to a consumer (e.g. an `Offer` with no `price`). A structured-data consumer that expects the schema.org contract may silently skip or down-rank an incomplete block -- the site "has" JSON-LD in the sense of shipping a `<script type="application/ld+json">` tag, but the facts inside it don't actually reach whatever's parsing it.
- **Detection method:** match each JSON-LD block's `@type` against a small bundled schema.org subset (`assets/schema-subset.json` -- offline, no network dependency, per the project's determinism constraint) listing required properties per type; flag missing ones.
- **Evidence artifact:** the JSON-LD block's `@type` and which required properties are absent.
- **Severity default:** medium (degrades extractability without blocking the page outright -- the visible text still carries the fact).
- **Confidence:** high — direct presence/absence check against a fixed, bundled spec subset.
- **Fix pattern:** add the missing required properties to the structured data.
- **Source:** engineering-derived from the build plan's Day 4 requirement ("validate against the bundled schema.org subset"); not yet observed on a real site.

### EXTRACT-003 — Heading hierarchy breaks the document outline
- **Stage:** extract
- **Mechanism:** extraction and chunking pipelines (this project's own stage ④ included) commonly use heading structure to infer a document's outline and segment content into topically-coherent pieces. A page with zero `<h1>`, multiple competing `<h1>`s, or a level skip (`<h2>` straight to `<h4>` with no `<h3>`) gives such a pipeline an ambiguous or broken outline to work from, risking content getting attributed to the wrong section or chunk boundaries landing in the wrong place -- a structural problem that's invisible to a human skimming the rendered page (which just shows visually-styled text, not the underlying outline) but very visible to anything parsing the DOM structure.
- **Detection method:** walk `<h1>`-`<h6>` tags in DOM order **within the page's main-content region only** (`trafilatura`'s boilerplate-stripped extraction, HTML output mode -- the same tool `RENDER-001`/`EXTRACT-001` already use for the visible-text side, applied here to preserve structure instead of flattening to text); flag (a) zero `<h1>` tags, (b) more than one `<h1>` tag, (c) any level skip (a heading whose level is more than one greater than the running maximum level seen so far). Scoping to main content isn't optional polish -- see the false-positive note below.
- **Evidence artifact:** the sequence of heading levels found, and the specific tag(s) that violate the rule.
- **Severity default:** low (a structural risk, not an observed retrieval failure by itself -- its real cost shows up downstream in stage ④, which doesn't exist yet).
- **Confidence:** high — directly observed from DOM structure, no inference involved.
- **Fix pattern:** ensure exactly one `<h1>` per page and no heading-level skips.
- **False positive caught and fixed during Day 4 real-site validation:** the first implementation scanned the *entire* page DOM, not just main content. Run against docs.python.org (a real site, not a fixture), it flagged a "heading skip" on all 8 sampled version pages -- every single instance was a `<h3>Download</h3>` living inside `<nav class="menu">` / `<div class="sphinxsidebar">`, pure navigational chrome with nothing to do with the article's own outline. Fixed by scoping to `trafilatura`'s main-content extraction; re-validated clean on the same 8 pages afterward. This is exactly the "wild diversity sweep" the build plan's Part 6 calls for finding, applied a day early because it was cheap to check.
- **Source:** engineering-derived from the build plan's Day 4 requirement ("semantic HTML integrity"); the detector itself surfaced a real (if minor, low-severity) instance on a live Allbirds product page during that same validation pass -- content sections marked up with `<h2>`/`<h3>` but the product title itself never marked up as `<h1>` anywhere in main content.

### EXTRACT-004 — Numeric-looking facts locked in `alt`-less images
- **Stage:** extract
- **Mechanism:** a spec table, price chart, or similar fact-bearing content delivered as an image with no `alt` text is invisible to any text-based extraction pipeline -- there's no OCR step in most retrieval systems (and deliberately none in this audit either, since that would need a model). Unlike `RENDER-001` (content missing from the HTTP response entirely), this content is present in the DOM as an `<img>` tag, so a naive "does the page have this content" check would say yes -- it's specifically *unextractable*, not *unreachable*.
- **Detection method:** deliberately narrow and heuristic, not exhaustive: within the page's main-content region only (same `trafilatura`-based scoping as `EXTRACT-003`, for the same reason -- a decorative logo living in a persistent sidebar isn't part of what a reader or a retrieval pipeline treats as this page's content), flag `<img>` tags with no (or empty) `alt` attribute whose `src` filename matches fact-bearing keywords (`price`, `chart`, `spec`, `table`, `pricing`) -- a real OCR-based check would need model weights the project's constraints rule out, and a broader heuristic (e.g. "any alt-less image") would flag every decorative icon and logo on the internet, which is exactly the kind of generic-checklist noise this project exists to avoid.
- **Evidence artifact:** the `<img>` tag's `src` and the page URL.
- **Severity default:** low (heuristic-driven, not a confirmed fact-loss the way `EXTRACT-001`/`RENDER-001` are).
- **Confidence:** low — a filename match is a weak, indirect signal (a false positive is plausible: a decorative image that happens to be named `price-banner.png` without carrying real price data); shipped as `low` confidence deliberately rather than tuned to look more certain than it is.
- **Fix pattern:** add descriptive `alt` text carrying the actual fact, or better, deliver the fact as real text/structured data alongside the image.
- **Source:** engineering-derived from the build plan's Day 4 requirement ("facts-locked-in-images detection"); not yet observed on a real site.

## CHUNK-00x

### CHUNK-001 — Buyer-intent queries unanswerable from the AI-reachable corpus
- **Stage:** retrieve
- **Mechanism:** a deterministically-generated buyer-intent query (6 intent classes x 3 templates, expanded from the site's own detected entity) fails to surface a grounded, verbatim answer when run against a BM25 index of the chunked, AI-reachable corpus (the stage ①/② survivors, minus any page stage ② proved is an empty JS-only shell). This is the direct, outcome-anchored metric the industry actually cares about (answer visibility / citation frequency) rather than an intermediate proxy like "does the page contain this content somewhere" -- a page can nominally "have" the information and still fail here if it isn't retrievable the way a real assistant's retrieval pipeline would actually find it.
- **Detection method:** chunk the corpus (400-600 tokens, overlap, provenance-tracked to URL + nearest heading); index with hand-rolled BM25; classify each expanded query's outcome (`ANSWERABLE`/`PARTIAL`/`UNGROUNDED`/`UNRETRIEVABLE`) by checking every top-k retrieved chunk independently against a coverage-of-substantive-query-terms threshold (excluding the entity's own name tokens and question-scaffolding words like "how"/"does" from the coverage calculation -- both diluted the signal enough in early testing to make a real $89 price and a real contact email both score as false negatives), cross-checked against a concrete fact type (currency/contact) where the intent has one. A single aggregate finding is emitted (not one per failing query) when >=25% of the 18 queries are UNRETRIEVABLE or UNGROUNDED.
- **Evidence artifact:** up to 10 example `[intent] 'query' -> outcome` lines, plus artifact URLs for up to 3 corpus pages.
- **Severity default:** medium (degrades citation/answer quality across the corpus without blocking a stage outright).
- **Confidence:** high -- the classification is a deterministic function of the (fully reproducible) BM25 scores and fact-extraction checks; re-running the same corpus produces byte-identical results, confirmed as this stage's own DoD (`tests/test_retrieve_stage.py`).
- **Fix pattern:** add direct, front-loaded answers to buyer-intent questions in the site's own language (the `affected_queries` list names exactly which ones), not just marketing narrative -- the fix is query-specific, not a generic "add more content" suggestion.
- **Source:** engineering-derived from the build plan's own report-schema example ("5 of 18 buyer-intent queries are UNANSWERABLE"); validated end-to-end against `tests/fixtures/retrieval-answerable`, a fixture built specifically so some intents (identity/pricing/contact, directly addressed) come back answerable and others (comparison/trust, never mentioned at all) come back honestly ungrounded rather than uniformly one or the other -- confirming the classifier discriminates real content from its absence rather than just reporting the same verdict regardless of what's actually on the page.

**A cluster of bugs found and fixed while building this detector, not before it (see `docs/progress.md` for the full trace):** a latent `selectolax` grouped-CSS-selector bug (cross-tag document order isn't preserved -- also silently affected `EXTRACT-003` since Day 4, undetected until this stage's per-word heading attribution made it obvious); section headings weren't part of any chunk's searchable text at all, so a query like "how do I contact them" could never match a "Contact" section by heading alone; the entity's own name tokens and question-scaffolding words ("how", "does", "what") diluted the coverage calculation enough to make directly-stated facts score as false negatives; the classifier only ever checked the top-ranked BM25 result, missing a correctly-retrieved-but-not-ranked-first answer chunk; no stemming meant "cost" (query) never matched "costs" (page text); and an empty-corpus edge case (every page excluded as a `RENDER-001` shell) crashed on `Finding`'s own `min_length=1` artifacts constraint. Left detailed here rather than only in the commit history because the *pattern* -- test against real, structured content early, not just whether the code runs without raising -- is the actual lesson, not any one specific fix.

### CHUNK-002 — Orphan fact: a value with no identifying subject in the same chunk
- **Stage:** retrieve
- **Mechanism:** a chunk contains a price (or other currency fact) but nothing in the chunk names *what* the fact is about — no section heading, no proper-noun-like phrase identifying a subject. The build plan's own illustrative example: a `<td>₹24,999</td>` whose product name sits 40 DOM nodes upstream in an `<h1>`. Retrieval operates on chunks, not pages — a fact whose subject and value land in different chunks is unretrievable even though the page as a whole "has" both.
- **Detection method:** for every chunk carrying a currency fact (via `brand_audit.facts.extract_facts`), check for an identifying subject: the chunk's own `section_heading` (strongest signal — chunk headings are now prepended to chunk text, see `RENDER`/`CHUNK-001` notes) or, failing that, a proper-noun-like phrase (two or more consecutive capitalized words) anywhere in the chunk text. Neither present -> orphaned. One aggregate finding across all orphaned chunks found, not one per chunk.
- **Evidence artifact:** up to 5 `url#chunk_index: text snippet` lines.
- **Severity default:** medium (degrades retrieval quality for that specific fact without blocking a stage outright).
- **Confidence:** medium — the proper-noun-phrase regex is a heuristic (crude proxy for real subject identification, not real NER — see `brand_audit.facts`'s equivalent note on why a full NER model isn't used), so a false positive is plausible for a chunk whose subject is named some other way this heuristic doesn't recognize.
- **Fix pattern:** co-locate the subject and its value — add a heading, or a lead-in sentence naming the subject, near each standalone fact.
- **Source:** engineering-derived from the build plan's Day 6 requirement ("orphan-fact detector"); unit-tested against both a deliberately-orphaned synthetic chunk and a properly-identified one, not yet observed as a defect on a real site (the `retrieval-answerable` fixture's own price chunk is correctly *not* orphaned, since it has a heading).

### CHUNK-003 — Answer only exists by combining facts from different pages
- **Stage:** retrieve
- **Mechanism:** a `PARTIAL` answerability outcome (facts must be assembled across the top-k retrieved chunks to reach the coverage threshold, per `CHUNK-001`'s classifier) where the contributing chunks span more than one distinct URL, not just different sections of one page — e.g. one page's specification plus a different page's price. Real assistants rarely perform this cross-page join at query time, so this is a strictly weaker, more fragile case than a same-page multi-chunk `PARTIAL`.
- **Detection method:** `retrieve_detect.classify()` already tracks, for every `PARTIAL` outcome, which chunks contributed a *substantive* (non-entity-token) matched term; if those chunks' URLs aren't all the same, the outcome is flagged `cross_page`. One aggregate finding across all cross-page `PARTIAL` queries.
- **Evidence artifact:** up to 5 `[intent] 'query'` lines.
- **Severity default:** medium (degrades citation quality — the fact is technically assemblable, just unrealistically so).
- **Confidence:** medium — inferring "this chunk contributed to the answer" from which chunks shared a substantive matched term with the query is itself an approximation of what a real multi-chunk retrieval system would actually combine.
- **Fix pattern:** summarize the combined fact (e.g. spec + price together) on at least one page, rather than relying on a reader — or a retriever — to join two pages.
- **Source:** engineering-derived from the build plan's Day 6 requirement and Part 2 §③'s "cross-page join" mechanism; confirmed firing on real sites during the Day 6 wild-corpus sweep (stripe.com, notion.com both showed cross-page-dependent `PARTIAL` answers), not just the synthetic fixture.

### CHUNK-004 — Chunk diluted with boilerplate text
- **Stage:** retrieve
- **Mechanism:** a chunk's real signal is diluted by cookie-notice/legal/social-follow boilerplate phrases making up an unusually high fraction of its characters — even though chunking already runs on `trafilatura`'s boilerplate-*stripped* main-content extraction (see `chunk.py`), so a diluted chunk reaching this far means that upstream stripping itself missed something.
- **Detection method:** match chunk text (case-insensitively) against a small bundled list of common boilerplate phrases ("all rights reserved", "privacy policy", "we use cookies", "follow us on", ...); flag chunks where matched-phrase characters make up ≥15% of the chunk's total length.
- **Evidence artifact:** up to 5 `url#chunk_index: NN% boilerplate` lines.
- **Severity default:** medium (degrades retrieval quality for that chunk without blocking a stage outright).
- **Confidence:** medium — a fixed phrase list can't cover every boilerplate pattern; absence of a match doesn't prove a chunk is clean, only that it doesn't match *this* list.
- **Fix pattern:** move repeated legal/social boilerplate into a template region (footer/modal) clearly separated from the article content flow, so upstream boilerplate-detection can distinguish it.
- **Source:** engineering-derived from the build plan's Day 6 requirement ("boilerplate-ratio scoring"); expected to rarely fire in this pipeline specifically, by design — see the mechanism note — and indeed stayed silent across the entire Day 6 wild-corpus sweep, which is the expected, honest result of `trafilatura`'s upstream stripping already doing its job on real sites, not evidence the detector doesn't work (confirmed separately against a deliberately-crafted synthetic chunk).

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

### TRUST-005 — Missing entity anchoring (no sameAs), automated detector
- **Stage:** cite
- **Mechanism:** the general, automated version of `TRUST-004`'s hand-found case: a JSON-LD `Organization`/`LocalBusiness` node declares a `name` but no (or an empty) `sameAs` array. Without a `sameAs` anchor, a system trying to verify or disambiguate this entity — including against a same-named different company — has no machine-readable signal pointing to an authoritative external profile; the brand's identity rests entirely on unverified self-assertion. This is the on-site half of entity anchoring the build plan's own cut list says to keep, deliberately in place of a live name-collision web search (see the skill's module docstring for why: a live search breaks the project's determinism/portability constraints, and the cut list names it as the first thing to cut if behind schedule).
- **Detection method:** walk every page's JSON-LD for an `Organization`/`LocalBusiness` node with a `name`; if the first one found (in deterministic sorted-URL order) has no non-empty `sameAs`, flag it. Whole-site check, one finding, not one per page.
- **Evidence artifact:** the page URL and confirmation that `name` is present but `sameAs` is absent/empty.
- **Severity default:** medium (degrades trust/corroboration signal without blocking a stage outright).
- **Confidence:** high — direct presence/absence check, no inference.
- **Fix pattern:** add a `sameAs` array to the Organization JSON-LD, pointing to owned authoritative profiles (Wikidata, LinkedIn, Crunchbase, verified social accounts).
- **Source:** engineering-derived from the build plan's Day 6 requirement ("entity anchoring/sameAs"); confirmed firing on a real site during the Day 6 wild-corpus sweep (the `retrieval-answerable` fixture's own Organization node, which was never given a `sameAs` — an honest gap in a fixture built for a different stage, not a false positive).

### TRUST-006 — Stale dateModified
- **Stage:** cite
- **Mechanism:** a page's JSON-LD `dateModified`/`datePublished` is more than a year old. Not proof any specific fact is wrong — proof the page hasn't been reviewed recently, which matters for freshness-sensitive claims (pricing, availability, current offerings) that an assistant might otherwise treat as current just because the page loaded successfully today.
- **Detection method:** parse `dateModified`/`datePublished` from JSON-LD as ISO 8601; compare against a reference date (real "now" in production, parameterized for testability); flag if the gap exceeds 365 days.
- **Evidence artifact:** the property name, its raw value, and the computed age in days.
- **Severity default:** medium (degrades trust signal without blocking a stage outright).
- **Confidence:** medium — staleness is a risk signal, not proof the content is actually wrong; a page can be old and still perfectly accurate.
- **Fix pattern:** review the page's content and update `dateModified` to reflect the actual last-reviewed date.
- **Source:** engineering-derived from the build plan's Day 6 requirement ("freshness... contradictions"); unit-tested with a parameterized reference date (not a live `datetime.now()` call scattered through the detector) so the test suite stays deterministic without mocking the clock.

### TRUST-007 — Description drift across title/meta/JSON-LD/OG
- **Stage:** cite
- **Mechanism:** the brand's one-line self-description should read as the same story everywhere it's expressed. Compares the homepage's meta description, JSON-LD `description`, and `og:description` pairwise via token (Jaccard) overlap — not exact-match, since some wording variation is normal, but very low overlap between two fields that both exist means a system reading only one of them (search snippets typically use meta description; social shares use `og:description`; structured-data consumers use the JSON-LD description) forms a different picture of the brand depending on which one it happened to read, with no canonical framing to converge on.
- **Detection method:** extract all three fields from the homepage (resolved by normalized root path via `brand_audit.crawl.find_homepage_url`, not exact string match — see that function's docstring for why exact match was a real Day 5 bug); for every pair where both are present, compute Jaccard token overlap; flag the first pair below 15%.
- **Evidence artifact:** the two field names and their literal text.
- **Severity default:** medium (degrades trust/consistency signal without blocking a stage outright).
- **Confidence:** medium — token overlap is a proxy for "same story," not a certainty; two descriptions could share few words while still being consistent (or share many while contradicting each other on a key fact), though the former is far more common in practice.
- **Fix pattern:** align the brand's one-line self-description across meta description, JSON-LD, and OpenGraph tags — the same sentence, or a close paraphrase, in all three.
- **Source:** engineering-derived from the build plan's Day 6 requirement ("description drift across title/meta/JSON-LD/OG/footer" — title and footer not yet included, see `trust-corroboration-audit/SKILL.md` Status for the honest scope note); unit-tested, not yet observed as a defect on a real site (none of the wild-corpus sweep sites had fewer than 2 of the 3 checked fields consistent enough, or inconsistent enough, to trigger it either way in this pass).

### TRUST-008 — Low attribution/statistic density
- **Stage:** cite
- **Mechanism:** the KDD 2024 GEO study (Aggarwal et al., *GEO: Generative Engine Optimization*, KDD '24 / [arXiv:2311.09735](https://arxiv.org/abs/2311.09735)) evaluated nine optimization strategies — including adding source citations, quotations, and statistics — across ~10,000 queries, and reports visibility gains in generative-engine responses of **"up to 40%"**, explicitly noting that efficacy varies across domains. A page stating multiple numeric claims with zero citation language anywhere reads as self-asserted, which weakens their weight for a system trying to corroborate them. (Stated as the paper's own headline figure and scope, deliberately not as a per-strategy expected range — the paper's abstract supports "up to 40%" overall, not a guaranteed uplift for citations specifically; an earlier draft of this entry overstated it as "~+20-40% relative" and was corrected on Day 10 after checking the source directly.)
- **Detection method:** for each page, count numeric/currency facts (via `brand_audit.facts.extract_facts`) and check for citation-like language ("according to", "study shows", "source:", ...) anywhere on the page; a page with ≥2 numeric facts and zero citation signals counts toward the pattern. Only flagged when this is the *majority* pattern across the sampled corpus — one page without a citation isn't a site-wide attribution gap, and flagging it as one would be exactly the kind of single-page overreach the taxonomy's own admission rule exists to prevent.
- **Evidence artifact:** up to 5 affected page URLs.
- **Severity default:** low (proactive/beyond-defect layer — the KDD study's own effect is about improving visibility, not fixing a defect that's actively blocking anything).
- **Confidence:** low — citation-phrase matching is a narrow, easily-missed heuristic (a page could attribute a stat in a way this fixed phrase list doesn't recognize); shipped at `low` confidence deliberately rather than tuned to look more certain than it is, consistent with `EXTRACT-004`'s equivalent honesty about a weak heuristic.
- **Fix pattern:** attribute key statistics to a source (internal data, a named study or survey) rather than stating bare numbers.
- **Source:** engineering-derived from the build plan's Day 6 requirement and Part 2 §⑦'s cited KDD 2024 GEO study; confirmed firing on real sites during the Day 6 wild-corpus sweep (stripe.com, notion.com both showed the majority-unattributed pattern) as well as the synthetic fixtures.

## ENGAGE-00x

### ENGAGE-001 — Citable answer buried below the page's own midpoint
- **Stage:** arrive
- **Mechanism:** an AI-referred visitor arrives deep-linked and mid-task, already given a partial answer by the assistant — they scan to confirm it, not to read the page fresh. `top_chunk_position_ratio` (computed once in stage ④, `brand_audit.chunk.page_content_length`) is a text-offset proxy for "above the fold" — exact pixel position needs rendering this stage doesn't do, but a chunk starting past a page's own midpoint cannot plausibly be above any reasonable fold either. An answer buried there asks a visitor to re-find what they were already told.
- **Detection method:** scan the answerability_matrix for `citable=True` entries whose `top_chunk_position_ratio >= 0.6`; flag if any exist. Aggregate finding, scope is checked = citable entries with position data, affected = buried ones.
- **Evidence artifact:** the query, its intent, the winning chunk's URL, and its position ratio.
- **Severity default:** medium (degrades the arrival experience without blocking a stage outright).
- **Confidence:** medium — position ratio is a real computed value, not a keyword heuristic, but it's still a text-offset proxy for a visual "above the fold" concept this stage can't measure directly (no rendering).
- **Fix pattern:** move the cited answer, or a direct one-line restatement of it, higher in the page's main content.
- **Source:** engineering-derived from the build plan's Day 7 requirement ("answer proximity... present in text above the fold, or buried below three hero sections"); reuses position data stage ④ already computes rather than re-deriving it — see the char-offset regression fix noted in `docs/progress.md`'s Day 7 entry.

### ENGAGE-002 — Orientation gap: brand not named near the top of a citable page
- **Stage:** arrive
- **Mechanism:** a cold AI-referred arrival never sees the nav or logo as onboarding — they land on this exact page, never the homepage, with zero prior context. If the page's own main content never names the brand at all, or only far below its opening content, a cold arrival has nothing on the page itself confirming what company this is or that the citation landed somewhere legitimate.
- **Detection method:** for each citable page, tokenize the detected entity name and the page's trafilatura-extracted main content; flag if the entity's tokens never appear in the main content at all (medium confidence), or only outside the first 500 characters (low confidence — a weaker signal, since "not in the lead window" is a softer claim than "never mentioned").
- **Evidence artifact:** the page URL and which of the two conditions applied.
- **Severity default:** high in the "never mentioned at all" case, discounted per `severity-model.md`'s confidence clamp in the "late mention" case (medium confidence → medium; low confidence → clamped from what would otherwise be high/medium down to medium, never higher).
- **Confidence:** medium (never mentioned) or low (mentioned late) — tokenized substring presence is a real check, but doesn't account for the brand being named via a logo image, a stylized wordmark not in the text, or a common abbreviation this check doesn't try to match.
- **Fix pattern:** name the brand explicitly in the page's opening content, not just in the nav/logo.
- **Source:** engineering-derived from the build plan's Day 7 requirement ("orientation... can a cold arrival tell what the company is"); found firing correctly on a real site during the Day 7 wild-corpus sweep (allbirds.com product pages lead with the product name, not "Allbirds", within the first 500 characters).

### ENGAGE-003 — Context reset: deep link redirects to the homepage or a locale gate
- **Stage:** arrive
- **Mechanism:** the "outright killer" case the build plan names explicitly: a deep link that redirects away from its own content resolves the assistant's citation to nothing useful. Distinct from `REACH-002`'s locale-*prefix* redirect (still resolves to the *same* page under a `/en-us/`-style path, a crawler-fetch concern) — this is about losing the deep link's specificity entirely, an arrival-experience concern.
- **Detection method:** for each citable URL, compare its already-followed-redirect `FetchRecord.final_url` (captured in stage ① — no second fetch needed) against the original path. A cosmetic redirect (trailing slash, http→https, same resolved path) is not flagged. Flagged when the final path collapses to the domain root, or when the destination page's own text (if it happens to be in the already-fetched corpus) matches a locale/region-selector phrase ("select your country", "choose your region", ...).
- **Evidence artifact:** the original URL, the resolved `final_url`, and the HTTP status.
- **Severity default:** high (page_class blast radius — the affected deep link stops working as a citation target entirely).
- **Confidence:** high — `final_url` divergence from the original path is a direct observation, not an inference.
- **Fix pattern:** stop redirecting the deep link away from its own content; if geolocation-based redirection is required, redirect within the same content rather than to the homepage or a bare selector.
- **Source:** engineering-derived from the build plan's Day 7 requirement and the SKILL.md's own field-research note flagging `REACH-002` as an adjacent candidate mechanism; not yet observed firing on a real site during the Day 7 sweep (the two live sites checked, docs.python.org and allbirds.com, had no qualifying redirects in their sampled pages) — unit-tested against both the homepage-redirect and locale-gate cases.

### ENGAGE-004 — Entry interference: consent/gate overlay signature detected
- **Stage:** arrive
- **Mechanism:** an AI-referred visitor arrives already mid-task expecting to confirm a specific answer. A consent wall, age gate, or modal sitting between them and the page's own content adds friction a search visitor (who browsed in cold anyway) tolerates but an already-informed visitor doesn't — and if it blocks first paint, it can hide the very answer the assistant cited.
- **Detection method:** static signature match against known consent-management-platform / age-gate library tokens (`cookiebot`, `onetrust`, `cookieyes`, `cc-window`, `gdpr-consent`, `age-gate`, ...) in each citable page's raw HTML. Deliberately not a rendered-page check — no real visual blocking confirmation is attempted, consistent with this stage not requiring Playwright as a dependency (see `render-gap-audit/SKILL.md` for why the project treats Playwright as strictly optional).
- **Evidence artifact:** the page URL and the matched signature token.
- **Severity default:** medium (degrades the arrival experience without blocking a stage outright).
- **Confidence:** medium — signature presence in the markup is a strong signal the library is loaded, but not confirmed proof it actually renders a blocking overlay on every visit (some configurations are non-blocking by design).
- **Fix pattern:** make consent/gate overlays non-blocking — render page content first, or default to the most restrictive consent choice rather than gating first paint on an explicit answer.
- **Source:** engineering-derived from the build plan's Day 7 requirement ("entry interference... blocking first meaningful paint"); confirmed firing on a real site during the Day 7 wild-corpus sweep (allbirds.com's product pages all carry a OneTrust signature).

### ENGAGE-005 — Missing next-step / call-to-action on citable pages
- **Stage:** arrive
- **Mechanism:** a visitor who arrives mid-task with their question already answered needs the next action available on the landing page itself — requiring a navigation hunt to find it loses exactly the visitor this stage is scoped to, since (unlike a browsing visitor) they have no accumulated site context telling them where to look.
- **Detection method:** for each citable page, check its trafilatura-extracted main content against a fixed phrase list ("contact us", "get started", "buy now", "sign up", ...); flag only when the *majority* of the citable set has none — the same precision-first majority-gating `TRUST-008` uses for an equivalently noisy phrase-matching heuristic, since a fixed phrase list under-recognizes real CTAs (icon-only buttons, differently-worded links).
- **Evidence artifact:** up to 5 affected page URLs.
- **Severity default:** medium (degrades the arrival experience without blocking a stage outright), shipped at low confidence.
- **Confidence:** low — same honesty as `TRUST-008` about a narrow, easily-missed phrase-matching heuristic; a page can have a perfectly good CTA this fixed list doesn't recognize.
- **Fix pattern:** add an explicit next-step action (contact, buy, sign up, demo) directly on the citable pages, not just in global nav.
- **Source:** engineering-derived from the build plan's Day 7 requirement ("next-step availability... not behind a navigation hunt"); observed firing at low confidence on a real non-commercial site during the Day 7 sweep (docs.python.org's version-index page, where "no CTA" is arguably an accurate but low-stakes finding for a documentation site rather than a commercial one — recorded honestly rather than suppressed, see `docs/progress.md`).

### ENGAGE-006 — No AI-referral-capable instrumentation detected
- **Stage:** arrive
- **Mechanism:** most brands cannot see `chatgpt.com`/`perplexity.ai`/`claude.ai` referral traffic even when it's happening, because they have no analytics at all, let alone referrer segmentation for it — so they can't tell this whole funnel is failing for them. This is the "beyond-defect" proactive framing: not a defect on any one page, a capability gap across the whole site.
- **Detection method:** whole-corpus (not citable-only — analytics snippets are typically injected site-wide via a shared template) scan for known analytics script signatures (`googletagmanager.com`, `google-analytics.com`, `plausible.io`, `posthog`, `mixpanel`, ...) across every sampled page; flag only if none are found anywhere.
- **Evidence artifact:** confirmation that no known signature was found across N sampled pages.
- **Severity default:** low (proactive/beyond-defect layer, per the build plan's own framing — not a defect actively blocking anything).
- **Confidence:** medium — signature absence across a sampled subset is a reasonably strong signal for "no analytics of any kind," deliberately not claimed for the narrower, unverifiable-from-static-HTML question of whether an *existing* setup specifically segments AI referrals.
- **Fix pattern:** add basic web analytics site-wide, then a referrer segment or UTM convention for chatgpt.com / perplexity.ai / claude.ai traffic specifically.
- **Source:** engineering-derived from the build plan's Day 7 requirement ("AI-referral instrumentation... most brands cannot see this traffic at all"); confirmed firing on a real site during the Day 7 wild-corpus sweep (docs.python.org carries no known analytics signature in its server-rendered HTML).

### ENGAGE-007 — Slow response time on citable pages
- **Stage:** arrive
- **Mechanism:** an AI-referred visitor arrives already mid-task and abandons a slow load more readily than a search visitor who deliberately chose to click a result — per Google/SOASTA's 2016 mobile benchmark, abandonment rises sharply past roughly three seconds. This is the build plan's own explicit cut-list fallback: "keep TTFB — cheap and adequate" in place of LCP/INP, which this stage has no rendering step to measure directly.
- **Detection method:** httpx's `Response.elapsed` (send-to-full-response latency, captured for free during stage ①'s own fetch — no second fetch) on the citable page set only, not the homepage; flag any citable page at or above 3.0s.
- **Evidence artifact:** the page URL and its measured latency in seconds.
- **Severity default:** medium (degrades the arrival experience without blocking a stage outright).
- **Confidence:** medium — full-response latency is a directly measured proxy for real perceived load time (LCP/INP), not the metric itself; a page can have a slow initial response and still paint quickly, or vice versa.
- **Fix pattern:** profile and reduce server/CDN response time on the affected citable pages specifically.
- **Source:** engineering-derived from the build plan's Day 7 requirement and its own Part 8 cut-list language; not yet observed firing on a real site during the Day 7 sweep (both live sites checked responded well under the threshold) — unit-tested against both a slow and a fast synthetic case.

---

## Controls (no defect — recorded because a negative result is evidence too)

- **docs.python.org** — official docs and `pip.pypa.io` (an official project domain) both appear directly in citation results for a how-to query; `robots.txt` disallows only `/dev`, `/release`, and EOL version paths, current docs stay fully open. Baseline "everything working" case.
- **allbirds.com** — product page carries a complete `ProductGroup`/`Offer` JSON-LD block (price, currency, availability, rating) in the raw non-JS HTML. For a narrowly-scoped product-spec query, 6 of 10 returned links were allbirds.com pages — the brand's own domain dominated the result set. Recorded specifically as a **contrast case against TRUST-001**: good EXTRACT hygiene correlates with strong citation on product-spec queries, but did *not* help Stripe/Linear/Notion on pricing-genre queries — suggesting TRUST-001's mechanism is query-genre-specific (comparison/calculator content has its own gravity), not a general EXTRACT failure. This distinction is what keeps TRUST-001 from being overfit advice ("just add schema").

---

**Status:** 31 entries across REACH (7), RENDER (1), EXTRACT (4), CHUNK (4), TRUST (8), ENGAGE (7). Field-verified (Day 1 research): REACH-001/002/003, RENDER-001, TRUST-001 (reproduced 3-for-3), TRUST-002/003 (explicit observations, unverified), TRUST-004 (low-severity note). Found on a real site during pipeline validation, not hand-researched first: REACH-007 (allbirds.com's WAF contradicting its own robots.txt). Engineering-derived from the build plan's own stage requirements, confirmed against real sites during validation sweeps even where not first discovered there: REACH-004/005/006 (Day 3), EXTRACT-001/002/003/004 (Day 4), CHUNK-001/002/003/004 (Days 5–6), TRUST-005/006/007/008 (Day 6), ENGAGE-002/004/005/006 (Day 7 — ENGAGE-001/003/007 unit-tested but not yet observed firing on a live site) — flagged by origin throughout rather than presented with uniform authority. Every entry through CHUNK, every TRUST entry from 005 on, and every ENGAGE entry is live, tested detector code, not just documentation — see `skills/crawl-reach-audit/scripts/detect.py`, `skills/render-gap-audit/scripts/render_detect.py`, `skills/extractability-audit/scripts/extract_detect.py`, `skills/retrieval-simulation/scripts/retrieve_detect.py`, `skills/trust-corroboration-audit/scripts/trust_detect.py`, `skills/arrival-engagement-audit/scripts/arrive_detect.py`. Deliberately not padded to a round number for its own sake — the count landed here because Days 6–9's wild-corpus and eval-harness validation kept surfacing genuine mechanisms and miscalibrations to fix (REACH-007 on Day 6; REACH-001's AI-specific-targeting refinement and ARRIVE's empty-corpus guard on Day 9), not because entries were added to hit a target. All six funnel stages have live detector code, `finding-verification` falsifies every finding, and `assemble_report.dedup_findings` merges known same-root-cause pairs — the pipeline is feature-complete as of Day 8, precision-hardened as of Day 9 (published confusion matrix: precision 1.00, recall 1.00, FP-rate on clean controls 0.00 — see `docs/progress.md`).
