"""Stage (2) RENDER: the dual-fetch differential.

Fetch every page twice -- plain HTTP GET (already done by stage (1),
reused here) vs. headless-rendered -- and diff at the fact level, not
the character level. This is the highest-ROI mechanism in the audit;
see RENDER-001 in ai-visibility-orchestrator/references/taxonomy.md for
two field-verified examples (docsify.js.org, app.uniswap.org) including
byte counts and the citation consequence.

Optional dependency: `playwright`. If it's not importable, the caller
should skip this stage entirely and suppress RENDER findings -- never
guess. See docs/build-plan.md Part 4 / Part 8.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import trafilatura  # noqa: E402

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
    return f"F-RENDER-{_finding_counter:03d}"


def _unverified() -> Verification:
    return Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented")


# --- fact extraction -------------------------------------------------
#
# Deliberately regex-based, not a real NER model: a full entity extractor
# would itself need model weights, which the project's own constraints
# rule out (see docs/build-plan.md Part 4). This covers 4 of the 5 fact
# types the build plan names (currency, numeric, date, contact) --
# "entity" extraction is left as documented future work rather than
# faked with a noisy heuristic.

_CURRENCY_RE = re.compile(r"[$€£₹]\s?\d[\d,]*(?:\.\d+)?")
_NUMERIC_RE = re.compile(r"\b\d{2,}(?:\.\d+)?%?\b")
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b"
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")

# Noise: hex-looking tokens (hashes, CSRF tokens, session ids) that a
# naive numeric/date regex would otherwise pick up as a "fact".
_HEX_NOISE_RE = re.compile(r"^[a-f0-9]{12,}$", re.IGNORECASE)


def extract_facts(text: str, *, today_iso: str | None = None) -> dict[str, set[str]]:
    facts = {
        "currency": set(_CURRENCY_RE.findall(text)),
        "numeric": {n for n in _NUMERIC_RE.findall(text) if not _HEX_NOISE_RE.match(n)},
        "date": set(_DATE_RE.findall(text)),
        "contact": set(_EMAIL_RE.findall(text)) | set(_PHONE_RE.findall(text)),
    }
    if today_iso:
        facts["date"].discard(today_iso)  # suppress "generated at" timestamps, not content dates
    # numeric facts that are substrings of an already-captured currency
    # fact aren't a separate finding (e.g. "$49" also matching \d{2,})
    currency_digits = {re.sub(r"[^\d.]", "", c) for c in facts["currency"]}
    facts["numeric"] = {n for n in facts["numeric"] if n not in currency_digits}
    return facts


@dataclass
class RenderComparison:
    url: str
    raw_text: str
    rendered_text: str
    raw_facts: dict[str, set[str]]
    rendered_facts: dict[str, set[str]]


def compare(url: str, raw_html: str, rendered_html: str, *, today_iso: str | None = None) -> RenderComparison:
    raw_text = trafilatura.extract(raw_html) or ""
    rendered_text = trafilatura.extract(rendered_html) or ""
    return RenderComparison(
        url=url,
        raw_text=raw_text,
        rendered_text=rendered_text,
        raw_facts=extract_facts(raw_text, today_iso=today_iso),
        rendered_facts=extract_facts(rendered_text, today_iso=today_iso),
    )


# Below this many stripped chars, treat the raw extraction as
# "effectively empty" -- matches the field-verified pattern exactly
# (docsify.js.org: 7 chars; app.uniswap.org: 64 chars).
EMPTY_SHELL_THRESHOLD_CHARS = 80
SUBSTANTIAL_CONTENT_THRESHOLD_CHARS = 150


def detect_render_gap(comparison: RenderComparison) -> list[Finding]:
    raw_len = len(comparison.raw_text.strip())
    rendered_len = len(comparison.rendered_text.strip())

    findings: list[Finding] = []

    # --- Primary signal: total empty-shell pattern (RENDER-001 core case) ---
    if raw_len < EMPTY_SHELL_THRESHOLD_CHARS and rendered_len >= SUBSTANTIAL_CONTENT_THRESHOLD_CHARS:
        confidence = Confidence.HIGH
        severity = compute_severity(Stage.RENDER, BlastRadius.SITE_WIDE, confidence)
        findings.append(
            Finding(
                id=_next_id(),
                title=f"{comparison.url} ships an empty content shell -- all text requires JavaScript",
                severity=severity,
                stage=Stage.RENDER,
                taxonomy_id="RENDER-001",
                scope=Scope(checked=1, affected=1),
                evidence=(
                    f"Raw HTTP fetch: {raw_len} chars of extracted text "
                    f"({comparison.raw_text.strip()[:100]!r}). "
                    f"Headless-rendered fetch: {rendered_len} chars "
                    f"({comparison.rendered_text.strip()[:150]!r})."
                ),
                artifacts=[
                    Artifact(
                        url=comparison.url,
                        html_only_extract=comparison.raw_text[:2000],
                        rendered_extract=comparison.rendered_text[:2000],
                    )
                ],
                confidence=confidence,
                verification=_unverified(),
                impact_mechanism=(
                    "A crawler that doesn't execute JavaScript -- which major documented AI "
                    "crawlers are inconsistent about -- receives a page with nothing to extract, "
                    "index, or cite, regardless of how good the eventually-rendered content is."
                ),
                affected_queries=[],
                suggested_action=SuggestedAction(
                    summary="Server-render or statically pre-render the primary content.",
                    priority=severity,
                    impact="high",
                    effort="high",
                    confidence=confidence,
                    stage_unblocked=Stage.RENDER,
                    implementation=[
                        "Add an SSR/SSG build step for the primary content surface",
                        "Or serve a prerendered snapshot to non-JS user agents",
                    ],
                    verification_step=f"curl -s -A GPTBot {comparison.url} | wc -c -- should return substantial content, not an empty shell",
                    rationale_ref="references/taxonomy.md#render-001",
                ),
            )
        )
        return findings  # the whole-page case subsumes any per-fact diff below

    # --- Secondary signal: raw page is substantial, but specific facts
    # are JS-only within an otherwise-rendered page ---
    for category in ("currency", "date", "contact"):
        missing = comparison.rendered_facts[category] - comparison.raw_facts[category]
        if not missing:
            continue
        confidence = Confidence.MEDIUM
        severity = compute_severity(Stage.RENDER, BlastRadius.DEGRADES, confidence)
        findings.append(
            Finding(
                id=_next_id(),
                title=f"{comparison.url}: {category} fact(s) only present after JavaScript execution",
                severity=severity,
                stage=Stage.RENDER,
                taxonomy_id="RENDER-001",
                scope=Scope(checked=1, affected=1),
                evidence=f"{category} facts in rendered but not raw HTML: {sorted(missing)[:10]}",
                artifacts=[
                    Artifact(
                        url=comparison.url,
                        html_only_extract=comparison.raw_text[:1000],
                        rendered_extract=comparison.rendered_text[:1000],
                    )
                ],
                confidence=confidence,
                verification=_unverified(),
                impact_mechanism=(
                    f"This page is otherwise reachable in the raw HTTP response, but {category} "
                    "facts specifically are injected by JavaScript -- a query relying on this fact "
                    "retrieves the page but finds the fact ungrounded."
                ),
                affected_queries=[],
                suggested_action=SuggestedAction(
                    summary=f"Server-render the {category} fact(s) rather than injecting them client-side.",
                    priority=severity,
                    impact="medium",
                    effort="medium",
                    confidence=confidence,
                    stage_unblocked=Stage.RENDER,
                    implementation=[f"Move the {category}-bearing widget/component to server-rendered output"],
                    verification_step=f"curl -s -A GPTBot {comparison.url} | grep -o '<fact pattern>'",
                    rationale_ref="references/taxonomy.md#render-001",
                ),
            )
        )
    return findings


async def render_fetch(urls: list[str], *, timeout_ms: int = 15000) -> dict[str, str | None]:
    """Render each URL with headless Chromium, return {url: rendered_html}.
    A value of `None` means the render itself failed or timed out --
    callers must treat that as "unknown", not "confirmed empty": a page
    that never reaches networkidle (persistent websockets, analytics
    polling -- real sites do this, e.g. curve.finance during Day 1 field
    research) would otherwise silently collapse to an empty string
    indistinguishable from a genuine JS-only-empty-shell case, which
    would make a real RENDER-001 case go undetected rather than flagged
    -- exactly backwards from what a detector should fail toward.

    Raises ImportError if playwright isn't installed -- caller decides
    whether to skip the stage entirely (it should)."""
    from playwright.async_api import async_playwright  # deferred: optional dep

    results: dict[str, str | None] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for url in urls:
                page = await browser.new_page()
                try:
                    # "load" rather than "networkidle": networkidle never
                    # fires on pages with persistent connections (some
                    # analytics/websocket setups keep the network "busy"
                    # forever), which would otherwise burn the full
                    # timeout on every such page. The short extra wait
                    # covers synchronous on-load JS (our own js-only-price
                    # fixture included) without networkidle's fragility.
                    await page.goto(url, timeout=timeout_ms, wait_until="load")
                    await page.wait_for_timeout(500)
                    results[url] = await page.content()
                except Exception as exc:  # noqa: BLE001 -- a single page's render failure shouldn't abort the run
                    results[url] = None
                    print(f"warning: render failed for {url}: {exc}", file=sys.stderr)
                finally:
                    await page.close()
        finally:
            await browser.close()
    return results
