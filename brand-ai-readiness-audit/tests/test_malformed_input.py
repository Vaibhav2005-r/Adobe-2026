"""Real sites serve broken things. Every case here was verified to
crash, silently discard data, or mis-measure against the code as it
stood -- none is hypothetical.

Grouped by the primitive that failed rather than by the stage that
consumed it, because each of these is one shared function that several
stages call: `extract_json_ld` is used by EXTRACT, RETRIEVE and CITE;
`fetch_many` by REACH and RENDER; `discover_sitemap_urls` gates the
whole crawl.
"""

from __future__ import annotations

import asyncio
import gzip
import http.server
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brand_audit.crawl import RobotsPolicy, _maybe_gunzip, discover_sitemap_urls  # noqa: E402
from brand_audit.fetch import fetch_many  # noqa: E402
from brand_audit.jsonld import extract_json_ld  # noqa: E402
from brand_audit.language import (  # noqa: E402
    detect_corpus_language,
    lexicons_cover,
    page_language,
)


# --- malformed JSON-LD must not end the audit --------------------------------


def _ld(payload: str) -> str:
    return f'<html><head><script type="application/ld+json">{payload}</script></head><body><p>x</p></body></html>'


@pytest.mark.parametrize(
    "payload",
    [
        "",  # an empty tag -- ships in a lot of CMS themes, and raised on its own
        "{a:1}",  # unquoted key
        '{"a": "b',  # truncated template
        '{"a": "he said "hi""}',  # unescaped quote inside a description
        "{",
        "not json at all",
    ],
    ids=["empty", "unquoted-key", "truncated", "unescaped-quote", "brace", "prose"],
)
def test_malformed_json_ld_returns_empty_instead_of_raising(payload):
    # `extruct.extract` lets json's own JSONDecodeError propagate, and
    # nothing in EXTRACT/RETRIEVE/CITE caught it: one bad block on one
    # sampled page ended the whole run.
    assert extract_json_ld(_ld(payload)) == []


def test_one_malformed_block_does_not_discard_the_valid_ones():
    # The salvage path is per-block, so a page with three good blocks and
    # one broken one still contributes three -- returning [] for the whole
    # page would turn a real defect into "this page has no structured data".
    html = _ld("{oops") + _ld('{"@type": "Organization", "name": "Rowan"}')
    assert extract_json_ld(html) == [{"@type": "Organization", "name": "Rowan"}]


@pytest.mark.parametrize(
    "payload",
    ['// <![CDATA[\n{"a": 1}\n// ]]>', '<!--{"a": 1}-->'],
    ids=["cdata", "html-comment"],
)
def test_legacy_wrapped_json_ld_is_recovered(payload):
    # Not valid JSON, but browsers and Google's parser both accept it and
    # CMS templates still emit it -- the facts are really there.
    assert extract_json_ld(_ld(payload)) == [{"a": 1}]


def test_well_formed_json_ld_is_unaffected():
    assert extract_json_ld(_ld('{"@type": "Product", "price": "149.00"}')) == [
        {"@type": "Product", "price": "149.00"}
    ]


# --- malformed URLs must not end the crawl -----------------------------------


def test_fetch_many_survives_urls_that_break_url_parsing():
    # `httpx.URL()` raises `httpx.InvalidURL` (not an `HTTPError`) on a
    # bad host or port, and `idna.IDNAError` (a `ValueError`, from
    # neither library's hierarchy) on a hostname it can't encode. Both
    # escaped `except httpx.HTTPError`, and the per-host lock lookup that
    # triggered them sat outside the try block entirely. Sitemap <loc>
    # entries are just CMS-authored text, so this is ordinary input.
    urls = [
        "http://\udcff.com/",  # unencodable IDNA hostname
        "http://[::1",  # unparseable port
        "mailto:hello@example.com",  # non-HTTP scheme
        "javascript:void(0)",
        "not a url at all",
    ]
    outcomes = asyncio.run(fetch_many(urls, timeout_s=2.0))
    assert len(outcomes) == len(urls)
    assert all(o.record is None and o.error for o in outcomes), "each bad URL should degrade to an error, not a crash"


def test_httpx_still_refuses_these_urls():
    # Guards the premise of the test above: if httpx ever starts accepting
    # these, the regression test stops testing anything.
    with pytest.raises(Exception):
        httpx.URL("http://\udcff.com/").host


# --- sitemaps that don't match the textbook ----------------------------------


_SITEMAP_BODIES = {
    "/ns.xml": b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<url><loc>http://example.com/a</loc></url></urlset>",
    "/no-ns.xml": b"<urlset><url><loc>http://example.com/b</loc></url></urlset>",
    "/legacy-ns.xml": b'<urlset xmlns="http://www.google.com/schemas/sitemap/0.84">'
    b"<url><loc>http://example.com/c</loc></url></urlset>",
    "/compressed.xml.gz": gzip.compress(
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>http://example.com/d</loc></url></urlset>"
    ),
    "/junk.xml": b"this is not xml",
}


class _SitemapHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- http.server's own naming
        body = _SITEMAP_BODIES.get(self.path, b"")
        self.send_response(200 if body else 404)
        # Deliberately NOT `Content-Encoding: gzip` -- a .gz sitemap
        # served as a gzip *file* (the correct labelling, and what most
        # servers do) never gets transparently decompressed by httpx.
        self.send_header("Content-Type", "application/gzip" if self.path.endswith(".gz") else "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def sitemap_server():
    server = http.server.ThreadingHTTPServer(("localhost", 8135), _SitemapHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://localhost:8135"
    server.shutdown()


def _discover(base: str, path: str):
    async def run():
        async with httpx.AsyncClient() as client:
            policy = RobotsPolicy(
                fetched=True, status=200, raw_text="", parser=None, sitemap_urls=[f"{base}{path}"]
            )
            return await discover_sitemap_urls(client, base, policy)

    return asyncio.run(run())


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/ns.xml", "http://example.com/a"),
        ("/no-ns.xml", "http://example.com/b"),
        ("/legacy-ns.xml", "http://example.com/c"),
        ("/compressed.xml.gz", "http://example.com/d"),
    ],
    ids=["sitemaps-org-ns", "no-namespace", "legacy-0.84-ns", "gzipped"],
)
def test_sitemap_shapes_all_yield_their_urls(sitemap_server, path, expected):
    # Binding the literal sitemaps.org 0.9 namespace made the last three
    # of these return zero URLs, which fell through to the documented
    # `[base_url]` fallback -- so a 50,000-URL site was audited as one
    # page, with nothing anywhere reporting that discovery had failed.
    urls, fetch_ok = _discover(sitemap_server, path)
    assert fetch_ok is True
    # Membership, not equality: the origin is also always a candidate (see
    # test_the_homepage_is_always_a_candidate below), and these fixture
    # sitemaps deliberately point at a different host, so the homepage is
    # never among the URLs the sitemap itself declares. What this test is
    # about is whether the sitemap's own <loc> survived parsing.
    assert expected in urls


def test_the_homepage_is_always_a_candidate_even_when_the_sitemap_omits_it(sitemap_server):
    # ghost.org's sitemap index yields 500 theme and integration URLs
    # before it ever reaches `/`, so the homepage was not merely
    # unsampled -- it was never in the pool the sampler chose from. Entity
    # detection reads the homepage to decide what the brand is called, and
    # every generated buyer-intent query is built from that name.
    urls, _ = _discover(sitemap_server, "/ns.xml")
    assert any(urlparse(u).path in ("", "/") for u in urls)


def test_genuinely_unparseable_sitemap_still_falls_back_honestly(sitemap_server):
    urls, fetch_ok = _discover(sitemap_server, "/junk.xml")
    assert urls == [sitemap_server]
    assert fetch_ok is False, "the fallback must stay distinguishable from a working sitemap"


def test_maybe_gunzip_passes_through_plain_bytes_and_refuses_to_mangle_bad_gzip():
    assert _maybe_gunzip(b"<urlset/>") == b"<urlset/>"
    truncated = gzip.compress(b"<urlset/>")[:5]
    assert _maybe_gunzip(truncated) == truncated  # left for the XML parser to reject, not raised on
    with pytest.raises(ElementTree.ParseError):
        ElementTree.fromstring(_maybe_gunzip(truncated))


# --- corpus language ---------------------------------------------------------


@pytest.mark.parametrize(
    "html,expected",
    [
        ('<html lang="de">', "de"),
        ("<html lang='de-AT'>", "de"),
        ('<html lang="en-US" dir="ltr">', "en"),
        ('<html class="x" lang=ja>', "ja"),
        ("<html>", None),
        ('<html data-lang="fr">', None),  # an i18n-framework attribute, not the document language
        ('<html data-lang="fr" lang="en">', "en"),  # both present -- the real one wins
        ('<html xml:lang="ja">', "ja"),  # the XHTML equivalent
    ],
    ids=["plain", "region", "quoted-region", "unquoted", "absent", "lookalike-attr", "both", "xml-lang"],
)
def test_page_language_reads_the_html_lang_attribute(html, expected):
    assert page_language(html + "<body>x</body></html>") == expected


def test_corpus_language_is_a_majority_vote():
    pages = {"/a": '<html lang="de">', "/b": '<html lang="de">', "/c": '<html lang="en">'}
    assert detect_corpus_language(pages) == "de"


def test_corpus_language_ties_break_deterministically():
    pages = {"/a": '<html lang="fr">', "/b": '<html lang="de">'}
    assert detect_corpus_language(pages) == detect_corpus_language(dict(reversed(list(pages.items())))) == "de"


def test_undeclared_language_keeps_the_english_lexicons_enabled():
    # Asymmetric on purpose: act on an explicit declaration, never on an
    # absence. Treating "no lang attribute" as unsupported would skip the
    # crown-jewel stage on the many ordinary English sites that never set
    # it -- trading one false-positive class for a bigger false-negative one.
    assert detect_corpus_language({"/a": "<html><body>x</body></html>"}) is None
    assert lexicons_cover(None) is True


def test_declared_non_english_disables_the_english_lexicons():
    assert lexicons_cover("de") is False
    assert lexicons_cover("en") is True


# --- no sitemap: seed the sampler from the homepage, not one page -----------


class _NoSitemapHandler(http.server.BaseHTTPRequestHandler):
    """robots.txt with no `Sitemap:` line, and /sitemap.xml 404s -- exactly
    the shape python.org, react.dev, apache.org and mit.edu present."""

    PAGES = {"/", "/about.html", "/docs.html", "/contact.html"}

    def do_GET(self):  # noqa: N802 -- http.server's own naming
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /private/\n"
        elif self.path in self.PAGES:
            body = (
                b'<html lang="en"><body><nav>'
                b'<a href="/about.html">About</a><a href="/docs.html">Docs</a>'
                b'<a href="/contact.html">Contact</a><a href="/private/secret.html">Private</a>'
                b'<a href="https://elsewhere.example.com/x">Offsite</a>'
                b'<a href="/about.html#team">Anchor dupe</a><a href="/about.html?utm=1">Query dupe</a>'
                b"</nav><main><p>content</p></main></body></html>"
            )
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def no_sitemap_server():
    server = http.server.ThreadingHTTPServer(("localhost", 8136), _NoSitemapHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://localhost:8136"
    server.shutdown()


def _discover_all(base: str):
    async def run():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            from brand_audit.crawl import fetch_robots

            robots = await fetch_robots(client, base)
            return await discover_sitemap_urls(client, base, robots)

    return asyncio.run(run())


def test_a_site_with_no_sitemap_is_seeded_from_its_homepage_links(no_sitemap_server):
    # Without this fallback the whole audit ran against one page: every
    # downstream stage reported on a single document. Measured on a
    # 196-site sweep, 39 of 131 completed audits (30%) crawled exactly one
    # page -- wikipedia.org, python.org, react.dev, rust-lang.org, mit.edu.
    # None of them publish a sitemap; all 404 on /sitemap.xml.
    urls, fetch_ok = _discover_all(no_sitemap_server)
    assert fetch_ok is False, "there genuinely is no sitemap -- REACH-006 must still be able to say so"
    assert len(urls) > 1, "a sitemap-less site must not collapse to a single-page audit"
    assert f"{no_sitemap_server}/about.html" in urls
    assert f"{no_sitemap_server}/docs.html" in urls


def test_homepage_link_discovery_respects_robots_and_stays_on_host(no_sitemap_server):
    urls, _ = _discover_all(no_sitemap_server)
    assert not any("/private/" in u for u in urls), "robots.txt Disallow must be honoured"
    assert not any("elsewhere.example.com" in u for u in urls), "off-host links must not be crawled"


def test_homepage_link_discovery_collapses_fragment_and_query_duplicates(no_sitemap_server):
    urls, _ = _discover_all(no_sitemap_server)
    about = [u for u in urls if u.rstrip("/").endswith("about.html")]
    assert len(about) == 1, f"the same page reached three ways must occupy one slot, got {about}"


def test_homepage_link_discovery_is_deterministic(no_sitemap_server):
    assert _discover_all(no_sitemap_server)[0] == _discover_all(no_sitemap_server)[0]
