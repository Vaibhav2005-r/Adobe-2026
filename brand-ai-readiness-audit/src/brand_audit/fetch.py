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
) -> list[FetchOutcome]:
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
            )
            return FetchOutcome(url=url, record=record)

    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(headers=headers, http2=True, follow_redirects=True) as client:
        return await asyncio.gather(*(fetch_one(client, u) for u in urls))
