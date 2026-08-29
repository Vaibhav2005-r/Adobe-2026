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

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import trafilatura  # noqa: E402

from brand_audit.facts import extract_facts  # noqa: E402
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


# Fact extraction (currency/numeric/date/contact) lives in
# brand_audit.facts, shared with extractability-audit's schema-vs-text
# contradiction detector. Deliberately regex-based, not a real NER
# model: a full entity extractor would itself need model weights, which
# the project's own constraints rule out (see docs/build-plan.md Part
# 4). This covers 4 of the 5 fact types the build plan names -- "entity"
# extraction is left as documented future work rather than faked with a
# noisy heuristic.


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

# Matches REACH-001's own precedent (Day 3) for the same underlying
# question -- "is this pattern really site-wide, or just some pages?"
# -- reusing the numeric threshold rather than inventing a second one.
_SITE_WIDE_EMPTY_SHELL_RATIO = 0.9


def is_empty_shell(comparison: RenderComparison) -> bool:
    raw_len = len(comparison.raw_text.strip())
    rendered_len = len(comparison.rendered_text.strip())
    return raw_len < EMPTY_SHELL_THRESHOLD_CHARS and rendered_len >= SUBSTANTIAL_CONTENT_THRESHOLD_CHARS


def detect_empty_shell_pages(comparisons: list[RenderComparison]) -> Finding | None:
    """RENDER-001 primary signal: pages that ship a near-empty raw HTTP
    response but substantial rendered content. One aggregate finding
    covering every affected page (matching the CHUNK-001/TRUST-00x
    convention for a corpus-wide pattern), not one per page.

    Blast radius is only SITE_WIDE -- and severity therefore only
    CRITICAL -- when the pattern spans >=90% of the *actual render
    sample checked*, not merely "this one page is empty." A single
    empty page out of a much larger unrendered corpus cannot support a
    "your whole site is JS-only" claim; every page below the threshold
    is scoped to PAGE_CLASS instead. This was a real bug through Day 7:
    every empty-shell page unconditionally claimed SITE_WIDE with
    `Scope(checked=1, ...)`, which `finding-verification`'s sample-
    adequacy check (Day 8) then correctly started catching and
    demoting -- fixed at the source rather than left for verification
    to paper over every single time, since the miscalibration was real
    independent of whether verification existed to catch it."""
    if not comparisons:
        return None
    empty = [c for c in comparisons if is_empty_shell(c)]
    if not empty:
        return None

    confidence = Confidence.HIGH
    site_wide = (len(empty) / len(comparisons)) >= _SITE_WIDE_EMPTY_SHELL_RATIO
    severity = compute_severity(Stage.RENDER, BlastRadius.SITE_WIDE if site_wide else BlastRadius.PAGE_CLASS, confidence)
    example = empty[0]
    title = (
        f"All {len(comparisons)} rendered page(s) ship an empty content shell -- all text requires JavaScript"
        if site_wide
        else f"{len(empty)} of {len(comparisons)} rendered pages ship an empty content shell -- all text requires JavaScript"
    )
    return Finding(
        id=_next_id(),
        title=title,
        severity=severity,
        stage=Stage.RENDER,
        taxonomy_id="RENDER-001",
        scope=Scope(checked=len(comparisons), affected=len(empty)),
        evidence=(
            f"Raw HTTP fetch of {example.url}: {len(example.raw_text.strip())} chars of extracted text "
            f"({example.raw_text.strip()[:100]!r}). Headless-rendered fetch: "
            f"{len(example.rendered_text.strip())} chars ({example.rendered_text.strip()[:150]!r}). "
            f"Reproduced on {len(empty)}/{len(comparisons)} sampled pages."
        ),
        # Every affected URL, not just a few examples (unlike most
        # aggregate findings' artifacts elsewhere in this codebase):
        # retrieval-simulation's own composition-contract gating
        # (run_retrieve_stage) excludes exactly the URLs listed here
        # from the AI-reachable corpus it indexes, so a truncated list
        # would silently let some genuinely-empty pages back in.
        artifacts=[
            Artifact(url=c.url, html_only_extract=c.raw_text[:2000], rendered_extract=c.rendered_text[:2000])
            for c in empty
        ],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "The major AI crawlers fetch raw HTML and do not execute JavaScript: Vercel's "
            "crawler study found no evidence of JS execution across 500M+ GPTBot fetches, and "
            "measured GPTBot downloading JS files in ~11.5% of requests and ClaudeBot in ~23.8% "
            "without ever running them. Such a crawler receives a page with nothing to extract, "
            "index, or cite, regardless of how good the eventually-rendered content is. Two "
            "documented exceptions exist and are deliberately not claimed here: Applebot uses a "
            "browser-based crawler that does render, and Gemini rides Googlebot's rendering "
            "infrastructure -- so this finding is scoped to the fetch-only majority "
            "(GPTBot, ClaudeBot, PerplexityBot, CCBot, Bytespider and the OpenAI/Anthropic "
            "search and user agents), not to every AI crawler that exists."
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
            verification_step=f"curl -s -A GPTBot {example.url} | wc -c -- should return substantial content, not an empty shell",
            rationale_ref="references/taxonomy.md#render-001",
        ),
    )


def detect_partial_render_gap(comparison: RenderComparison) -> list[Finding]:
    """RENDER-001 secondary signal: the raw page is substantial, but
    specific fact categories are JS-only within it. Caller skips this
    for any page already covered by `detect_empty_shell_pages` -- the
    whole-page-empty case subsumes any per-fact diff, same as the
    original single-function version did with its early `return`."""
    findings: list[Finding] = []
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
