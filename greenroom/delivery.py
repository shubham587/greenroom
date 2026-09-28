"""Delivery metrics: arithmetic over the transcript, no model involved.

Worth noticing that a good share of the report's value needs no inference at
all. Filler words, pace and pause length are counted, and counted numbers do
not hallucinate.
"""

from __future__ import annotations

import re

FILLERS = {
    "um", "uh", "er", "ah", "like", "basically", "actually", "literally",
    "sort", "kind", "right", "yeah", "so", "just",
}  # fmt: skip


def metrics(turns: list[dict]) -> dict:
    """turns: dicts with speaker, text, t_start, t_end - the candidate's only."""
    said = [t for t in turns if t["speaker"] == "candidate"]
    if not said:
        return {}

    words: list[str] = []
    speaking_s = 0.0
    longest = 0.0
    for t in said:
        words += re.findall(r"[a-z']+", t["text"].lower())
        duration = max(0.0, t["t_end"] - t["t_start"])
        speaking_s += duration
        longest = max(longest, duration)

    fillers = sum(1 for w in words if w in FILLERS)

    # gap between the interviewer finishing and the candidate starting
    pauses: list[float] = []
    for prev, nxt in zip(turns, turns[1:], strict=False):
        if prev["speaker"] == "interviewer" and nxt["speaker"] == "candidate":
            pauses.append(max(0.0, nxt["t_start"] - prev["t_end"]))

    out = {
        "turns": len(said),
        "words": len(words),
        "filler_words": fillers,
        "fillers_per_100_words": round(100 * fillers / len(words), 1) if words else 0.0,
    }

    # Anything that needs duration is only real for a voice session. Text mode
    # has no speaking time, and reporting "longest answer: 0.0s" as though it
    # were measured is worse than not reporting it.
    if speaking_s > 0:
        out["words_per_minute"] = round(len(words) / (speaking_s / 60))
        out["longest_answer_s"] = round(longest, 1)
        if pauses:
            out["avg_pause_before_answering_s"] = round(sum(pauses) / len(pauses), 2)

    return out
