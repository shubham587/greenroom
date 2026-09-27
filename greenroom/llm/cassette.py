"""Record and replay model calls, so iterating costs nothing.

Phase 8 needs to re-run the same transcripts after every prompt change and
compare agreement. Paying the API each time makes that a thing you avoid
doing, which defeats the point of having an eval set at all. A cassette is
keyed on everything that determines the answer, so a replay is only ever
served for an identical call.

Modes:
    off     - always call the model, save nothing
    record  - always call the model, save the result
    replay  - serve from disk when present, otherwise call and save

`replay` is the one to develop in: the first run pays, every run after is
free, and a changed prompt misses the cache and records itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from greenroom.llm.client import LLM

log = logging.getLogger(__name__)

CASSETTE_DIR = Path("evals/cassettes")


def _key(model: str, system: str, user: str, max_tokens: int) -> str:
    blob = json.dumps([model, system, user, max_tokens], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class CassetteLLM:
    """Wraps an LLM and remembers what it said."""

    def __init__(self, inner: LLM, model: str, mode: str, directory: Path | None = None) -> None:
        self._inner = inner
        self._model = model
        self._mode = mode
        self._dir = directory or CASSETTE_DIR

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    async def stream(self, system: str, user: str, *, max_tokens: int = 150) -> AsyncIterator[str]:
        key = _key(self._model, system, user, max_tokens)
        path = self._path(key)

        if self._mode == "replay" and path.exists():
            data = json.loads(path.read_text())
            log.debug("cassette hit %s", key)
            for chunk in data["chunks"]:
                yield chunk
            return

        chunks: list[str] = []
        async for chunk in self._inner.stream(system, user, max_tokens=max_tokens):
            chunks.append(chunk)
            yield chunk

        if self._mode in {"record", "replay"}:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "model": self._model,
                        "max_tokens": max_tokens,
                        # kept readable on purpose: a cassette you cannot read
                        # is a cache, and phase 8 needs these as fixtures
                        "system": system,
                        "user": user,
                        "chunks": chunks,
                        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    indent=2,
                )
            )
            log.debug("cassette saved %s", key)
