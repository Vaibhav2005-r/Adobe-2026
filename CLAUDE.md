See @docs/build-plan.md for the full 10-day plan, rubric strategy, report schema, and risk/cut list. Read it before doing any work — it is the source of truth for scope and architecture decisions.

# Project: Brand AI Readiness Audit (Adobe Hackathon Round 3)

10-day take-home, Fri 28 Aug → Sun 6 Sep 2026. Deliverable: a Claude Skills marketplace (`brand-ai-readiness-audit/`) that audits a website's visibility to AI assistants.

## The thesis (never lose sight of this)

Don't audit the page — simulate the retrieval pipeline an AI assistant runs, and report the exact stage where the brand falls out: REACH → RENDER → EXTRACT → RETRIEVE → CITE → ARRIVE. Every finding must be stage-localised and artifact-backed (URL + status + selector/byte-offset + literal extracted strings). No artifact, no finding.

## Hard constraints (non-negotiable, check before every commit)

- ≤50 MB zip, no bundled model weights
- <5 minute runtime per audit (hard watchdog with a degradation ladder — record degradations in the report, never fail silently)
- Fully deterministic: same site in → same report out (three runs, byte-identical modulo `audited_at`)
- Read-only, robots-respecting, no auth, no writes to the audited site
- Portable: must run on a judge's bare machine — every optional dependency (Playwright) needs a stdlib/graceful-skip fallback

## Repo layout

```
brand-ai-readiness-audit/
├── marketplace.json          # exactly one entrypoint
├── README.md                 # thesis, composition contract, eval results
└── skills/
    ├── ai-visibility-orchestrator/   ENTRYPOINT — pipeline driver, report assembly
    ├── crawl-reach-audit/            ① REACH
    ├── render-gap-audit/             ② RENDER — dual-fetch differential
    ├── extractability-audit/         ③ EXTRACT
    ├── retrieval-simulation/         ④ RETRIEVE — crown jewel, BM25 answerability probe
    ├── trust-corroboration-audit/    ⑤ CITE
    ├── arrival-engagement-audit/     ⑥ ARRIVE
    └── finding-verification/         cross-cutting falsification pass
```

Each stage skill reads a shared `run_context` and writes `StageResult{findings[], artifacts[], corpus_delta, metrics}`. `retrieval-simulation` only sees the corpus that survived stages ① and ②. This gating is the composition story — don't break it by letting stages read the raw crawl directly.

## Tech stack (see build-plan for full rationale)

Python 3.11+, `httpx` (async), `protego` (robots), `playwright` (optional, stage ② only), `selectolax`/`lxml`, `trafilatura` (main-content extraction, identical on both fetch paths), `extruct` (structured data), hand-rolled BM25 (~120 LOC, no embeddings — deliberate: deterministic, no model weights, no API key). Pydantic v2 models generate `report_schema.json` — models are the source of truth, never hand-edit the schema.

## Working rules

- **Every rule must state a mechanism**, not just a symptom, before it enters the rule pack (`references/taxonomy.md`). If a fix only helps one site, it's overfitting — delete it.
- **Falsification before shipping a finding**: re-fetch, check reproducibility, look for contradicting signals, check sample adequacy. Findings that fail get demoted to `observations`, never silently dropped.
- Confidence/severity are computed by the deterministic `severity = f(stage, blast_radius, confidence)` function in `references/severity-model.md` — never hand-assigned.
- LLM usage is confined to two schema-constrained, temperature-0 calls (answerability classification, suggested-action prose) with deterministic fallbacks. Everything else is deterministic code.
- Validate every skill folder with `skills-ref validate` before committing; CI runs it on all 8 + manifest lint.

## Current status

**Project complete — all 10 days shipped.** Day 10 (Sun 6 Sep): package & narrative — done. The real README replaces the Day 2 placeholder (thesis, composition contract, the published confusion matrix, a corrected "fully deterministic, zero LLM calls anywhere" statement — verified by grep before writing it down, not assumed from the build plan's own aspiration, which had reserved two LLM touchpoints that ended up implemented as deterministic code instead). Every `SKILL.md` was already under the 500-line hygiene target with no retrofitting needed. The Day 10 DoD was met literally, not just claimed: zip built (216 KB), extracted into a directory that never touched the dev `.venv`, installed into a brand-new virtualenv with zero pre-existing state, and run end-to-end using only the README's own Quickstart command — produced a valid report in 3.2s, with the full test suite also passing in that same clean environment (155 passed, 1 correctly-skipped Playwright module, confirming the bare-machine story is real). A committed sample report (`sample-report/`, allbirds.com) uses `--skip-render` deliberately — the configuration most graders will actually experience, not the one that looks most complete. Two more stale-doc bugs caught in `taxonomy.md`'s own footer while touching it (a "33 entries" arithmetic slip that was actually 31, and a "Day 8 remaining" line three days out of date). 161 tests passing throughout. See `docs/progress.md` for the full ten-day accounting, including a flagged assumption about `marketplace.json`'s exact format (the original hackathon brief isn't available in-session, only this file's summary of it — worth double-checking against the real brief before final submission).

## Commands

- Setup: `cd brand-ai-readiness-audit && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Run an audit: `python skills/ai-visibility-orchestrator/scripts/run_audit.py <site> [--max-pages 40] [--out report.json]` (also writes `report.html` + `report.md` alongside it)
- Validate skills: `for d in skills/*/; do npx --yes skills-ref validate "$d"; done`
- Manifest lint: `python skills/ai-visibility-orchestrator/scripts/lint_marketplace.py`
- Regenerate report schema after editing models: `python skills/ai-visibility-orchestrator/scripts/gen_schema.py`
- Tests (smoke + determinism, local fixture, no network): `python -m pytest tests/ -v`
- Run fixture eval / confusion matrix: `python scripts/eval_fixtures.py [--out results.md]`
