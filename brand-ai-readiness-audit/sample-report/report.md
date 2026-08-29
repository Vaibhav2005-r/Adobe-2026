# AI Visibility Audit — allbirds.com

**7 of 18 buyer-intent queries are unanswerable from the AI-reachable corpus**

Audited 2026-08-29 09:26:25.740732+00:00 · 12 pages crawled, 0 rendered · 38.9s

## Funnel status

| ① REACH | ② RENDER | ③ EXTRACT | ④ RETRIEVE | ⑤ CITE | ⑥ ARRIVE |
|---|---|---|---|---|---|
| ✅ pass | ⏭️ skipped | ⚠️ partial | ⚠️ partial | ✅ pass | ⚠️ partial |

## Summary

| Critical | High | Medium | Low | Total |
|---|---|---|---|---|
| 0 | 0 | 6 | 6 | 12 |

Answerability: 5 answerable, 6 partial, 7 ungrounded, 0 unretrievable (of 18 simulated buyer-intent queries).

## Prioritized action list

1. **[MEDIUM]** Add direct, front-loaded answers to buyer-intent questions in the site's own language, not just marketing narrative. _(unblocks retrieve, impact: high, effort: medium)_
2. **[MEDIUM]** Co-locate the related facts on a single page rather than relying on a reader (or retriever) to combine two pages. _(unblocks retrieve, impact: medium, effort: medium)_
3. **[MEDIUM]** Name the brand explicitly in the page's opening content, not just in the nav/logo. _(unblocks arrive, impact: low, effort: low)_
4. **[MEDIUM]** Name the brand explicitly in the page's opening content, not just in the nav/logo. _(unblocks arrive, impact: low, effort: low)_
5. **[MEDIUM]** Name the brand explicitly in the page's opening content, not just in the nav/logo. _(unblocks arrive, impact: low, effort: low)_
6. **[MEDIUM]** Make consent/gate overlays non-blocking: render page content first, or default to a reasonable choice instead of gating first paint. _(unblocks arrive, impact: medium, effort: medium)_
7. **[LOW]** Use exactly one <h1> per page and avoid heading-level skips. _(unblocks extract, impact: low, effort: low)_
8. **[LOW]** Use exactly one <h1> per page and avoid heading-level skips. _(unblocks extract, impact: low, effort: low)_
9. **[LOW]** Use exactly one <h1> per page and avoid heading-level skips. _(unblocks extract, impact: low, effort: low)_
10. **[LOW]** Use exactly one <h1> per page and avoid heading-level skips. _(unblocks extract, impact: low, effort: low)_

## Findings by stage

### ③ EXTRACT

- **[LOW] https://www.allbirds.com/products/anytime-ankle-sock-blizzard-sienna-blush: heading hierarchy issue(s) -- heading level skip: jumped to h3 after h1 (text: 'Notify me when back in stock')** (`EXTRACT-003`, confidence: high, checked 1/affected 1)
- **[LOW] https://www.allbirds.com/products/mens-wool-runners-true-black: heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 1/affected 1)
- **[LOW] https://www.allbirds.com/products/mens-dasher-nz-natural-black-blizzard: heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 1/affected 1)
- **[LOW] https://www.allbirds.com/products/womens-tree-runner-go-blizzard-vivid-red: heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 1/affected 1)
- **[LOW] https://www.allbirds.com/products/mens-strider-medium-grey: heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 1/affected 1)
- **[LOW] https://www.allbirds.com/products/womens-tree-dashers-rustic-brown: heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 1/affected 1)

### ④ RETRIEVE

- **[MEDIUM] 7 of 18 buyer-intent queries are unanswerable from the AI-reachable corpus** (`CHUNK-001`, confidence: high, checked 18/affected 7)
- **[MEDIUM] 6 buyer-intent queries can only be answered by combining facts from different pages** (`CHUNK-003`, confidence: medium, checked 18/affected 6)

### ⑥ ARRIVE

- **[MEDIUM] https://www.allbirds.com/products/anytime-ankle-sock-blizzard-sienna-blush: a cold arrival can't tell what this is without the nav** (`ENGAGE-002`, confidence: low, checked 1/affected 1)
- **[MEDIUM] https://www.allbirds.com/products/mens-wool-runners-true-black: a cold arrival can't tell what this is without the nav** (`ENGAGE-002`, confidence: low, checked 1/affected 1)
- **[MEDIUM] https://www.allbirds.com/products/womens-tree-runner-nz-medium-grey: a cold arrival can't tell what this is without the nav** (`ENGAGE-002`, confidence: low, checked 1/affected 1)
- **[MEDIUM] 4 of 4 citable page(s) carry a consent/gate overlay that can block first meaningful paint** (`ENGAGE-004`, confidence: medium, checked 4/affected 4)

## Proactive recommendations (no defect found)

- **No page answers comparison-intent questions**
- **No page answers contact-intent questions**
- **No page answers trust-intent questions**
- **6 queries are one edit away from being citable**


**Degradations recorded this run:** `render_stage_skipped_by_flag`

---
_Full evidence, artifacts, and implementation steps for every finding are in the accompanying JSON and HTML reports._
