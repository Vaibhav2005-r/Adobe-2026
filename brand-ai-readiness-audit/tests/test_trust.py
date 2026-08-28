"""Stage (5) CITE: unit tests for trust-corroboration-audit's four
detectors (entity anchoring, staleness, description drift, attribution
density), each with both a defect case and a clean-control case.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import trust_detect as td

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"

# --- TRUST-005: entity anchoring --------------------------------------------


def test_missing_same_as_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Organization","name":"Acme Corp"}</script></head><body></body></html>'
    finding = td.detect_missing_entity_anchoring({"https://example.com/": html})
    assert finding is not None
    assert finding.taxonomy_id == "TRUST-005"


def test_present_same_as_not_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Organization","name":"Acme Corp","sameAs":["https://en.wikipedia.org/wiki/Acme"]}</script></head><body></body></html>'
    assert td.detect_missing_entity_anchoring({"https://example.com/": html}) is None


def test_empty_same_as_list_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Organization","name":"Acme Corp","sameAs":[]}</script></head><body></body></html>'
    finding = td.detect_missing_entity_anchoring({"https://example.com/": html})
    assert finding is not None


def test_no_organization_node_not_flagged():
    # Nothing to anchor if there's no named entity at all -- this is a
    # different (unbuilt) concern, not TRUST-005's.
    html = "<html><body>No structured data here.</body></html>"
    assert td.detect_missing_entity_anchoring({"https://example.com/": html}) is None


# --- TRUST-006: staleness ----------------------------------------------------


def test_old_date_modified_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Article","dateModified":"2020-01-01"}</script></head><body></body></html>'
    finding = td.detect_staleness({"https://example.com/": html}, reference_date=date(2026, 8, 29))
    assert finding is not None
    assert finding.taxonomy_id == "TRUST-006"


def test_recent_date_modified_not_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Article","dateModified":"2026-08-01"}</script></head><body></body></html>'
    assert td.detect_staleness({"https://example.com/": html}, reference_date=date(2026, 8, 29)) is None


def test_no_date_modified_not_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Article","headline":"x"}</script></head><body></body></html>'
    assert td.detect_staleness({"https://example.com/": html}, reference_date=date(2026, 8, 29)) is None


def test_malformed_date_does_not_crash():
    html = '<html><head><script type="application/ld+json">{"@type":"Article","dateModified":"not-a-date"}</script></head><body></body></html>'
    assert td.detect_staleness({"https://example.com/": html}, reference_date=date(2026, 8, 29)) is None


# --- TRUST-007: description drift --------------------------------------------


def test_mismatched_descriptions_flagged():
    html = '''<html><head>
    <meta name="description" content="Acme Corp sells industrial widgets and gears for manufacturing.">
    <meta property="og:description" content="Best pizza in downtown Springfield, order online now!">
    </head><body></body></html>'''
    finding = td.detect_description_drift({"https://example.com/": html}, "https://example.com/")
    assert finding is not None
    assert finding.taxonomy_id == "TRUST-007"


def test_consistent_descriptions_not_flagged():
    html = '''<html><head>
    <meta name="description" content="Acme Corp sells industrial widgets and gears for manufacturing.">
    <meta property="og:description" content="Acme Corp: industrial widgets and gears for manufacturing since 1994.">
    </head><body></body></html>'''
    assert td.detect_description_drift({"https://example.com/": html}, "https://example.com/") is None


def test_only_one_description_field_not_flagged():
    # Need at least 2 fields to compare -- can't detect drift from one.
    html = '<html><head><meta name="description" content="Acme Corp sells widgets."></head><body></body></html>'
    assert td.detect_description_drift({"https://example.com/": html}, "https://example.com/") is None


def test_description_drift_resolves_homepage_by_root_path_not_exact_match():
    # Same Day-5-derived bug class: the hint URL essentially never
    # exactly matches a real crawled URL (trailing slash, scheme).
    html = '''<html><head>
    <meta name="description" content="Acme Corp sells industrial widgets and gears for manufacturing.">
    <meta property="og:description" content="Best pizza in downtown Springfield, order online now!">
    </head><body></body></html>'''
    finding = td.detect_description_drift({"https://example.com/": html}, "https://example.com")  # no trailing slash
    assert finding is not None


# --- TRUST-008: attribution density ------------------------------------------


def test_unattributed_stats_flagged_when_majority_of_corpus():
    html = "<html><body><p>Our widgets reduce downtime by 42% and cost 15% less, with 99 percent uptime.</p></body></html>"
    finding = td.detect_low_attribution_density({"https://example.com/a": html, "https://example.com/b": html})
    assert finding is not None
    assert finding.taxonomy_id == "TRUST-008"


def test_attributed_stats_not_flagged():
    html = "<html><body><p>According to a 2025 industry study, our widgets reduce downtime by 42%.</p></body></html>"
    assert td.detect_low_attribution_density({"https://example.com/a": html, "https://example.com/b": html}) is None


def test_single_page_without_attribution_not_flagged_as_site_wide():
    # One page out of several isn't a site-wide pattern -- only flag
    # when it's the majority.
    stats_html = "<html><body><p>Our widgets reduce downtime by 42% and cost 15% less.</p></body></html>"
    plain_html = "<html><body><p>Welcome to our site. We sell widgets.</p></body></html>"
    pages = {f"https://example.com/{i}": plain_html for i in range(5)}
    pages["https://example.com/one-stats-page"] = stats_html
    assert td.detect_low_attribution_density(pages) is None


# --- end-to-end: CITE stage clean control ------------------------------------

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


def test_trust_clean_fixture_has_zero_cite_findings(tmp_path):
    # Proper sameAs, a recent dateModified, consistent descriptions
    # across meta/JSON-LD/OG, and an attributed statistic -- every
    # CITE-stage detector should stay silent.
    server = _serve("trust-clean", 8130)
    try:
        report = run_audit("http://localhost:8130", tmp_path / "run")
    finally:
        server.shutdown()

    cite_findings = [f for f in report["findings"] if f["stage"] == "cite"]
    assert cite_findings == []
    assert report["summary"]["ai_readiness"]["cite"] == "pass"
