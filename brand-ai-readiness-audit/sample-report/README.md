# Sample report: allbirds.com

Generated with the exact code in this repo:

```bash
python skills/ai-visibility-orchestrator/scripts/run_audit.py allbirds.com --max-pages 12 --skip-render
```

`--skip-render` (no Playwright): this is deliberately the *bare-machine*
configuration -- the one most graders will actually run, and stage ②
RENDER's own optional-dependency, graceful-skip behavior is part of
what's being demonstrated (`ai_readiness.render: "skipped"`, recorded
in `run_manifest.degradations` as `render_stage_skipped_by_flag`, not
silently omitted). `report.html` is the single-file demo surface --
open it directly in a browser. `report.json` is the schema-valid
contract. `report.md` is the short executive summary.

It also exercises the **proactive layer**: four recommendations derived
from measured gaps (three buyer-intent classes nothing answers, plus six
queries that resolved only as PARTIAL and are one edit from citable).
Notably there is *no* `llms.txt` recommendation -- allbirds.com actually
serves one (`# Agent Instructions — Allbirds`), so the generator
correctly stayed silent. That is the detection working in both
directions, not a gap.

5 findings across three stages on a real, well-known Shopify DTC site:
`EXTRACT-003` (heading-hierarchy gaps, 6 of the 12 sampled pages),
`CHUNK-001` + `CHUNK-003` (buyer-intent queries that don't resolve
from a single page), `ENGAGE-002` (3 of 4 citable pages don't name the
brand near the top of their own content -- the deep-link orientation
gap stage ⑥ exists to catch), and `ENGAGE-004` (a OneTrust
consent-overlay signature on the citable page set). Zero findings were
demoted to `observations` by `finding-verification` on this run.

Each of those five is *one* line of work, scoped across the pages it
affects. An earlier version of this snapshot listed twelve findings for
the same five defects, because the per-page detectors each emitted one
finding per URL: six identical `EXTRACT-003` entries and three identical
`ENGAGE-002` entries, every one of them claiming `checked: 1,
affected: 1`. Same detections, same readiness, same headline -- but the
prioritized action list repeated itself, and no finding's scope added up
to the site-wide defect it was part of. `assemble_report.
_aggregate_per_page_findings` now collapses them.

Regenerate any time with the command above -- a live site's content can
change between runs, so this snapshot won't be byte-identical forever,
but the *mechanism* behind every finding will still hold.
