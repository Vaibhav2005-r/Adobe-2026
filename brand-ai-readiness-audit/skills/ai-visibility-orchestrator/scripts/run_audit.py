#!/usr/bin/env python3
"""Pipeline driver: crawl a site, run whatever stages are wired up, emit a
schema-valid AuditReport.

Day 8 milestone: the full pipeline is feature-complete. All six funnel
stages (REACH through ARRIVE) detect; `finding-verification` falsifies
every finding before it ships (re-fetch, sample-adequacy, contradiction
search, demotion to `observations`); `assemble_report.dedup_findings`
merges known same-root-cause cross-stage pairs. `render_html.py` and
`render_markdown.py` turn the same validated report into the HTML demo
surface and a Markdown executive summary -- one command now produces
JSON + HTML + Markdown, per the Day 8 DoD.

Usage:
    python run_audit.py example.com
    python run_audit.py https://example.com --max-pages 40 --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_REPO_SRC = Path(__file__).resolve().parents[3] / "src"
sys.path.insert(0, str(_REPO_SRC))
_REACH_SCRIPTS = Path(__file__).resolve().parents[2] / "crawl-reach-audit" / "scripts"
sys.path.insert(0, str(_REACH_SCRIPTS))
_RENDER_SCRIPTS = Path(__file__).resolve().parents[2] / "render-gap-audit" / "scripts"
sys.path.insert(0, str(_RENDER_SCRIPTS))
_EXTRACT_SCRIPTS = Path(__file__).resolve().parents[2] / "extractability-audit" / "scripts"
sys.path.insert(0, str(_EXTRACT_SCRIPTS))
_RETRIEVE_SCRIPTS = Path(__file__).resolve().parents[2] / "retrieval-simulation" / "scripts"
sys.path.insert(0, str(_RETRIEVE_SCRIPTS))
_TRUST_SCRIPTS = Path(__file__).resolve().parents[2] / "trust-corroboration-audit" / "scripts"
sys.path.insert(0, str(_TRUST_SCRIPTS))
_ARRIVE_SCRIPTS = Path(__file__).resolve().parents[2] / "arrival-engagement-audit" / "scripts"
sys.path.insert(0, str(_ARRIVE_SCRIPTS))
_VERIFY_SCRIPTS = Path(__file__).resolve().parents[2] / "finding-verification" / "scripts"
sys.path.insert(0, str(_VERIFY_SCRIPTS))

from brand_audit.crawl import (  # noqa: E402
    DEFAULT_FETCH_UA,
    BudgetManager,
    discover_sitemap_urls,
    fetch_robots,
    sample_seed_for,
    stratified_sample,
)
from brand_audit.fetch import fetch_many, probe_user_agents  # noqa: E402
from brand_audit.artifact_store import ArtifactStore  # noqa: E402
from brand_audit.models import Stage, StageResult  # noqa: E402

import httpx

from assemble_report import assemble_report  # noqa: E402
import detect as reach_detect  # noqa: E402
import verify_findings  # noqa: E402
from render_html import render_html_report  # noqa: E402
from render_markdown import render_markdown_summary  # noqa: E402


def normalize_site(site: str) -> str:
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


async def run_reach_stage(
    base_url: str, max_pages: int, run_dir: Path
) -> tuple[StageResult, list, str]:
    """Robots + sitemap discovery + deterministic sample + fetch, then the
    stage (1) detectors. Returns (StageResult, fetch outcomes, sample_seed)
    -- the outcomes are reused by the render stage so pages aren't fetched
    twice for the "raw" half of the dual-fetch differential."""

    async with httpx.AsyncClient(follow_redirects=True) as client:
        robots = await fetch_robots(client, base_url)
        sitemap_urls, sitemap_fetch_ok = await discover_sitemap_urls(client, base_url, robots)

    domain = urlparse(base_url).netloc
    seed = sample_seed_for(domain)
    sample = stratified_sample(sitemap_urls, seed, max_pages=max_pages)

    # Robots-respecting is a hard constraint (CLAUDE.md), not a courtesy:
    # only fetch URLs our own crawl UA is actually allowed to. The
    # REACH-001 detector below still checks the *full* sample for named
    # AI-bot rules -- that's a robots.txt rule lookup, not a fetch, so it
    # can safely see paths we never touch ourselves.
    crawl_targets = [u for u in sample if robots.allowed(u, DEFAULT_FETCH_UA)]
    excluded_by_robots = len(sample) - len(crawl_targets)

    outcomes = await fetch_many(crawl_targets)  # follows redirects -- final content
    no_redirect_outcomes = await fetch_many(crawl_targets, follow_redirects=False)  # immediate response

    store = ArtifactStore(run_dir)
    corpus_delta: list[str] = []
    fetched_ok = 0
    for outcome in outcomes:
        if outcome.record is None:
            continue
        store.record(outcome.record)
        if outcome.record.http_status and outcome.record.http_status < 400:
            fetched_ok += 1
            corpus_delta.append(outcome.url)

    findings = []
    findings += reach_detect.detect_ai_ua_block(base_url, robots, sample)
    findings += reach_detect.detect_locale_redirect(base_url, no_redirect_outcomes)
    findings += reach_detect.detect_soft_404(base_url, outcomes)
    findings += reach_detect.detect_canonical_issues(base_url, outcomes)
    findings += reach_detect.detect_sitemap_health(base_url, robots, sitemap_reachable=sitemap_fetch_ok)
    findings += reach_detect.detect_waf_contradicts_robots(base_url, outcomes)

    if not robots.fetched:
        waf_probe = await probe_user_agents(base_url, reach_detect.WAF_PROBE_UAS)
        findings += reach_detect.detect_waf_block(base_url, waf_probe, robots)

    stage_result = StageResult(
        stage=Stage.REACH,
        findings=findings,
        artifacts=[],
        corpus_delta=corpus_delta,
        metrics={
            "pages_discovered": len(sitemap_urls),
            "pages_sampled": len(sample),
            "pages_excluded_by_robots": excluded_by_robots,
            "pages_fetched_ok": fetched_ok,
            "robots_fetched": robots.fetched,
        },
    )
    return stage_result, outcomes, seed


MIN_RENDER_BUDGET_S = 30.0  # not worth paying Chromium startup cost for less than this


async def run_render_stage(
    corpus_urls: list[str], reach_outcomes: list, max_render_pages: int, budget: BudgetManager
) -> tuple[StageResult | None, str | None, frozenset[str]]:
    """Dual-fetch differential over the stage (1) survivors. Returns
    (StageResult, None, empty_shell_urls) on success, or
    (None, degradation_reason, frozenset()) if playwright isn't
    installed, or budget is too tight to be worth starting -- the
    caller must NOT run this stage's findings in either case, per the
    "never guess" rule. `empty_shell_urls` is returned explicitly
    (not re-derived by the caller from finding severity/taxonomy_id)
    because a page's emptiness is a fact about that one page,
    independent of whether the *aggregate* pattern across the render
    sample happened to cross the site-wide threshold -- see
    render_detect.detect_empty_shell_pages."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return None, "render_stage_skipped_no_playwright", frozenset()

    if budget.remaining() < MIN_RENDER_BUDGET_S:
        return None, "render_stage_skipped_low_budget", frozenset()

    import render_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    targets = [u for u in corpus_urls if u in raw_by_url][:max_render_pages]
    if not targets:
        return StageResult(stage=Stage.RENDER, findings=[], corpus_delta=[], metrics={"pages_rendered": 0}), None, frozenset()

    rendered_html = await render_detect.render_fetch(targets)

    today_iso = datetime.now(timezone.utc).date().isoformat()
    render_failed = 0
    compared: list[str] = []
    comparisons: list = []
    for url in targets:
        rendered = rendered_html.get(url)
        if rendered is None:
            # Render failed/timed out -- comparing against "" would risk
            # a false RENDER-001 (raw substantial, "rendered" empty is
            # exactly backwards from the real signal) or silently
            # mask a real one. Skip rather than guess either way.
            render_failed += 1
            continue
        compared.append(url)
        comparisons.append(render_detect.compare(url, raw_by_url[url], rendered, today_iso=today_iso))

    # Primary empty-shell signal is computed once, across the whole
    # render sample (not per-page) -- see detect_empty_shell_pages for
    # why: whether it's site-wide or page-class depends on what
    # fraction of the *sample* is empty, not any one page in isolation.
    findings = []
    empty_shell_finding = render_detect.detect_empty_shell_pages(comparisons)
    empty_shell_urls: set[str] = set()
    if empty_shell_finding is not None:
        findings.append(empty_shell_finding)
        empty_shell_urls = {c.url for c in comparisons if render_detect.is_empty_shell(c)}
    for comparison in comparisons:
        if comparison.url in empty_shell_urls:
            continue  # already covered by the aggregate empty-shell finding above
        findings += render_detect.detect_partial_render_gap(comparison)

    stage_result = StageResult(
        stage=Stage.RENDER,
        findings=findings,
        corpus_delta=compared,
        metrics={"pages_rendered": len(compared), "pages_render_failed": render_failed},
    )
    return stage_result, None, frozenset(empty_shell_urls)


def run_extract_stage(corpus_urls: list[str], reach_outcomes: list) -> StageResult:
    """Structured-data/semantic-HTML checks over the stage (1) survivors.
    Pure parsing, no network calls -- runs on the raw HTML from stage (1)
    (not a rendered variant, even for pages stage (2) rendered): JSON-LD
    is overwhelmingly server-rendered even on otherwise JS-heavy sites,
    and a page RENDER already flagged as an empty shell simply has
    nothing for these checks to find either way, which is harmless, not
    a false negative -- RENDER already reported the more fundamental
    problem for that page."""
    import extract_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    findings = []
    checked = 0
    for url in corpus_urls:
        html = raw_by_url.get(url)
        if html is None:
            continue
        checked += 1
        findings += extract_detect.detect_schema_text_contradiction(url, html)
        findings += extract_detect.detect_missing_required_properties(url, html)
        findings += extract_detect.detect_heading_hierarchy_issues(url, html)
        findings += extract_detect.detect_facts_in_images(url, html)

    return StageResult(
        stage=Stage.EXTRACT,
        findings=findings,
        corpus_delta=list(corpus_urls),
        metrics={"pages_checked": checked},
    )


def run_retrieve_stage(
    reach_corpus_urls: list[str], reach_outcomes: list, empty_shell_urls: frozenset[str], base_url: str
) -> tuple[StageResult, list, retrieve_detect.Entity]:
    """The answerability probe. Composition contract: consumes the
    stage (1) survivors, minus any page stage (2) proved is an empty
    JS-only shell -- there's genuinely nothing on such a page for a
    non-JS-executing retrieval pipeline to chunk, so including it would
    misrepresent what's actually reachable. Pages RENDER didn't get to
    (bounded by --max-render-pages) are NOT excluded -- not being
    checked isn't the same as being proven empty, and shrinking the
    corpus based on a performance-budget artifact rather than an actual
    gating failure would misrepresent the corpus size, not narrow it
    correctly.

    `empty_shell_urls` comes straight from `run_render_stage`'s own
    return value, not re-derived here from `f.severity == "critical"`
    -- since Day 8, RENDER-001's severity is CRITICAL only when the
    empty-shell pattern spans >=90% of the render sample (site-wide)
    and PAGE_CLASS/`high` otherwise (see render_detect.
    detect_empty_shell_pages), so severity no longer doubles as a
    reliable "is this URL empty" signal the way it used to."""
    import retrieve_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    pages = {
        url: raw_by_url[url]
        for url in reach_corpus_urls
        if url in raw_by_url and url not in empty_shell_urls
    }

    matrix, retrieve_findings, entity = retrieve_detect.run_retrieval_simulation(pages, homepage_url=base_url)

    stage_result = StageResult(
        stage=Stage.RETRIEVE,
        findings=retrieve_findings,
        corpus_delta=list(pages),
        metrics={
            "pages_indexed": len(pages),
            "pages_excluded_empty_shell": len(empty_shell_urls),
            "entity_name": entity.name,
            "entity_source": entity.source,
        },
    )
    return stage_result, matrix, entity


def run_cite_stage(corpus_urls: list[str], reach_outcomes: list, base_url: str) -> StageResult:
    """Entity anchoring, freshness, description drift, attribution
    density. Pure parsing over raw HTML (same reasoning as EXTRACT):
    JSON-LD and meta tags live in <head> and are overwhelmingly server-
    rendered even on JS-heavy sites, so this runs on the full stage (1)
    survivor set directly rather than RETRIEVE's more narrowly-gated
    corpus -- CITE doesn't need chunked/indexed content, just the raw
    pages."""
    import trust_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    pages = {url: raw_by_url[url] for url in corpus_urls if url in raw_by_url}

    findings = []
    for f in (
        trust_detect.detect_missing_entity_anchoring(pages),
        trust_detect.detect_staleness(pages),
        trust_detect.detect_description_drift(pages, base_url),
        trust_detect.detect_low_attribution_density(pages),
    ):
        if f is not None:
            findings.append(f)

    return StageResult(
        stage=Stage.CITE,
        findings=findings,
        corpus_delta=list(pages),
        metrics={"pages_checked": len(pages)},
    )


def run_arrive_stage(
    reach_corpus_urls: list[str], reach_outcomes: list, matrix: list, entity: retrieve_detect.Entity
) -> StageResult:
    """Mid-task arrival model. Composition contract: reads the
    answerability_matrix stage (4) already computed -- `citable=True`
    entries ARE the pages most likely to be cited, a more precise
    definition than re-deriving "likely to be cited" from scratch, and
    it's the literal set this stage's own persona framing refers to. No
    new fetches: ENGAGE-003 (context reset) and ENGAGE-007 (scoped
    latency) reuse the FetchRecord stage (1) already captured per page
    (`final_url`, `elapsed_s`); ENGAGE-006 (instrumentation) checks the
    full stage (1) survivor set, since analytics snippets are typically
    injected site-wide, not per-page."""
    import arrive_detect

    record_by_url = {o.url: o.record for o in reach_outcomes if o.record is not None}
    all_pages = {url: record.text for url, record in record_by_url.items()}

    citable_urls = sorted({e.top_chunk_url for e in matrix if e.citable and e.top_chunk_url})
    citable_pages = {u: all_pages[u] for u in citable_urls if u in all_pages}
    citable_records = {u: record_by_url[u] for u in citable_urls if u in record_by_url}

    # Fall back to the full REACH survivor set if nothing in the corpus
    # won a query (e.g. a tiny fixture, or every query came back
    # UNRETRIEVABLE) -- the alternative is auditing nothing at all for
    # arrival/engagement on a site that still has real pages to check.
    if not citable_pages:
        citable_urls = sorted(u for u in reach_corpus_urls if u in all_pages)
        citable_pages = {u: all_pages[u] for u in citable_urls}
        citable_records = {u: record_by_url[u] for u in citable_urls if u in record_by_url}

    findings = arrive_detect.run_arrival_engagement_audit(
        citable_pages, citable_records, all_pages, matrix, entity.name
    )

    return StageResult(
        stage=Stage.ARRIVE,
        findings=findings,
        corpus_delta=citable_urls,
        metrics={"citable_pages_checked": len(citable_pages), "total_pages_checked": len(all_pages)},
    )


async def main_async(args: argparse.Namespace) -> int:
    site = normalize_site(args.site)
    domain = urlparse(site).netloc
    budget = BudgetManager(total_budget_s=args.budget_s)

    run_dir = Path(args.run_dir) if args.run_dir else Path("runs") / domain
    run_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        reach_result, reach_outcomes, sample_seed = await asyncio.wait_for(
            run_reach_stage(site, args.max_pages, run_dir), timeout=budget.remaining()
        )
    except httpx.HTTPError as exc:
        print(f"error: could not reach {site}: {exc}", file=sys.stderr)
        return 1
    except asyncio.TimeoutError:
        # The hard watchdog itself: never run past the budget, and never
        # fail silently -- still emit a valid, honest (empty) report
        # rather than crash or hang.
        print(f"error: stage REACH exceeded the {budget.total_budget_s:.0f}s time budget for {site}", file=sys.stderr)
        report = assemble_report(
            site=domain,
            stage_results=[],
            duration_s=budget.elapsed(),
            sample_seed=sample_seed_for(domain),
            pages_crawled=0,
            pages_rendered=0,
            degradations=["reach_stage_timed_out_budget_exhausted"],
        )
        out_path = Path(args.out) if args.out else run_dir / "report.json"
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        html_path = out_path.with_suffix(".html")
        html_path.write_text(render_html_report(report), encoding="utf-8")
        md_path = out_path.with_suffix(".md")
        md_path.write_text(render_markdown_summary(report), encoding="utf-8")
        print(f"Degraded reports written to {out_path}, {html_path}, {md_path}")
        return 0

    stage_results = [reach_result]
    degradations = list(budget.degradations)
    pages_rendered = 0
    render_result: StageResult | None = None  # stays None if skipped -- appended to stage_results only if it ran
    empty_shell_urls: frozenset[str] = frozenset()

    if args.skip_render:
        degradations.append("render_stage_skipped_by_flag")
    else:
        try:
            render_result, degradation, empty_shell_urls = await asyncio.wait_for(
                run_render_stage(reach_result.corpus_delta, reach_outcomes, args.max_render_pages, budget),
                timeout=budget.remaining(),
            )
        except asyncio.TimeoutError:
            render_result, degradation = None, "render_stage_timed_out_budget_exhausted"
        if render_result is not None:
            stage_results.append(render_result)
            pages_rendered = render_result.metrics.get("pages_rendered", 0)
        if degradation:
            degradations.append(degradation)

    # EXTRACT is pure parsing over already-fetched HTML -- no network
    # wait, so no asyncio.wait_for needed -- but still budget-gated for
    # consistency with "never run past the cap" on a pathologically large
    # corpus, and so a timed-out run doesn't silently claim EXTRACT ran
    # when the budget was actually already gone.
    if budget.over_budget():
        degradations.append("extract_stage_skipped_low_budget")
    else:
        extract_result = run_extract_stage(reach_result.corpus_delta, reach_outcomes)
        stage_results.append(extract_result)

    # RETRIEVE is also pure computation (chunking + BM25 are in-memory,
    # no network) -- same budget-gating rationale as EXTRACT.
    answerability_matrix = []
    retrieve_entity = None  # stays None if skipped -- run_arrive_stage needs to know either way, same pattern as render_result
    if budget.over_budget():
        degradations.append("retrieve_stage_skipped_low_budget")
    else:
        retrieve_result, answerability_matrix, retrieve_entity = run_retrieve_stage(
            reach_result.corpus_delta, reach_outcomes, empty_shell_urls, site
        )
        stage_results.append(retrieve_result)

    # CITE is also pure parsing, no network -- same budget-gating
    # rationale as EXTRACT/RETRIEVE.
    if budget.over_budget():
        degradations.append("cite_stage_skipped_low_budget")
    else:
        cite_result = run_cite_stage(reach_result.corpus_delta, reach_outcomes, site)
        stage_results.append(cite_result)

    # ARRIVE reads RETRIEVE's own output (the answerability_matrix), so
    # it's gated on RETRIEVE having actually run, not just on budget --
    # composition contract, not an independent stage.
    if budget.over_budget():
        degradations.append("arrive_stage_skipped_low_budget")
    elif retrieve_entity is None:
        degradations.append("arrive_stage_skipped_retrieve_unavailable")
    else:
        arrive_result = run_arrive_stage(
            reach_result.corpus_delta, reach_outcomes, answerability_matrix, retrieve_entity
        )
        stage_results.append(arrive_result)

    # finding-verification: the falsification pass, cross-cutting across
    # every stage's own findings. Runs last, after detection is done, so
    # it has the full findings list to re-fetch and re-test against --
    # budget-gated like every other stage, and if skipped, findings ship
    # as-is (still carrying each detector's own `_unverified()` marker)
    # rather than blocking the report on a check that ran out of time.
    all_findings = [f for r in stage_results for f in r.findings]
    observations: list = []
    if all_findings and not budget.over_budget():
        try:
            verified, observations = await asyncio.wait_for(
                verify_findings.run_finding_verification(
                    all_findings, total_pages_available=reach_result.metrics["pages_fetched_ok"]
                ),
                timeout=budget.remaining()
            )
            all_findings = verified
        except asyncio.TimeoutError:
            degradations.append("finding_verification_timed_out_budget_exhausted")
    elif all_findings:
        degradations.append("finding_verification_skipped_low_budget")

    duration_s = time.monotonic() - start

    report = assemble_report(
        site=domain,
        stage_results=stage_results,
        findings=all_findings,
        observations=observations,
        duration_s=duration_s,
        sample_seed=sample_seed,
        pages_crawled=reach_result.metrics["pages_fetched_ok"],  # successfully fetched, not merely attempted
        pages_rendered=pages_rendered,
        degradations=degradations,
        answerability_matrix=answerability_matrix,
    )

    out_path = Path(args.out) if args.out else run_dir / "report.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    # Day 8 DoD: one command -> JSON + HTML + Markdown summary. Both are
    # rendered from the same validated `report` object already in hand
    # -- pure string-building, no I/O or network, so there's no runtime-
    # budget reason to make either one skippable.
    html_path = out_path.with_suffix(".html")
    html_path.write_text(render_html_report(report), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_markdown_summary(report), encoding="utf-8")

    print(f"Audited {domain}: {report.summary.total_findings} findings "
          f"({reach_result.metrics['pages_fetched_ok']}/{reach_result.metrics['pages_sampled']} "
          f"sampled pages reachable, {pages_rendered} rendered) in {duration_s:.1f}s")
    print(f"Reports written to {out_path}, {html_path}, {md_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="Domain or URL to audit, e.g. example.com")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--max-render-pages", type=int, default=10, help="Cap on pages dual-fetched in stage 2 (headless rendering is the slow part)")
    parser.add_argument("--skip-render", action="store_true", help="Skip stage 2 RENDER even if playwright is installed")
    parser.add_argument("--budget-s", type=float, default=270.0, help="Time budget in seconds (default 270s, leaving buffer under the 5-minute hard cap)")
    parser.add_argument("--out", help="Output path for report.json (default: runs/<domain>/report.json)")
    parser.add_argument("--run-dir", help="Directory for run artifacts (default: runs/<domain>)")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
