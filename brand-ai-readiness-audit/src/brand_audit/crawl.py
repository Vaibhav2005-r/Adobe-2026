"""Crawl core: robots/AI-UA checks, sitemap discovery, deterministic
sampling, and the time-budget watchdog.

Everything here is stdlib + httpx + protego -- no optional dependency.
Stage detectors (crawl-reach-audit, etc.) build on top of this; it does
not itself emit findings.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from protego import Protego

# Documented AI-crawler UAs, per docs/build-plan.md Part 4. Kept as a flat
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

DEFAULT_FETCH_UA = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +https://www.anthropic.com/claude-bot)"

# A second, distinct AI-crawler UA -- used only by finding-verification's
# re-fetch check ("re-fetch and re-test with a different UA... does it
# reproduce?", per docs/build-plan.md Part 2 (4)). Deliberately a
# *different* named bot from DEFAULT_FETCH_UA, not a generic browser
# string: the point is to catch a UA-conditional response (a WAF or
# origin server treating one AI crawler differently from another), which
# a browser-UA re-fetch wouldn't exercise at all.
VERIFICATION_UA = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot"


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
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            continue
        sitemap_fetch_ok = True

        tag = root.tag.lower()
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if tag.endswith("sitemapindex"):
            for loc in root.findall(".//sm:sitemap/sm:loc", ns):
                if loc.text:
                    candidates.append(loc.text.strip())
        else:  # urlset
            for loc in root.findall(".//sm:url/sm:loc", ns):
                if loc.text:
                    urls.append(loc.text.strip())

    if not urls:
        urls = [base_url]
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
    existed as a shared function -- see docs/progress.md Day 5. Kept
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


def stratified_sample(urls: list[str], seed: str, max_pages: int = 40) -> list[str]:
    """Deterministic sample via seeded URL-hash tie-break.

    Full page-class stratification (home / pricing / product xN / about /
    contact / docs / blog, per the build plan's runtime-budget section) is
    a stage-1 detector concern layered on top of this once page
    classification exists (Day 3). This function guarantees the
    determinism property the rest of the pipeline depends on: given the
    same `urls` and `seed`, the output is always byte-identical.
    """
    deduped = sorted(set(urls))  # sort first so hash tie-break is the only
    # source of ordering -- set() iteration order is not guaranteed stable
    # across interpreters/runs.

    def rank(url: str) -> str:
        return hashlib.sha256((seed + "|" + url).encode("utf-8")).hexdigest()

    ranked = sorted(deduped, key=rank)
    return ranked[:max_pages]


class BudgetManager:
    """Hard watchdog for the <5-minute runtime constraint. Degradations are
    recorded, never silent -- see docs/build-plan.md Part 4 ("Runtime
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
