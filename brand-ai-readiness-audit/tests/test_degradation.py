"""Day 9 degradation testing: docs/build-plan.md Part 7 names six
specific degraded conditions the pipeline must survive gracefully. Four
already have dedicated coverage elsewhere and aren't repeated here:

- no Playwright -> tests/test_smoke.py's PLAYWRIGHT_AVAILABLE branch,
  exercised on every CI run without the optional dependency.
- robots-blocked -> tests/test_robots_compliance.py (crawler behavior)
  and tests/test_reach_detectors.py (REACH-001 detection).
- JS-heavy SPA -> tests/test_render_gap.py (tests/fixtures/js-only-price).
- no network mid-run -> tests/test_budget.py's near-zero-budget cases
  exercise the same "bail out honestly, don't hang" path a mid-run
  network failure would need; a literal network-drop injection isn't
  practical to simulate deterministically in this test suite.

This file covers the two that don't: a sitemap-less site (does the
crawl still audit something instead of finding zero URLs?) and a very
large sitemap (does the sampler stay fast and correctly bounded, not
just "eventually" bounded?).
"""

from __future__ import annotations

import hashlib
import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brand_audit.crawl import sample_seed_for, stratified_sample  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"


# --- large sitemap: sampler stays fast and correctly bounded ----------------


def test_stratified_sample_handles_5000_urls_quickly_and_deterministically():
    urls = [f"https://example.com/product/{i}" for i in range(5000)]
    seed = sample_seed_for("example.com")

    start = time.monotonic()
    sample_a = stratified_sample(urls, seed, max_pages=40)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"sampling 5000 URLs took {elapsed:.2f}s -- should be near-instant"
    assert len(sample_a) == 40
    assert len(set(sample_a)) == 40  # no duplicates
    assert all(u in urls for u in sample_a)  # every sampled URL came from the input

    sample_b = stratified_sample(urls, seed, max_pages=40)
    assert sample_a == sample_b  # determinism holds at this scale too


def test_stratified_sample_handles_more_urls_than_max_pages_requested():
    urls = [f"https://example.com/page/{i}" for i in range(5000)]
    seed = sample_seed_for("example.com")
    sample = stratified_sample(urls, seed, max_pages=5)
    assert len(sample) == 5


# --- no sitemap: crawl still audits the homepage, not zero pages ------------


def _serve(fixture_name: str, port: int):
    directory = str(REPO_ROOT / "tests" / "fixtures" / fixture_name)
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(a[0], a[1], a[2], directory=directory)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("localhost", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run_audit(site: str, run_dir: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), site, "--run-dir", str(run_dir), "--skip-render"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"run_audit.py failed: {result.stderr}"
    return json.loads((run_dir / "report.json").read_text())


def test_site_with_no_sitemap_still_gets_audited(tmp_path):
    # No sitemap.xml file, no Sitemap: line in robots.txt -- confirms
    # discover_sitemap_urls's documented fallback (falls back to
    # [base_url] when nothing is discovered) actually reaches a
    # real, schema-valid report, not just an internal function return
    # value.
    server = _serve("no-sitemap", 8132)
    try:
        report = run_audit("http://localhost:8132", tmp_path / "run")
    finally:
        server.shutdown()

    assert report["run_manifest"]["pages_crawled"] >= 1
    assert report["summary"]["ai_readiness"]["reach"] == "pass"
    # The one page that exists was actually examined by later stages too,
    # not just fetched and ignored -- confirms the fallback sample
    # propagates through the whole pipeline, not just the REACH stage.
    assert len(report["answerability_matrix"]) == 18
