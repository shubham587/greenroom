"""Speech provider seam.

Phase 2's gate is p95 under 800 ms, with a budget of 60-120 ms for
speech-to-text and 40-100 ms for the first text-to-speech chunk. OpenAI is the
default because the credits are already paid for, but it is not built for that
first-chunk number the way Deepgram and Cartesia are.

So the provider is a config value, not a code change: phase 2 measures the
combinations and picks with data instead of with an opinion. Plugins are
imported lazily, so an uninstalled provider costs nothing until it is asked for.
"""

from __future__ import annotations

from typing import Any

from greenroom.config import settings


def _missing(provider: str, package: str) -> Exception:
    return SystemExit(
        f"{provider} is selected but its plugin is not installed.\n"
        f"  uv add {package}\n"
        f"Or set the provider back to 'openai' in .env."
    )


def build_stt() -> Any:
    name = settings.stt_provider.lower()

    if name == "openai":
        from livekit.plugins import openai

        return openai.STT(model=settings.stt_model)

    if name == "deepgram":
        try:
            from livekit.plugins import deepgram
        except ImportError:
            raise _missing("deepgram", "livekit-plugins-deepgram") from None
        # interim_results is what lets phase 2 fire the router speculatively
        return deepgram.STT(api_key=settings.deepgram_api_key or None, interim_results=True)

    raise SystemExit(f"unknown STT_PROVIDER: {settings.stt_provider!r} (openai | deepgram)")


def build_tts() -> Any:
    name = settings.tts_provider.lower()

    if name == "openai":
        from livekit.plugins import openai

        return openai.TTS(model=settings.tts_model, voice=settings.tts_voice)

    if name == "cartesia":
        try:
            from livekit.plugins import cartesia
        except ImportError:
            raise _missing("cartesia", "livekit-plugins-cartesia") from None
        return cartesia.TTS(api_key=settings.cartesia_api_key or None)

    raise SystemExit(f"unknown TTS_PROVIDER: {settings.tts_provider!r} (openai | cartesia)")
