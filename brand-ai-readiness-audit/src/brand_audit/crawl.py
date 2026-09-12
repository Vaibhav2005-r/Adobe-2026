"""Crawl core: robots/AI-UA checks, sitemap discovery, deterministic
sampling, and the time-budget watchdog.

Everything here is stdlib + httpx + protego -- no optional dependency.
Stage detectors (crawl-reach-audit, etc.) build on top of this; it does
not itself emit findings.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from protego import Protego
from selectolax.parser import HTMLParser

# Documented AI-crawler UAs, per the project's build plan, Part 4. Kept as a flat
# list (not per-vendor) because REACH-001-style detection needs the exact
# name a robots.txt author would have written.
AI_USER_AGENTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Google-Extended",
    "CCBot",
    "Bytespider",
    "Applebot",
    "anthropic-ai",
]

# Of the UAs above, the documented exceptions to "AI crawlers don't execute
# JavaScript" -- kept explicit so RENDER-001's impact_mechanism can be
# precise rather than sweeping (added Day 10 after checking the evidence:
# an earlier version implied all 12 were JS-blind, which overclaims).
#
#   Applebot        -- Apple documents a browser-based crawler that renders.
#   Google-Extended -- not a fetching crawler at all: it is a training-usage
#                      control token. Gemini itself rides Googlebot's
#                      rendering infrastructure.
#
# Everything else in AI_USER_AGENTS (GPTBot, ClaudeBot, PerplexityBot,
# CCBot, Bytespider, the OpenAI/Anthropic search+user agents) is
# measured as fetch-only. See Vercel's crawler study, cited in
# render_detect.detect_empty_shell_pages.
JS_RENDERING_OR_NON_FETCHING_UAS = frozenset({"Applebot", "Google-Extended"})

# Everything a single URL can plausibly fail with, so one bad URL degrades
# to a recorded failure instead of ending the crawl.
#
# `httpx.HTTPError` alone is not enough: `httpx.InvalidURL` does not
# subclass it (it is a bare Exception), and a hostname `idna` refuses to
# encode raises `idna.IDNAError`, which comes from neither package's
# hierarchy -- it is a `ValueError`. Both escape a bare
# `except httpx.HTTPError` and both are reachable from a sitemap `<loc>`
# or an `<a href>`, which are just CMS-authored text. Kept as an explicit
# tuple rather than `except Exception` so a genuine bug still surfaces as
# a crash instead of being silently recorded as a fetch failure.
#
# Defined here rather than in fetch.py because fetch.py imports from this
# module, so the dependency only runs one way.
FETCH_ERRORS = (httpx.HTTPError, httpx.InvalidURL, ValueError)

DEFAULT_FETCH_UA = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +https://www.anthropic.com/claude-bot)"

# A second, distinct AI-crawler UA -- used only by finding-verification's
# re-fetch check ("re-fetch and re-test with a different UA... does it
# reproduce?", per the project's build plan, Part 2 (4)). Deliberately a
# *different* named bot from DEFAULT_FETCH_UA, not a generic browser
# string: the point is to catch a UA-conditional response (a WAF or
# origin server treating one AI crawler differently from another), which
# a browser-UA re-fetch wouldn't exercise at all.
VERIFICATION_UA = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot"

# A real, well-known non-AI crawler UA -- used only by REACH-001 to test
# whether a robots.txt exclusion is actually AI-*specific*, or just a
# generic `User-agent: *` rule that would exclude any crawler equally
# (a staff directory or admin panel blocked from everyone, AI bots
# included only incidentally, isn't the "brand deliberately blocks AI
# bots" mechanism this taxonomy entry is about). Googlebot specifically
# because it's the crawler robots.txt authors are most likely to have
# tested against, making it a realistic proxy for "a generic, non-AI
# crawler."
GENERIC_CRAWLER_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


@dataclass
class RobotsPolicy:
    """Parsed robots.txt, keyed by the UAs we care about."""

    fetched: bool
    status: int | None
    raw_text: str
    parser: Protego | None
    sitemap_urls: list[str] = field(default_factory=list)

    def allowed(self, url: str, user_agent: str = DEFAULT_FETCH_UA) -> bool:
        if not self.fetched or self.parser is None:
            # No robots.txt (or unreadable) -> open by default, per REP.
            return True
        return self.parser.can_fetch(url, user_agent)

    def disallowed_ai_uas(self, url: str) -> list[str]:
        """Which named AI UAs are blocked from `url` -- feeds REACH-001."""
        if not self.fetched or self.parser is None:
            return []
        return [ua for ua in AI_USER_AGENTS if not self.parser.can_fetch(url, ua)]


async def fetch_robots(client: httpx.AsyncClient, base_url: str) -> RobotsPolicy:
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        resp = await client.get(robots_url, timeout=10.0)
    except httpx.HTTPError:
        return RobotsPolicy(fetched=False, status=None, raw_text="", parser=None)

    if resp.status_code >= 400:
        return RobotsPolicy(fetched=False, status=resp.status_code, raw_text="", parser=None)

    text = resp.text
    parser = Protego.parse(text)
    return RobotsPolicy(
        fetched=True,
        status=resp.status_code,
        raw_text=text,
        parser=parser,
        sitemap_urls=list(parser.sitemaps),
    )


async def fetch_llms_txt(client: httpx.AsyncClient, base_url: str, robots: RobotsPolicy) -> tuple[bool, int | None]:
    """Is there an `/llms.txt` at the root? Returns (present, status).

    `llms.txt` is a proposed convention for a plain-text file telling AI
    systems what a site is about and which pages matter -- effectively a
    curated index, where `robots.txt` is a permission list. It is not a
    ratified standard and no major AI vendor has publicly committed to
    honouring it, which is exactly why its absence is reported as a
    *proactive recommendation* rather than a defect finding: a site
    without one is not broken, it has simply skipped a cheap, low-risk
    hedge. See the proactive layer in
    `ai-visibility-orchestrator/scripts/proactive.py`.

    Robots-checked before fetching, like every other request this
    pipeline makes -- `/llms.txt` is an ordinary URL, not a special case
    the way `/robots.txt` is.
    """
    llms_url = urljoin(base_url, "/llms.txt")
    if not robots.allowed(llms_url, DEFAULT_FETCH_UA):
        return False, None
    try:
        resp = await client.get(llms_url, timeout=10.0)
    except httpx.HTTPError:
        return False, None
    return resp.status_code < 400, resp.status_code


def _maybe_gunzip(content: bytes) -> bytes:
    """Transparently decompress a gzipped sitemap body.

    Large sites routinely declare `sitemap.xml.gz` in robots.txt. Whether
    `httpx` has already decompressed it depends entirely on how the
    server labelled it: `Content-Encoding: gzip` is handled by the
    transport, but a `.gz` file served as `Content-Type: application/gzip`
    -- which is the *correct* labelling for a gzip file, and what most
    servers do -- arrives as raw gzip bytes. Those hit
    `ElementTree.fromstring` as binary, raise `ParseError`, and the
    sitemap is skipped silently: `urls` stays empty, the fallback to
    `[base_url]` fires, and a 50,000-URL site gets audited as one page.

    Sniffing the two-byte gzip magic number rather than trusting the URL
    suffix or the content type, since both are frequently wrong and the
    magic number never is.
    """
    if content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except (OSError, EOFError, zlib.error):
            return content  # truncated or lying about being gzip -- let the XML parser reject it
    return content


async def discover_links_from_homepage(
    client: httpx.AsyncClient, base_url: str, robots: RobotsPolicy, max_urls: int = 500
) -> list[str]:
    """Same-host, robots-allowed links found on the homepage, in a
    deterministic order.

    The fallback for a site with no sitemap at all. Without it, sitemap
    discovery returns `[base_url]` and the *entire* audit runs against one
    page: every downstream stage then reports on a single document, the
    answerability probe indexes one page's chunks, and `TRUST-*`/`ENGAGE-*`
    scopes read `1 of 1`. Measured on a 196-site sweep: **39 of 131
    completed audits (30%) crawled exactly one page**, among them
    wikipedia.org, python.org, react.dev, rust-lang.org and mit.edu --
    none of which publish a sitemap, and all of which return 404 for
    `/sitemap.xml`. Those audits were not wrong, they were nearly empty.

    Deliberately one level deep, homepage only. This is a seed list for
    the existing deterministic sampler, not a recursive crawler: one
    extra request, bounded output, no queue, and nothing that could push
    the run past its own time budget. Same-host only (no subdomains, no
    off-site), robots-checked per URL like every other request this
    pipeline makes, and `#fragment`/`?query` stripped so the same page
    reached three ways doesn't occupy three sample slots.

    Sorted before returning: the sampler's determinism guarantee is only
    as good as the order of what it samples from, and DOM order would
    make the corpus depend on the site's own nav markup.
    """
    try:
        resp = await client.get(base_url, timeout=10.0)
    except FETCH_ERRORS:
        return []
    if resp.status_code >= 400:
        return []

    host = urlparse(str(resp.url)).netloc
    found: set[str] = set()
    for node in HTMLParser(resp.text).css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(str(resp.url), href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != host:
            continue
        clean = parsed._replace(query="", fragment="").geturl()
        if robots.allowed(clean, DEFAULT_FETCH_UA):
            found.add(clean)

    return sorted(found)[:max_urls]


async def discover_sitemap_urls(
    client: httpx.AsyncClient, base_url: str, robots: RobotsPolicy, max_urls: int = 500
) -> tuple[list[str], bool]:
    """Sitemap-first URL discovery. Falls back to /sitemap.xml, then to
    just the homepage if nothing is declared -- the sampler still runs,
    it just has less to choose from (recorded, not fatal).

    Returns (urls, sitemap_fetch_ok). `sitemap_fetch_ok` tracks whether a
    *declared* sitemap was actually fetched and parsed successfully --
    kept separate from `urls` because `urls` always falls back to
    `[base_url]` when discovery yields nothing, which would otherwise
    make "did the sitemap work" indistinguishable from "we have a URL to
    sample" (see REACH-006 / detect_sitemap_health, which needs the
    former, not the latter)."""

    candidates = list(robots.sitemap_urls) or [urljoin(base_url, "/sitemap.xml")]
    urls: list[str] = []
    seen_sitemaps: set[str] = set()
    sitemap_fetch_ok = False

    while candidates and len(urls) < max_urls:
        sitemap_url = candidates.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            resp = await client.get(sitemap_url, timeout=10.0)
        except httpx.HTTPError:
            continue
        if resp.status_code >= 400:
            continue
        try:
            root = ElementTree.fromstring(_maybe_gunzip(resp.content))
        except ElementTree.ParseError:
            continue
        sitemap_fetch_ok = True

        # `{*}` matches any namespace (or none). Binding the literal
        # sitemaps.org 0.9 namespace instead -- the obvious way to write
        # this -- silently returned zero URLs for two shapes that are
        # common in the wild: a bare `<urlset>` with no xmlns at all, and
        # the legacy `google.com/schemas/sitemap/0.84` namespace. Both
        # then fell through to the `[base_url]` fallback, so the whole
        # site got audited as a single page with no error anywhere.
        # `root.tag.lower()` already ignores the namespace for the
        # index-vs-urlset decision, so this makes the two consistent.
        tag = root.tag.lower()
        if tag.endswith("sitemapindex"):
            for loc in root.findall(".//{*}sitemap/{*}loc"):
                if loc.text:
                    candidates.append(loc.text.strip())
        else:  # urlset
            for loc in root.findall(".//{*}url/{*}loc"):
                if loc.text:
                    urls.append(loc.text.strip())

    if not urls:
        # No sitemap anywhere: seed the sampler from the homepage's own
        # links rather than auditing a single page. `sitemap_fetch_ok`
        # stays False either way -- REACH-006 still reports the missing
        # sitemap, which is a real finding; this only stops the *rest* of
        # the audit from being starved by it.
        urls = await discover_links_from_homepage(client, base_url, robots, max_urls)

    # The homepage is always a candidate, even when a large sitemap
    # already filled the cap. ghost.org's sitemap index yields 500 theme
    # and integration URLs before it ever reaches `/`, so the homepage was
    # not merely unsampled -- it was never in the pool the sampler chose
    # from. That matters more than one page's worth of coverage: entity
    # detection reads the homepage to decide what the brand is called, and
    # every generated buyer-intent query is built from that name.
    if not any(_is_homepage(u) for u in urls):
        urls = [base_url] + urls
    return urls[:max_urls], sitemap_fetch_ok


def find_homepage_url(urls, hint_url: str | None = None) -> str | None:
    """Which of `urls` (any iterable, typically a crawled-pages dict's
    keys) is actually the homepage -- matched by normalized root path
    (`""`/`"/"`), not exact string equality against `hint_url`.

    Exact-equality was the first implementation's bug (retrieval-
    simulation's entity detection, Day 5): the CLI's site argument
    ("https://example.com") essentially never byte-for-byte matches a
    real crawled URL, which always carries whatever path/trailing-slash
    the sitemap or crawl happened to produce ("https://example.com/").
    Confirmed against a real site (docs.python.org) before this helper
    existed as a shared function -- see the development log, Day 5. Kept
    here, not duplicated a third time, once trust-corroboration-audit
    needed the same lookup for its own homepage-scoped checks (Day 6).

    Returns `hint_url` itself if it happens to be an exact match (cheap
    win, no reason not to take it), else the alphabetically-first
    root-path URL, else None if nothing in `urls` looks like a
    homepage at all.
    """
    url_set = set(urls)
    if hint_url in url_set:
        return hint_url
    root_urls = sorted(u for u in url_set if urlparse(u).path in ("", "/"))
    return root_urls[0] if root_urls else None


def sample_seed_for(domain: str) -> str:
    """Deterministic, time-independent seed -- same site always hashes to
    the same value, so the sample (and therefore the whole report) is
    reproducible across runs and across days."""
    return "sha256:" + hashlib.sha256(domain.encode("utf-8")).hexdigest()


# Page classes worth guaranteeing a slot, in priority order. Matched on the
# URL path, which is the only signal available before anything is fetched.
#
# These are not arbitrary: they are the classes the *answerability probe*
# asks about. The buyer-intent query bank has pricing, contact and trust
# intents, so a sample that happens to contain no pricing page makes those
# queries unanswerable by construction -- and the proactive layer then
# recommends publishing a pricing page to a brand that already has one.
_PAGE_CLASS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("pricing", re.compile(r"/(pricing|plans?|price|subscribe|upgrade)(/|$)", re.I)),
    ("contact", re.compile(r"/(contact|support|help|customer-service)(/|$)", re.I)),
    ("about", re.compile(r"/(about|company|team|who-we-are|our-story)(/|$)", re.I)),
    ("docs", re.compile(r"/(docs?|documentation|guides?|faq|knowledge-?base)(/|$)", re.I)),
    ("product", re.compile(r"/(products?|features?|solutions?|services?)(/|$)", re.I)),
]


def _is_homepage(url: str) -> bool:
    return urlparse(url).path in ("", "/")


def _page_class(url: str) -> str | None:
    path = urlparse(url).path
    for name, pattern in _PAGE_CLASS_PATTERNS:
        if pattern.search(path):
            return name
    return None


def stratified_sample(
    urls: list[str], seed: str, max_pages: int = 40, *, pinned: str | None = None
) -> list[str]:
    """Deterministic, page-class-stratified sample.

    Order of guarantees, each filled from the hash-ranked candidates so the
    result stays byte-identical for the same inputs:

      1. `pinned` -- the URL the caller explicitly named, if any.
      2. The homepage. It is the single highest-value page in a brand
         audit: entity detection reads its JSON-LD `Organization` name,
         `<title>` and `<h1>` to decide *what the brand is called*, and
         every one of the 18 generated buyer-intent queries is built from
         that name.
      3. One page from each class in `_PAGE_CLASS_PATTERNS`.
      4. Everything else by seeded URL-hash rank, until `max_pages`.

    Steps 2 and 3 are the build plan's "stratified deterministic sample --
    home, top nav L1, pricing/plans, product/service class xN, about,
    contact, docs/help". They were deferred on Day 3 with a note in this
    docstring saying page classification didn't exist yet, and the note
    outlived the excuse. A live audit of ghost.org showed the cost: the
    hash-ranked 25-page sample drew theme and integration pages only, with
    no homepage and no pricing page, so (a) entity detection fell back to
    a `/resources/` page title and named the brand **"Ghost Resources"**,
    making all 18 queries ask about a company that does not exist, and
    (b) the report recommended publishing a pricing page to a brand whose
    `/pricing/` page was in the sitemap the whole time, merely unsampled.
    A uniform random sample is the right tool for estimating a proportion
    and the wrong one for finding the specific pages a buyer asks about.
    """
    deduped = sorted(set(urls))  # sort first so hash tie-break is the only
    # source of ordering -- set() iteration order is not guaranteed stable
    # across interpreters/runs.

    def rank(url: str) -> str:
        return hashlib.sha256((seed + "|" + url).encode("utf-8")).hexdigest()

    ranked = sorted(deduped, key=rank)
    picked: list[str] = []
    seen: set[str] = set()

    def take(url: str | None) -> None:
        if url is not None and url not in seen and len(picked) < max_pages:
            picked.append(url)
            seen.add(url)

    take(pinned)
    take(next((u for u in ranked if _is_homepage(u)), None))
    for name, _ in _PAGE_CLASS_PATTERNS:
        take(next((u for u in ranked if u not in seen and _page_class(u) == name), None))
    for url in ranked:
        take(url)
    return picked


class BudgetManager:
    """Hard watchdog for the <5-minute runtime constraint. Degradations are
    recorded, never silent -- see the project's build plan, Part 4 ("Runtime
    budget") and Part 8 (degradation ladder)."""

    # Order matters: first to go under pressure, per the build plan's cut
    # list (drop stage (6) perf first, then render sample size, then page
    # count).
    DEGRADATION_LADDER = [
        "drop_arrive_performance_metrics",
        "reduce_render_sample_size",
        "reduce_page_count",
    ]

    def __init__(self, total_budget_s: float = 270.0):
        self.total_budget_s = total_budget_s
        self.start = time.monotonic()
        self.degradations: list[str] = []
        self._ladder_index = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def remaining(self) -> float:
        return max(0.0, self.total_budget_s - self.elapsed())

    def over_budget(self) -> bool:
        return self.elapsed() >= self.total_budget_s

    def maybe_degrade(self) -> str | None:
        """Call when a stage is about to start and budget is tight. Applies
        the next rung of the ladder and records it; returns the rung name,
        or None if nothing left to cut (caller should stop early instead)."""
        if self._ladder_index >= len(self.DEGRADATION_LADDER):
            return None
        rung = self.DEGRADATION_LADDER[self._ladder_index]
        self._ladder_index += 1
        self.degradations.append(rung)
        return rung
