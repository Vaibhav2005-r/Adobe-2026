"""Stage (4) RETRIEVE: the answerability probe (crown jewel).

Pipeline: detect the brand entity from the corpus -> expand a
deterministic query set from the bundled template bank -> chunk +
BM25-index the AI-reachable corpus -> classify each query's outcome.

Entirely deterministic -- no LLM call, no embeddings, no network beyond
what stage (1) already fetched. See docs/build-plan.md Part 4: BM25 is
the "conservative floor," defensible specifically because it needs no
model weights and no API key.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.chunk import Chunk, chunk_page, page_content_length  # noqa: E402
from brand_audit.crawl import find_homepage_url  # noqa: E402
from brand_audit.facts import extract_facts  # noqa: E402
from brand_audit.jsonld import extract_json_ld, walk  # noqa: E402
from brand_audit.models import (  # noqa: E402
    AnswerabilityMatrixEntry,
    AnswerabilityOutcome,
    Artifact,
    Confidence,
    Finding,
    Scope,
    Stage,
    SuggestedAction,
    Verification,
)
from brand_audit.retrieval import BM25Retriever, ScoredChunk, tokenize  # noqa: E402
from brand_audit.severity import BlastRadius, compute_severity  # noqa: E402

import trafilatura

_finding_counter = 0
_TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "assets" / "query-templates.json"


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"F-CHUNK-{_finding_counter:03d}"


def _unverified() -> Verification:
    return Verification(reproduced=False, method="single-pass detection; falsification pass not yet implemented")


# --- entity detection ---------------------------------------------------

_CATEGORY_BY_TYPE = {
    "Product": "product",
    "Offer": "product",
    "SoftwareApplication": "software",
    "LocalBusiness": "business",
    "Restaurant": "business",
    "Store": "business",
}

_TITLE_SEPARATORS = re.compile(r"\s*[|\-–—:]\s*")


@dataclass
class Entity:
    name: str
    category: str
    source: str  # "json-ld" | "title" | "h1" | "domain" | "fallback"


def _domain_derived_name(homepage_url: str | None) -> str | None:
    """Last-resort brand name derived from the audited domain itself --
    e.g. "https://www.allbirds.com" -> "Allbirds". Always available
    (homepage_url is always the site under audit) and, unlike guessing
    from some sampled page's own title/h1, can't be hijacked by an
    unrelated page. Not required to be linguistically perfect (a
    multi-part domain like "example.co.uk" derives "Example", not
    "Example UK") -- just a safe floor for query-template expansion."""
    if not homepage_url:
        return None
    netloc = urlparse(homepage_url).netloc or homepage_url
    netloc = netloc.split(":")[0]  # drop a port, if present
    if netloc.startswith("www."):
        netloc = netloc[4:]
    label = netloc.split(".")[0]
    return label.capitalize() if label else None


def detect_entity(pages: dict[str, str], homepage_url: str | None = None) -> Entity:
    """Derive the brand's entity + category from the site itself --
    JSON-LD Organization first (most reliable), then the homepage's own
    <title>, then its <h1>, then a domain-derived name. Checked in
    deterministic order (sorted URLs) so the result doesn't depend on
    dict/crawl ordering."""
    # Two passes over every JSON-LD node, not return-on-first-match:
    # the organization name and the category signal are often on
    # *different* nodes (an Organization plus a sibling Product in the
    # same page's JSON-LD, or on different pages entirely), and
    # returning as soon as a named Organization is found -- the first
    # implementation's bug, caught by a unit test with exactly this
    # Organization+Product shape -- would stop scanning before ever
    # reaching a category-bearing node that comes later in walk order.
    category = "business"
    org_name: str | None = None
    for url in sorted(pages):
        for block in extract_json_ld(pages[url]):
            for node in walk(block):
                types = node.get("@type")
                types = types if isinstance(types, list) else [types]
                for t in types:
                    if t in _CATEGORY_BY_TYPE:
                        category = _CATEGORY_BY_TYPE[t]
                if org_name is None and any(t in ("Organization", "LocalBusiness") for t in types) and node.get("name"):
                    org_name = str(node["name"])
    if org_name is not None:
        return Entity(name=org_name, category=category, source="json-ld")

    # find_homepage_url matches by normalized root path, not exact string
    # equality against `homepage_url` -- see its docstring (brand_audit.
    # crawl) for why exact equality was a real bug here on Day 5.
    #
    # Deliberately NOT falling back further to *some other* sampled
    # page's title/h1 when the homepage itself isn't among them (the
    # original approach here, through Day 6). A deterministic stratified
    # sample of N pages has no guarantee the bare domain root is even a
    # sitemap entry -- confirmed directly against a real site: a live
    # allbirds.com crawl never sampled "/" at all (not every sitemap
    # lists the root), and falling back to "whichever sampled page
    # sorts first" landed on https://www.allbirds.com/pages/design-system
    # -- a real, legitimate page whose own <title> is literally "Design
    # System", taken as the detected brand name for the entire audit
    # purely because of alphabetical sort order. A domain-derived name
    # is a strictly safer floor: it can't be hijacked by an unrelated
    # subpage's own title the way "guess from any sampled page" could.
    resolved_homepage = find_homepage_url(pages, homepage_url)
    if resolved_homepage is not None:
        html = pages[resolved_homepage]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            raw = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            parts = [p for p in _TITLE_SEPARATORS.split(raw) if p]
            if parts:
                return Entity(name=parts[0], category=category, source="title")

        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if h1_match:
            text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            if text:
                return Entity(name=text, category=category, source="h1")

    domain_name = _domain_derived_name(homepage_url)
    if domain_name:
        return Entity(name=domain_name, category=category, source="domain")

    return Entity(name="the site", category=category, source="fallback")


# --- query expansion ------------------------------------------------------


def load_query_templates() -> dict[str, list[str]]:
    data = json.loads(_TEMPLATES_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def expand_queries(entity: Entity) -> list[tuple[str, str]]:
    """Deterministic expansion -- every template x every intent class,
    filled in from the detected entity. Returns [(query, intent), ...]."""
    templates = load_query_templates()
    queries = []
    for intent, template_list in templates.items():
        for template in template_list:
            queries.append((template.format(brand=entity.name, category=entity.category), intent))
    return queries


# --- answerability classification ------------------------------------------

# Intents where a specific fact type grounds the answer -- for these, a
# topically-close chunk isn't enough; the concrete fact must actually be
# present. Other intents (identity/comparison/capability/trust) don't
# have a crisp fact signature to check for, so they fall back to a
# stricter coverage-only bar instead.
_FACT_CHECK_BY_INTENT = {"pricing": "currency", "contact": "contact"}

_SINGLE_CHUNK_THRESHOLD = {"pricing": 0.5, "contact": 0.5}
_DEFAULT_SINGLE_CHUNK_THRESHOLD = 0.7
_ASSEMBLED_THRESHOLD = 0.6


def _coverage(matched: frozenset[str], query_terms: frozenset[str], entity_tokens: frozenset[str]) -> float:
    """Fraction of *substantive* query terms matched -- excludes the
    entity's own name tokens from both numerator and denominator.

    Every template bakes in {brand}, but a real page about pricing or
    contact info rarely repeats the company's full name verbatim right
    next to the fact itself (that's implied by site-wide branding, not
    something that needs re-grounding per page). Scoring raw term
    coverage including brand tokens punishes exactly the pages that
    *should* count as answerable: confirmed by testing against a
    synthetic 3-page fixture where a real $89 price and a real contact
    email both scored as UNGROUNDED purely because "Rowan Cast Iron Co."
    (4 tokens) didn't repeat next to them, swamping the 1-2 substantive
    terms ("cost", "contact") that actually mattered.
    """
    substantive_query = query_terms - entity_tokens
    if not substantive_query:
        return 1.0 if matched else 0.0  # identity-only query ("what is X") -- any match at all counts
    substantive_matched = matched - entity_tokens
    return len(substantive_matched) / len(substantive_query)


def classify(
    query: str, intent: str, retriever: BM25Retriever, entity_tokens: frozenset[str]
) -> tuple[AnswerabilityOutcome, ScoredChunk | None, bool]:
    """Returns (outcome, top_result, cross_page). `cross_page` is only
    meaningful when outcome is PARTIAL -- True if the chunks whose
    matched terms had to be combined to reach the assembled-coverage
    threshold span more than one URL. A same-page multi-chunk assembly
    is already fragile (per the build plan's own framing: "answer must
    be assembled across chunks/pages... fragile under real retrieval");
    a *cross-page* one is worse, since real assistants rarely join facts
    from two different pages at all -- see CHUNK-003."""
    results = retriever.query(query, top_k=5)
    if not results:
        return AnswerabilityOutcome.UNRETRIEVABLE, None, False

    threshold = _SINGLE_CHUNK_THRESHOLD.get(intent, _DEFAULT_SINGLE_CHUNK_THRESHOLD)
    fact_type = _FACT_CHECK_BY_INTENT.get(intent)

    # Check every top-k result independently, not just results[0]: BM25
    # ranks by raw score, which rewards rare terms regardless of which
    # question they answer -- a page's own distinctive brand-name tokens
    # can outscore a topically-perfect chunk on a *different* page that
    # only matches the query's one or two substantive terms. Confirmed
    # directly: a fixture's pricing chunk (containing the actual $89
    # price) ranked #2 behind the homepage chunk, which shared no
    # substantive term with the query at all -- only brand-name tokens.
    # Whether an answer exists in the reachable corpus shouldn't depend
    # on which chunk BM25 happened to rank first.
    for r in results:
        coverage = _coverage(r.matched_terms, r.query_terms, entity_tokens)
        fact_present = bool(extract_facts(r.chunk.text)[fact_type]) if fact_type else True
        if coverage >= threshold and fact_present:
            return AnswerabilityOutcome.ANSWERABLE, r, False

    top = results[0]
    union_matched: set[str] = set()
    contributing_urls: set[str] = set()
    for r in results:
        if r.matched_terms - entity_tokens:  # only chunks contributing a *substantive* term count
            contributing_urls.add(r.chunk.url)
        union_matched |= r.matched_terms
    union_coverage = _coverage(frozenset(union_matched), top.query_terms, entity_tokens)
    if union_coverage >= _ASSEMBLED_THRESHOLD:
        return AnswerabilityOutcome.PARTIAL, top, len(contributing_urls) > 1

    return AnswerabilityOutcome.UNGROUNDED, top, False


# --- orphan-fact detection (CHUNK-002) --------------------------------------

# Two or more consecutive capitalized words -- a crude proper-noun-phrase
# proxy (product names, brand names), not real NER. Chosen because a real
# NER model would need weights the project's constraints rule out (same
# reasoning as brand_audit.facts skipping "entity" fact extraction).
_PROPER_NOUN_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){1,4}\b")


def _has_identifying_subject(chunk: Chunk) -> bool:
    """Is there anything in this chunk that names *what* a fact is
    about? The chunk's own heading (already prepended to its text as of
    Day 5) is the strongest signal; a proper-noun-like phrase anywhere
    in the chunk is a weaker fallback for chunks with no heading at
    all."""
    if chunk.section_heading:
        return True
    return bool(_PROPER_NOUN_PHRASE_RE.search(chunk.text))


def find_orphan_fact_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if extract_facts(c.text)["currency"] and not _has_identifying_subject(c)]


def detect_orphan_facts(chunks: list[Chunk]) -> Finding | None:
    """CHUNK-002: a chunk contains a price but nothing in the chunk
    identifies what it's the price *of* -- the build plan's own example
    is a `<td>` price cell 40 DOM nodes downstream of the product name
    in an `<h1>`. One aggregate finding, not one per chunk, matching
    CHUNK-001's dedup pattern."""
    orphans = find_orphan_fact_chunks(chunks)
    if not orphans:
        return None
    confidence = Confidence.MEDIUM  # proper-noun-phrase regex is a heuristic, not certain
    severity = compute_severity(Stage.RETRIEVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(orphans)} chunk(s) contain a price with no identifying subject nearby",
        severity=severity,
        stage=Stage.RETRIEVE,
        taxonomy_id="CHUNK-002",
        scope=Scope(checked=len(chunks), affected=len(orphans)),
        evidence="; ".join(f"{c.url}#{c.chunk_index}: {c.text[:120]!r}" for c in orphans[:5]),
        artifacts=[Artifact(url=c.url, selector=f"chunk {c.chunk_index}") for c in orphans[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "Retrieval operates on chunks, not pages -- a fact whose subject and value land in "
            "different chunks is unretrievable even though the page nominally 'has' it. A chunk "
            "containing only a price, with no product name or heading to anchor it, answers no "
            "buyer question on its own no matter how well it's retrieved."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Co-locate the subject and its value: add a heading or a naming sentence in the same section as the fact.",
            priority=severity,
            impact="medium",
            effort="low",
            confidence=confidence,
            stage_unblocked=Stage.RETRIEVE,
            implementation=["Add a section heading, or a lead-in sentence naming the subject, near each standalone price/fact"],
            verification_step="Re-run the audit and confirm the chunk now resolves via detect_orphan_facts",
            rationale_ref="references/taxonomy.md#chunk-002",
        ),
    )


# --- boilerplate-ratio scoring (CHUNK-004) -----------------------------------

_BOILERPLATE_PHRASES = [
    "all rights reserved", "privacy policy", "terms of service", "terms and conditions",
    "cookie policy", "sign up for our newsletter", "subscribe to our newsletter",
    "we use cookies", "accept all cookies", "follow us on", "copyright ©",
    "skip to content", "skip to main content",
]


def boilerplate_ratio(chunk: Chunk) -> float:
    """Fraction of a chunk's characters covered by known boilerplate
    phrases. Expected to rarely trigger in this pipeline specifically:
    chunking already runs on trafilatura's boilerplate-*stripped* main-
    content extraction (see chunk.py), so contamination reaching a
    chunk at all means trafilatura's own boilerplate detection missed
    it -- a real, if rarer, signal worth keeping rather than assuming
    away."""
    text_lower = chunk.text.lower()
    matched_chars = sum(len(p) for p in _BOILERPLATE_PHRASES if p in text_lower)
    return min(1.0, matched_chars / max(1, len(chunk.text)))


_BOILERPLATE_RATIO_THRESHOLD = 0.15


def detect_boilerplate_dilution(chunks: list[Chunk]) -> Finding | None:
    """CHUNK-004: chunks where boilerplate phrases make up an unusually
    high fraction of the text, diluting whatever real signal is there
    below what a retrieval system would rank highly."""
    diluted = [c for c in chunks if boilerplate_ratio(c) >= _BOILERPLATE_RATIO_THRESHOLD]
    if not diluted:
        return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.RETRIEVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(diluted)} chunk(s) are diluted with boilerplate text (cookie/legal/social-follow phrases)",
        severity=severity,
        stage=Stage.RETRIEVE,
        taxonomy_id="CHUNK-004",
        scope=Scope(checked=len(chunks), affected=len(diluted)),
        evidence="; ".join(f"{c.url}#{c.chunk_index}: {boilerplate_ratio(c):.0%} boilerplate" for c in diluted[:5]),
        artifacts=[Artifact(url=c.url, selector=f"chunk {c.chunk_index}") for c in diluted[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "A chunk that's mostly cookie-notice/legal/social-follow boilerplate has whatever real "
            "signal it carries diluted below what a retrieval system ranks highly -- the fact is "
            "technically present in the corpus but competes against noise for the same chunk's "
            "term-frequency budget."
        ),
        affected_queries=[],
        suggested_action=SuggestedAction(
            summary="Move boilerplate (cookie notices, legal text, social links) out of the main content flow.",
            priority=severity,
            impact="low",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.RETRIEVE,
            implementation=["Move repeated legal/social boilerplate into a template region (footer/modal) separate from article content"],
            verification_step="Re-run the audit and confirm the affected chunk's boilerplate_ratio drops",
            rationale_ref="references/taxonomy.md#chunk-004",
        ),
    )


def detect_cross_page_join_reliance(
    matrix_with_cross_page: list[tuple[AnswerabilityMatrixEntry, bool]], pages: dict[str, str]
) -> Finding | None:
    """CHUNK-003: a PARTIAL answer that required combining chunks from
    *different* pages, not just different sections of one page. Real
    assistants rarely perform this join at all -- see docs/build-plan.md
    Part 2 (3)."""
    cross_page_entries = [e for e, cp in matrix_with_cross_page if cp]
    if not cross_page_entries:
        return None
    confidence = Confidence.MEDIUM
    severity = compute_severity(Stage.RETRIEVE, BlastRadius.DEGRADES, confidence)
    return Finding(
        id=_next_id(),
        title=f"{len(cross_page_entries)} buyer-intent quer{'y' if len(cross_page_entries) == 1 else 'ies'} can only be answered by combining facts from different pages",
        severity=severity,
        stage=Stage.RETRIEVE,
        taxonomy_id="CHUNK-003",
        scope=Scope(checked=len(matrix_with_cross_page), affected=len(cross_page_entries)),
        evidence="; ".join(f"[{e.intent}] {e.query!r}" for e in cross_page_entries[:5]),
        artifacts=[Artifact(url=u) for u in sorted(pages)[:3]],
        confidence=confidence,
        verification=_unverified(),
        impact_mechanism=(
            "The answer exists in the corpus but only by combining facts from two or more distinct "
            "pages -- e.g. one page's specification plus another page's price. Real retrieval "
            "pipelines rarely perform this cross-page join at query time, so a PARTIAL outcome "
            "here is more fragile than a same-page multi-chunk assembly."
        ),
        affected_queries=[e.query for e in cross_page_entries[:10]],
        suggested_action=SuggestedAction(
            summary="Co-locate the related facts on a single page rather than relying on a reader (or retriever) to combine two pages.",
            priority=severity,
            impact="medium",
            effort="medium",
            confidence=confidence,
            stage_unblocked=Stage.RETRIEVE,
            implementation=["Summarize the combined fact (e.g. spec + price together) on at least one page"],
            verification_step="Re-run the audit and confirm the query now resolves from a single page",
            rationale_ref="references/taxonomy.md#chunk-003",
        ),
    )


# --- pipeline ---------------------------------------------------------------


def run_retrieval_simulation(
    pages: dict[str, str], homepage_url: str | None = None
) -> tuple[list[AnswerabilityMatrixEntry], list[Finding], Entity]:
    """pages: {url: raw_html} for the AI-reachable corpus (already
    gated through stages (1)/(2) by the caller -- this function doesn't
    re-derive that gate, per the composition contract)."""
    entity = detect_entity(pages, homepage_url)
    entity_tokens = frozenset(tokenize(entity.name))
    queries = expand_queries(entity)

    chunks: list[Chunk] = []
    page_lengths: dict[str, int] = {}
    for url in sorted(pages):
        main_html = trafilatura.extract(pages[url], output_format="html", include_formatting=True, include_images=False) or ""
        chunks += chunk_page(main_html, url)
        page_lengths[url] = page_content_length(main_html)

    retriever = BM25Retriever()
    retriever.index(chunks)

    matrix: list[AnswerabilityMatrixEntry] = []
    matrix_with_cross_page: list[tuple[AnswerabilityMatrixEntry, bool]] = []
    unanswerable_examples: list[str] = []
    for query, intent in queries:
        outcome, top, cross_page = classify(query, intent, retriever, entity_tokens)
        position_ratio = None
        if top is not None:
            total_length = page_lengths.get(top.chunk.url, 0)
            if total_length > 0:
                position_ratio = min(1.0, top.chunk.char_offset / total_length)
        entry = AnswerabilityMatrixEntry(
            query=query,
            intent=intent,
            outcome=outcome,
            top_chunk_url=top.chunk.url if top else None,
            citable=outcome in (AnswerabilityOutcome.ANSWERABLE, AnswerabilityOutcome.PARTIAL),
            top_chunk_position_ratio=position_ratio,
        )
        matrix.append(entry)
        matrix_with_cross_page.append((entry, cross_page))
        if outcome in (AnswerabilityOutcome.UNRETRIEVABLE, AnswerabilityOutcome.UNGROUNDED):
            unanswerable_examples.append(f"[{intent}] {query!r} -> {outcome.value}")

    findings: list[Finding] = []
    # `pages` empty (e.g. a single-page site whose only page was excluded
    # upstream as a RENDER-001 empty shell) means there's no page left to
    # cite as evidence -- Finding requires >=1 artifact by construction
    # ("no artifact, no finding"), and forcing one here would either
    # crash (confirmed: this exact case raised a pydantic ValidationError
    # against the js-only-price fixture) or fabricate an artifact that
    # doesn't back the claim. The matrix itself still reports honestly
    # (every query UNRETRIEVABLE); RENDER-001 already carries the actual
    # evidence for *why*, so a redundant, evidence-less finding here
    # wouldn't add information anyway. All four detectors below share
    # this guard for the same reason.
    if pages and matrix and len(unanswerable_examples) / len(matrix) >= 0.25:
        confidence = Confidence.HIGH
        severity = compute_severity(Stage.RETRIEVE, BlastRadius.DEGRADES, confidence)
        findings.append(Finding(
            id=_next_id(),
            title=f"{len(unanswerable_examples)} of {len(matrix)} buyer-intent queries are unanswerable from the AI-reachable corpus",
            severity=severity,
            stage=Stage.RETRIEVE,
            taxonomy_id="CHUNK-001",
            scope=Scope(checked=len(matrix), affected=len(unanswerable_examples)),
            evidence="; ".join(unanswerable_examples[:10]),
            artifacts=[Artifact(url=u) for u in sorted(pages)[:3]],
            confidence=confidence,
            verification=_unverified(),
            impact_mechanism=(
                "Even where a page nominally contains this information somewhere on the site, "
                "it isn't retrievable the way an assistant's own retrieval pipeline would actually "
                "find it -- the query's own terms don't surface a chunk that grounds an answer. "
                "This is the direct, outcome-anchored metric that determines answer visibility, "
                "not an intermediate proxy."
            ),
            affected_queries=[q for q, _ in queries if any(q in ex for ex in unanswerable_examples)][:10],
            suggested_action=SuggestedAction(
                summary="Add direct, front-loaded answers to buyer-intent questions in the site's own language, not just marketing narrative.",
                priority=severity,
                impact="high",
                effort="medium",
                confidence=confidence,
                stage_unblocked=Stage.RETRIEVE,
                implementation=[
                    "Review the affected_queries list and add a page or section that states each answer directly",
                    "Use the buyer's own phrasing, not just internal terminology",
                ],
                verification_step="Re-run the audit after publishing the change and confirm the query's outcome improves",
                rationale_ref="references/taxonomy.md#chunk-001",
            ),
        ))

    if pages:
        for f in (
            detect_orphan_facts(chunks),
            detect_boilerplate_dilution(chunks),
            detect_cross_page_join_reliance(matrix_with_cross_page, pages),
        ):
            if f is not None:
                findings.append(f)

    return matrix, findings, entity
