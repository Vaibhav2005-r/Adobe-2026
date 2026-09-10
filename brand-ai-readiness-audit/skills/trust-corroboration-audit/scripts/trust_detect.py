"""Stage (5) CITE detectors (trust-corroboration-audit).

Each function takes already-fetched HTML (no network calls of its own)
and returns `Finding`s. Deliberately does NOT do a live name-collision
web search: the project's build plan (Part 8) cut list names this the
first thing to cut if behind schedule ("Name-collision web probe (keep
on-site entity anchoring)"), and a live search is also a real tension
with the project's determinism/portability constraints -- results
change over time and need network access a judge's bare machine can't
be assumed to have. Kept: on-site entity anchoring (TRUST-005), exactly
as the cut list says to.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.crawl import find_homepage_url  # noqa: E402
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
from brand_audit.retrieval import tokenize  # noqa: E402
from brand_audit.severity import BlastRadius, compute_severity  # noqa: E402

_finding_counter = 0


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"F-TRUST-{_finding_counter:03d}"


def _unverified() -> Verification:
    # Detector-local placeholder. `finding-verification` overwrites this
    # for every finding it processes; it survives into the report only
    # when that stage is skipped for budget, which the report records as
    # a degradation. Says "did not run", not "does not exist" -- the
    # falsification pass has been wired into run_audit.py since Day 8,
    # and the older wording told a reader of a degraded report that the
    # feature was missing.
    return Verification(reproduced=False, method="single-pass detection; falsification pass did not run")


def _extract_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None


def _extract_meta_content(html: str, attr: str, value: str) -> str | None:
    """`<meta name="description" content="...">` or
    `<meta property="og:description" content="...">` -- attribute order
    isn't assumed (content= can come before or after name=/property=),
    unlike a naive single-pattern regex would assume."""
    pattern = (
        rf'<meta[^>]+{attr}=["\']?{re.escape(value)}["\']?[^>]*content=["\']([^"\']*)["\']'
        rf'|<meta[^>]+content=["\']([^"\']*)["\'][^>]*{attr}=["\']?{re.escape(value)}["\']?'
    )
    m = re.search(pattern, html, re.IGNORECASE)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip() or None


# --- TRUST-005: entity anchoring gap ----------------------------------------


def _named_org_nodes(html: str):
    """Every named Organization/LocalBusiness node in a page's JSON-LD,
    paired with whether it carries a non-empty `sameAs`."""
    for block in extract_json_ld(html):
        for node in walk(block):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(t in ("Organization", "LocalBusiness") for t in types):
                continue
            if not node.get("name"):
                continue
            same_as = node.get("sameAs")
            yield node, (len(same_as) > 0 if isinstance(same_as, list) else bool(same_as))


def detect_missing_entity_anchoring(pages: dict[str, str]) -> Finding | None:
    """A named Organization/LocalBusiness exists in the site's own
    JSON-LD, but declares no `sameAs` links to authoritative external
    profiles (social, Wikidata, Crunchbase, ...) -- there's no
    machine-verifiable anchor tying this page's brand name to a
    canonical identity elsewhere on the web.

    Scans the whole corpus before deciding, in both directions. The
    original implementation returned on the *first* unanchored entity it
    saw, which contradicted its own "whole-site check" framing: a site
    whose homepage carries a fully-anchored Organization block and whose
    product template carries a thinner one would be reported as
    unanchored purely because of sorted-URL ordering. One anchored entity
    anywhere in the corpus means the brand is anchored, so that case now
    wins wherever it appears.

    Scope counts pages, not the first hit -- reporting checked=1 out of a
    40-page crawl both understated the finding and fed a wrong denominator
    to the sample-adequacy check in `finding-verification`."""
    unanchored: list[tuple[str, str]] = []  # (url, entity name), at most one entry per page
    for url in sorted(pages):
        for node, has_same_as in _named_org_nodes(pages[url]):
            if has_same_as:
                return None  # anchored somewhere in the corpus -- the brand is anchored
            if not any(u == url for u, _ in unanchored):
                unanchored.append((url, node["name"]))

    if not unanchored:
        return None

    url, name = unanchored[0]
    confidence = Confidence.HIGH
    severity = compute_severity(Stage.CITE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{name} has no sameAs links to an authoritative external profile",
        severity=severity,
        stage=Stage.CITE,
        taxonomy_id="TRUST-005",
        scope=Scope(checked=len(pages), affected=len(unanchored)),
        evidence=(
            f"{len(unanchored)} of {len(pages)} sampled page(s) carry a named Organization "
            f"JSON-LD block with no (or empty) 'sameAs', and no page in the corpus carries "
            f"an anchored one; first: {url}"
        ),
        artifacts=[
            Artifact(url=u, selector="application/ld+json Organization.sameAs")
            for u, _ in unanchored[:3]
        ],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "Without a sameAs anchor, a system trying to verify or disambiguate this "
            "entity (e.g. against a same-named different company) has no machine-"
            "readable signal pointing to an authoritative external profile -- the "
            "brand's identity rests entirely on unverified self-assertion."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Add sameAs links to the Organization JSON-LD, pointing to owned authoritative profiles (Wikidata, LinkedIn, Crunchbase, verified social accounts).",
            priority=severity,
            impact="medium",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.CITE,
            implementation=['Add a "sameAs": [...] array to the Organization JSON-LD block'],
            verification_step=f"curl -s {url} | grep -A3 sameAs",
            rationale_ref="references/taxonomy.md#trust-005",
        ),
    )

# --- TRUST-006: freshness / staleness ---------------------------------------

_DATE_PROPERTIES = ("dateModified", "datePublished")
_STALE_THRESHOLD_DAYS = 365


def _parse_iso_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _stalest_date_on_page(html: str, reference_date: date) -> tuple[str, str, int] | None:
    """The single oldest over-threshold (prop, raw, age_days) on one page,
    or None. Oldest rather than first-found so the evidence quotes the
    worst case on the page, and so the result doesn't depend on JSON-LD
    block ordering."""
    oldest: tuple[str, str, int] | None = None
    for block in extract_json_ld(html):
        for node in walk(block):
            for prop in _DATE_PROPERTIES:
                raw = node.get(prop)
                if not raw or not isinstance(raw, str):
                    continue
                parsed = _parse_iso_date(raw)
                if parsed is None:
                    continue
                age_days = (reference_date - parsed).days
                if age_days > _STALE_THRESHOLD_DAYS and (oldest is None or age_days > oldest[2]):
                    oldest = (prop, raw, age_days)
    return oldest


def detect_staleness(pages: dict[str, str], *, reference_date: date | None = None) -> Finding | None:
    """A page's JSON-LD claims a dateModified/datePublished well over a
    year old. Not proof the content is wrong -- proof it hasn't been
    reviewed recently, which matters for freshness-sensitive claims
    (pricing, availability) an assistant might otherwise treat as
    current just because the page loaded successfully today.

    Scans the whole corpus and reports once, aggregated. The original
    implementation returned from inside the page loop on the first stale
    date it saw, which produced a `Scope(checked=1, affected=1)` finding
    no matter how much of the site was stale -- a 40-page archive and a
    single forgotten page were indistinguishable in the report. Worse,
    the understated scope fed straight into `finding-verification`'s
    sample-adequacy check and into `severity = f(stage, blast_radius,
    confidence)`, so a genuinely site-wide freshness problem could not
    reach the blast radius it deserved."""
    reference_date = reference_date or date.today()
    stale: list[tuple[str, str, str, int]] = []  # (url, prop, raw, age_days)
    for url in sorted(pages):
        found = _stalest_date_on_page(pages[url], reference_date)
        if found is not None:
            stale.append((url, *found))
    if not stale:
        return None

    # Widest blast radius the evidence supports: a majority-stale corpus is
    # a page-class problem, one stale page among many is a local one.
    by_age = sorted(stale, key=lambda s: (-s[3], s[0]))
    worst_url, worst_prop, worst_raw, worst_age = by_age[0]
    blast = BlastRadius.PAGE_CLASS if len(stale) > len(pages) / 2 else BlastRadius.DEGRADES
    confidence = Confidence.MEDIUM  # staleness is a risk signal, not proof of a wrong fact
    severity = compute_severity(Stage.CITE, blast, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(stale)} of {len(pages)} page(s) carry a last-updated date over a year old",
        severity=severity,
        stage=Stage.CITE,
        taxonomy_id="TRUST-006",
        scope=Scope(checked=len(pages), affected=len(stale)),
        evidence="; ".join(
            f"{u}: {prop}={raw!r} ({age} days before {reference_date.isoformat()})"
            for u, prop, raw, age in by_age[:5]
        ),
        artifacts=[
            Artifact(url=u, selector=f"application/ld+json .{prop}") for u, prop, _, _ in by_age[:3]
        ],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            f"A {worst_prop} this old signals the page hasn't been reviewed in over a "
            "year -- an assistant citing freshness-sensitive facts (pricing, "
            "availability, current offerings) from this page has no signal that "
            "they might be stale."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary=(
                f"Review these {len(stale)} page(s) and update their last-modified dates to "
                "reflect the actual last-reviewed date."
            ),
            priority=severity,
            impact="low",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.CITE,
            implementation=[
                f"Update {worst_prop} in JSON-LD after reviewing the page content",
                f"Start with the oldest: {worst_url} ({worst_raw})",
            ],
            verification_step=f"curl -s {worst_url} | grep {worst_prop}",
            rationale_ref="references/taxonomy.md#trust-006",
        ),
    )


# --- TRUST-007: description drift -------------------------------------------

_DRIFT_OVERLAP_THRESHOLD = 0.15


def _token_overlap(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 1.0  # nothing to compare -- not a drift signal either way
    return len(ta & tb) / len(ta | tb)


def detect_description_drift(pages: dict[str, str], homepage_hint: str | None = None) -> Finding | None:
    """The brand's self-description should read as the same story
    everywhere it's expressed. Compares meta description, JSON-LD
    description, and OpenGraph description on the homepage via token
    (Jaccard) overlap -- not exact-match, since some wording variation
    is normal, but very low overlap between two fields that both exist
    means a system reading only one of them can't converge on a
    canonical framing of the brand.

    `homepage_hint` is matched by normalized root path via
    `find_homepage_url`, not exact string equality -- see that
    function's docstring."""
    homepage_url = find_homepage_url(pages, homepage_hint)
    if homepage_url is None:
        return None
    html = pages[homepage_url]

    meta_desc = _extract_meta_content(html, "name", "description")
    og_desc = _extract_meta_content(html, "property", "og:description")
    jsonld_desc = None
    for block in extract_json_ld(html):
        for node in walk(block):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("Organization", "LocalBusiness", "WebSite") for t in types) and node.get("description"):
                jsonld_desc = str(node["description"])
                break
        if jsonld_desc:
            break

    fields = {"meta description": meta_desc, "JSON-LD description": jsonld_desc, "og:description": og_desc}
    present = {k: v for k, v in fields.items() if v}
    if len(present) < 2:
        return None  # need at least 2 to compare

    names = list(present)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, b_name = names[i], names[j]
            overlap = _token_overlap(present[a_name], present[b_name])
            if overlap < _DRIFT_OVERLAP_THRESHOLD:
                confidence = Confidence.MEDIUM  # token overlap is a proxy for "same story," not a certainty
                severity = compute_severity(Stage.CITE, BlastRadius.DEGRADES, confidence)
                return Finding(
                    id=_next_id(),
                    title=f"{a_name} and {b_name} describe the brand very differently ({overlap:.0%} word overlap)",
                    severity=severity,
                    stage=Stage.CITE,
                    taxonomy_id="TRUST-007",
                    scope=Scope(checked=len(present), affected=2),
                    evidence=f"{a_name}: {present[a_name]!r} vs. {b_name}: {present[b_name]!r}",
                    artifacts=[Artifact(url=homepage_url, selector=f"{a_name} vs {b_name}")],
                    confidence=confidence,
                    verification=_unverified(),
                    impact_mechanism=(
                        "A system that reads only one of these fields (search snippets typically use "
                        "meta description; social shares use og:description; structured-data "
                        "consumers use the JSON-LD description) forms a different picture of the "
                        "brand depending on which one it happened to read -- there's no single "
                        "canonical framing for it to converge on."
                    ),
                    affected_queries=[],
                    suggested_action=SuggestedAction(
                        summary="Align the brand's one-line self-description across meta description, JSON-LD, and OpenGraph tags.",
                        priority=severity,
                        impact="low",
                        effort="low",
                        confidence=confidence,
                        stage_unblocked=Stage.CITE,
                        implementation=["Use the same one-line description (or a close paraphrase) in all three fields"],
                        verification_step=f"curl -s {homepage_url} | grep -iE 'description|og:description'",
                        rationale_ref="references/taxonomy.md#trust-007",
                    ),
                )
    return None


# --- TRUST-008: low attribution / statistic density -------------------------

_CITATION_PHRASES = (
    "according to", "study shows", "study found", "research shows", "source:",
    "cited by", "as reported by", "survey found", "data shows",
)


def _has_citation_signal(html: str) -> bool:
    text_lower = html.lower()
    return any(p in text_lower for p in _CITATION_PHRASES)


def detect_low_attribution_density(pages: dict[str, str]) -> Finding | None:
    """Pages carrying statistical/numeric claims but zero citation
    language anywhere -- the KDD 2024 GEO study (Aggarwal et al.,
    arXiv:2311.09735) tested citation-, quotation- and statistic-adding
    among nine strategies across ~10k queries and reports visibility
    gains of "up to 40%", with efficacy varying by domain; their
    complete absence across the sampled corpus is worth flagging as a
    proactive gap, not a defect on any one page."""
    from brand_audit.facts import extract_facts

    pages_with_stats = []
    for url in sorted(pages):
        html = pages[url]
        text = re.sub(r"<[^>]+>", " ", html)
        facts = extract_facts(text)
        if len(facts["numeric"]) + len(facts["currency"]) >= 2 and not _has_citation_signal(html):
            pages_with_stats.append(url)

    if not pages_with_stats or len(pages_with_stats) < max(1, len(pages) // 2):
        # Only worth flagging if it's the *majority* pattern across the
        # sampled corpus -- one page without a citation isn't a site-wide
        # attribution gap.
        return None

    confidence = Confidence.LOW  # citation-phrase matching is a narrow, easily-missed heuristic
    severity = compute_severity(Stage.CITE, BlastRadius.NONE, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(pages_with_stats)} of {len(pages)} pages state numeric claims with no visible attribution",
        severity=severity,
        stage=Stage.CITE,
        taxonomy_id="TRUST-008",
        scope=Scope(checked=len(pages), affected=len(pages_with_stats)),
        evidence="; ".join(pages_with_stats[:5]),
        artifacts=[Artifact(url=u) for u in pages_with_stats[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "The KDD 2024 GEO study (Aggarwal et al., arXiv:2311.09735) found that adding source "
            "citations, quotations and statistics measurably improves visibility in generative-engine "
            "responses -- up to 40% in its own evaluation, varying by domain. Numeric claims with no attribution language "
            "anywhere on the page read as self-asserted, which weakens their weight for a system "
            "trying to corroborate them."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Attribute key statistics to a source (internal data, a study, a named survey) rather than stating bare numbers.",
            priority=severity,
            impact="low",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.CITE,
            implementation=["Add 'according to ...' / 'Source: ...' framing near the most important numeric claims"],
            verification_step="Re-run the audit and confirm fewer pages appear in this finding's scope",
            rationale_ref="references/taxonomy.md#trust-008",
        ),
    )
