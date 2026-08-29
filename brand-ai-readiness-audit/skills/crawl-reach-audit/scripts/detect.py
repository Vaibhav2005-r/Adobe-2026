"""Stage (1) REACH detectors.

Each function takes already-fetched crawl data (no network calls of its
own -- that's `src/brand_audit/crawl.py` and `fetch.py`) and returns
`Finding`s. Every detector here traces back to a taxonomy entry in
`ai-visibility-orchestrator/references/taxonomy.md`; several are
translated directly from Day 1 field-research evidence (REACH-001,
REACH-002, REACH-003), not written from a generic checklist.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from selectolax.parser import HTMLParser  # noqa: E402

from brand_audit.crawl import AI_USER_AGENTS, GENERIC_CRAWLER_UA, RobotsPolicy  # noqa: E402
from brand_audit.fetch import FetchOutcome  # noqa: E402
from brand_audit.models import (  # noqa: E402
    Artifact,
    Confidence,
    Finding,
    Scope,
    Stage,
    SuggestedAction,
    Verification,
)
from brand_audit.severity import BlastRadius, compute_severity  # noqa: E402

_finding_counter = 0


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"F-REACH-{_finding_counter:03d}"


def _unverified() -> Verification:
    # finding-verification (the falsification pass) isn't wired up yet
    # (Day 8) -- honest placeholder rather than claiming a reproduction
    # check that didn't happen.
    return Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented")


def detect_ai_ua_block(site: str, robots: RobotsPolicy, sample_urls: list[str]) -> list[Finding]:
    """REACH-001: named AI crawlers explicitly disallowed.

    Checks every sampled URL, not just the homepage -- robots.txt rules
    can be path-scoped (e.g. `Disallow: /products` only), and a brand
    that blocks AI bots from its entire product catalog while leaving
    the homepage open would be invisible to this detector if it only
    ever checked `/`. This is a pure robots.txt rule lookup (no network
    fetch), so it's safe to run over the full sample regardless of
    which of those pages we actually end up crawling.
    """
    if not robots.fetched or not sample_urls:
        return []
    per_url_blocked = {url: robots.disallowed_ai_uas(url) for url in sample_urls}

    # A URL only counts here if the exclusion is actually AI-*specific*
    # -- i.e. a generic, unnamed crawler (GENERIC_CRAWLER_UA) would
    # still be let in. A blanket `User-agent: *` rule that excludes
    # every crawler equally (a staff directory, an admin panel, a
    # search-results page) blocks AI bots only as an incidental side
    # effect of a completely ordinary access-control decision -- not
    # the "brand deliberately disallows named AI crawlers" mechanism
    # this taxonomy entry is about. Found live during the Day 9 eval
    # harness: a single-page `User-agent: *` exclusion in a compliance
    # fixture scored `medium` and titled "disallows 12 of 12 named AI
    # crawlers" -- technically accurate about bot coverage, misleading
    # about what actually happened (everyone was excluded from one
    # page, not AI specifically). Filtering here, rather than adding a
    # page-count floor, keeps the *actually* AI-targeted single-page
    # case intact -- e.g. 12 named-bot-only `Disallow: /pricing` rules
    # with no `User-agent: *` at all still fires, correctly (see
    # tests/test_reach_detectors.py).
    per_url_blocked = {
        url: uas for url, uas in per_url_blocked.items() if uas and robots.allowed(url, GENERIC_CRAWLER_UA)
    }
    blocked = sorted(set().union(*per_url_blocked.values())) if per_url_blocked else []
    if not blocked:
        return []
    pages_affected = sum(1 for b in per_url_blocked.values() if b)

    # Deliberately thresholds, not exact equality, and deliberately
    # two-dimensional (bots blocked x pages affected):
    #
    # nytimes.com's robots.txt blocks 11 of 12 named bots but allows
    # plain "Applebot" (distinct from "Applebot-Extended", which it does
    # block) -- Apple's own documented split between search-indexing and
    # AI-training bots. Requiring literal 100% bot coverage would
    # under-count this as partial when it's functionally site-wide.
    #
    # Separately, a rule scoped to one path (e.g. `Disallow: /products`)
    # can block 100% of named bots *for that path* without being
    # site-wide at all -- that's what page_coverage guards against, now
    # that this checks every sampled URL instead of just the homepage.
    bot_coverage = len(blocked) / len(AI_USER_AGENTS)
    page_coverage = pages_affected / len(sample_urls)
    site_wide = bot_coverage >= 0.9 and page_coverage >= 0.9
    blast = BlastRadius.SITE_WIDE if site_wide else BlastRadius.DEGRADES
    confidence = Confidence.HIGH  # directly parsed from robots.txt, unambiguous
    severity = compute_severity(Stage.REACH, blast, confidence)

    bot_note = "every named AI crawler" if site_wide else f"{len(blocked)} of {len(AI_USER_AGENTS)} named AI crawlers"
    page_note = "" if site_wide else f" on {pages_affected}/{len(sample_urls)} sampled pages"
    return [
        Finding(
            id=_next_id(),
            title=f"robots.txt disallows {bot_note}{page_note}",
            severity=severity,
            stage=Stage.REACH,
            taxonomy_id="REACH-001",
            scope=Scope(checked=len(sample_urls), affected=pages_affected),
            evidence=(
                f"robots.txt at {urlparse(site).scheme}://{urlparse(site).netloc}/robots.txt "
                f"disallows: {', '.join(sorted(blocked))} (on {pages_affected}/{len(sample_urls)} sampled pages)"
            ),
            artifacts=[
                Artifact(
                    url=f"{urlparse(site).scheme}://{urlparse(site).netloc}/robots.txt",
                    http_status=robots.status,
                    selector=f"User-agent rules for: {', '.join(sorted(blocked))}",
                )
            ],
            confidence=confidence,
            verification=_unverified(),
            impact_mechanism=(
                "A robots-respecting AI crawler never fetches a single byte of a page its UA is "
                "disallowed from, so the brand can only appear in an assistant's answer via "
                "third-party syndication or licensing -- never a first-party citation."
            ),
            affected_queries=[],
            suggested_action=SuggestedAction(
                summary="Confirm this is intentional; if not, remove the named-AI-UA Disallow rules.",
                priority=severity,
                impact="high" if site_wide else "medium",
                effort="low",
                confidence=confidence,
                stage_unblocked=Stage.REACH,
                implementation=[
                    "Review robots.txt for Disallow rules under the named AI-bot user-agents",
                    "Remove or narrow the rules if AI-assistant visibility is desired",
                ],
                verification_step=f"curl -A GPTBot {urlparse(site).scheme}://{urlparse(site).netloc}/robots.txt",
                rationale_ref="references/taxonomy.md#reach-001",
            ),
        )
    ]


_LOCALE_PREFIX_RE = re.compile(r"^/([a-z]{2}(-[a-z]{2})?)(/.*)?$", re.IGNORECASE)


def detect_locale_redirect(site: str, no_redirect_outcomes: list[FetchOutcome]) -> list[Finding]:
    """REACH-002: a canonical URL 3xx-redirects to a locale-prefixed
    variant of the same path, chosen by requester geolocation rather than
    an explicit signal. Deliberately narrow (matches only the
    locale-prefix structural pattern) to avoid flagging ordinary
    redirects (trailing-slash normalization, http->https, page moves)."""
    findings = []
    for outcome in no_redirect_outcomes:
        rec = outcome.record
        if rec is None or rec.http_status is None or not (300 <= rec.http_status < 400):
            continue
        location = rec.headers.get("location", "")
        if not location:
            continue

        source_path = urlparse(rec.url).path or "/"
        dest_path = urlparse(location).path or location
        m = _LOCALE_PREFIX_RE.match(dest_path)
        if not m:
            continue
        remainder = m.group(3) or "/"
        if remainder.rstrip("/") != source_path.rstrip("/"):
            continue  # not the same page, just a locale-prefixed one -- a real page move

        empty_body = len(rec.body) == 0
        confidence = Confidence.HIGH if empty_body else Confidence.MEDIUM
        severity = compute_severity(Stage.REACH, BlastRadius.PAGE_CLASS, confidence)

        findings.append(
            Finding(
                id=_next_id(),
                title=f"{source_path} redirects to a locale-specific variant with{'out' if not empty_body else ''} content",
                severity=severity,
                stage=Stage.REACH,
                taxonomy_id="REACH-002",
                scope=Scope(checked=1, affected=1, page_class=source_path),
                evidence=(
                    f"{rec.url} -> HTTP {rec.http_status}, Location: {location}, "
                    f"body length: {len(rec.body)} bytes"
                ),
                artifacts=[
                    Artifact(
                        url=rec.url,
                        http_status=rec.http_status,
                        selector=f"Location: {location}",
                    )
                ],
                confidence=confidence,
                verification=_unverified(),
                impact_mechanism=(
                    "A stateless AI crawler with no persistent session/geo signal fetching the "
                    "canonical, most-commonly-linked URL either doesn't follow a redirect chosen by "
                    "IP geolocation, or lands on whatever locale variant its egress IP maps to -- "
                    "the 'citable' URL a person would naturally link to carries no stable, "
                    "predictable content of its own."
                ),
                affected_queries=[],
                suggested_action=SuggestedAction(
                    summary="Serve canonical, locale-neutral content directly at the un-prefixed path.",
                    priority=severity,
                    impact="high",
                    effort="medium",
                    confidence=confidence,
                    stage_unblocked=Stage.REACH,
                    implementation=[
                        "Serve a default-locale version of the content at the canonical path",
                        "Reserve geo-redirects for sessions carrying explicit locale signals (Accept-Language, cookie), not IP alone",
                    ],
                    verification_step=f"curl -I {rec.url} -- Location should not change based on requester IP",
                    rationale_ref="references/taxonomy.md#reach-002",
                ),
            )
        )
    return findings


WAF_PROBE_UAS = ["GPTBot", "Mozilla/5.0 (compatible; ClaudeBot/1.0)",
                  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"]


def detect_waf_block(site: str, waf_probe: dict[str, FetchOutcome], robots: RobotsPolicy) -> list[Finding]:
    """REACH-003: every UA (including a plain browser string with no bot
    signature) gets blocked/challenged, and robots.txt itself is
    unreadable -- an infrastructure-level gate, not a declared policy."""
    if robots.fetched:
        # robots.txt was readable -- if there's still a block, it's better
        # explained by REACH-001 (declared policy) than an opaque WAF gate.
        return []

    blocked_uas = []
    for ua, outcome in waf_probe.items():
        rec = outcome.record
        if rec is None or (rec.http_status is not None and rec.http_status >= 400):
            blocked_uas.append(ua)

    if len(blocked_uas) < len(waf_probe):
        return []  # at least one UA got through -- not a blanket infra block

    confidence = Confidence.HIGH
    severity = compute_severity(Stage.REACH, BlastRadius.SITE_WIDE, confidence)
    sample_status = next((o.record.http_status for o in waf_probe.values() if o.record), None)

    return [
        Finding(
            id=_next_id(),
            title="WAF/bot-challenge blocks every tested user agent, including a plain browser string",
            severity=severity,
            stage=Stage.REACH,
            taxonomy_id="REACH-003",
            scope=Scope(checked=len(waf_probe), affected=len(blocked_uas)),
            evidence=(
                f"{site} blocked all {len(waf_probe)} probed UAs (status ~{sample_status}); "
                f"robots.txt itself was also unreachable, so declared crawl policy can't be read."
            ),
            artifacts=[
                Artifact(url=site, http_status=sample_status, selector=f"UAs tested: {', '.join(waf_probe.keys())}")
            ],
            confidence=confidence,
            verification=_unverified(),
            impact_mechanism=(
                "An infrastructure-level bot-management layer blocks the request before any "
                "declared robots.txt policy is even reachable -- a fully honest, robots-compliant "
                "AI crawler gets nothing, with no way to discover whether it would have been allowed."
            ),
            affected_queries=[],
            suggested_action=SuggestedAction(
                summary="Exempt documented AI-crawler UAs from the challenge gate, or at minimum always serve /robots.txt unchallenged.",
                priority=severity,
                impact="high",
                effort="medium",
                confidence=confidence,
                stage_unblocked=Stage.REACH,
                implementation=[
                    "Add documented AI-crawler UAs to the WAF/bot-management allowlist",
                    "Ensure /robots.txt is served unconditionally, per most bot-management vendors' own best practice",
                ],
                verification_step=f"curl -I -A GPTBot {site} -- should not be challenged/blocked",
                rationale_ref="references/taxonomy.md#reach-003",
            ),
        )
    ]


_BLOCKED_LIKE_STATUSES = {403, 429, 503}


def detect_waf_contradicts_robots(site: str, allowed_outcomes: list[FetchOutcome]) -> list[Finding]:
    """REACH-007: robots.txt explicitly *allows* these paths (they
    already passed the crawler's own permission check before being
    fetched at all), but fetching them still returns a block-shaped
    status (403/429/503) -- an infrastructure layer (WAF/bot-management)
    contradicting the site's own declared policy. Distinct from
    REACH-003, which requires robots.txt to be unreadable in the first
    place; this is the site telling a crawler "you're welcome here" and
    then blocking it anyway.

    Found on a real site, not hypothesized: a wild-corpus validation run
    against allbirds.com hit this exactly -- robots.txt is a standard,
    permissive Shopify robots.txt with no rule blocking the sampled
    product/page URLs, yet every one of them returned HTTP 403 for this
    project's own declared crawler UA.
    """
    if not allowed_outcomes:
        return []
    blocked = [o for o in allowed_outcomes if o.record is not None and o.record.http_status in _BLOCKED_LIKE_STATUSES]
    if len(blocked) / len(allowed_outcomes) < 0.8:
        return []  # a handful of isolated 403s isn't a policy contradiction -- most of the allowed sample needs to be blocked

    confidence = Confidence.HIGH
    severity = compute_severity(Stage.REACH, BlastRadius.SITE_WIDE, confidence)
    sample_status = blocked[0].record.http_status
    return [
        Finding(
            id=_next_id(),
            title=f"robots.txt allows these pages, but {len(blocked)}/{len(allowed_outcomes)} still return HTTP {sample_status}",
            severity=severity,
            stage=Stage.REACH,
            taxonomy_id="REACH-007",
            scope=Scope(checked=len(allowed_outcomes), affected=len(blocked)),
            evidence="; ".join(f"{o.url} -> {o.record.http_status}" for o in blocked[:5]),
            artifacts=[Artifact(url=o.url, http_status=o.record.http_status) for o in blocked[:3]],
            confidence=confidence,
            verification=_unverified(),
            impact_mechanism=(
                "robots.txt is the crawler's contract with the site -- a compliant AI crawler checks "
                "it, sees these paths allowed, and proceeds in good faith. An infrastructure layer "
                "blocking the fetch anyway means the declared policy is misleading: robots.txt says "
                "'crawl me' while the site's actual behavior says 'not you.'"
            ),
            affected_queries=[],
            suggested_action=SuggestedAction(
                summary="Align the WAF/bot-management allowlist with the declared robots.txt policy, or update robots.txt to reflect what's actually blocked.",
                priority=severity,
                impact="high",
                effort="medium",
                confidence=confidence,
                stage_unblocked=Stage.REACH,
                implementation=[
                    "Add documented AI-crawler UAs to the WAF allowlist for paths robots.txt already permits",
                    "Alternatively, add explicit Disallow rules for paths that are actually blocked, so crawlers don't waste budget on them",
                ],
                verification_step=f"curl -I -A ClaudeBot {allowed_outcomes[0].url} -- should not return {sample_status}",
                rationale_ref="references/taxonomy.md#reach-007",
            ),
        )
    ]


_NOT_FOUND_RE = re.compile(r"\b(page not found|404 error|doesn.t exist|cannot be found|no longer available)\b", re.IGNORECASE)


def detect_soft_404(site: str, outcomes: list[FetchOutcome]) -> list[Finding]:
    """A page returns HTTP 200 but its content says it's missing --
    crawlers that trust the status code index it as real, live content."""
    findings = []
    for outcome in outcomes:
        rec = outcome.record
        if rec is None or rec.http_status != 200:
            continue
        text = rec.text
        stripped = re.sub(r"<[^>]+>", " ", text)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if len(stripped) < 300 and _NOT_FOUND_RE.search(stripped):
            confidence = Confidence.MEDIUM
            severity = compute_severity(Stage.REACH, BlastRadius.PAGE_CLASS, confidence)
            findings.append(
                Finding(
                    id=_next_id(),
                    title=f"{rec.url} returns HTTP 200 but reads as a not-found page (soft-404)",
                    severity=severity,
                    stage=Stage.REACH,
                    taxonomy_id="REACH-004",
                    scope=Scope(checked=1, affected=1),
                    evidence=f"HTTP 200, {len(stripped)} chars of stripped content: {stripped[:200]!r}",
                    artifacts=[Artifact(url=rec.url, http_status=rec.http_status, selector="body text")],
                    confidence=confidence,
                    verification=_unverified(),
                    impact_mechanism=(
                        "A crawler that trusts the 200 status code treats this as valid, citable "
                        "content; an assistant may cite a URL whose actual content tells a human "
                        "reader (and would tell an LLM reading the text) that nothing is there."
                    ),
                    affected_queries=[],
                    suggested_action=SuggestedAction(
                        summary="Return a real 404 status for missing content instead of 200.",
                        priority=severity,
                        impact="medium",
                        effort="low",
                        confidence=confidence,
                        stage_unblocked=Stage.REACH,
                        implementation=["Return HTTP 404 (or 410) for pages that no longer exist"],
                        verification_step=f"curl -I {rec.url} -- status should be 404, not 200",
                        rationale_ref="references/taxonomy.md#reach-004",
                    ),
                )
            )
    return findings


def detect_canonical_issues(site: str, outcomes: list[FetchOutcome]) -> list[Finding]:
    """Cross-domain or duplicate rel=canonical tags -- narrow checks,
    chosen to avoid flagging the (very common, non-defective) absence of
    a canonical tag entirely."""
    findings = []
    for outcome in outcomes:
        rec = outcome.record
        if rec is None or rec.http_status != 200:
            continue
        # A real HTML parser, not a regex: `<link href=".." rel="canonical">`
        # (attribute order reversed from the more common
        # `rel=".." href="..">`) is valid HTML that a hand-rolled regex
        # requiring `rel=` before `href=` in source order would silently
        # miss -- selectolax is already a project dependency for exactly
        # this kind of parsing.
        tree = HTMLParser(rec.text)
        matches = [
            node.attributes.get("href", "")
            for node in tree.css('link[rel="canonical"]')
            if node.attributes.get("href")
        ]
        if len(matches) > 1 and len(set(matches)) > 1:
            confidence = Confidence.MEDIUM
            severity = compute_severity(Stage.REACH, BlastRadius.DEGRADES, confidence)
            findings.append(
                Finding(
                    id=_next_id(),
                    title=f"{rec.url} has multiple conflicting rel=canonical tags",
                    severity=severity,
                    stage=Stage.REACH,
                    taxonomy_id="REACH-005",
                    scope=Scope(checked=1, affected=1),
                    evidence=f"canonical hrefs found: {matches}",
                    artifacts=[Artifact(url=rec.url, http_status=rec.http_status, selector="link[rel=canonical]")],
                    confidence=confidence,
                    verification=_unverified(),
                    impact_mechanism=(
                        "Ambiguous canonical signals leave a crawler unable to determine which URL "
                        "should receive citation credit for this content, splitting authority "
                        "between two URLs instead of consolidating it on one."
                    ),
                    affected_queries=[],
                    suggested_action=SuggestedAction(
                        summary="Emit exactly one rel=canonical tag per page.",
                        priority=severity,
                        impact="low",
                        effort="low",
                        confidence=confidence,
                        stage_unblocked=Stage.REACH,
                        implementation=["Remove duplicate <link rel=canonical> tags, keep one"],
                        verification_step=f"curl -s {rec.url} | grep -c 'rel=\"canonical\"' -- should be 1",
                        rationale_ref="references/taxonomy.md#reach-005",
                    ),
                )
            )
            continue
        if matches:
            href = matches[0]
            if href.startswith("http") and urlparse(href).netloc and urlparse(href).netloc != urlparse(rec.url).netloc:
                confidence = Confidence.MEDIUM
                severity = compute_severity(Stage.REACH, BlastRadius.DEGRADES, confidence)
                findings.append(
                    Finding(
                        id=_next_id(),
                        title=f"{rec.url} canonicalizes to a different domain ({urlparse(href).netloc})",
                        severity=severity,
                        stage=Stage.REACH,
                        taxonomy_id="REACH-005",
                        scope=Scope(checked=1, affected=1),
                        evidence=f"canonical href: {href}",
                        artifacts=[Artifact(url=rec.url, http_status=rec.http_status, selector="link[rel=canonical]")],
                        confidence=confidence,
                        verification=_unverified(),
                        impact_mechanism=(
                            "A cross-domain canonical tells crawlers this page's citation credit "
                            "belongs to a different domain entirely -- if unintentional (e.g. a "
                            "staging/CDN artifact), the brand's own domain never accrues citation "
                            "authority for its own content."
                        ),
                        affected_queries=[],
                        suggested_action=SuggestedAction(
                            summary="Confirm the cross-domain canonical is intentional; fix if it's a misconfiguration.",
                            priority=severity,
                            impact="medium",
                            effort="low",
                            confidence=confidence,
                            stage_unblocked=Stage.REACH,
                            implementation=["Review templating/CDN config that sets rel=canonical"],
                            verification_step=f"curl -s {rec.url} | grep 'rel=\"canonical\"'",
                            rationale_ref="references/taxonomy.md#reach-005",
                        ),
                    )
                )
    return findings


def detect_sitemap_health(site: str, robots: RobotsPolicy, sitemap_reachable: bool) -> list[Finding]:
    if robots.sitemap_urls and not sitemap_reachable:
        confidence = Confidence.HIGH
        severity = compute_severity(Stage.REACH, BlastRadius.DEGRADES, confidence)
        return [
            Finding(
                id=_next_id(),
                title="robots.txt declares a sitemap that is unreachable",
                severity=severity,
                stage=Stage.REACH,
                taxonomy_id="REACH-006",
                scope=Scope(checked=len(robots.sitemap_urls), affected=len(robots.sitemap_urls)),
                evidence=f"declared sitemap(s): {robots.sitemap_urls}",
                artifacts=[Artifact(url=robots.sitemap_urls[0], http_status=None)],
                confidence=confidence,
                verification=_unverified(),
                impact_mechanism=(
                    "Sitemap-first discovery (the fastest, most reliable way a crawler finds pages) "
                    "gets nothing; the crawler falls back to slower internal-link discovery, which "
                    "may miss pages entirely under a crawl budget."
                ),
                affected_queries=[],
                suggested_action=SuggestedAction(
                    summary="Fix or remove the declared sitemap URL.",
                    priority=severity,
                    impact="medium",
                    effort="low",
                    confidence=confidence,
                    stage_unblocked=Stage.REACH,
                    implementation=["Ensure the sitemap URL in robots.txt returns a valid sitemap"],
                    verification_step=f"curl -I {robots.sitemap_urls[0]} -- should be 200",
                    rationale_ref="references/taxonomy.md#reach-006",
                ),
            )
        ]
    return []
