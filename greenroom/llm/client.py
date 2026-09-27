"""The LLM seam.

The conversation call lives here, in our code, rather than inside LiveKit's
pipeline. That keeps the stage machine provider-agnostic, makes the call
cassette-able in phase 2, and lets the text adapter run with no API key.
"""

from __future__ import annotations

import logging
from typing import Protocol

from greenroom.config import settings

log = logging.getLogger(__name__)


class LLM(Protocol):
    async def complete(self, system: str, user: str, *, max_tokens: int = 150) -> str: ...


class OpenAILLM:
    def __init__(self, model: str, api_key: str) -> None:
        from openai import AsyncOpenAI

        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)

    async def complete(self, system: str, user: str, *, max_tokens: int = 150) -> str:
        # Static content first so the provider's prefix cache can hit it.
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()


class StubLLM:
    """Deterministic stand-in so the interview runs with no API key.

    Not a mock for tests to assert against cleverly — it exists so `make text`
    works on a laptop with an empty .env.
    """

    async def complete(self, system: str, user: str, *, max_tokens: int = 150) -> str:
        return "Got it, thanks."


def get_llm(model: str | None = None) -> LLM:
    model = model or settings.model_conversation
    if not settings.openai_api_key or not model:
        log.warning("OPENAI_API_KEY or MODEL_CONVERSATION unset - using StubLLM")
        return StubLLM()
    return OpenAILLM(model, settings.openai_api_key)
