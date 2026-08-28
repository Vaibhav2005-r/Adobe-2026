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

Day 6 (Wed 2 Sep): stage ④ RETRIEVE part 2 + stage ⑤ CITE — done, all five detection stages now wired end-to-end. RETRIEVE gained orphan-fact (`CHUNK-002`), cross-page-join (`CHUNK-003`), and boilerplate-ratio (`CHUNK-004`) detectors; `trust-corroboration-audit` (entity anchoring, staleness, description drift, attribution density) is real, tested code. Deliberately skipped the live name-collision web search the build plan itself lists as first-to-cut (also a real determinism/portability conflict, not just a time-saver). Day 6's own DoD ("full pipeline runs end-to-end on the wild corpus without crashing") was run for real against 11 diverse live sites — zero crashes, and the sweep itself surfaced a genuine new mechanism (`REACH-007`: a site's WAF blocking fetches its own robots.txt explicitly allows), found, implemented, and shipped the same session. 104 tests passing. See `docs/progress.md` for the full accounting, including a flagged assumption about `marketplace.json`'s exact format (the original hackathon brief isn't available in-session, only this file's summary of it — worth double-checking). Update this section (or better, ask me to log it in `docs/progress.md`) as each day's DoD from the build plan is met, so a fresh session picks up where the last one left off.

## Commands

- Setup: `cd brand-ai-readiness-audit && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Run an audit: `python skills/ai-visibility-orchestrator/scripts/run_audit.py <site> [--max-pages 40] [--out report.json]`
- Validate skills: `for d in skills/*/; do npx --yes skills-ref validate "$d"; done`
- Manifest lint: `python skills/ai-visibility-orchestrator/scripts/lint_marketplace.py`
- Regenerate report schema after editing models: `python skills/ai-visibility-orchestrator/scripts/gen_schema.py`
- Tests (smoke + determinism, local fixture, no network): `python -m pytest tests/ -v`
- Run fixture eval / confusion matrix: `TBD` (Day 9)
