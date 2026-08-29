"""Stage (6) ARRIVE: unit tests for arrival-engagement-audit's seven
detectors (answer proximity, orientation, context reset, entry
interference, next-step, AI-referral instrumentation, scoped latency),
each with both a defect case and a clean-control case, plus the Day 7
DoD as an executable end-to-end test against a dedicated clean fixture.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import arrive_detect as ad
from brand_audit.artifact_store import FetchRecord
from brand_audit.models import AnswerabilityMatrixEntry, AnswerabilityOutcome

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"


def _record(url: str, *, final_url: str | None = None, elapsed_s: float | None = None, status: int = 200) -> FetchRecord:
    return FetchRecord(url=url, http_status=status, body=b"", fetched_with_ua="test", final_url=final_url, elapsed_s=elapsed_s)


def _matrix_entry(*, citable: bool, position_ratio: float | None, url: str = "https://example.com/pricing") -> AnswerabilityMatrixEntry:
    return AnswerabilityMatrixEntry(
        query="what does it cost", intent="pricing", outcome=AnswerabilityOutcome.ANSWERABLE if citable else AnswerabilityOutcome.UNGROUNDED,
        top_chunk_url=url if citable else None, citable=citable, top_chunk_position_ratio=position_ratio,
    )


# --- ENGAGE-001: answer proximity -------------------------------------------


def test_buried_citable_answer_flagged():
    matrix = [_matrix_entry(citable=True, position_ratio=0.85)]
    finding = ad.detect_buried_answers(matrix)
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-001"


def test_answer_near_top_not_flagged():
    matrix = [_matrix_entry(citable=True, position_ratio=0.05)]
    assert ad.detect_buried_answers(matrix) is None


def test_non_citable_entries_ignored():
    matrix = [_matrix_entry(citable=False, position_ratio=0.9)]
    assert ad.detect_buried_answers(matrix) is None


def test_missing_position_ratio_not_flagged():
    # citable=True but no position data (e.g. page_content_length was 0)
    # -- nothing to judge, not a defect either way.
    matrix = [_matrix_entry(citable=True, position_ratio=None)]
    assert ad.detect_buried_answers(matrix) is None


# --- ENGAGE-002: orientation gap --------------------------------------------


def test_entity_never_mentioned_flagged():
    html = "<html><body><h1>Welcome</h1><p>We sell things. Great things, for everyone, always.</p></body></html>"
    finding = ad.detect_orientation_gap("https://example.com/x", html, "Acme Corp")
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-002"


def test_entity_named_near_top_not_flagged():
    html = "<html><body><h1>Acme Corp</h1><p>Acme Corp sells industrial widgets to manufacturers nationwide, with same-day shipping on most orders.</p></body></html>"
    assert ad.detect_orientation_gap("https://example.com/x", html, "Acme Corp") is None


def test_entity_named_only_far_below_the_fold_flagged():
    filler = " ".join(f"word{i}" for i in range(150))  # >500 chars of filler before the brand is ever named
    html = f"<html><body><h1>Products</h1><p>{filler} Acme Corp made this.</p></body></html>"
    finding = ad.detect_orientation_gap("https://example.com/x", html, "Acme Corp")
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-002"


def test_no_main_content_not_flagged():
    assert ad.detect_orientation_gap("https://example.com/x", "<html><body></body></html>", "Acme Corp") is None


# --- ENGAGE-003: context reset -----------------------------------------------


def test_deep_link_redirect_to_homepage_flagged():
    record = _record("https://example.com/products/atlas", final_url="https://example.com/")
    finding = ad.detect_context_reset("https://example.com/products/atlas", record, {})
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-003"


def test_deep_link_redirect_to_locale_gate_flagged():
    gate_html = "<html><body><h1>Choose your region</h1><p>Please select your country to continue.</p></body></html>"
    record = _record("https://example.com/products/atlas", final_url="https://example.com/region-select")
    pages = {"https://example.com/region-select": gate_html}
    finding = ad.detect_context_reset("https://example.com/products/atlas", record, pages)
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-003"


def test_no_redirect_not_flagged():
    record = _record("https://example.com/products/atlas", final_url=None)
    assert ad.detect_context_reset("https://example.com/products/atlas", record, {}) is None


def test_cosmetic_trailing_slash_redirect_not_flagged():
    record = _record("https://example.com/products/atlas", final_url="https://example.com/products/atlas/")
    assert ad.detect_context_reset("https://example.com/products/atlas", record, {}) is None


def test_homepage_itself_not_flagged():
    record = _record("https://example.com/", final_url="https://example.com/home")
    assert ad.detect_context_reset("https://example.com/", record, {}) is None


def test_redirect_to_another_specific_page_not_flagged():
    # Landed somewhere else concrete (not root, not a locale gate) --
    # not the context-reset pattern this detector targets.
    other_html = "<html><body><h1>New Product Page</h1><p>Details about the new page.</p></body></html>"
    record = _record("https://example.com/products/atlas", final_url="https://example.com/products/atlas-v2")
    pages = {"https://example.com/products/atlas-v2": other_html}
    assert ad.detect_context_reset("https://example.com/products/atlas", record, pages) is None


# --- ENGAGE-004: entry interference ------------------------------------------


def test_known_consent_library_signature_flagged():
    html = '<html><head><script src="https://consent.cookiebot.com/uc.js"></script></head><body></body></html>'
    finding = ad.detect_entry_interference({"https://example.com/": html})
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-004"


def test_no_consent_signature_not_flagged():
    html = "<html><body><p>Ordinary page content with no overlay of any kind.</p></body></html>"
    assert ad.detect_entry_interference({"https://example.com/": html}) is None


# --- ENGAGE-005: missing next-step / CTA -------------------------------------


def test_majority_missing_cta_flagged():
    no_cta = "<html><body><p>Just some descriptive text about the product with no call to action anywhere.</p></body></html>"
    pages = {f"https://example.com/{i}": no_cta for i in range(3)}
    finding = ad.detect_missing_next_step(pages)
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-005"


def test_majority_with_cta_not_flagged():
    with_cta = "<html><body><p>Ready to start? Contact us today to get started with your order.</p></body></html>"
    pages = {f"https://example.com/{i}": with_cta for i in range(3)}
    assert ad.detect_missing_next_step(pages) is None


def test_single_page_missing_cta_out_of_many_not_flagged():
    with_cta = "<html><body><p>Contact us today to get started.</p></body></html>"
    no_cta = "<html><body><p>Just descriptive text, nothing actionable here.</p></body></html>"
    pages = {f"https://example.com/{i}": with_cta for i in range(5)}
    pages["https://example.com/one-off"] = no_cta
    assert ad.detect_missing_next_step(pages) is None


# --- ENGAGE-006: no AI-referral instrumentation ------------------------------


def test_no_analytics_anywhere_flagged():
    html = "<html><head></head><body><p>No tracking here.</p></body></html>"
    finding = ad.detect_no_ai_referral_instrumentation({"https://example.com/a": html, "https://example.com/b": html})
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-006"


def test_analytics_snippet_present_not_flagged():
    with_ga = '<html><head><script src="https://www.googletagmanager.com/gtag/js?id=G-X"></script></head><body></body></html>'
    plain = "<html><body></body></html>"
    assert ad.detect_no_ai_referral_instrumentation({"https://example.com/a": with_ga, "https://example.com/b": plain}) is None


def test_no_pages_at_all_does_not_crash():
    # Real Day 9 crash: zalando.de returned zero successful REACH-stage
    # fetches, so ARRIVE's all_pages was {} -- this detector had no
    # guard for that (unlike every other ARRIVE detector) and
    # unconditionally built a Finding with artifacts=[], which fails
    # Finding's own min_length=1 constraint. There's no page left to
    # cite as evidence, so the honest answer is "nothing to report,"
    # not a fabricated artifact.
    assert ad.detect_no_ai_referral_instrumentation({}) is None


# --- ENGAGE-007: scoped response latency -------------------------------------


def test_slow_citable_page_flagged():
    records = {"https://example.com/pricing": _record("https://example.com/pricing", elapsed_s=4.2)}
    finding = ad.detect_slow_citable_pages(records)
    assert finding is not None
    assert finding.taxonomy_id == "ENGAGE-007"


def test_fast_citable_pages_not_flagged():
    records = {"https://example.com/pricing": _record("https://example.com/pricing", elapsed_s=0.3)}
    assert ad.detect_slow_citable_pages(records) is None


def test_unmeasured_latency_not_flagged():
    records = {"https://example.com/pricing": _record("https://example.com/pricing", elapsed_s=None)}
    assert ad.detect_slow_citable_pages(records) is None


# --- end-to-end: ARRIVE stage clean control ----------------------------------


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


def test_arrival_clean_fixture_has_zero_arrive_findings(tmp_path):
    # Entity named at the top of every page, a CTA on every page, an
    # analytics snippet, no redirects, no consent overlay -- every
    # ARRIVE-stage detector should stay silent.
    server = _serve("arrival-clean", 8131)
    try:
        report = run_audit("http://localhost:8131", tmp_path / "run")
    finally:
        server.shutdown()

    arrive_findings = [f for f in report["findings"] if f["stage"] == "arrive"]
    assert arrive_findings == []
    assert report["summary"]["ai_readiness"]["arrive"] == "pass"
    assert "arrive" in report["run_manifest"]["stages_completed"]


def test_arrive_stage_is_byte_identical_across_three_runs(tmp_path):
    # Three runs, matching the Day 9 DoD's own literal wording -- this
    # is the suite's most comprehensive determinism check (ARRIVE runs
    # last, after every other stage plus finding-verification's own
    # re-fetch), so it's the one upgraded from two to three rather than
    # every determinism test in the suite.
    server = _serve("arrival-clean", 8131)
    try:
        report_a = run_audit("http://localhost:8131", tmp_path / "run_a")
        report_b = run_audit("http://localhost:8131", tmp_path / "run_b")
        report_c = run_audit("http://localhost:8131", tmp_path / "run_c")
    finally:
        server.shutdown()

    for r in (report_a, report_b, report_c):
        r["audited_at"] = None
        r["run_manifest"]["duration_s"] = None
        # elapsed_s isn't part of the report itself (only feeds ENGAGE-007's
        # internal decision), so no further scrubbing needed for determinism.

    assert report_a == report_b == report_c
