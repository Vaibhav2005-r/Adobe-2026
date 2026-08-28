#!/usr/bin/env python3
"""Pipeline driver: crawl a site, run whatever stages are wired up, emit a
schema-valid AuditReport.

Day 2 milestone: only the crawl core runs (robots, sitemap, deterministic
sample, fetch). No detectors exist yet, so every finding list is empty --
the skeleton is meant to be end-to-end *before* any detector, so each
later day adds a stage the skeleton already knows how to run and gate.

Usage:
    python run_audit.py example.com
    python run_audit.py https://example.com --max-pages 40 --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from brand_audit.crawl import (  # noqa: E402
    BudgetManager,
    discover_sitemap_urls,
    fetch_robots,
    sample_seed_for,
    stratified_sample,
)
from brand_audit.fetch import fetch_many  # noqa: E402
from brand_audit.artifact_store import ArtifactStore  # noqa: E402
from brand_audit.models import Stage, StageResult  # noqa: E402

import httpx

from assemble_report import assemble_report  # noqa: E402


def normalize_site(site: str) -> str:
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


async def run_reach_stage(
    base_url: str, budget: BudgetManager, max_pages: int, run_dir: Path
) -> tuple[StageResult, int]:
    """Robots + sitemap discovery + deterministic sample + fetch. Returns
    the StageResult (empty findings -- Day 2 has no detector yet) and the
    count of pages successfully fetched (2xx-4xx, i.e. reachable at all)."""

    async with httpx.AsyncClient(follow_redirects=True) as client:
        robots = await fetch_robots(client, base_url)
        sitemap_urls = await discover_sitemap_urls(client, base_url, robots)

    domain = urlparse(base_url).netloc
    seed = sample_seed_for(domain)
    sample = stratified_sample(sitemap_urls, seed, max_pages=max_pages)

    outcomes = await fetch_many(sample)

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

    stage_result = StageResult(
        stage=Stage.REACH,
        findings=[],  # detectors land Day 3 (crawl-reach-audit)
        artifacts=[],
        corpus_delta=corpus_delta,
        metrics={
            "pages_discovered": len(sitemap_urls),
            "pages_sampled": len(sample),
            "pages_fetched_ok": fetched_ok,
            "robots_fetched": robots.fetched,
        },
    )
    return stage_result, len(sample)


async def main_async(args: argparse.Namespace) -> int:
    site = normalize_site(args.site)
    domain = urlparse(site).netloc
    budget = BudgetManager(total_budget_s=args.budget_s)

    run_dir = Path(args.run_dir) if args.run_dir else Path("runs") / domain
    run_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        reach_result, pages_sampled = await run_reach_stage(site, budget, args.max_pages, run_dir)
    except httpx.HTTPError as exc:
        print(f"error: could not reach {site}: {exc}", file=sys.stderr)
        return 1

    duration_s = time.monotonic() - start
    domain_seed = sample_seed_for(domain)

    report = assemble_report(
        site=domain,
        stage_results=[reach_result],
        duration_s=duration_s,
        sample_seed=domain_seed,
        pages_crawled=pages_sampled,
        pages_rendered=0,  # stage 2 not wired up yet
        degradations=budget.degradations,
    )

    out_path = Path(args.out) if args.out else run_dir / "report.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"Audited {domain}: {report.summary.total_findings} findings "
          f"({reach_result.metrics['pages_fetched_ok']}/{reach_result.metrics['pages_sampled']} "
          f"sampled pages reachable) in {duration_s:.1f}s")
    print(f"Report written to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="Domain or URL to audit, e.g. example.com")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--budget-s", type=float, default=270.0, help="Time budget in seconds (default 270s, leaving buffer under the 5-minute hard cap)")
    parser.add_argument("--out", help="Output path for report.json (default: runs/<domain>/report.json)")
    parser.add_argument("--run-dir", help="Directory for run artifacts (default: runs/<domain>)")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
