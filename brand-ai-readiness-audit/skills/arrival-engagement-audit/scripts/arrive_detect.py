"""Stage (6) ARRIVE detectors (arrival-engagement-audit).

Answers: does the visitor stay? Deliberately not a generic UX audit --
every check here is framed against the AI-referred persona specifically
(deep-linked, mid-task, already given a partial answer, zero context),
per the build plan's own DoD warning: "if a finding would be identical
for a Google visitor, rewrite it or drop it."

All seven detectors run on data the pipeline already collected --
raw HTML from stage (1), the FetchRecord (final_url, elapsed_s) stage
(1) already captured per fetch, and the answerability_matrix stage (4)
already computed. No new network calls, no rendering. LCP/INP are
deliberately NOT measured here: the build plan's own cut list (Part 8)
names them first-to-cut, explicitly pairing that with "keep TTFB --
cheap and adequate" -- ENGAGE-007 below measures full-response latency
(a TTFB-adjacent proxy httpx already records for free) instead.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.artifact_store import FetchRecord  # noqa: E402
from brand_audit.models import (  # noqa: E402
    AnswerabilityMatrixEntry,
    Artifact,
    Confidence,
    Finding,
    Scope,
    Stage,
    SuggestedAction,
    Verification,
)
from brand_audit.retrieval import tokenize  # noqa: E402
from brand_audit.severity import BlastRadius, compute_severity  # noqa: E402

import trafilatura

_finding_counter = 0


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"F-ENGAGE-{_finding_counter:03d}"


def _unverified() -> Verification:
    return Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented")


# --- ENGAGE-001: answer proximity -------------------------------------------

_BURIED_POSITION_THRESHOLD = 0.6


def detect_buried_answers(matrix: list[AnswerabilityMatrixEntry]) -> Finding | None:
    """A citable answer whose winning chunk sits deep in its page's main
    content. `top_chunk_position_ratio` (computed once in stage (4), see
    brand_audit.chunk.page_content_length) is a text-offset proxy for
    "above the fold" -- exact pixel position needs rendering this stage
    doesn't do, but a chunk starting past the page's own midpoint cannot
    plausibly be above any reasonable fold either."""
    citable = [e for e in matrix if e.citable and e.top_chunk_position_ratio is not None]
    buried = [e for e in citable if e.top_chunk_position_ratio >= _BURIED_POSITION_THRESHOLD]
    if not buried:
        return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.ARRIVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(buried)} of {len(citable)} citable answers sit in the back half of their page",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-001",
        scope=Scope(checked=len(citable), affected=len(buried)),
        evidence="; ".join(
            f"[{e.intent}] {e.query!r} -> {e.top_chunk_url} ({e.top_chunk_position_ratio:.0%} into the page)"
            for e in buried[:5]
        ),
        artifacts=[Artifact(url=e.top_chunk_url) for e in buried[:3] if e.top_chunk_url],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "An AI-referred visitor arrives deep-linked and mid-task, already given a partial "
            "answer by the assistant -- they scan to confirm it, not to read the page fresh. An "
            "answer buried past the page's own midpoint asks that visitor to re-find what they were "
            "already told, which is exactly the friction a search visitor (who chose to click in "
            "cold) tolerates but an AI-referred one doesn't."
        ),
        affected_queries=[e.query for e in buried[:10]],
        suggested_action=SuggestedAction(
            summary="Move the cited answer, or a direct one-line restatement of it, higher in the page's main content.",
            priority=severity,
            impact="medium",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Lead the relevant section with the direct answer before any narrative framing"],
            verification_step="Re-run the audit and confirm the query's top_chunk_position_ratio drops",
            rationale_ref="references/taxonomy.md#engage-001",
        ),
    )


# --- ENGAGE-002: orientation gap --------------------------------------------

_ORIENTATION_WINDOW_CHARS = 500


def _orientation_finding(url: str, evidence: str, confidence: Confidence) -> Finding:
    severity = compute_severity(Stage.ARRIVE, BlastRadius.PAGE_CLASS, confidence)
    return Finding(
        id=_next_id(),
        title=f"{url}: a cold arrival can't tell what this is without the nav",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-002",
        scope=Scope(checked=1, affected=1, page_class="citable"),
        evidence=evidence,
        artifacts=[Artifact(url=url)],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "An AI-referred visitor lands on this exact page, never the homepage, with zero prior "
            "context about the brand -- they don't see the nav or logo as onboarding, because they "
            "don't browse to get here. If the page's own main content never names the brand near "
            "the top, a cold arrival has nothing on the page itself confirming what company this is "
            "or that the assistant's citation landed somewhere legitimate."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Name the brand explicitly in the page's opening content, not just in the nav/logo.",
            priority=severity,
            impact="low",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Add a one-line brand-identifying sentence near the top of the main content"],
            verification_step="Re-run the audit and confirm this page no longer appears in ENGAGE-002",
            rationale_ref="references/taxonomy.md#engage-002",
        ),
    )


def detect_orientation_gap(url: str, html: str, entity_name: str) -> Finding | None:
    """Does this specific citable page's own main content name the
    brand near the top -- without relying on the nav/logo a deep-linked,
    never-browsed-here visitor never scans?"""
    text = trafilatura.extract(html) or ""
    if not text:
        return None  # nothing to check here -- RENDER/EXTRACT's problem, not ENGAGE's
    entity_tokens = frozenset(tokenize(entity_name))
    if not entity_tokens:
        return None  # entity name itself didn't tokenize (e.g. the "the site" fallback) -- nothing to check against
    body_tokens = frozenset(tokenize(text))
    if not (entity_tokens & body_tokens):
        return _orientation_finding(
            url, f"{entity_name!r} does not appear anywhere in this page's main content", Confidence.MEDIUM
        )
    lead_tokens = frozenset(tokenize(text[:_ORIENTATION_WINDOW_CHARS]))
    if entity_tokens & lead_tokens:
        return None
    return _orientation_finding(
        url,
        f"{entity_name!r} appears on the page but not in its first {_ORIENTATION_WINDOW_CHARS} characters",
        Confidence.LOW,
    )


# --- ENGAGE-003: context reset ----------------------------------------------

_LOCALE_GATE_PHRASES = (
    "select your country", "select your region", "choose your country",
    "choose your region", "select your language", "choose your language",
    "select country", "select region",
)


def _looks_like_locale_gate(html: str) -> bool:
    text = (trafilatura.extract(html) or html).lower()
    return any(p in text for p in _LOCALE_GATE_PHRASES)


def detect_context_reset(url: str, record: FetchRecord, pages: dict[str, str]) -> Finding | None:
    """A deep link that redirects to the homepage or a locale/region
    selector, not the page it points at. Distinct from REACH-002's
    locale-*prefix* redirect (still resolves to the same page under a
    `/en-us/`-style path) -- this is about losing the deep link's
    specificity entirely, the "outright killer" case the build plan
    names: the assistant's citation lands nowhere useful. Uses the
    already-followed-redirect FetchRecord's `final_url` -- no second
    fetch needed."""
    if record.final_url is None:
        return None
    original_path = urlparse(url).path.rstrip("/")
    if original_path == "":
        return None  # started at the homepage already -- nothing to reset
    final_path = urlparse(record.final_url).path.rstrip("/")
    if final_path == original_path:
        return None  # cosmetic redirect only (trailing slash, http->https) -- same destination

    if final_path == "":
        reason = "redirects to the homepage, losing the deep link's specificity entirely"
    elif pages.get(record.final_url) and _looks_like_locale_gate(pages[record.final_url]):
        reason = "redirects to a region/locale selector instead of the requested page"
    else:
        return None  # redirected somewhere else specific -- not the context-reset pattern

    confidence = Confidence.HIGH
    severity = compute_severity(Stage.ARRIVE, BlastRadius.PAGE_CLASS, confidence)
    return Finding(
        id=_next_id(),
        title=f"{url} {reason}",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-003",
        scope=Scope(checked=1, affected=1, page_class="citable"),
        evidence=f"{url} -> {record.final_url} (HTTP {record.http_status})",
        artifacts=[Artifact(url=url, http_status=record.http_status, selector=f"redirect to {record.final_url}")],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "This exact URL is the one an assistant would cite and a visitor would click -- if it "
            "redirects away from the specific answer to a generic landing point, the citation "
            "resolves to nothing useful. The visitor arrives with the assistant's partial answer "
            "already in mind and has to re-find it from scratch, or gives up."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Stop redirecting this deep link away from its own content; if a locale gate is required, make it non-blocking (default to a sensible locale, offer to switch).",
            priority=severity,
            impact="high",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Serve the requested page directly", "If geolocation-based redirection is required, redirect within the same content, not to the homepage or a bare selector"],
            verification_step=f"curl -sI -A GPTBot {url} | grep -i location",
            rationale_ref="references/taxonomy.md#engage-003",
        ),
    )


# --- ENGAGE-004: entry interference -----------------------------------------

_INTERFERENCE_SIGNATURES = (
    "cookiebot", "onetrust", "cookieyes", "cc-window", "cookie-consent-banner",
    "gdpr-consent", "consent-modal", "age-gate", "age-verification", "cookielaw",
)


def detect_entry_interference(pages: dict[str, str]) -> Finding | None:
    """Static signature match for known consent/gate overlay libraries
    in the raw markup -- not a rendered-page check (no real visual
    blocking confirmation is possible without Playwright, and this
    stage doesn't require it as a dependency), so this flags presence
    in the markup, not confirmed proof the overlay blocks paint on
    every visit."""
    affected = []
    for url in sorted(pages):
        html_lower = pages[url].lower()
        hit = next((s for s in _INTERFERENCE_SIGNATURES if s in html_lower), None)
        if hit:
            affected.append((url, hit))
    if not affected:
        return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.ARRIVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(affected)} of {len(pages)} citable page(s) carry a consent/gate overlay that can block first meaningful paint",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-004",
        scope=Scope(checked=len(pages), affected=len(affected), page_class="citable"),
        evidence="; ".join(f"{u}: {sig!r} signature present" for u, sig in affected[:5]),
        artifacts=[Artifact(url=u) for u, _ in affected[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "An AI-referred visitor arrives already mid-task expecting to confirm a specific answer. "
            "A consent wall, age gate, or modal between them and the page's own content adds "
            "friction a search visitor (who browsed in cold) tolerates but an already-informed "
            "visitor doesn't -- and if it blocks first paint, it can hide the very answer the "
            "assistant cited."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Make consent/gate overlays non-blocking: render page content first, or default to a reasonable choice instead of gating first paint.",
            priority=severity,
            impact="medium",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Defer the overlay's own script so it doesn't block content rendering", "Default to the most restrictive consent choice rather than blocking until an explicit answer"],
            verification_step="Re-run the audit and confirm the page no longer matches a known overlay signature",
            rationale_ref="references/taxonomy.md#engage-004",
        ),
    )


# --- ENGAGE-005: missing next-step / CTA ------------------------------------

_CTA_PHRASES = (
    "contact us", "get started", "request a quote", "book a demo", "schedule a call",
    "sign up", "buy now", "add to cart", "get in touch", "start your trial",
    "request a demo", "get a quote", "talk to sales", "start free trial", "learn more",
)


def detect_missing_next_step(pages: dict[str, str]) -> Finding | None:
    """Citable pages with no recognizable call-to-action phrase in their
    main content at all. A fixed phrase list under-recognizes real CTAs
    (a plain "Contact" nav link, an icon-only button) -- flagged only
    when it's the majority pattern across the citable set, the same
    precision-first gating TRUST-008 uses for an equivalently noisy
    heuristic."""
    missing = []
    for url in sorted(pages):
        text = (trafilatura.extract(pages[url]) or "").lower()
        if not any(p in text for p in _CTA_PHRASES):
            missing.append(url)
    if not missing or len(missing) < max(1, len(pages) // 2):
        return None
    confidence = Confidence.LOW  # fixed-phrase CTA matching is a narrow heuristic, same honesty as TRUST-008
    severity = compute_severity(Stage.ARRIVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(missing)} of {len(pages)} citable pages have no recognizable next step for the visitor",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-005",
        scope=Scope(checked=len(pages), affected=len(missing), page_class="citable"),
        evidence="; ".join(missing[:5]),
        artifacts=[Artifact(url=u) for u in missing[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "A visitor who arrives mid-task with their question already answered needs the next "
            "action available on the landing page itself -- requiring a navigation hunt to find it "
            "loses exactly the visitor this stage is scoped to, since they have no accumulated site "
            "context (unlike a browsing visitor) to know where to look."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Add an explicit next-step action (contact, buy, sign up, demo) directly on the citable pages, not just in global nav.",
            priority=severity,
            impact="low",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Add a clear CTA near the end of the main content on each affected page"],
            verification_step="Re-run the audit and confirm fewer pages appear in this finding's scope",
            rationale_ref="references/taxonomy.md#engage-005",
        ),
    )


# --- ENGAGE-006: no AI-referral-capable instrumentation ---------------------

_ANALYTICS_SIGNATURES = (
    "googletagmanager.com", "google-analytics.com", "gtag(", "plausible.io",
    "cdn.segment.com", "js.hs-analytics.net", "connect.facebook.net", "posthog",
    "mixpanel", "fathom", "matomo", "clarity.ms",
)


def detect_no_ai_referral_instrumentation(pages: dict[str, str]) -> Finding | None:
    """Whole-corpus, not citable-only: analytics snippets are typically
    injected site-wide via a shared template, so this checks every
    sampled page. Deliberately conservative in what it claims -- static
    HTML can confirm "no analytics at all" but not whether an existing
    setup specifically segments chatgpt.com/perplexity.ai/claude.ai
    referrals, so it only ever fires on the stronger, cruder gap."""
    for url in sorted(pages):
        html_lower = pages[url].lower()
        if any(sig in html_lower for sig in _ANALYTICS_SIGNATURES):
            return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.ARRIVE, BlastRadius.NONE, confidence)
    return Finding(
        id=_next_id(),
        title=f"No analytics instrumentation detected across {len(pages)} sampled page(s) -- AI-referral traffic is invisible",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-006",
        scope=Scope(checked=len(pages), affected=len(pages)),
        evidence=f"No known analytics script signature found across {len(pages)} sampled pages' raw HTML",
        artifacts=[Artifact(url=u) for u in sorted(pages)[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "Most brands cannot see chatgpt.com/perplexity.ai/claude.ai referral traffic even when "
            "it's happening, because they have no analytics at all, let alone referrer segmentation "
            "for it -- so they can't tell this whole funnel is failing. This check confirms only the "
            "cruder gap (zero instrumentation of any kind); it cannot verify AI-referral-specific "
            "segmentation from static HTML alone."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Add basic web analytics, then a referrer segment or UTM convention for chatgpt.com / perplexity.ai / claude.ai traffic specifically.",
            priority=severity,
            impact="low",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=[
                "Add an analytics snippet (any provider) site-wide",
                "Create a referrer or landing-page segment for chatgpt.com, perplexity.ai, claude.ai, and copilot.microsoft.com",
            ],
            verification_step="Re-run the audit and confirm an analytics signature is now detected",
            rationale_ref="references/taxonomy.md#engage-006",
        ),
    )


# --- ENGAGE-007: scoped response latency ------------------------------------

_SLOW_RESPONSE_THRESHOLD_S = 3.0  # Google/SOASTA 2016: mobile abandonment rises sharply past ~3s


def detect_slow_citable_pages(records: dict[str, FetchRecord]) -> Finding | None:
    """Full-response latency (httpx's `Response.elapsed`) on the citable
    page set only, not the homepage -- the build plan's own cut list
    (Part 8) names LCP/INP first-to-cut and "keep TTFB -- cheap and
    adequate" as the fallback; this is that fallback. A proxy for real
    perceived load time, not the metric itself -- there's no rendering
    step in this stage to measure LCP/INP directly."""
    slow = [
        (u, r.elapsed_s)
        for u, r in sorted(records.items())
        if r.elapsed_s is not None and r.elapsed_s >= _SLOW_RESPONSE_THRESHOLD_S
    ]
    if not slow:
        return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.ARRIVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(slow)} of {len(records)} citable page(s) take over {_SLOW_RESPONSE_THRESHOLD_S:.0f}s to respond",
        severity=severity,
        stage=Stage.ARRIVE,
        taxonomy_id="ENGAGE-007",
        scope=Scope(checked=len(records), affected=len(slow), page_class="citable"),
        evidence="; ".join(f"{u}: {s:.2f}s" for u, s in slow[:5]),
        artifacts=[Artifact(url=u, http_status=records[u].http_status) for u, _ in slow[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "An AI-referred visitor arrives already mid-task and abandons a slow load more readily "
            "than a search visitor who deliberately chose to click a result -- per Google/SOASTA's "
            "2016 mobile benchmark, abandonment rises sharply past roughly three seconds. Scoped "
            "deliberately to the citable page set, since those are the pages an AI-referred visitor "
            "actually lands on, not the homepage."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Investigate and reduce server response time on the affected citable pages.",
            priority=severity,
            impact="medium",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.ARRIVE,
            implementation=["Profile server/CDN response time for the affected URLs", "Check for uncached or uncompressed responses on these specific routes"],
            verification_step=f"curl -w '%{{time_total}}\\n' -o /dev/null -s <url>  # should read below {_SLOW_RESPONSE_THRESHOLD_S:.0f}",
            rationale_ref="references/taxonomy.md#engage-007",
        ),
    )


# --- pipeline ----------------------------------------------------------------


def run_arrival_engagement_audit(
    citable_pages: dict[str, str],
    citable_records: dict[str, FetchRecord],
    all_pages: dict[str, str],
    matrix: list[AnswerabilityMatrixEntry],
    entity_name: str,
) -> list[Finding]:
    """citable_pages/citable_records: the pages that actually won a
    buyer-intent query in stage (4) (`citable=True` in the
    answerability_matrix) -- the pages an AI-referred visitor would
    actually land on, per this stage's own persona framing. all_pages:
    the full stage (1) survivor set, needed for ENGAGE-003's redirect-
    destination lookup and ENGAGE-006's site-wide instrumentation check.
    """
    findings: list[Finding] = []

    buried = detect_buried_answers(matrix)
    if buried is not None:
        findings.append(buried)

    for url in sorted(citable_pages):
        f = detect_orientation_gap(url, citable_pages[url], entity_name)
        if f is not None:
            findings.append(f)

    for url in sorted(citable_records):
        f = detect_context_reset(url, citable_records[url], all_pages)
        if f is not None:
            findings.append(f)

    for f in (
        detect_entry_interference(citable_pages),
        detect_missing_next_step(citable_pages),
        detect_no_ai_referral_instrumentation(all_pages),
        detect_slow_citable_pages(citable_records),
    ):
        if f is not None:
            findings.append(f)

    return findings
