#!/usr/bin/env python3
"""Pipeline driver: crawl a site, run whatever stages are wired up, emit a
schema-valid AuditReport.

Day 5 milestone: stage (1) REACH, stage (2) RENDER, stage (3) EXTRACT,
and stage (4) RETRIEVE (retrieval-simulation -- chunking, BM25,
answerability matrix) are wired up. Stages (5)-(6) don't exist yet, so
their ai_readiness field reports "skipped", not "pass".

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
) -> tuple[StageResult | None, str | None]:
    """Dual-fetch differential over the stage (1) survivors. Returns
    (StageResult, None) on success, or (None, degradation_reason) if
    playwright isn't installed, or budget is too tight to be worth
    starting -- the caller must NOT run this stage's findings in either
    case, per the "never guess" rule."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return None, "render_stage_skipped_no_playwright"

    if budget.remaining() < MIN_RENDER_BUDGET_S:
        return None, "render_stage_skipped_low_budget"

    import render_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    targets = [u for u in corpus_urls if u in raw_by_url][:max_render_pages]
    if not targets:
        return StageResult(stage=Stage.RENDER, findings=[], corpus_delta=[], metrics={"pages_rendered": 0}), None

    rendered_html = await render_detect.render_fetch(targets)

    today_iso = datetime.now(timezone.utc).date().isoformat()
    findings = []
    render_failed = 0
    compared: list[str] = []
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
        comparison = render_detect.compare(url, raw_by_url[url], rendered, today_iso=today_iso)
        findings += render_detect.detect_render_gap(comparison)

    stage_result = StageResult(
        stage=Stage.RENDER,
        findings=findings,
        corpus_delta=compared,
        metrics={"pages_rendered": len(compared), "pages_render_failed": render_failed},
    )
    return stage_result, None


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
    reach_corpus_urls: list[str], reach_outcomes: list, render_result: StageResult | None, base_url: str
) -> tuple[StageResult, list]:
    """The answerability probe. Composition contract: consumes the
    stage (1) survivors, minus any page stage (2) proved is an empty
    JS-only shell -- there's genuinely nothing on such a page for a
    non-JS-executing retrieval pipeline to chunk, so including it would
    misrepresent what's actually reachable. Pages RENDER didn't get to
    (bounded by --max-render-pages) are NOT excluded -- not being
    checked isn't the same as being proven empty, and shrinking the
    corpus based on a performance-budget artifact rather than an actual
    gating failure would misrepresent the corpus size, not narrow it
    correctly."""
    import retrieve_detect

    empty_shell_urls = set()
    if render_result is not None:
        for f in render_result.findings:
            if f.taxonomy_id == "RENDER-001" and f.severity == "critical":
                empty_shell_urls.update(a.url for a in f.artifacts)

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    pages = {
        url: raw_by_url[url]
        for url in reach_corpus_urls
        if url in raw_by_url and url not in empty_shell_urls
    }

    matrix, finding, entity = retrieve_detect.run_retrieval_simulation(pages, homepage_url=base_url)

    stage_result = StageResult(
        stage=Stage.RETRIEVE,
        findings=[finding] if finding else [],
        corpus_delta=list(pages),
        metrics={
            "pages_indexed": len(pages),
            "pages_excluded_empty_shell": len(empty_shell_urls),
            "entity_name": entity.name,
            "entity_source": entity.source,
        },
    )
    return stage_result, matrix


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
        print(f"Degraded report written to {out_path}")
        return 0

    stage_results = [reach_result]
    degradations = list(budget.degradations)
    pages_rendered = 0
    render_result: StageResult | None = None  # stays None if skipped -- run_retrieve_stage needs to know either way

    if args.skip_render:
        degradations.append("render_stage_skipped_by_flag")
    else:
        try:
            render_result, degradation = await asyncio.wait_for(
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
    if budget.over_budget():
        degradations.append("retrieve_stage_skipped_low_budget")
    else:
        retrieve_result, answerability_matrix = run_retrieve_stage(
            reach_result.corpus_delta, reach_outcomes, render_result, site
        )
        stage_results.append(retrieve_result)

    duration_s = time.monotonic() - start

    report = assemble_report(
        site=domain,
        stage_results=stage_results,
        duration_s=duration_s,
        sample_seed=sample_seed,
        pages_crawled=reach_result.metrics["pages_fetched_ok"],  # successfully fetched, not merely attempted
        pages_rendered=pages_rendered,
        degradations=degradations,
        answerability_matrix=answerability_matrix,
    )

    out_path = Path(args.out) if args.out else run_dir / "report.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"Audited {domain}: {report.summary.total_findings} findings "
          f"({reach_result.metrics['pages_fetched_ok']}/{reach_result.metrics['pages_sampled']} "
          f"sampled pages reachable, {pages_rendered} rendered) in {duration_s:.1f}s")
    print(f"Report written to {out_path}")
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
