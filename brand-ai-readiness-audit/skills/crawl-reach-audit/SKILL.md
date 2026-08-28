---
name: crawl-reach-audit
description: Internal pipeline stage of the Brand AI Readiness Audit, invoked by ai-visibility-orchestrator. Not meant to be invoked directly. Owns stage 1 REACH -- can a bot fetch the site at all -- via AI-user-agent robots.txt probes, status/soft-404 detection, canonical integrity, WAF/interstitial detection, and sitemap health.
metadata:
  role: stage
  stage: reach
---

# crawl-reach-audit -- Stage ① REACH

Answers: **can a bot fetch it?** If not, nothing downstream can work --
REACH failures are the only findings that default to `critical` severity
by blocking the whole funnel.

## Detects

- Explicit AI-crawler blocks in `robots.txt` (named UAs: GPTBot,
  ChatGPT-User, ClaudeBot, anthropic-ai, Google-Extended, PerplexityBot,
  CCBot, Bytespider, Applebot, ...) -- see `RENDER-001`-adjacent
  `REACH-001` in `references/taxonomy.md` at the orchestrator.
- Status/soft-404 detection, canonical tag integrity.
- WAF/bot-challenge interstitials that block every UA regardless of
  declared identity (not just a robots.txt policy decision) -- see
  `REACH-003`.
- Sitemap health (missing, stale, sitemap index depth).

## Input / output contract

Reads the shared `run_context` (site, budget remaining, sample seed).
Writes a `StageResult` with `stage: reach`, findings (artifact-backed
per `Finding.artifacts`), and `corpus_delta`: the URLs that survive this
stage and get passed to `render-gap-audit`.

## Status

Crawl core (robots parsing, sitemap discovery, deterministic sampling,
fetch) lives in `src/brand_audit/crawl.py`. Detector logic lives in
`scripts/detect.py`: `REACH-001` (named AI-UA robots block), `REACH-002`
(locale-redirect empty body), `REACH-003` (WAF/bot-challenge block) are
translated directly from Day 1 field-research evidence; `REACH-004`
(soft-404), `REACH-005` (canonical integrity), `REACH-006` (sitemap
health) are engineering-derived from the build plan's own requirements
and unit-tested (`tests/test_reach_detectors.py`) but not yet observed
on a real site -- see
`docs/progress.md` at the repo root.
