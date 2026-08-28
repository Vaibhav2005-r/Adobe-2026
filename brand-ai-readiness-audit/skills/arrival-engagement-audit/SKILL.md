---
name: arrival-engagement-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 6 ARRIVE, the mid-task arrival model -- audits the pages most likely to be cited against an AI-referred visitor persona (deep-linked, mid-task, zero context) for answer proximity, orientation, context reset, entry interference, next-step availability, AI-referral instrumentation, and scoped Core Web Vitals.
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

- Answer proximity: is the answer the assistant would have cited present
  in text above the fold?
- Orientation: can a cold arrival tell what the company is and what this
  page is, from this page alone, without the nav?
- Context reset: do deep links redirect to `/` or a region/locale
  selector? (An outright killer -- the assistant's citation lands
  nowhere useful.)
- Entry interference: consent walls, modals, chat popups, age gates
  blocking first meaningful paint.
- Next-step availability on the landing page itself, not behind a
  navigation hunt.
- AI-referral instrumentation: is the site even set up to detect
  `chatgpt.com` / `perplexity.ai` / `claude.ai` referrals? Most brands
  can't see this traffic, so they can't tell it's failing.
- Performance (LCP/INP/TTFB), scoped to the citable page set only, not
  the homepage.

Field research already flagged one candidate mechanism worth testing
here once this stage exists: a canonical marketing URL that returns an
empty-body redirect to a locale-specific variant based on IP geolocation
(`REACH-002` in `references/taxonomy.md` at the orchestrator) is a
crawler-fetch problem as currently classified, but the same redirect
behavior is also exactly the "context reset" pattern this stage is
meant to catch for a real deep-link arrival -- worth testing both
framings once stage ⑥ can run.

## Input / output contract

Reads the stage-⑤ survivor set (the pages most likely to be cited).
Writes a `StageResult` with `stage: arrive`.

## Status

Not yet implemented -- see `docs/progress.md` at the repo root.
