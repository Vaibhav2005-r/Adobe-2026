"""End-to-end smoke test: run_audit.py against the clean-control fixture,
end-to-end, and assert the report is schema-valid, has zero REACH/
RENDER/EXTRACT findings (the clean control has no injected defects for
those stages -- it was never built to comprehensively answer all 18
RETRIEVE-stage buyer-intent queries, so a RETRIEVE finding here is
expected, not a regression; see tests/fixtures/retrieval-answerable for
the fixture that actually exercises answerability), and is byte-identical
across two runs modulo `audited_at` / `duration_s` (the determinism
proof).

No live network access required -- serves tests/fixtures/clean-control
over a local http.server, matching how a judge running this offline
would still get a real report on their own bare machine.

Whether stage (2) RENDER actually runs depends on whether playwright is
installed (it's an optional dependency, per docs/build-plan.md Part 4) --
this test asserts the *correct* behavior for whichever case is true
rather than assuming one, so it passes in both the full-dependency and
bare-machine configurations.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "clean-control"
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"
PORT = 8123

try:
    import playwright  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@pytest.fixture(scope="module")
def fixture_server():
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(FIXTURE_DIR), **kw
    )
    server = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{PORT}"
    server.shutdown()


def run_audit(site: str, run_dir: Path, *extra_args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), site, "--run-dir", str(run_dir), *extra_args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"run_audit.py failed: {result.stderr}"
    return json.loads((run_dir / "report.json").read_text())


def test_clean_control_produces_zero_findings(fixture_server, tmp_path):
    report = run_audit(fixture_server, tmp_path / "run1")
    non_retrieve_findings = [f for f in report["findings"] if f["stage"] != "retrieve"]
    assert non_retrieve_findings == []
    assert report["run_manifest"]["pages_crawled"] >= 1
    assert report["summary"]["ai_readiness"]["reach"] == "pass"
    assert report["summary"]["ai_readiness"]["extract"] == "pass"
    # RETRIEVE did run and produced a real matrix -- just not asserting
    # it's all-answerable, since this fixture was never built for that.
    assert len(report["answerability_matrix"]) == 18

    if PLAYWRIGHT_AVAILABLE:
        assert report["summary"]["ai_readiness"]["render"] == "pass"
        assert report["run_manifest"]["pages_rendered"] >= 1
        assert "render_stage_skipped_no_playwright" not in report["run_manifest"]["degradations"]
    else:
        assert report["summary"]["ai_readiness"]["render"] == "skipped"
        assert "render_stage_skipped_no_playwright" in report["run_manifest"]["degradations"]


def test_determinism_across_runs(fixture_server, tmp_path):
    # --skip-render: this test is about the crawl/report-assembly
    # determinism guarantee specifically, not render correctness (that's
    # tests/test_render_gap.py) -- keeping it fast and focused.
    report_a = run_audit(fixture_server, tmp_path / "run_a", "--skip-render")
    report_b = run_audit(fixture_server, tmp_path / "run_b", "--skip-render")

    for r in (report_a, report_b):
        r["audited_at"] = None
        r["run_manifest"]["duration_s"] = None

    assert report_a == report_b
