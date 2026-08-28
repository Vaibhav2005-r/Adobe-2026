"""Stage (3) EXTRACT: unit tests per detector (synthetic HTML, fast,
isolated) plus the Day 4 DoD as an executable end-to-end test --
'contradiction detector has zero false positives on controls', proven
against a fixture with matching price/complete structured data/correct
heading hierarchy, not just asserted.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import extract_detect

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"


# --- unit tests: schema-vs-text contradiction (EXTRACT-001) -----------

def test_contradiction_flagged():
    html = '''<html><head><script type="application/ld+json">
    {"@type":"Product","offers":{"@type":"Offer","price":"199","priceCurrency":"USD"}}
    </script></head><body><h1>X</h1><p>Costs $249.</p></body></html>'''
    findings = extract_detect.detect_schema_text_contradiction("https://example.com/p", html)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "EXTRACT-001"
    assert findings[0].severity == "high"


def test_matching_price_different_formatting_not_flagged():
    # '199' (JSON-LD, no symbol/decimals) vs '$199.00' (text) are the
    # same fact -- naive string comparison would false-positive here.
    html = '''<html><head><script type="application/ld+json">
    {"@type":"Product","offers":{"@type":"Offer","price":"199","priceCurrency":"USD"}}
    </script></head><body><h1>X</h1><p>Costs $199.00 today.</p></body></html>'''
    findings = extract_detect.detect_schema_text_contradiction("https://example.com/p", html)
    assert findings == []


def test_no_json_ld_not_flagged():
    html = "<html><body><h1>X</h1><p>Costs $249.</p></body></html>"
    findings = extract_detect.detect_schema_text_contradiction("https://example.com/p", html)
    assert findings == []


def test_no_visible_text_price_not_flagged():
    # Nothing to contradict against -- shouldn't guess.
    html = '''<html><head><script type="application/ld+json">
    {"@type":"Product","offers":{"@type":"Offer","price":"199","priceCurrency":"USD"}}
    </script></head><body><h1>X</h1><p>No price mentioned here.</p></body></html>'''
    findings = extract_detect.detect_schema_text_contradiction("https://example.com/p", html)
    assert findings == []


# --- unit tests: missing required properties (EXTRACT-002) ------------

def test_offer_missing_price_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Offer","priceCurrency":"USD"}</script></head><body>x</body></html>'
    findings = extract_detect.detect_missing_required_properties("https://example.com/p", html)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "EXTRACT-002"


def test_complete_offer_not_flagged():
    html = '<html><head><script type="application/ld+json">{"@type":"Offer","price":"10","priceCurrency":"USD"}</script></head><body>x</body></html>'
    findings = extract_detect.detect_missing_required_properties("https://example.com/p", html)
    assert findings == []


def test_unrecognized_type_not_flagged():
    # A type not in the bundled subset shouldn't be silently assumed
    # invalid -- only checked types are checked.
    html = '<html><head><script type="application/ld+json">{"@type":"SomeUnknownType"}</script></head><body>x</body></html>'
    findings = extract_detect.detect_missing_required_properties("https://example.com/p", html)
    assert findings == []


# --- unit tests: heading hierarchy (EXTRACT-003) -----------------------
#
# EXTRACT-003/004 are scoped to trafilatura's main-content extraction
# (see extract_detect._main_content_html), not the raw page -- confirmed
# necessary against real sites (docs.python.org's sidebar nav widgets
# false-positived a "heading skip" when the whole page was scanned; see
# docs/progress.md). trafilatura's own boilerplate-detection heuristics
# reject bare, minimal HTML snippets as "not real content" and discard
# them entirely, so unit tests need a realistic page shell (nav/main/
# footer, substantial paragraph text) for the *positive* (should-flag)
# cases to actually exercise the code path rather than accidentally pass
# because trafilatura extracted nothing at all.

_LOREM = (
    "This paragraph carries enough real sentence content for trafilatura's "
    "extraction heuristics to treat it as substantive article body text "
    "rather than boilerplate to discard, which is what every one of these "
    "fixtures needs to actually exercise the detector."
)


def _page(body_inner: str) -> str:
    return (
        "<html><body>"
        "<nav><a href='/'>Home</a> <a href='/about'>About</a></nav>"
        f"<main>{body_inner}</main>"
        "<footer>Copyright 2026</footer>"
        "</body></html>"
    )


def test_heading_skip_flagged():
    html = _page(f"<h1>T</h1><p>{_LOREM}</p><h2>S</h2><p>{_LOREM}</p><h4>Skip</h4><p>{_LOREM}</p>")
    findings = extract_detect.detect_heading_hierarchy_issues("https://example.com/p", html)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "EXTRACT-003"


def test_multiple_h1_flagged():
    html = _page(f"<h1>A</h1><p>{_LOREM}</p><h1>B</h1><p>{_LOREM}</p>")
    findings = extract_detect.detect_heading_hierarchy_issues("https://example.com/p", html)
    assert len(findings) == 1


def test_clean_hierarchy_not_flagged():
    html = _page(f"<h1>T</h1><p>{_LOREM}</p><h2>S</h2><p>{_LOREM}</p><h3>Sub</h3><p>{_LOREM}</p><h2>S2</h2><p>{_LOREM}</p>")
    findings = extract_detect.detect_heading_hierarchy_issues("https://example.com/p", html)
    assert findings == []


def test_no_headings_at_all_not_flagged():
    # No headings isn't the same defect as "has headings but zero h1s" --
    # e.g. a page that's just a single block of prose.
    html = _page(f"<p>{_LOREM}</p>")
    findings = extract_detect.detect_heading_hierarchy_issues("https://example.com/p", html)
    assert findings == []


def test_sidebar_nav_headings_do_not_cause_a_false_positive():
    # The exact docs.python.org shape: a heading-level skip that exists
    # only in navigational chrome, never inside main content.
    html = (
        "<html><body>"
        "<nav class='sidebar'><h3>Download</h3><h3>Other resources</h3></nav>"
        f"<main><h1>T</h1><p>{_LOREM}</p></main>"
        "</body></html>"
    )
    findings = extract_detect.detect_heading_hierarchy_issues("https://example.com/p", html)
    assert findings == []


# --- unit tests: facts locked in images (EXTRACT-004) ------------------

def test_alt_less_price_image_flagged():
    html = _page(f"<h1>T</h1><p>{_LOREM}</p><img src='/img/price-chart.png'><p>{_LOREM}</p>")
    findings = extract_detect.detect_facts_in_images("https://example.com/p", html)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "EXTRACT-004"
    assert findings[0].confidence == "low"


def test_decorative_alt_less_image_not_flagged():
    html = _page(f"<h1>T</h1><p>{_LOREM}</p><img src='/img/logo.png'><p>{_LOREM}</p>")
    findings = extract_detect.detect_facts_in_images("https://example.com/p", html)
    assert findings == []


def test_price_image_with_alt_text_not_flagged():
    html = _page(f"<h1>T</h1><p>{_LOREM}</p><img src='/img/price-chart.png' alt='Pricing: $10/mo, $99/yr'><p>{_LOREM}</p>")
    findings = extract_detect.detect_facts_in_images("https://example.com/p", html)
    assert findings == []


def test_nav_logo_image_does_not_cause_a_false_positive():
    # A logo image living in persistent nav chrome, outside main content.
    html = (
        "<html><body>"
        "<nav><img src='/img/price-tag-logo.png' alt=''></nav>"
        f"<main><h1>T</h1><p>{_LOREM}</p></main>"
        "</body></html>"
    )
    findings = extract_detect.detect_facts_in_images("https://example.com/p", html)
    assert findings == []


# --- Day 4 DoD, end-to-end: fixtures via run_audit.py -------------------

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


def test_schema_contradiction_fixture_is_flagged_end_to_end(tmp_path):
    server = _serve("schema-contradiction", 8127)
    try:
        report = run_audit("http://localhost:8127", tmp_path / "run")
    finally:
        server.shutdown()

    extract_findings = [f for f in report["findings"] if f["stage"] == "extract"]
    assert len(extract_findings) == 1
    assert extract_findings[0]["taxonomy_id"] == "EXTRACT-001"
    assert report["summary"]["ai_readiness"]["extract"] == "fail"


def test_clean_product_fixture_has_zero_false_positives(tmp_path):
    # The Day 4 DoD, verbatim: "contradiction detector has zero false
    # positives on controls." Matching price, complete required
    # properties, correct heading hierarchy, alt text present.
    server = _serve("schema-clean-product", 8128)
    try:
        report = run_audit("http://localhost:8128", tmp_path / "run")
    finally:
        server.shutdown()

    assert report["findings"] == []
    assert report["summary"]["ai_readiness"]["extract"] == "pass"
