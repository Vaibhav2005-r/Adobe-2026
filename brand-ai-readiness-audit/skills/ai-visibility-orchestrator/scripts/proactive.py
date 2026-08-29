"""The beyond-defect proactive layer (docs/build-plan.md Part 2 §8).

The rubric rewards suggestions "even where no explicit defect was
found," and calls out "relevant and non-obvious." That is a different
job from detection: a `Finding` requires an artifact proving something
is *wrong*, whereas a proactive recommendation points at something
*absent* -- and absence has no artifact to point at, which is precisely
why these live in their own array rather than being smuggled in as
low-severity findings.

The hard rule that keeps this from degenerating into a static
best-practices list: **every recommendation must be derived from
something this run actually measured.** Each generator below names the
measurement it reads. If a generator cannot cite a measured gap, it
does not emit anything.

Deliberately kept to three generators rather than padded out. Each one
covers a distinct kind of absence:

  1. an entire buyer-intent class that nothing on the site answers
     (read from stage (4)'s answerability matrix)
  2. queries that *nearly* resolve -- the cheapest wins available
     (read from the same matrix's PARTIAL outcomes)
  3. no `/llms.txt`, with a proposal generated from the site's own
     sampled URLs rather than a stub (read from stage (1))

Overlap with detection is avoided on purpose: CHUNK-001 fires on the
corpus-wide unanswerable *ratio*, while (1) here fires on a single
intent class being wholly unanswered even when that ratio is fine;
CHUNK-003 covers only *cross-page* PARTIALs, while (2) here covers the
same-page ones nothing else looks at.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.models import (  # noqa: E402
    AnswerabilityMatrixEntry,
    AnswerabilityOutcome,
    Confidence,
    ProactiveRecommendation,
    Severity,
    Stage,
    SuggestedAction,
)

# Plain-language descriptions of what each intent class is *for*, so a
# recommendation reads as advice rather than as a dump of internal
# taxonomy vocabulary. Keyed to the query-template bank's own intents.
_INTENT_PURPOSE = {
    "identity": "explain what the brand is and does",
    "pricing": "state what things cost",
    "comparison": "compare the brand against alternatives",
    "capability": "describe features and specifications",
    "trust": "provide reviews, proof, or credibility signals",
    "contact": "say how to get in touch or where the business is",
}

_MAX_LLMS_TXT_URLS = 25


def _recommend_missing_intent_coverage(
    matrix: list[AnswerabilityMatrixEntry],
) -> list[ProactiveRecommendation]:
    """An entire intent class where *no* query resolved. Distinct from
    CHUNK-001, which measures the corpus-wide unanswerable ratio: a site
    can sit comfortably under that threshold and still answer nothing at
    all about, say, comparison -- which is the gap a competitor's
    comparison page fills instead."""
    by_intent: dict[str, list[AnswerabilityMatrixEntry]] = defaultdict(list)
    for e in matrix:
        by_intent[e.intent].append(e)

    recs: list[ProactiveRecommendation] = []
    for intent in sorted(by_intent):
        entries = by_intent[intent]
        if any(e.outcome == AnswerabilityOutcome.ANSWERABLE for e in entries):
            continue
        purpose = _INTENT_PURPOSE.get(intent, f"answer {intent}-intent questions")
        recs.append(
            ProactiveRecommendation(
                title=f"No page answers {intent}-intent questions",
                rationale=(
                    f"All {len(entries)} simulated {intent}-intent queries came back unanswerable "
                    f"from the AI-reachable corpus (outcomes: "
                    f"{', '.join(sorted({e.outcome.value for e in entries}))}). No defect was "
                    f"detected on any individual page -- the gap is that no page exists that would "
                    f"{purpose} in a form retrieval can surface. An assistant asked this will cite "
                    f"whoever does have such a page, which is usually a competitor or an aggregator."
                ),
                suggested_action=SuggestedAction(
                    summary=f"Publish a page that directly answers {intent}-intent questions in the buyer's own phrasing.",
                    priority=Severity.LOW,
                    impact="medium",
                    effort="medium",
                    confidence=Confidence.MEDIUM,
                    stage_unblocked=Stage.RETRIEVE,
                    implementation=[
                        f"Review the {intent} queries in the answerability matrix -- they are the literal phrasings to answer",
                        "State each answer directly in text, not only in marketing narrative or an image",
                        "Keep the subject and the fact in the same section so they land in the same retrieval chunk",
                    ],
                    verification_step="Re-run the audit and confirm at least one query in this intent class becomes 'answerable'",
                    rationale_ref="references/taxonomy.md#chunk-001",
                ),
            )
        )
    return recs


def _recommend_near_miss_upgrades(
    matrix: list[AnswerabilityMatrixEntry],
) -> list[ProactiveRecommendation]:
    """Queries that resolved only as PARTIAL -- the answer exists but has
    to be assembled. These are the cheapest available wins: the content
    is already written, it is only badly co-located."""
    partials = [e for e in matrix if e.outcome == AnswerabilityOutcome.PARTIAL]
    if not partials:
        return []
    examples = "; ".join(f"[{e.intent}] {e.query!r}" for e in partials[:5])
    return [
        ProactiveRecommendation(
            title=f"{len(partials)} quer{'y is' if len(partials) == 1 else 'ies are'} one edit away from being citable",
            rationale=(
                f"These queries resolved as PARTIAL: the facts needed are present in the corpus, but "
                f"only by assembling them across chunks rather than from one self-contained passage. "
                f"Real retrieval pipelines do this assembly unreliably, so a PARTIAL is fragile rather "
                f"than safe. Because the content already exists, these are the lowest-effort upgrades "
                f"available -- no new page required. Affected: {examples}"
            ),
            suggested_action=SuggestedAction(
                summary="Co-locate each partially-answered fact into a single self-contained passage.",
                priority=Severity.LOW,
                impact="medium",
                effort="low",
                confidence=Confidence.MEDIUM,
                stage_unblocked=Stage.RETRIEVE,
                implementation=[
                    "For each affected query, find where the facts currently live",
                    "Add one sentence or section that states the complete answer in one place",
                    "Name the subject explicitly in that passage -- do not rely on a heading several chunks earlier",
                ],
                verification_step="Re-run the audit and confirm these queries move from 'partial' to 'answerable'",
                rationale_ref="references/taxonomy.md#chunk-003",
            ),
        )
    ]


def _recommend_llms_txt(
    llms_txt_present: bool, corpus_urls: list[str], site: str
) -> list[ProactiveRecommendation]:
    """No `/llms.txt`. The proposal is generated from the site's own
    sampled URLs -- per the build plan's explicit instruction that this
    be "generated from the actual site map, not a stub." A generic
    template would be exactly the static best-practices advice this
    layer exists to avoid."""
    if llms_txt_present or not corpus_urls:
        return []

    listed = sorted(corpus_urls)[:_MAX_LLMS_TXT_URLS]
    domain = urlparse(site).netloc or site
    proposal_lines = [f"# {domain}", "", "## Pages"]
    proposal_lines += [f"- [{urlparse(u).path or '/'}]({u})" for u in listed]
    proposal = "\n".join(proposal_lines)

    return [
        ProactiveRecommendation(
            title="No /llms.txt -- a curated index for AI systems is absent",
            rationale=(
                f"No `/llms.txt` was served at the site root. This is not a defect: it is a proposed "
                f"convention, not a ratified standard, and no major AI vendor has publicly committed "
                f"to honouring it -- which is why it is raised here rather than as a finding. It is, "
                f"however, a cheap and low-risk hedge: where `robots.txt` says what a crawler *may* "
                f"read, `llms.txt` says what is worth reading. A draft generated from the "
                f"{len(listed)} page(s) this audit actually sampled is below, so it reflects the real "
                f"site rather than a template.\n\n{proposal}"
            ),
            suggested_action=SuggestedAction(
                summary="Publish an /llms.txt listing the pages most worth citing, using the generated draft as a starting point.",
                priority=Severity.LOW,
                impact="low",
                effort="low",
                confidence=Confidence.LOW,
                stage_unblocked=Stage.REACH,
                implementation=[
                    "Save the generated draft above as /llms.txt at the site root",
                    "Trim it to the pages you actually want cited, and add a one-line description per page",
                    "Serve it as text/plain",
                ],
                verification_step=f"curl -s {site.rstrip('/')}/llms.txt -- should return the file, not a 404",
                rationale_ref="references/composition.md",
            ),
        )
    ]


def derive_proactive_recommendations(
    matrix: list[AnswerabilityMatrixEntry],
    corpus_urls: list[str],
    site: str,
    llms_txt_present: bool,
) -> list[ProactiveRecommendation]:
    """Every recommendation traces to something measured this run. Order
    is deterministic (intent gaps sorted by intent name, then near-miss,
    then llms.txt) so the report stays byte-reproducible."""
    recs: list[ProactiveRecommendation] = []
    recs += _recommend_missing_intent_coverage(matrix)
    recs += _recommend_near_miss_upgrades(matrix)
    recs += _recommend_llms_txt(llms_txt_present, corpus_urls, site)
    return recs
