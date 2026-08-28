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

from brand_audit.chunk import Chunk, chunk_page  # noqa: E402
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
    source: str  # "json-ld" | "title" | "h1" | "fallback"


def detect_entity(pages: dict[str, str], homepage_url: str | None = None) -> Entity:
    """Derive the brand's entity + category from the site itself --
    JSON-LD Organization first (most reliable), then <title>, then
    <h1>. Checked in deterministic order (sorted URLs) so the result
    doesn't depend on dict/crawl ordering."""
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

    # Find the actual homepage among crawled URLs by normalized path, not
    # exact string equality against the passed `homepage_url` -- that
    # requires byte-identical formatting (trailing slash, scheme) between
    # the CLI's site argument and a real crawled URL, which real sites
    # essentially never satisfy (confirmed: against docs.python.org this
    # returned "3.10.20 Documentation" as the detected entity name --
    # the title of whichever crawled URL happened to sort first
    # alphabetically -- instead of falling through to any homepage-like
    # page at all, because "https://docs.python.org" was never literally
    # a key in `pages`). A root path ("" or "/") is a much more reliable
    # signal of "this is the homepage" than string equality.
    root_urls = [u for u in sorted(pages) if urlparse(u).path in ("", "/")]
    exact_urls = [homepage_url] if homepage_url in pages else []
    candidates = exact_urls + [u for u in root_urls if u not in exact_urls]
    candidates += [u for u in sorted(pages) if u not in candidates]

    for url in candidates:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", pages[url], re.IGNORECASE | re.DOTALL)
        if title_match:
            raw = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            parts = [p for p in _TITLE_SEPARATORS.split(raw) if p]
            if parts:
                return Entity(name=parts[0], category=category, source="title")

    for url in candidates:
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", pages[url], re.IGNORECASE | re.DOTALL)
        if h1_match:
            text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            if text:
                return Entity(name=text, category=category, source="h1")

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
) -> tuple[AnswerabilityOutcome, ScoredChunk | None]:
    results = retriever.query(query, top_k=5)
    if not results:
        return AnswerabilityOutcome.UNRETRIEVABLE, None

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
            return AnswerabilityOutcome.ANSWERABLE, r

    top = results[0]
    union_matched: set[str] = set()
    for r in results:
        union_matched |= r.matched_terms
    union_coverage = _coverage(frozenset(union_matched), top.query_terms, entity_tokens)
    if union_coverage >= _ASSEMBLED_THRESHOLD:
        return AnswerabilityOutcome.PARTIAL, top

    return AnswerabilityOutcome.UNGROUNDED, top


# --- pipeline ---------------------------------------------------------------


def run_retrieval_simulation(
    pages: dict[str, str], homepage_url: str | None = None
) -> tuple[list[AnswerabilityMatrixEntry], Finding | None, Entity]:
    """pages: {url: raw_html} for the AI-reachable corpus (already
    gated through stages (1)/(2) by the caller -- this function doesn't
    re-derive that gate, per the composition contract)."""
    entity = detect_entity(pages, homepage_url)
    entity_tokens = frozenset(tokenize(entity.name))
    queries = expand_queries(entity)

    chunks: list[Chunk] = []
    for url in sorted(pages):
        main_html = trafilatura.extract(pages[url], output_format="html", include_formatting=True, include_images=False) or ""
        chunks += chunk_page(main_html, url)

    retriever = BM25Retriever()
    retriever.index(chunks)

    matrix: list[AnswerabilityMatrixEntry] = []
    unanswerable_examples: list[str] = []
    for query, intent in queries:
        outcome, top = classify(query, intent, retriever, entity_tokens)
        matrix.append(
            AnswerabilityMatrixEntry(
                query=query,
                intent=intent,
                outcome=outcome,
                top_chunk_url=top.chunk.url if top else None,
                citable=outcome in (AnswerabilityOutcome.ANSWERABLE, AnswerabilityOutcome.PARTIAL),
            )
        )
        if outcome in (AnswerabilityOutcome.UNRETRIEVABLE, AnswerabilityOutcome.UNGROUNDED):
            unanswerable_examples.append(f"[{intent}] {query!r} -> {outcome.value}")

    finding = None
    # `pages` empty (e.g. a single-page site whose only page was excluded
    # upstream as a RENDER-001 empty shell) means there's no page left to
    # cite as evidence -- Finding requires >=1 artifact by construction
    # ("no artifact, no finding"), and forcing one here would either
    # crash (confirmed: this exact case raised a pydantic ValidationError
    # against the js-only-price fixture) or fabricate an artifact that
    # doesn't back the claim. The matrix itself still reports honestly
    # (every query UNRETRIEVABLE); RENDER-001 already carries the actual
    # evidence for *why*, so a redundant, evidence-less CHUNK-001 finding
    # wouldn't add information anyway.
    if pages and matrix and len(unanswerable_examples) / len(matrix) >= 0.25:
        confidence = Confidence.HIGH
        severity = compute_severity(Stage.RETRIEVE, BlastRadius.DEGRADES, confidence)
        finding = Finding(
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
        )

    return matrix, finding, entity
