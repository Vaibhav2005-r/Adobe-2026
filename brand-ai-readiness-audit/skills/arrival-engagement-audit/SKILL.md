---
name: arrival-engagement-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 6 ARRIVE, the mid-task arrival model -- audits the pages most likely to be cited against an AI-referred visitor persona (deep-linked, mid-task, zero context) for answer proximity, orientation, context reset, entry interference, next-step availability, AI-referral instrumentation, and scoped response latency.
metadata:
  role: stage
  stage: arrive
---

# arrival-engagement-audit -- Stage ⑥ ARRIVE

Answers: **does the visitor stay?** Deliberately not a generic UX audit
-- an AI-referred visitor is fundamentally different from a search
visitor: deep-linked (never the homepage), mid-task with a specific
question already formed, already given a partial answer by the
assistant, with zero context about who the brand is. If a finding would
be identical for a Google visitor, it doesn't belong here.

## Detects

- **`ENGAGE-001`** Answer proximity: is the answer the assistant would
  have cited present in the top half of the page's own main content?
  (A text-offset proxy for "above the fold" -- this stage does no
  rendering, so exact pixel position isn't available.)
- **`ENGAGE-002`** Orientation gap: does a citable page name the brand
  near the top of its own main content, without relying on the nav a
  deep-linked visitor never scans?
- **`ENGAGE-003`** Context reset: does a citable deep link redirect to
  `/` or a region/locale selector? (An outright killer -- the
  assistant's citation lands nowhere useful.)
- **`ENGAGE-004`** Entry interference: a known consent-wall / age-gate
  / modal library signature detected in a citable page's markup.
- **`ENGAGE-005`** Missing next-step: no recognizable call-to-action
  phrase anywhere in the citable page set's main content.
- **`ENGAGE-006`** AI-referral instrumentation: is the site even set up
  to detect *any* referral traffic? Most brands have no analytics at
  all, so they can't tell `chatgpt.com` / `perplexity.ai` / `claude.ai`
  traffic is failing -- this check can only confirm that cruder,
  stronger gap, not verify AI-referral-specific segmentation from
  static HTML.
- **`ENGAGE-007`** Scoped response latency: citable pages (not the
  homepage) taking over 3 seconds to respond -- the build plan's own
  cut-list fallback ("keep TTFB -- cheap and adequate") in place of
  LCP/INP, which this stage has no rendering step to measure.

All seven run on data the pipeline already collected in stage ① (raw
HTML, each fetch's `FetchRecord`) and stage ④ (the answerability_matrix)
-- no new network calls, no rendering, consistent with this stage
having no hard dependency beyond what earlier stages already produced.

Field research had flagged one candidate mechanism worth testing here:
a canonical marketing URL that returns an empty-body redirect to a
locale-specific variant based on IP geolocation (`REACH-002` in
`references/taxonomy.md` at the orchestrator) is a crawler-fetch
problem as currently classified, but the same redirect behavior is also
exactly the "context reset" pattern this stage catches for a real
deep-link arrival -- `ENGAGE-003` is that detector, built and tested,
though not yet observed re-triggering the specific `REACH-002` case on
a live re-check.

## Input / output contract

Reads the `citable=True` pages from stage ④'s own answerability_matrix
-- the pages that actually won a buyer-intent query, not a re-derived
guess at "pages likely to be cited" (a more precise definition than the
stage-⑤ CITE survivor set this doc originally proposed, since CITE
doesn't itself filter by citability). Falls back to the full stage ①
survivor set if nothing won a query, so a tiny fixture or an
all-UNRETRIEVABLE corpus still gets an arrival/engagement check rather
than none. `ENGAGE-006` (instrumentation) checks the full stage ①
survivor set regardless, since analytics snippets are typically
injected site-wide. Writes a `StageResult` with `stage: arrive`; gated
in `run_audit.py` on stage ④ having actually run (not just on budget),
since it reads stage ④'s own output directly.

## Status

Implemented in `scripts/arrive_detect.py`. All seven detectors are
unit-tested against both a defect case and a clean-control case
(`tests/test_arrive.py`), plus an end-to-end fixture
(`tests/fixtures/arrival-clean`) with the brand named up top on every
page, a CTA on every page, an analytics snippet, and no redirects or
consent overlays -- every detector confirmed silent on it, and the
stage confirmed byte-identical across two runs. `ENGAGE-002`,
`ENGAGE-004`, `ENGAGE-005`, and `ENGAGE-006` confirmed firing on real
sites (not just fixtures) during the Day 7 wild-corpus sweep; see
`docs/progress.md` for the full accounting, including a real
entity-detection bug (Day 5-era code, in `retrieval-simulation`, not
this skill) that this stage's own findings surfaced and that was fixed
the same day.
