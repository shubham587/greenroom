"""Tracing into Langfuse, over plain OpenTelemetry.

Langfuse ingests OTLP directly, and LiveKit's agents already emit OTel spans
and accept a tracer provider. So this needs no Langfuse SDK: standard
exporter, their endpoint, basic auth from the two keys. One less dependency
that can disagree with LiveKit's own OTel version.

Unconfigured is the normal case, not an error - `setup()` returns False and
everything runs untraced.
"""

from __future__ import annotations

import atexit
import base64
import logging

from greenroom.config import settings

log = logging.getLogger(__name__)

_tracer = None
_provider = None


def setup() -> bool:
    """Point OTel at Langfuse. Safe to call more than once."""
    global _tracer, _provider

    if _tracer is not None:
        return True
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        log.info("langfuse keys unset - running untraced")
        return False

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()

    provider = TracerProvider(resource=Resource.create({"service.name": "greenroom"}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {auth}"},
            )
        )
    )

    # LiveKit emits its own speech-to-text, text-to-speech and turn spans into
    # whatever provider it is given, so this picks those up for free.
    try:
        from livekit.agents import telemetry

        telemetry.set_tracer_provider(provider)
    except Exception:  # text adapter runs without livekit installed in future
        log.debug("livekit telemetry not available; tracing our spans only")

    _provider = provider
    _tracer = provider.get_tracer("greenroom")

    # Spans are batched, and a short-lived process exits before the batch is
    # sent - the first run of this traced nothing at all for exactly that
    # reason. Nobody else calls shutdown, so register it here.
    atexit.register(flush)

    log.info("tracing to %s", settings.langfuse_host)
    return True


def flush() -> None:
    """Send anything still batched. Called at exit, and safe to call by hand."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=5000)


def tracer():
    """The tracer, or None when tracing is off. Callers must handle None."""
    return _tracer
