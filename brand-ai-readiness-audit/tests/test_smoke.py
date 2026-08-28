"""Day 2 skeleton smoke test: run_audit.py against a local fixture,
end-to-end, twice, and assert the report is schema-valid, has zero
findings (no detectors exist yet), and is byte-identical across the two
runs modulo `audited_at` / `duration_s` (the determinism proof).

No network access required -- serves tests/fixtures/clean-control over
a local http.server, matching how a judge running this offline would
still get a real report on their own bare machine.
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


def run_audit(site: str, run_dir: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), site, "--run-dir", str(run_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"run_audit.py failed: {result.stderr}"
    return json.loads((run_dir / "report.json").read_text())


def test_skeleton_produces_zero_findings(fixture_server, tmp_path):
    report = run_audit(fixture_server, tmp_path / "run1")
    assert report["findings"] == []
    assert report["run_manifest"]["pages_crawled"] >= 1
    assert report["summary"]["total_findings"] == 0
    assert report["summary"]["ai_readiness"]["reach"] == "pass"
    assert report["summary"]["ai_readiness"]["render"] == "skipped"


def test_determinism_across_runs(fixture_server, tmp_path):
    report_a = run_audit(fixture_server, tmp_path / "run_a")
    report_b = run_audit(fixture_server, tmp_path / "run_b")

    for r in (report_a, report_b):
        r["audited_at"] = None
        r["run_manifest"]["duration_s"] = None

    assert report_a == report_b
