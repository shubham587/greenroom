from dataclasses import dataclass

from greenroom.latency import LatencyBook, percentile


def test_percentile_is_nearest_rank():
    assert percentile([], 50) == 0
    assert percentile([5], 95) == 5
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4], 95) == 4


def test_summary_is_per_layer_never_a_single_total():
    b = LatencyBook()
    for ms in (100, 200, 300):
        b.record("llm_ttft", ms)
    b.record("tts_ttfb", 50)

    s = b.summary()
    assert set(s) == {"llm_ttft", "tts_ttfb"}
    assert s["llm_ttft"] == {"n": 3, "p50": 200, "p95": 300}
    assert s["tts_ttfb"]["n"] == 1


def test_format_flags_a_layer_over_its_budget():
    b = LatencyBook()
    b.record("tts_ttfb", 1400)  # budget is 40-100 ms
    out = b.format()
    assert "tts_ttfb" in out
    assert "x over" in out


def test_format_survives_no_samples():
    assert "no latency samples" in LatencyBook().format()


@dataclass
class FakeTTSMetrics:
    type: str = "tts_metrics"
    ttfb: float = 0.12  # LiveKit reports seconds


@dataclass
class FakeSTTMetrics:
    type: str = "stt_metrics"
    duration: float = 0.9


@dataclass
class FakeEOUMetrics:
    type: str = "eou_metrics"
    end_of_utterance_delay: float = 0.45


def test_livekit_metrics_are_converted_to_ms_per_layer():
    b = LatencyBook()
    b.on_livekit_metrics(FakeTTSMetrics())
    b.on_livekit_metrics(FakeSTTMetrics())
    b.on_livekit_metrics(FakeEOUMetrics())

    s = b.summary()
    assert s["tts_ttfb"]["p50"] == 120
    assert s["stt"]["p50"] == 900
    assert s["eou"]["p50"] == 450


def test_unknown_metric_types_are_ignored_rather_than_crashing():
    @dataclass
    class Weird:
        type: str = "vad_metrics"
        idle_time: float = 3.0

    b = LatencyBook()
    b.on_livekit_metrics(Weird())
    b.on_livekit_metrics(object())
    assert b.summary() == {}
