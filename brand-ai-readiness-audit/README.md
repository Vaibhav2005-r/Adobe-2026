# Brand AI Readiness Audit

> Every other submission scores your website against a checklist. Ours
> reproduces the pipeline an AI assistant actually runs -- reach, render,
> extract, retrieve, cite, arrive -- tells you the exact stage where your
> brand falls out, proves it with the two extractions side by side, and
> then tries to prove itself wrong before it reports anything.

**This README is a placeholder.** The full narrative (thesis, composition
story, published eval results with confusion matrix, limitations stated
honestly) is Day 10 work, by design -- see `docs/build-plan.md` Part 7 at
the repo root. What's here now is enough to run the current skeleton.

## Quickstart

```
pip install -e .
python skills/ai-visibility-orchestrator/scripts/run_audit.py example.com
```

Runtime is hard-capped under 5 minutes; `report.json` is written to
`runs/<domain>/report.json` by default. See
`skills/ai-visibility-orchestrator/SKILL.md` for the full CLI and the
composition contract.

## Status

Stage ① (REACH) crawl core only -- no detectors wired up yet, so every
report currently has zero findings by construction. See
`docs/progress.md` at the repo root for the honest day-by-day accounting.

## Structure

```
marketplace.json              one entrypoint: ai-visibility-orchestrator
skills/
  ai-visibility-orchestrator/ pipeline driver, report assembly (ENTRYPOINT)
  crawl-reach-audit/          stage 1 REACH
  render-gap-audit/           stage 2 RENDER
  extractability-audit/       stage 3 EXTRACT
  retrieval-simulation/       stage 4 RETRIEVE
  trust-corroboration-audit/  stage 5 CITE
  arrival-engagement-audit/   stage 6 ARRIVE
  finding-verification/       cross-cutting falsification pass
src/brand_audit/              shared models + crawl core, imported by stage scripts
tests/fixtures/               local fixture sites (no live network needed for CI)
```
