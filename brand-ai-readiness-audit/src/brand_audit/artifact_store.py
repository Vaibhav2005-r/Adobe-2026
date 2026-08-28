"""Artifact store: every fetch this pipeline makes gets hashed and, if the
caller asks, persisted to the run directory. This is what makes "no
artifact, no finding" enforceable -- a Finding.artifacts entry always
traces back to something captured here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FetchRecord:
    url: str
    http_status: int | None
    body: bytes
    fetched_with_ua: str
    headers: dict[str, str] = None  # type: ignore[assignment]
    final_url: str | None = None  # after redirects, if any were followed

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class ArtifactStore:
    """Writes fetch records under `<run_dir>/artifacts/<sha256>.json` so a
    finding's evidence can be independently re-checked after the run."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.artifacts_dir = run_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, str] = {}  # url -> sha256

    def record(self, fetch: FetchRecord) -> str:
        """Persist a fetch, return its sha256 (the artifact's stable id)."""
        digest = fetch.sha256
        path = self.artifacts_dir / f"{digest}.json"
        if not path.exists():
            path.write_text(
                json.dumps(
                    {
                        "url": fetch.url,
                        "http_status": fetch.http_status,
                        "fetched_with_ua": fetch.fetched_with_ua,
                        "headers": fetch.headers,
                        "final_url": fetch.final_url,
                        "sha256": digest,
                        "body_text": fetch.text,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        self._index[fetch.url] = digest
        return digest

    def sha256_for(self, url: str) -> str | None:
        return self._index.get(url)
