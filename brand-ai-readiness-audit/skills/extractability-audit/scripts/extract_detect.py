"""Stage (3) EXTRACT detectors.

Each function takes the raw fetched HTML of a page (no network calls of
its own) and returns `Finding`s. Every detector traces back to a
taxonomy entry in `ai-visibility-orchestrator/references/taxonomy.md`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import trafilatura  # noqa: E402
from selectolax.parser import HTMLParser  # noqa: E402

from brand_audit.facts import extract_facts, normalize_currency_value  # noqa: E402
from brand_audit.jsonld import extract_json_ld, walk  # noqa: E402
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
_SCHEMA_SUBSET_PATH = Path(__file__).resolve().parent.parent / "assets" / "schema-subset.json"


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"F-EXTRACT-{_finding_counter:03d}"


def _unverified() -> Verification:
    return Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented")


def _load_schema_subset() -> dict:
    return json.loads(_SCHEMA_SUBSET_PATH.read_text(encoding="utf-8"))


def detect_schema_text_contradiction(url: str, html: str) -> list[Finding]:
    """EXTRACT-001: JSON-LD claims a price the visible text doesn't
    corroborate. Normalizes both sides to a float before comparing --
    without that, '199' (JSON-LD) vs '$199.00' (text) would look like a
    contradiction when they're the same fact differently formatted,
    which would fail this detector's own zero-false-positives bar on the
    very first well-formed page it saw."""
    findings: list[Finding] = []
    blocks = extract_json_ld(html)
    if not blocks:
        return []

    visible_text = trafilatura.extract(html) or ""
    visible_currency_values = {
        v for c in extract_facts(visible_text)["currency"] if (v := normalize_currency_value(c)) is not None
    }

    seen_prices: set[float] = set()
    for root in blocks:
        for node in walk(root):
            price = node.get("price")
            if price is None:
                continue
            normalized = normalize_currency_value(price)
            if normalized is None or normalized in seen_prices:
                continue
            seen_prices.add(normalized)
            if visible_currency_values and normalized not in visible_currency_values:
                confidence = Confidence.HIGH
                severity = compute_severity(Stage.EXTRACT, BlastRadius.PAGE_CLASS, confidence)
                findings.append(
                    Finding(
                        id=_next_id(),
                        title=f"{url}: JSON-LD price ({price}) doesn't match any visible-text price",
                        severity=severity,
                        stage=Stage.EXTRACT,
                        taxonomy_id="EXTRACT-001",
                        scope=Scope(checked=1, affected=1),
                        evidence=(
                            f"JSON-LD offers.price = {price!r} (normalized {normalized}); "
                            f"visible-text currency facts found: {sorted(visible_currency_values)}"
                        ),
                        artifacts=[
                            Artifact(
                                url=url,
                                html_only_extract=visible_text[:1000],
                                selector=f"application/ld+json .offers.price = {price!r}",
                            )
                        ],
                        confidence=confidence,
                        verification=_unverified(),
                        impact_mechanism=(
                            "Structured data is a shortcut extraction systems prefer over parsing "
                            "prose. When it disagrees with what a human reader would actually see on "
                            "the page, an assistant relying on the structured data cites the wrong "
                            "fact with high confidence -- a defect invisible to a manual read-through, "
                            "since a human never looks at the JSON-LD."
                        ),
                        affected_queries=[],
                        suggested_action=SuggestedAction(
                            summary="Regenerate structured data from the same source of truth as the visible price, or remove the stale property.",
                            priority=severity,
                            impact="high",
                            effort="medium",
                            confidence=confidence,
                            stage_unblocked=Stage.EXTRACT,
                            implementation=["Point the JSON-LD generation at the same price source as the rendered template"],
                            verification_step=f"curl -s {url} | grep -A2 '\"price\"' -- compare against the visible price",
                            rationale_ref="references/taxonomy.md#extract-001",
                        ),
                    )
                )
    return findings


def detect_missing_required_properties(url: str, html: str) -> list[Finding]:
    """EXTRACT-002: a JSON-LD block declares a type but omits properties
    that type needs to be useful to a consumer."""
    schema_subset = _load_schema_subset()
    findings: list[Finding] = []
    for block in extract_json_ld(html):
        types = block.get("@type")
        types = types if isinstance(types, list) else [types]
        for t in types:
            spec = schema_subset.get(t)
            if not spec:
                continue
            missing = [prop for prop in spec["required"] if prop not in block]
            if not missing:
                continue
            confidence = Confidence.HIGH
            severity = compute_severity(Stage.EXTRACT, BlastRadius.DEGRADES, confidence)
            findings.append(
                Finding(
                    id=_next_id(),
                    title=f"{url}: {t} structured data is missing required propert{'y' if len(missing) == 1 else 'ies'} {', '.join(missing)}",
                    severity=severity,
                    stage=Stage.EXTRACT,
                    taxonomy_id="EXTRACT-002",
                    scope=Scope(checked=1, affected=1),
                    evidence=f"@type={t!r}, missing: {missing}, present keys: {sorted(block.keys())}",
                    artifacts=[Artifact(url=url, selector=f"application/ld+json @type={t!r}")],
                    confidence=confidence,
                    verification=_unverified(),
                    impact_mechanism=(
                        f"A structured-data consumer expecting the schema.org {t} contract may "
                        "silently skip or down-rank this block -- the page ships a JSON-LD tag, but "
                        "the facts inside it don't reliably reach whatever's parsing it."
                    ),
                    affected_queries=[],
                    suggested_action=SuggestedAction(
                        summary=f"Add the missing required propert{'y' if len(missing) == 1 else 'ies'} to the {t} structured data.",
                        priority=severity,
                        impact="medium",
                        effort="low",
                        confidence=confidence,
                        stage_unblocked=Stage.EXTRACT,
                        implementation=[f"Add {prop!r} to the {t} JSON-LD block" for prop in missing],
                        verification_step=f"curl -s {url} | python3 -c \"import json,sys,re; print('ok')\"",
                        rationale_ref="references/taxonomy.md#extract-002",
                    ),
                )
            )
    return findings


def _main_content_html(html: str) -> str:
    """trafilatura's boilerplate-stripped extraction, HTML output (tags
    preserved, not the plain-text form EXTRACT-001 uses). `include_images`
    defaults to False in trafilatura and silently drops every <img> tag
    if left unset -- easy to get burned by since the function still
    returns a plausible-looking result either way, just missing what
    detect_facts_in_images actually needs."""
    return trafilatura.extract(html, output_format="html", include_formatting=True, include_images=True) or ""


def detect_heading_hierarchy_issues(url: str, html: str) -> list[Finding]:
    """EXTRACT-003: zero/multiple H1s, or a heading-level skip -- scoped
    to trafilatura's main-content extraction, not the raw full-page DOM.

    Confirmed against real sites, not just synthetic fixtures: scanning
    the full page flagged docs.python.org's sidebar navigation widgets
    (a "Download" h3 inside <nav class="menu"> / <div class="sphinxsidebar">,
    nothing to do with the article's own outline) as a heading-level skip
    on every single page checked -- a false positive from navigational
    chrome, not the document's actual structure. The taxonomy entry's own
    mechanism is specifically about the outline a chunking/retrieval
    pipeline would infer for the *content*, which is what trafilatura's
    boilerplate-stripped extraction targets in the first place -- the
    same reasoning EXTRACT-001 already applies to its visible-text side.
    """
    tree = HTMLParser(_main_content_html(html))
    # tree.iter(), not tree.css("h1, h2, ..."): a grouped CSS selector in
    # selectolax returns all matches of the first selector in the group,
    # then the second, and so on -- concatenated per-tag, not merged
    # into document order (confirmed directly; see
    # src/brand_audit/chunk.py's _extract_segments docstring, which hit
    # the same bug harder and traced it). For level-skip detection,
    # order is the entire point -- this was a latent correctness bug
    # that happened not to produce a wrong verdict on anything tested so
    # far only because every test/real-page case checked against had
    # headings whose tag-grouped order was indistinguishable from their
    # true document order.
    ordered = [
        (int(node.tag[1]), (node.text() or "").strip()[:60])
        for node in (tree.body.iter() if tree.body else [])
        if node.tag in ("h1", "h2", "h3", "h4", "h5", "h6")
    ]

    h1_count = sum(1 for level, _ in ordered if level == 1)
    issues = []
    if h1_count == 0 and ordered:
        issues.append("no <h1> found")
    elif h1_count > 1:
        issues.append(f"{h1_count} <h1> tags found (should be exactly 1)")

    running_max = 0
    for level, text in ordered:
        if running_max and level > running_max + 1:
            issues.append(f"heading level skip: jumped to h{level} after h{running_max} (text: {text!r})")
        running_max = max(running_max, level)

    if not issues:
        return []

    confidence = Confidence.HIGH
    severity = compute_severity(Stage.EXTRACT, BlastRadius.NONE, confidence)
    return [
        Finding(
            id=_next_id(),
            title=f"{url}: heading hierarchy issue(s) -- {'; '.join(issues)}",
            severity=severity,
            stage=Stage.EXTRACT,
            taxonomy_id="EXTRACT-003",
            scope=Scope(checked=1, affected=1),
            evidence=f"heading sequence: {[level for level, _ in ordered]}; issues: {issues}",
            artifacts=[Artifact(url=url, selector="h1, h2, h3, h4, h5, h6")],
            confidence=confidence,
            verification=_unverified(),
            impact_mechanism=(
                "Extraction/chunking pipelines commonly use heading structure to infer a "
                "document's outline and segment content. An ambiguous or broken outline risks "
                "content getting attributed to the wrong section, or chunk boundaries landing in "
                "the wrong place -- invisible to a human skimming the styled page, very visible to "
                "anything parsing the DOM structure."
            ),
            affected_queries=[],
            suggested_action=SuggestedAction(
                summary="Use exactly one <h1> per page and avoid heading-level skips.",
                priority=severity,
                impact="low",
                effort="low",
                confidence=confidence,
                stage_unblocked=Stage.EXTRACT,
                implementation=["Restructure headings to a single h1 with no level skips"],
                verification_step=f"curl -s {url} | grep -oE '<h[1-6]' -- should start with h1 and never skip a level",
                rationale_ref="references/taxonomy.md#extract-003",
            ),
        )
    ]


_FACT_BEARING_IMAGE_RE_KEYWORDS = ("price", "chart", "spec", "table", "pricing")


def detect_facts_in_images(url: str, html: str) -> list[Finding]:
    """EXTRACT-004: alt-less images whose filename suggests fact-bearing
    content (spec table, price chart). Deliberately narrow -- see the
    taxonomy entry for why a broader "any alt-less image" check would be
    generic-checklist noise, not a real signal. Scoped to main content
    for the same reason as EXTRACT-003 -- a decorative icon living in a
    persistent sidebar/nav isn't part of what a reader or a retrieval
    pipeline would treat as this page's actual content."""
    tree = HTMLParser(_main_content_html(html))
    findings = []
    for node in tree.css("img"):
        alt = (node.attributes.get("alt") or "").strip()
        if alt:
            continue
        src = (node.attributes.get("src") or "").lower()
        if not any(kw in src for kw in _FACT_BEARING_IMAGE_RE_KEYWORDS):
            continue
        confidence = Confidence.LOW  # filename match is a weak, indirect signal -- see taxonomy.md#extract-004
        severity = compute_severity(Stage.EXTRACT, BlastRadius.NONE, confidence)
        findings.append(
            Finding(
                id=_next_id(),
                title=f"{url}: image with no alt text and a fact-suggesting filename ({node.attributes.get('src')})",
                severity=severity,
                stage=Stage.EXTRACT,
                taxonomy_id="EXTRACT-004",
                scope=Scope(checked=1, affected=1),
                evidence=f"<img src={node.attributes.get('src')!r} alt=''> (or alt missing)",
                artifacts=[Artifact(url=url, selector=f"img[src*='{node.attributes.get('src')}']")],
                confidence=confidence,
                verification=_unverified(),
                impact_mechanism=(
                    "Content delivered as an image with no alt text is invisible to any "
                    "text-based extraction pipeline -- present in the DOM (so a naive check would "
                    "say the page 'has' this content) but not extractable as text."
                ),
                affected_queries=[],
                suggested_action=SuggestedAction(
                    summary="Add descriptive alt text carrying the actual fact, or deliver it as real text/structured data.",
                    priority=severity,
                    impact="low",
                    effort="low",
                    confidence=confidence,
                    stage_unblocked=Stage.EXTRACT,
                    implementation=["Add alt text describing the specific fact the image conveys"],
                    verification_step=f"curl -s {url} | grep -o '<img[^>]*{node.attributes.get('src', '')}[^>]*>'",
                    rationale_ref="references/taxonomy.md#extract-004",
                ),
            )
        )
    return findings
