# AI Visibility Audit — allbirds.com

**6 of 18 buyer-intent queries are unanswerable from the AI-reachable corpus**

Audited 2026-09-12 14:07:45.874109+00:00 · 12 pages crawled, 0 rendered · 37.5s

## Funnel status

| ① REACH | ② RENDER | ③ EXTRACT | ④ RETRIEVE | ⑤ CITE | ⑥ ARRIVE |
|---|---|---|---|---|---|
| ✅ pass | ⏭️ skipped | ⚠️ partial | ⚠️ partial | ✅ pass | ⚠️ partial |

## Summary

| Critical | High | Medium | Low | Total |
|---|---|---|---|---|
| 0 | 0 | 6 | 1 | 7 |

Answerability: 7 answerable, 5 partial, 6 ungrounded, 0 unretrievable (of 18 simulated buyer-intent queries).

## Prioritized action list

1. **[MEDIUM]** Add direct, front-loaded answers to buyer-intent questions in the site's own language, not just marketing narrative. _(unblocks retrieve, impact: high, effort: medium)_
2. **[MEDIUM]** Co-locate the related facts on a single page rather than relying on a reader (or retriever) to combine two pages. _(unblocks retrieve, impact: medium, effort: medium)_
3. **[MEDIUM]** Move the cited answer, or a direct one-line restatement of it, higher in the page's main content. _(unblocks arrive, impact: medium, effort: low)_
4. **[MEDIUM]** Name the brand explicitly in the page's opening content, not just in the nav/logo. _(unblocks arrive, impact: low, effort: low)_
5. **[MEDIUM]** Make consent/gate overlays non-blocking: render page content first, or default to a reasonable choice instead of gating first paint. _(unblocks arrive, impact: medium, effort: medium)_
6. **[MEDIUM]** Add an explicit next-step action (contact, buy, sign up, demo) directly on the citable pages, not just in global nav. _(unblocks arrive, impact: low, effort: low)_
7. **[LOW]** Use exactly one <h1> per page and avoid heading-level skips. _(unblocks extract, impact: low, effort: low)_

## Findings by stage

### ③ EXTRACT

- **[LOW] 2 of 12 page(s): heading hierarchy issue(s) -- no <h1> found** (`EXTRACT-003`, confidence: high, checked 12/affected 2)

### ④ RETRIEVE

- **[MEDIUM] 6 of 18 buyer-intent queries are unanswerable from the AI-reachable corpus** (`CHUNK-001`, confidence: high, checked 18/affected 6)
- **[MEDIUM] 5 buyer-intent queries can only be answered by combining facts from different pages** (`CHUNK-003`, confidence: medium, checked 18/affected 5)

### ⑥ ARRIVE

- **[MEDIUM] 6 of 12 citable answers sit in the back half of their page** (`ENGAGE-001`, confidence: medium, checked 12/affected 6)
- **[MEDIUM] 2 of 3 page(s): a cold arrival can't tell what this is without the nav** (`ENGAGE-002`, confidence: low, checked 3/affected 2)
- **[MEDIUM] 3 of 3 citable page(s) carry a consent/gate overlay that may block first meaningful paint** (`ENGAGE-004`, confidence: low, checked 3/affected 3)
- **[MEDIUM] 2 of 3 citable pages have no recognizable next step for the visitor** (`ENGAGE-005`, confidence: low, checked 3/affected 2)

## Proactive recommendations (no defect found)

- **No page answers comparison-intent questions**
- **No page answers trust-intent questions**
- **5 queries are one edit away from being citable**


**Degradations recorded this run:** `render_stage_skipped_by_flag`

---
_Full evidence, artifacts, and implementation steps for every finding are in the accompanying JSON and HTML reports._
