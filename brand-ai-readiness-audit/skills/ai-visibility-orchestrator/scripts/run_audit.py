#!/usr/bin/env python3
"""Pipeline driver: crawl a site, run whatever stages are wired up, emit a
schema-valid AuditReport.

Day 3 milestone: stage (1) REACH (crawl-reach-audit) and stage (2)
RENDER (render-gap-audit) detectors are wired up. Stages (3)-(6) don't
exist yet, so their ai_readiness field reports "skipped", not "pass".

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

from brand_audit.crawl import (  # noqa: E402
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
        sitemap_urls = await discover_sitemap_urls(client, base_url, robots)

    domain = urlparse(base_url).netloc
    seed = sample_seed_for(domain)
    sample = stratified_sample(sitemap_urls, seed, max_pages=max_pages)

    outcomes = await fetch_many(sample)  # follows redirects -- final content
    no_redirect_outcomes = await fetch_many(sample, follow_redirects=False)  # immediate response

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
    findings += reach_detect.detect_ai_ua_block(base_url, robots, base_url)
    findings += reach_detect.detect_locale_redirect(base_url, no_redirect_outcomes)
    findings += reach_detect.detect_soft_404(base_url, outcomes)
    findings += reach_detect.detect_canonical_issues(base_url, outcomes)
    findings += reach_detect.detect_sitemap_health(base_url, robots, sitemap_reachable=bool(sitemap_urls))

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
            "pages_fetched_ok": fetched_ok,
            "robots_fetched": robots.fetched,
        },
    )
    return stage_result, outcomes, seed


async def run_render_stage(
    corpus_urls: list[str], reach_outcomes: list, max_render_pages: int
) -> tuple[StageResult | None, str | None]:
    """Dual-fetch differential over the stage (1) survivors. Returns
    (StageResult, None) on success, or (None, degradation_reason) if
    playwright isn't installed -- the caller must NOT run this stage's
    findings in that case, per the "never guess" rule."""
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return None, "render_stage_skipped_no_playwright"

    import render_detect

    raw_by_url = {o.url: o.record.text for o in reach_outcomes if o.record is not None}
    targets = [u for u in corpus_urls if u in raw_by_url][:max_render_pages]
    if not targets:
        return StageResult(stage=Stage.RENDER, findings=[], corpus_delta=[], metrics={"pages_rendered": 0}), None

    rendered_html = await render_detect.render_fetch(targets)

    today_iso = datetime.now(timezone.utc).date().isoformat()
    findings = []
    for url in targets:
        comparison = render_detect.compare(
            url, raw_by_url[url], rendered_html.get(url, ""), today_iso=today_iso
        )
        findings += render_detect.detect_render_gap(comparison)

    stage_result = StageResult(
        stage=Stage.RENDER,
        findings=findings,
        corpus_delta=list(targets),
        metrics={"pages_rendered": len(targets)},
    )
    return stage_result, None


async def main_async(args: argparse.Namespace) -> int:
    site = normalize_site(args.site)
    domain = urlparse(site).netloc
    budget = BudgetManager(total_budget_s=args.budget_s)

    run_dir = Path(args.run_dir) if args.run_dir else Path("runs") / domain
    run_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        reach_result, reach_outcomes, sample_seed = await run_reach_stage(site, args.max_pages, run_dir)
    except httpx.HTTPError as exc:
        print(f"error: could not reach {site}: {exc}", file=sys.stderr)
        return 1

    stage_results = [reach_result]
    degradations = list(budget.degradations)
    pages_rendered = 0

    if args.skip_render:
        degradations.append("render_stage_skipped_by_flag")
    else:
        render_result, degradation = await run_render_stage(
            reach_result.corpus_delta, reach_outcomes, args.max_render_pages
        )
        if render_result is not None:
            stage_results.append(render_result)
            pages_rendered = render_result.metrics.get("pages_rendered", 0)
        if degradation:
            degradations.append(degradation)

    duration_s = time.monotonic() - start

    report = assemble_report(
        site=domain,
        stage_results=stage_results,
        duration_s=duration_s,
        sample_seed=sample_seed,
        pages_crawled=reach_result.metrics["pages_sampled"],
        pages_rendered=pages_rendered,
        degradations=degradations,
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
