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
        extra = {}
        if settings.llm_reasoning_effort:
            extra["reasoning_effort"] = settings.llm_reasoning_effort

        # Static content first so the provider's prefix cache can hit it.
        # gpt-5/6 rejects max_tokens and wants max_completion_tokens.
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=max_tokens,
            **extra,
        )
        text = (resp.choices[0].message.content or "").strip()

        if not text:
            # Almost always a reasoning model spending the whole token budget
            # before it says anything. In voice this is silence, which reads as
            # a hang, so fail loudly rather than return nothing.
            used = getattr(resp.usage, "completion_tokens", "?")
            details = getattr(resp.usage, "completion_tokens_details", None)
            thinking = getattr(details, "reasoning_tokens", "?")
            raise RuntimeError(
                f"{self._model} returned empty content: "
                f"completion_tokens={used}, reasoning_tokens={thinking}, "
                f"max_completion_tokens={max_tokens}, "
                f"reasoning_effort={settings.llm_reasoning_effort!r}. "
                f"Raise the budget or turn reasoning off."
            )
        return text


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
