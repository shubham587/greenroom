"""The LLM seam.

The conversation call lives here, in our code, rather than inside LiveKit's
pipeline. That keeps the stage machine provider-agnostic, makes the call
cassette-able in phase 2, and lets the text adapter run with no API key.

`stream` is the primitive, not `complete`. Time to first token is the number
the latency budget cares about; a complete response is just a stream someone
waited for.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Protocol

from greenroom.config import settings

log = logging.getLogger(__name__)


class LLM(Protocol):
    def stream(self, system: str, user: str, *, max_tokens: int = 150) -> AsyncIterator[str]: ...


async def complete(llm: LLM, system: str, user: str, *, max_tokens: int = 150) -> str:
    """Drain a stream into a string. For callers with no latency budget."""
    return "".join([c async for c in llm.stream(system, user, max_tokens=max_tokens)])


class OpenAILLM:
    def __init__(self, model: str, api_key: str) -> None:
        from openai import AsyncOpenAI

        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)

    async def stream(self, system: str, user: str, *, max_tokens: int = 150) -> AsyncIterator[str]:
        extra = {}
        if settings.llm_reasoning_effort:
            extra["reasoning_effort"] = settings.llm_reasoning_effort

        # Static content first so the provider's prefix cache can hit it.
        # gpt-5/6 rejects max_tokens and wants max_completion_tokens.
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            **extra,
        )

        said_anything = False
        usage = None
        async for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content
            if piece:
                said_anything = True
                yield piece

        if not said_anything:
            # Almost always a reasoning model spending the whole token budget
            # before it says anything. In voice this is silence, which reads as
            # a hang, so fail loudly rather than yield nothing.
            details = getattr(usage, "completion_tokens_details", None)
            raise RuntimeError(
                f"{self._model} streamed no content: "
                f"completion_tokens={getattr(usage, 'completion_tokens', '?')}, "
                f"reasoning_tokens={getattr(details, 'reasoning_tokens', '?')}, "
                f"max_completion_tokens={max_tokens}, "
                f"reasoning_effort={settings.llm_reasoning_effort!r}. "
                f"Raise the budget or turn reasoning off."
            )


class StubLLM:
    """Deterministic stand-in so the interview runs with no API key.

    Yields in pieces rather than one blob, so the streaming path is the path
    exercised even on an empty .env.
    """

    async def stream(self, system: str, user: str, *, max_tokens: int = 150) -> AsyncIterator[str]:
        for piece in ("Got ", "it, ", "thanks."):
            yield piece


def get_llm(model: str | None = None) -> LLM:
    model = model or settings.model_conversation
    if not settings.openai_api_key or not model:
        log.warning("OPENAI_API_KEY or MODEL_CONVERSATION unset - using StubLLM")
        return StubLLM()

    llm: LLM = OpenAILLM(model, settings.openai_api_key)

    if settings.cassette_mode in {"record", "replay"}:
        from greenroom.llm.cassette import CassetteLLM

        log.info("cassettes: %s", settings.cassette_mode)
        llm = CassetteLLM(llm, model, settings.cassette_mode)

    return llm
