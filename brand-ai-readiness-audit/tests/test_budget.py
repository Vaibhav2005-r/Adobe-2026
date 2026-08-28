"""Proves the time-budget watchdog is actually enforced, not just
instantiated and ignored -- CLAUDE.md's "<5 minute runtime... hard
watchdog" hard constraint, checked end-to-end.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "clean-control"
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"
# clean-control's robots.txt/sitemap.xml hardcode localhost:8123 (see
# tests/fixtures/clean-control/robots.txt) -- must match, or the sitemap
# reference looks broken from this port's perspective and REACH-006
# (correctly) fires. Reserve 8123 for this fixture across test files
# rather than parametrizing the fixture itself for a port that doesn't
# matter to what this test is actually checking.
PORT = 8123


def _serve():
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(FIXTURE_DIR), **kw
    )
    server = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_near_zero_budget_produces_degraded_report_not_a_hang_or_crash(tmp_path):
    server = _serve()
    run_dir = tmp_path / "run"
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), f"http://localhost:{PORT}", "--run-dir", str(run_dir), "--budget-s", "0.001"],
            capture_output=True,
            text=True,
            timeout=30,  # the whole point: this must return quickly, not hang
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr  # degraded, not failed -- still produces output
    report = json.loads((run_dir / "report.json").read_text())
    assert report["run_manifest"]["degradations"] == ["reach_stage_timed_out_budget_exhausted"]
    assert report["findings"] == []
    assert report["summary"]["ai_readiness"]["reach"] == "skipped"


def test_budget_too_tight_for_render_skips_it_cleanly(tmp_path):
    # Enough budget for the (tiny, local) REACH stage to finish, but not
    # enough left over to be worth starting Chromium for RENDER.
    server = _serve()
    run_dir = tmp_path / "run"
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), f"http://localhost:{PORT}", "--run-dir", str(run_dir), "--budget-s", "5"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr
    report = json.loads((run_dir / "report.json").read_text())
    assert report["summary"]["ai_readiness"]["reach"] == "pass"
    # Either playwright isn't installed, or the budget check skipped it --
    # either way, render must not silently claim "pass" without running.
    if report["summary"]["ai_readiness"]["render"] != "skipped":
        raise AssertionError(report["run_manifest"]["degradations"])
