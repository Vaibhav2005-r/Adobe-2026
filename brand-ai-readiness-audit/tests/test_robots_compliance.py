"""Proves the crawler actually respects robots.txt Disallow rules when
fetching -- not just that RobotsPolicy.allowed() exists and is correct in
isolation, but that run_audit.py actually calls it before making a
request. This is CLAUDE.md's "read-only, robots-respecting" hard
constraint, checked end-to-end rather than trusted from code inspection.

The fixture's sitemap.xml deliberately lists a page robots.txt disallows
(a realistic inconsistency -- sitemaps and robots.txt drift out of sync
on real sites) specifically so the sampler has a chance to pick it up if
the robots filter isn't actually wired in.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "robots-restricted"
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"
PORT = 8125
DISALLOWED_URL = f"http://localhost:{PORT}/staff-directory.html"


def test_disallowed_page_is_never_fetched(tmp_path):
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(FIXTURE_DIR), **kw
    )
    server = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    run_dir = tmp_path / "run"
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), f"http://localhost:{PORT}", "--run-dir", str(run_dir), "--skip-render"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr

    report = json.loads((run_dir / "report.json").read_text())
    assert DISALLOWED_URL not in report["findings"] and True  # sanity: report parses

    # The real assertion: no artifact anywhere in the run directory
    # references the disallowed URL. If the robots filter weren't wired
    # up, the sampler would have picked this URL up from the sitemap
    # (which deliberately lists it) and fetched it, leaving an artifact
    # behind.
    artifacts_dir = run_dir / "artifacts"
    fetched_urls = set()
    if artifacts_dir.exists():
        for artifact_file in artifacts_dir.glob("*.json"):
            data = json.loads(artifact_file.read_text())
            fetched_urls.add(data["url"])

    assert DISALLOWED_URL not in fetched_urls, (
        f"robots.txt disallows {DISALLOWED_URL} but it was fetched anyway: {fetched_urls}"
    )
    # And the allowed page *was* fetched, so this isn't passing just
    # because nothing got fetched at all.
    assert f"http://localhost:{PORT}/" in fetched_urls
