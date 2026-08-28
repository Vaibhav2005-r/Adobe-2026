"""Stage (4) RETRIEVE: unit tests for entity detection, query expansion,
and classification, plus the Day 5 DoD as an executable end-to-end
test -- "given a fixture site, produces a reproducible answerability
matrix. Two runs, byte-identical output."
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import retrieve_detect as rd
from brand_audit.chunk import Chunk

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "ai-visibility-orchestrator" / "scripts" / "run_audit.py"


def _chunk(text: str, *, heading: str | None = None, url: str = "https://example.com/", idx: int = 0) -> Chunk:
    return Chunk(text=text, url=url, chunk_index=idx, token_count=len(text.split()), section_heading=heading, char_offset=0)


# --- entity detection ---------------------------------------------------

def test_entity_from_json_ld_organization():
    html = '<html><head><script type="application/ld+json">{"@type":"Organization","name":"Acme Corp"}</script></head><body></body></html>'
    entity = rd.detect_entity({"https://example.com/": html}, "https://example.com/")
    assert entity.name == "Acme Corp"
    assert entity.source == "json-ld"


def test_entity_category_from_product_type():
    html = '<html><head><script type="application/ld+json">[{"@type":"Organization","name":"Acme Corp"},{"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"10"}}]</script></head><body></body></html>'
    entity = rd.detect_entity({"https://example.com/": html}, "https://example.com/")
    assert entity.category == "product"


def test_entity_falls_back_to_title_when_no_json_ld():
    html = "<html><head><title>Acme Corp -- Widgets and More</title></head><body></body></html>"
    entity = rd.detect_entity({"https://example.com/": html}, "https://example.com/")
    assert entity.name == "Acme Corp"
    assert entity.source == "title"


def test_entity_falls_back_to_h1_when_no_title_or_json_ld():
    html = "<html><body><h1>Acme Corp</h1></body></html>"
    entity = rd.detect_entity({"https://example.com/": html}, "https://example.com/")
    assert entity.name == "Acme Corp"
    assert entity.source == "h1"


def test_entity_detection_is_deterministic_regardless_of_dict_order():
    pages_a = {"https://example.com/b": "<html><body></body></html>", "https://example.com/a": '<html><head><script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script></head><body></body></html>'}
    pages_b = dict(reversed(list(pages_a.items())))
    assert rd.detect_entity(pages_a) == rd.detect_entity(pages_b)


# --- query expansion ------------------------------------------------------

def test_expand_queries_produces_18_queries():
    entity = rd.Entity(name="Acme", category="product", source="json-ld")
    queries = rd.expand_queries(entity)
    assert len(queries) == 18
    assert len({intent for _, intent in queries}) == 6


def test_expand_queries_substitutes_brand_and_category():
    entity = rd.Entity(name="Acme Corp", category="software", source="json-ld")
    queries = rd.expand_queries(entity)
    assert any("Acme Corp" in q for q, _ in queries)
    assert any("software" in q for q, _ in queries)


# --- orphan-fact detection (CHUNK-002) -------------------------------------

def test_orphan_fact_flagged_when_no_heading_or_proper_noun():
    orphan = _chunk("the price is $499 per unit and it ships fast")
    findings = [orphan]
    assert rd.find_orphan_fact_chunks(findings) == [orphan]


def test_price_with_heading_is_not_orphaned():
    identified = _chunk("The price is $89.", heading="Trailhead Skillet")
    assert rd.find_orphan_fact_chunks([identified]) == []


def test_price_with_proper_noun_phrase_is_not_orphaned():
    identified = _chunk("The Trailhead Skillet costs $89 and ships fast.")
    assert rd.find_orphan_fact_chunks([identified]) == []


def test_no_price_at_all_is_not_orphaned():
    no_price = _chunk("this chunk has no currency fact in it at all")
    assert rd.find_orphan_fact_chunks([no_price]) == []


def test_detect_orphan_facts_returns_none_when_nothing_orphaned():
    identified = _chunk("The price is $89.", heading="Trailhead Skillet")
    assert rd.detect_orphan_facts([identified]) is None


def test_detect_orphan_facts_returns_finding_with_correct_taxonomy_id():
    orphan = _chunk("the price is $499 per unit")
    finding = rd.detect_orphan_facts([orphan])
    assert finding is not None
    assert finding.taxonomy_id == "CHUNK-002"
    assert finding.stage == "retrieve"


# --- boilerplate-ratio scoring (CHUNK-004) ----------------------------------

def test_boilerplate_heavy_chunk_flagged():
    diluted = _chunk(
        "All rights reserved. Privacy Policy. Terms of Service. Cookie Policy. "
        "Follow us on social media. We use cookies to improve your experience."
    )
    assert rd.boilerplate_ratio(diluted) >= rd._BOILERPLATE_RATIO_THRESHOLD
    finding = rd.detect_boilerplate_dilution([diluted])
    assert finding is not None
    assert finding.taxonomy_id == "CHUNK-004"


def test_real_content_chunk_not_flagged_as_boilerplate():
    real = _chunk("The Trailhead Skillet is hand-cast in Bozeman, Montana and costs $89.")
    assert rd.boilerplate_ratio(real) < rd._BOILERPLATE_RATIO_THRESHOLD
    assert rd.detect_boilerplate_dilution([real]) is None


# --- cross-page-join reliance (CHUNK-003) -----------------------------------

def test_cross_page_join_flagged_when_partial_answer_spans_two_urls():
    from brand_audit.models import AnswerabilityMatrixEntry, AnswerabilityOutcome

    entry = AnswerabilityMatrixEntry(
        query="what is the spec and price", intent="capability", outcome=AnswerabilityOutcome.PARTIAL,
        top_chunk_url="https://example.com/a", citable=True,
    )
    pages = {"https://example.com/a": "<html></html>", "https://example.com/b": "<html></html>"}
    finding = rd.detect_cross_page_join_reliance([(entry, True)], pages)
    assert finding is not None
    assert finding.taxonomy_id == "CHUNK-003"


def test_cross_page_join_not_flagged_when_no_cross_page_partials():
    from brand_audit.models import AnswerabilityMatrixEntry, AnswerabilityOutcome

    entry = AnswerabilityMatrixEntry(
        query="what is the spec and price", intent="capability", outcome=AnswerabilityOutcome.PARTIAL,
        top_chunk_url="https://example.com/a", citable=True,
    )
    pages = {"https://example.com/a": "<html></html>"}
    assert rd.detect_cross_page_join_reliance([(entry, False)], pages) is None


# --- end-to-end: the Day 5 DoD ---------------------------------------------

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


def test_answerability_matrix_reflects_real_content_not_generic_noise(tmp_path):
    server = _serve("retrieval-answerable", 8129)
    try:
        report = run_audit("http://localhost:8129", tmp_path / "run")
    finally:
        server.shutdown()

    matrix = {(e["intent"], e["query"]): e["outcome"] for e in report["answerability_matrix"]}
    assert len(matrix) == 18

    # Identity and contact are directly, explicitly stated in the
    # fixture -- must be answerable, not just "retrieved something".
    assert any(
        outcome == "answerable" for (intent, _), outcome in matrix.items() if intent == "identity"
    )
    assert any(
        outcome == "answerable" for (intent, _), outcome in matrix.items() if intent == "contact"
    )
    # The fixture never discusses competitors or customer reviews at
    # all -- comparison/trust queries must NOT be answerable; a
    # classifier that says otherwise is hallucinating an answer that
    # doesn't exist in the corpus.
    assert all(
        outcome != "answerable" for (intent, _), outcome in matrix.items() if intent == "comparison"
    )
    assert all(
        outcome != "answerable" for (intent, _), outcome in matrix.items() if intent == "trust"
    )


def test_answerability_matrix_is_byte_identical_across_two_runs(tmp_path):
    # The Day 5 DoD, verbatim: "given a fixture site, produces a
    # reproducible answerability matrix. Two runs, byte-identical
    # output."
    server = _serve("retrieval-answerable", 8129)
    try:
        report_a = run_audit("http://localhost:8129", tmp_path / "run_a")
        report_b = run_audit("http://localhost:8129", tmp_path / "run_b")
    finally:
        server.shutdown()

    for r in (report_a, report_b):
        r["audited_at"] = None
        r["run_manifest"]["duration_s"] = None

    assert report_a == report_b
    assert len(report_a["answerability_matrix"]) == 18
