"""Day 3 DoD: the dual-fetch differential correctly flags the
JS-only-price fixture and stays silent on the clean control.

Skipped entirely if playwright isn't installed, per the "optional
dependency, graceful skip" rule -- this is exactly the scenario that
absence is supposed to produce, not a reason to fail the suite.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"


def _serve(fixture_name: str, port: int):
    directory = str(REPO_ROOT / "tests" / "fixtures" / fixture_name)
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(a[0], a[1], a[2], directory=directory)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("localhost", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run_audit(site: str, run_dir: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), site, "--run-dir", str(run_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"run_audit.py failed: {result.stderr}"
    return json.loads((run_dir / "report.json").read_text())


def test_js_only_price_fixture_is_flagged(tmp_path):
    server = _serve("js-only-price", 8124)
    try:
        report = run_audit("http://localhost:8124", tmp_path / "run")
    finally:
        server.shutdown()

    render_findings = [f for f in report["findings"] if f["stage"] == "render"]
    assert len(render_findings) >= 1
    finding = render_findings[0]
    assert finding["taxonomy_id"] == "RENDER-001"
    assert finding["severity"] == "critical"
    assert finding["confidence"] == "high"
    assert len(finding["artifacts"]) >= 1
    assert finding["artifacts"][0]["rendered_extract"]
    assert "49.99" in finding["artifacts"][0]["rendered_extract"]
    assert report["summary"]["ai_readiness"]["render"] == "fail"


def test_clean_control_fixture_stays_silent(tmp_path):
    server = _serve("clean-control", 8123)
    try:
        report = run_audit("http://localhost:8123", tmp_path / "run")
    finally:
        server.shutdown()

    render_findings = [f for f in report["findings"] if f["stage"] == "render"]
    assert render_findings == []
    assert report["summary"]["ai_readiness"]["render"] == "pass"


def test_empty_shell_ratio_below_threshold_is_page_class_not_site_wide():
    # Real Day 8 bug: every empty-shell page used to claim SITE_WIDE
    # unconditionally, regardless of how many *other* rendered pages
    # were fine -- 1 empty page out of 10 rendered is not "your whole
    # site is JS-only."
    import render_detect

    comparisons = [
        render_detect.RenderComparison(
            url="https://example.com/empty", raw_text="", rendered_text="x" * 200,
            raw_facts={"currency": set(), "date": set(), "contact": set()},
            rendered_facts={"currency": set(), "date": set(), "contact": set()},
        )
    ] + [
        render_detect.RenderComparison(
            url=f"https://example.com/{i}", raw_text="substantial real content here " * 10, rendered_text="x" * 200,
            raw_facts={"currency": set(), "date": set(), "contact": set()},
            rendered_facts={"currency": set(), "date": set(), "contact": set()},
        )
        for i in range(9)
    ]
    finding = render_detect.detect_empty_shell_pages(comparisons)
    assert finding is not None
    assert finding.severity == "high"  # PAGE_CLASS, not CRITICAL
    assert finding.scope.checked == 10
    assert finding.scope.affected == 1


def test_empty_shell_ratio_above_threshold_is_site_wide():
    import render_detect

    comparisons = [
        render_detect.RenderComparison(
            url=f"https://example.com/{i}", raw_text="", rendered_text="x" * 200,
            raw_facts={"currency": set(), "date": set(), "contact": set()},
            rendered_facts={"currency": set(), "date": set(), "contact": set()},
        )
        for i in range(10)
    ]
    finding = render_detect.detect_empty_shell_pages(comparisons)
    assert finding is not None
    assert finding.severity == "critical"
    assert finding.scope.checked == 10
    assert finding.scope.affected == 10
    assert len(finding.artifacts) == 10  # every affected URL, not just a few examples -- RETRIEVE's gating depends on it


def test_no_comparisons_returns_none():
    import render_detect

    assert render_detect.detect_empty_shell_pages([]) is None


def test_render_failure_is_none_not_empty_string():
    # A render that fails/times out must be distinguishable from a page
    # that genuinely rendered to nothing -- conflating the two would make
    # a real RENDER-001 case (raw substantial, render genuinely failed)
    # silently vanish instead of being flagged or at least surfaced as
    # unknown. Port 8199 has nothing listening -- goto() will error.
    import asyncio

    sys.path.insert(0, str(REPO_ROOT / "skills" / "render-gap-audit" / "scripts"))
    import render_detect

    results = asyncio.run(render_detect.render_fetch(["http://localhost:8199/nothing-here"], timeout_ms=3000))
    assert results["http://localhost:8199/nothing-here"] is None
