"""Day 9 degradation testing: the project's build plan (Part 7) names six
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


class _WafBlockingHandler(http.server.SimpleHTTPRequestHandler):
    """Serves robots.txt and sitemap.xml normally, then 403s every actual
    page -- exactly the shape openai.com presents: a permissive
    `Allow: /` robots.txt with an edge that blocks AI crawlers anyway.
    A 403 is a *completed* HTTP transaction, so it produces a real
    FetchRecord; the point of this fixture is that downstream stages
    must not mistake a block page for content."""

    def do_GET(self):  # noqa: N802 -- http.server's own naming
        if self.path in ("/robots.txt", "/sitemap.xml"):
            body = (
                b"User-agent: *\nAllow: /\n"
                if self.path == "/robots.txt"
                else b'<?xml version="1.0" encoding="UTF-8"?>\n'
                b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                b"<url><loc>http://localhost:8133/</loc></url>"
                b"<url><loc>http://localhost:8133/a.html</loc></url>"
                b"</urlset>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # A realistic block page: substantial HTML, no analytics, no content.
        body = b"<html><head><title>Access denied</title></head><body><h1>Sorry, you have been blocked</h1></body></html>"
        self.send_response(403)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


def test_waf_blocked_site_does_not_mistake_block_pages_for_content(tmp_path):
    # Regression for a real bug found auditing openai.com: every sampled
    # URL 403'd, yet ARRIVE scanned the block pages and reported "no
    # analytics found across 15 sampled pages", and the proactive layer
    # emitted six "no page answers X-intent questions" recommendations
    # -- all derived from a corpus of zero successfully fetched pages.
    server = http.server.ThreadingHTTPServer(("localhost", 8133), _WafBlockingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        report = run_audit("http://localhost:8133", tmp_path / "run")
    finally:
        server.shutdown()

    assert report["run_manifest"]["pages_crawled"] == 0

    # REACH must still speak up -- being blocked is the finding.
    assert any(f["stage"] == "reach" for f in report["findings"]), "a fully blocked site must produce a REACH finding"

    # ...but no downstream stage may claim to have examined content.
    assert [f for f in report["findings"] if f["stage"] == "arrive"] == []
    assert report["proactive_recommendations"] == []


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


# --- a non-English corpus: report "not measured", never "measured, failed" ---


def test_non_english_site_does_not_get_audited_by_english_lexicons(tmp_path):
    # The buyer-intent query bank, the BM25 stopword list and ENGAGE-005's
    # CTA phrases are all English. Before this guard, a deliberately
    # well-built German fixture -- brand named up top on every page, JSON-LD
    # on two, prices stated in both schema and prose, three German CTAs --
    # audited as 15/18 queries unanswerable, with a CHUNK-001 finding, an
    # ENGAGE-005 finding, a false headline, and five "no page answers
    # X-intent questions" recommendations. Every one was an artifact of
    # asking English questions of a German site.
    server = _serve("non-english", 8134)
    try:
        report = run_audit("http://localhost:8134", tmp_path / "run")
    finally:
        server.shutdown()

    assert report["run_manifest"]["pages_crawled"] == 3, "the crawl itself is language-independent and must still work"

    # The probe didn't run, so the stage must not claim a verdict either way.
    assert report["summary"]["ai_readiness"]["retrieve"] == "skipped"
    assert report["answerability_matrix"] == []
    assert "english_only_lexicons_suppressed_corpus_language_de" in report["run_manifest"]["degradations"]

    # ...and none of the language-dependent findings may ship.
    taxonomy_ids = {f["taxonomy_id"] for f in report["findings"]}
    assert "CHUNK-001" not in taxonomy_ids
    assert "ENGAGE-005" not in taxonomy_ids
    assert not any("intent questions" in r["title"] for r in report["proactive_recommendations"])

    # Language-independent stages still do their job -- this is a
    # suppression of specific instruments, not of the audit.
    assert report["summary"]["ai_readiness"]["reach"] == "pass"
    assert report["summary"]["ai_readiness"]["extract"] == "pass"


# --- a named page must actually be audited ----------------------------------


def test_a_deep_url_is_pinned_into_the_sample():
    # Pointing the tool at https://example.com/index/some-article/ and
    # having it audit fifteen *other* pages of example.com -- never that
    # one -- answers a question nobody asked. Found on a real run against
    # a specific openai.com article: the report's evidence named fifteen
    # unrelated URLs and not the requested page.
    import run_audit

    requested = "https://example.com/index/some-article/"
    assert run_audit.requested_page(requested) == requested
    others = [f"https://example.com/p{i}" for i in range(50)]
    sample = sample_seed_for("example.com")
    picked = stratified_sample([requested, *others], sample, max_pages=5, pinned=requested)
    assert picked[0] == requested
    assert len(picked) == 5


def test_a_bare_domain_is_not_treated_as_a_page_request():
    import run_audit

    for site in ("https://example.com", "https://example.com/"):
        assert run_audit.requested_page(site) is None


def test_pinning_stays_deterministic_and_does_not_duplicate():
    requested = "https://example.com/a"
    urls = [requested, "https://example.com/b", "https://example.com/c"]
    seed = sample_seed_for("example.com")
    a = stratified_sample(urls, seed, max_pages=3, pinned=requested)
    b = stratified_sample(urls, seed, max_pages=3, pinned=requested)
    assert a == b
    assert a.count(requested) == 1


def test_a_fully_blocked_site_publishes_no_answerability_matrix(tmp_path):
    # The funnel table said stage 4 was `skipped` while the answerability
    # summary directly underneath it reported "18 unretrievable (of 18
    # simulated buyer-intent queries)" -- a verdict on content nothing had
    # fetched. BM25 over an empty index returns nothing for every query,
    # and the classifier faithfully recorded that as a measured result.
    server = http.server.ThreadingHTTPServer(("localhost", 8133), _WafBlockingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        report = run_audit("http://localhost:8133", tmp_path / "run")
    finally:
        server.shutdown()

    assert report["run_manifest"]["pages_crawled"] == 0
    assert report["answerability_matrix"] == []
    assert report["summary"]["answerability"] == {
        "answerable": 0, "partial": 0, "ungrounded": 0, "unretrievable": 0
    }
    assert report["summary"]["ai_readiness"]["retrieve"] == "skipped"


# --- stratified sampling: the pages a buyer asks about ----------------------


def _stratified(urls, max_pages=6, **kw):
    return stratified_sample(urls, sample_seed_for("example.com"), max_pages=max_pages, **kw)


def test_the_homepage_is_always_sampled():
    # Entity detection reads the homepage to decide what the brand is
    # called, and all 18 buyer-intent queries are built from that name. A
    # live ghost.org audit drew 25 theme and integration pages with no
    # homepage among them, so the detector fell back to a /resources/ page
    # title and named the brand "Ghost Resources" -- every query then asked
    # about a company that does not exist.
    urls = [f"https://example.com/themes/t{i}" for i in range(200)] + ["https://example.com/"]
    assert "https://example.com/" in _stratified(urls)


def test_high_value_page_classes_get_a_guaranteed_slot():
    # Same run recommended publishing a pricing page to a brand whose
    # /pricing/ page was in the sitemap the whole time, merely unsampled.
    urls = [f"https://example.com/themes/t{i}" for i in range(200)] + [
        "https://example.com/",
        "https://example.com/pricing/",
        "https://example.com/contact/",
        "https://example.com/about/",
    ]
    picked = _stratified(urls, max_pages=6)
    for expected in ("/pricing/", "/contact/", "/about/"):
        assert any(expected in u for u in picked), f"{expected} should have a guaranteed slot, got {picked}"


def test_stratification_respects_max_pages_and_never_duplicates():
    urls = ["https://example.com/", "https://example.com/pricing/", "https://example.com/about/"] + [
        f"https://example.com/p{i}" for i in range(50)
    ]
    picked = _stratified(urls, max_pages=3)
    assert len(picked) == 3
    assert len(set(picked)) == 3


def test_a_pinned_url_still_outranks_the_homepage():
    pinned = "https://example.com/index/some-article/"
    picked = _stratified([pinned, "https://example.com/", "https://example.com/pricing/"], pinned=pinned)
    assert picked[0] == pinned
    assert "https://example.com/" in picked  # ...and the homepage is still there


def test_stratified_sampling_is_deterministic():
    urls = ["https://example.com/", "https://example.com/pricing/"] + [
        f"https://example.com/p{i}" for i in range(80)
    ]
    assert _stratified(urls, max_pages=10) == _stratified(urls, max_pages=10)


def test_a_site_with_no_classifiable_pages_still_fills_the_sample():
    urls = [f"https://example.com/x/{i}" for i in range(100)]
    assert len(_stratified(urls, max_pages=10)) == 10
