"""Unit tests for the stage (1) REACH detectors -- no network involved,
synthetic robots.txt / fetch data built directly so each detector's logic
is tested in isolation and fast.
"""

from __future__ import annotations

from protego import Protego

import detect as reach_detect
from brand_audit.artifact_store import FetchRecord
from brand_audit.crawl import AI_USER_AGENTS, RobotsPolicy
from brand_audit.fetch import FetchOutcome


def _robots(text: str, fetched: bool = True, status: int = 200) -> RobotsPolicy:
    parser = Protego.parse(text) if fetched else None
    return RobotsPolicy(fetched=fetched, status=status if fetched else None, raw_text=text, parser=parser)


_SAMPLE = ["https://example.com/", "https://example.com/about", "https://example.com/pricing"]


def test_ai_ua_block_all_bots_is_critical():
    disallow_all = "\n".join(f"User-agent: {ua}\nDisallow: /" for ua in AI_USER_AGENTS)
    robots = _robots(disallow_all)
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, _SAMPLE)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-001"
    assert findings[0].severity == "critical"
    assert findings[0].confidence == "high"
    assert findings[0].scope.checked == len(_SAMPLE)
    assert findings[0].scope.affected == len(_SAMPLE)  # every sampled page is blocked


def test_ai_ua_block_open_robots_is_silent():
    robots = _robots("User-agent: *\nAllow: /")
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, _SAMPLE)
    assert findings == []


def test_ai_ua_block_partial_disallow_is_degraded_not_critical():
    text = "User-agent: GPTBot\nDisallow: /\nUser-agent: *\nAllow: /"
    robots = _robots(text)
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, _SAMPLE)
    assert len(findings) == 1
    assert findings[0].severity != "critical"  # only 1 of N bots blocked, not site-wide


def test_ai_ua_block_path_scoped_rule_is_not_site_wide_even_if_all_bots_blocked():
    # Disallow: /pricing (not /) blocks every named bot, but only from one
    # of the three sampled paths -- this must NOT be classified site-wide
    # even though bot coverage is 100%, because page coverage isn't.
    # Checking only the homepage (the pre-fix behavior) would have missed
    # this finding entirely, since "/" itself is never blocked.
    rules = "\n".join(f"User-agent: {ua}\nDisallow: /pricing" for ua in AI_USER_AGENTS)
    robots = _robots(rules)
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, _SAMPLE)
    assert len(findings) == 1
    assert findings[0].severity != "critical"
    assert findings[0].scope.affected == 1  # only /pricing is affected, not all 3 sampled pages


def test_ai_ua_block_no_sampled_urls_is_silent():
    robots = _robots("User-agent: *\nDisallow: /")
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, [])
    assert findings == []


def _outcome(url: str, status: int, body: bytes = b"", headers: dict | None = None) -> FetchOutcome:
    return FetchOutcome(url=url, record=FetchRecord(
        url=url, http_status=status, body=body, fetched_with_ua="test", headers=headers or {}
    ))


def test_locale_redirect_empty_body_flagged():
    outcomes = [_outcome(
        "https://example.com/pricing", 307, body=b"",
        headers={"location": "https://example.com/in/pricing"},
    )]
    findings = reach_detect.detect_locale_redirect("https://example.com", outcomes)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-002"
    assert findings[0].confidence == "high"  # empty body corroborates


def test_ordinary_page_move_redirect_not_flagged():
    outcomes = [_outcome(
        "https://example.com/old-page", 301, body=b"",
        headers={"location": "https://example.com/new-page"},
    )]
    findings = reach_detect.detect_locale_redirect("https://example.com", outcomes)
    assert findings == []


def test_soft_404_flagged():
    body = b"<html><body><h1>Page Not Found</h1><p>Sorry, this page doesn't exist.</p></body></html>"
    outcomes = [_outcome("https://example.com/gone", 200, body=body)]
    findings = reach_detect.detect_soft_404("https://example.com", outcomes)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-004"


def test_normal_long_page_not_flagged_as_soft_404():
    body = ("<html><body><h1>Welcome</h1><p>" + ("Real content. " * 60) + "</p></body></html>").encode()
    outcomes = [_outcome("https://example.com/", 200, body=body)]
    findings = reach_detect.detect_soft_404("https://example.com", outcomes)
    assert findings == []


def test_cross_domain_canonical_flagged():
    body = b'<html><head><link rel="canonical" href="https://other-domain.com/page"></head><body>x</body></html>'
    outcomes = [_outcome("https://example.com/page", 200, body=body)]
    findings = reach_detect.detect_canonical_issues("https://example.com", outcomes)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-005"


def test_same_domain_canonical_not_flagged():
    body = b'<html><head><link rel="canonical" href="https://example.com/page"></head><body>x</body></html>'
    outcomes = [_outcome("https://example.com/page", 200, body=body)]
    findings = reach_detect.detect_canonical_issues("https://example.com", outcomes)
    assert findings == []


def test_missing_canonical_not_flagged():
    # Absence of a canonical tag is common and not itself a defect --
    # only conflicting/cross-domain canonicals are.
    body = b"<html><head></head><body>x</body></html>"
    outcomes = [_outcome("https://example.com/page", 200, body=body)]
    findings = reach_detect.detect_canonical_issues("https://example.com", outcomes)
    assert findings == []


def test_cross_domain_canonical_flagged_with_reversed_attribute_order():
    # href before rel, the reverse of the more common ordering -- valid
    # HTML that a rel-then-href regex would silently miss. Real HTML
    # parsing (selectolax) shouldn't care about attribute order.
    body = b'<html><head><link href="https://other-domain.com/page" rel="canonical"></head><body>x</body></html>'
    outcomes = [_outcome("https://example.com/page", 200, body=body)]
    findings = reach_detect.detect_canonical_issues("https://example.com", outcomes)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-005"


def _sitemap_robots(sitemap_urls: list[str]) -> RobotsPolicy:
    text = "\n".join(f"Sitemap: {u}" for u in sitemap_urls) + "\nUser-agent: *\nAllow: /"
    robots = _robots(text)
    robots.sitemap_urls = sitemap_urls
    return robots


def test_sitemap_health_unreachable_flagged():
    robots = _sitemap_robots(["https://example.com/sitemap.xml"])
    findings = reach_detect.detect_sitemap_health("https://example.com", robots, sitemap_reachable=False)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-006"


def test_sitemap_health_reachable_is_silent():
    robots = _sitemap_robots(["https://example.com/sitemap.xml"])
    findings = reach_detect.detect_sitemap_health("https://example.com", robots, sitemap_reachable=True)
    assert findings == []


def test_sitemap_health_none_declared_is_silent():
    # No sitemap declared at all isn't a "declared but unreachable" case
    # -- shouldn't fire regardless of the reachable flag.
    robots = _robots("User-agent: *\nAllow: /")
    findings = reach_detect.detect_sitemap_health("https://example.com", robots, sitemap_reachable=False)
    assert findings == []


# --- WAF contradicts robots.txt (REACH-007) --------------------------------
# Found on a real site during Day 6's wild-corpus validation, not
# hypothesized: allbirds.com's robots.txt is a standard, permissive
# Shopify robots.txt with no rule blocking the sampled URLs, yet every
# one of them returned HTTP 403 for this project's own declared UA.

def test_waf_contradicts_robots_flagged_when_all_allowed_urls_blocked():
    outcomes = [_outcome(f"https://example.com/p{i}", 403) for i in range(5)]
    findings = reach_detect.detect_waf_contradicts_robots("https://example.com", outcomes)
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-007"
    assert findings[0].severity == "critical"


def test_waf_contradicts_robots_silent_when_most_allowed_urls_succeed():
    outcomes = [_outcome(f"https://example.com/p{i}", 200) for i in range(4)] + [_outcome("https://example.com/p4", 403)]
    findings = reach_detect.detect_waf_contradicts_robots("https://example.com", outcomes)
    assert findings == []


def test_waf_contradicts_robots_silent_when_no_outcomes():
    assert reach_detect.detect_waf_contradicts_robots("https://example.com", []) == []


def test_waf_contradicts_robots_ignores_failed_fetches():
    # A record=None (network error, not a block-shaped status) shouldn't
    # count toward the blocked fraction.
    outcomes = [_outcome(f"https://example.com/p{i}", 200) for i in range(4)]
    outcomes.append(FetchOutcome(url="https://example.com/p4", record=None, error="connection reset"))
    findings = reach_detect.detect_waf_contradicts_robots("https://example.com", outcomes)
    assert findings == []
