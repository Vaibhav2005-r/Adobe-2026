"""Concurrent, polite HTTP fetching. Shared by every stage that needs to
GET pages -- stage (1) reach uses it for status/canonical checks, stage (2)
render uses it for the non-JS half of the dual-fetch differential.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from .artifact_store import FetchRecord
from .crawl import DEFAULT_FETCH_UA

DEFAULT_CONCURRENCY = 8
DEFAULT_PER_HOST_DELAY_S = 0.25  # politeness delay between requests to the same host


@dataclass
class FetchOutcome:
    url: str
    record: FetchRecord | None
    error: str | None = None


async def fetch_many(
    urls: list[str],
    *,
    user_agent: str = DEFAULT_FETCH_UA,
    concurrency: int = DEFAULT_CONCURRENCY,
    per_host_delay_s: float = DEFAULT_PER_HOST_DELAY_S,
    timeout_s: float = 15.0,
    follow_redirects: bool = True,
) -> list[FetchOutcome]:
    """Fetch every URL once. `follow_redirects=False` is what
    crawl-reach-audit uses to see the *immediate* response (status,
    headers, body) rather than whatever a redirect chain resolves to --
    that's the only way to catch an empty-body redirect (REACH-002-style)
    at all, since a followed redirect just silently lands on the content
    the redirect target happens to have.
    """
    semaphore = asyncio.Semaphore(concurrency)
    host_locks: dict[str, asyncio.Lock] = {}

    def lock_for(url: str) -> asyncio.Lock:
        host = httpx.URL(url).host
        return host_locks.setdefault(host, asyncio.Lock())

    async def fetch_one(client: httpx.AsyncClient, url: str) -> FetchOutcome:
        async with semaphore:
            async with lock_for(url):
                try:
                    resp = await client.get(url, timeout=timeout_s)
                    await asyncio.sleep(per_host_delay_s)
                except httpx.HTTPError as exc:
                    return FetchOutcome(url=url, record=None, error=str(exc))
            record = FetchRecord(
                url=url,
                http_status=resp.status_code,
                body=resp.content,
                fetched_with_ua=user_agent,
                headers=dict(resp.headers),
                final_url=str(resp.url) if str(resp.url) != url else None,
            )
            return FetchOutcome(url=url, record=record)

    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(
        headers=headers, http2=True, follow_redirects=follow_redirects
    ) as client:
        return await asyncio.gather(*(fetch_one(client, u) for u in urls))


async def probe_user_agents(url: str, user_agents: list[str], *, timeout_s: float = 15.0) -> dict[str, FetchOutcome]:
    """Fetch the same URL once per UA -- used for WAF/interstitial
    detection (REACH-003-style): a block that reproduces across every UA,
    including a plain browser string with no bot signature, is an
    infrastructure-level gate, not a UA-based robots.txt policy decision.
    """
    results: dict[str, FetchOutcome] = {}
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        for ua in user_agents:
            try:
                resp = await client.get(url, headers={"User-Agent": ua}, timeout=timeout_s)
                record = FetchRecord(
                    url=url,
                    http_status=resp.status_code,
                    body=resp.content,
                    fetched_with_ua=ua,
                    headers=dict(resp.headers),
                )
                results[ua] = FetchOutcome(url=url, record=record)
            except httpx.HTTPError as exc:
                results[ua] = FetchOutcome(url=url, record=None, error=str(exc))
    return results
