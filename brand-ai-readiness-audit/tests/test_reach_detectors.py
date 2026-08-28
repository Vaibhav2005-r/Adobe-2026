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


def test_ai_ua_block_all_bots_is_critical():
    disallow_all = "\n".join(f"User-agent: {ua}\nDisallow: /" for ua in AI_USER_AGENTS)
    robots = _robots(disallow_all)
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, "https://example.com/")
    assert len(findings) == 1
    assert findings[0].taxonomy_id == "REACH-001"
    assert findings[0].severity == "critical"
    assert findings[0].confidence == "high"


def test_ai_ua_block_open_robots_is_silent():
    robots = _robots("User-agent: *\nAllow: /")
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, "https://example.com/")
    assert findings == []


def test_ai_ua_block_partial_disallow_is_degraded_not_critical():
    text = "User-agent: GPTBot\nDisallow: /\nUser-agent: *\nAllow: /"
    robots = _robots(text)
    findings = reach_detect.detect_ai_ua_block("https://example.com", robots, "https://example.com/")
    assert len(findings) == 1
    assert findings[0].severity != "critical"  # only 1 of N bots blocked, not site-wide


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
