"""Per-layer latency accounting.

The phase 2 gate is explicit that an unsplit total does not count, so samples
are kept per layer and reported per layer. Numbers come from two places: the
LLM leg from our own stage machine, since the conversation call does not run
inside LiveKit's pipeline, and the speech legs from LiveKit's metrics events.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

# What each layer is allowed, per the PRD's original design budget. Measurement
# moved the overall gate to 3.5 s p50, but these stay as the reference for how
# far each leg is from where it should be.
BUDGET_MS: dict[str, tuple[int, int]] = {
    "eou": (0, 200),  # endpointing: silence detected -> turn considered over
    "stt": (60, 120),
    "llm_ttft": (100, 250),
    "tts_ttfb": (40, 100),
}

LAYER_ORDER = ["eou", "stt", "llm_ttft", "llm_full", "tts_ttfb", "turn_total"]


def percentile(values: list[float], pct: float) -> int:
    """Nearest-rank. Exact on small samples, which is what we have."""
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered) + 0.5) - 1))
    return int(ordered[idx])


@dataclass
class LatencyBook:
    samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def record(self, layer: str, ms: float) -> None:
        self.samples[layer].append(ms)

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            layer: {
                "n": len(vals),
                "p50": percentile(vals, 50),
                "p95": percentile(vals, 95),
            }
            for layer, vals in self.samples.items()
            if vals
        }

    def format(self) -> str:
        s = self.summary()
        if not s:
            return "no latency samples"

        ordered = [k for k in LAYER_ORDER if k in s] + [k for k in s if k not in LAYER_ORDER]
        rows = ["", "── latency (ms) ──", f"{'layer':<12}{'n':>4}{'p50':>8}{'p95':>8}   budget"]
        for layer in ordered:
            v = s[layer]
            lo, hi = BUDGET_MS.get(layer, (0, 0))
            budget = f"{lo}-{hi}" if hi else ""
            over = ""
            if hi and v["p50"] > hi:
                over = f"   {v['p50'] / hi:.0f}x over"
            rows.append(f"{layer:<12}{v['n']:>4}{v['p50']:>8}{v['p95']:>8}   {budget}{over}")
        return "\n".join(rows)

    # ---- wiring ----

    def on_livekit_metrics(self, metrics: object) -> None:
        """Absorb a LiveKit MetricsCollectedEvent payload.

        Duck-typed on purpose: the SDK emits several metric classes through one
        event, and we want the fields we recognise without importing or
        isinstance-ing every one of them.
        """
        # LiveKit reports seconds; everything here is milliseconds.
        for attr, layer in (
            ("end_of_utterance_delay", "eou"),
            ("ttfb", "tts_ttfb"),
        ):
            val = getattr(metrics, attr, None)
            if isinstance(val, int | float) and val > 0:
                self.record(layer, val * 1000)

        # STT reports `duration` for the recognition request itself.
        if getattr(metrics, "type", None) == "stt_metrics":
            val = getattr(metrics, "duration", None)
            if isinstance(val, int | float) and val > 0:
                self.record("stt", val * 1000)
