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

12 findings across three stages on a real, well-known Shopify DTC
site: six `EXTRACT-003` (heading-hierarchy gaps on product pages),
`CHUNK-001` + `CHUNK-003` (buyer-intent queries that don't resolve
from a single page), three `ENGAGE-002` (product pages that don't name
the brand near the top of their own content -- the deep-link
orientation gap stage ⑥ exists to catch), and `ENGAGE-004` (a OneTrust
consent-overlay signature on the citable page set). Zero findings were
demoted to `observations` by `finding-verification` on this run.

Regenerate any time with the command above -- a live site's content can
change between runs, so this snapshot won't be byte-identical forever,
but the *mechanism* behind every finding will still hold.
