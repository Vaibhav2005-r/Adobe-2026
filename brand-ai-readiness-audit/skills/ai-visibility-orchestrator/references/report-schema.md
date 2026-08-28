# Report schema

**Source of truth:** `src/brand_audit/models.py` (Pydantic v2). The JSON
Schema at `assets/report_schema.json` is *generated* from these models by
`scripts/gen_schema.py` -- never hand-edit either the schema file or a
report; if the contract needs to change, change the models and
regenerate:

```
python scripts/gen_schema.py
```

## Top-level: `AuditReport`

| Field | Type | Notes |
|---|---|---|
| `site` | string | bare domain, e.g. `example.com` |
| `audited_at` | datetime | the only field allowed to differ between two runs of the same site (determinism proof) |
| `schema_version` | string | semver of this contract |
| `run_manifest` | `RunManifest` | determinism/degradation proof |
| `summary` | `Summary` | the headline a non-expert reads |
| `findings` | `Finding[]` | shipped, artifact-backed defects |
| `observations` | `Finding[]` | findings that failed falsification -- demoted, never dropped |
| `proactive_recommendations` | `ProactiveRecommendation[]` | the beyond-defect layer, derived from measured gaps |
| `answerability_matrix` | `AnswerabilityMatrixEntry[]` | per-query outcome from stage ④ |

## `RunManifest` -- the determinism proof

`marketplace_version`, `rule_pack_version`, `pages_crawled`,
`pages_rendered`, `sample_seed` (`sha256:<hash of the domain>` --
time-independent by construction, see `crawl.sample_seed_for`),
`duration_s`, `stages_completed`, `degradations` (recorded, never
silent).

## `Finding` -- the unit of output

Every finding must carry:

- `taxonomy_id` -- maps to an entry in `references/taxonomy.md`; no
  entry there, no finding here.
- `scope: {checked, affected, page_class}` -- can't claim site-wide off
  a sample of one.
- `artifacts: Artifact[]` (min length 1) -- **no artifact, no finding**,
  enforced at the model level (`min_length=1`).
- `evidence` -- the literal extracted strings, not a paraphrase.
- `impact_mechanism` -- why this breaks retrieval/citation, not a
  symptom restated.
- `confidence` and `verification` -- set by `finding-verification`, not
  hand-assigned by the detecting stage.
- `suggested_action` -- `stage_unblocked` ties the fix back to which
  stage broke, so the fix is mechanism-sound by construction;
  `verification_step` gives the reader a one-liner to confirm the fix
  worked.

## `StageResult` -- what every stage skill actually returns

Not part of the final report directly (the orchestrator's
`assemble_report.py` merges these) -- this is the contract stage skills
implement against. `stage`, `findings`, `artifacts`, `corpus_delta` (URLs
this stage adds to or removes from the AI-reachable corpus), `metrics`
(free-form, stage-specific counters -- e.g. stage ① writes
`pages_discovered`, `pages_sampled`, `pages_fetched_ok`).

See `references/composition.md` for how `corpus_delta` gates downstream
stages.
