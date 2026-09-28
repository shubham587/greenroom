"""What the interview is made of.

A stage carries its own budget, its own opening line and its own exit rule.
That is the point of a state machine over one long prompt: a prompt cannot
watch a clock, and a prompt that is asked to run a whole interview drifts
away from the rubric somewhere in the middle.
"""

from __future__ import annotations

from dataclasses import dataclass

SYSTEM = (
    "You are a technical interviewer. You have just heard the candidate's answer. "
    "Reply with ONE short sentence that acknowledges something specific they said. "
    "Do not ask a question - the next question is appended for you. "
    "Do not praise. Do not summarise at length."
)

OPENING = "Thanks for making the time. To start - tell me a bit about what you've been working on."

# Phase 1's fixed script. Still used when there is no coverage map, which is
# what the tests and a cold `make text` run exercise.
QUESTIONS: list[str] = [
    "What part of that system were you most responsible for?",
    "What's something in it you'd build differently now, and why?",
]

CLOSING = "That's everything from me. Thanks for walking me through it."


# What the interviewer says after the acknowledgement, per route. Templates
# rather than a second model call: the acknowledgement already streamed from
# the model, and a fixed follow-up costs nothing and arrives instantly.
FOLLOW_UP: dict[str, str] = {
    "drill": "Go a level deeper on {topic} - what was the hardest part of it?",
    "probe": "Be concrete about {topic} for me: what changed, and by how much?",
    "chase": "Tell me about {topic} - how did that come into it?",
    "pivot": "Let's move on. Tell me about your experience with {topic}.",
    "rescue": "That's alright. Talk me through what you do know about {topic}.",
}


@dataclass(frozen=True)
class Stage:
    name: str
    budget_s: float
    max_turns: int
    opening: str
    # said when moving ON from this stage - a template, not a model call, so
    # it costs nothing and lands the instant the stage ends
    bridge: str
    # injected at 80% of the budget rather than cutting anybody off
    nudge: str = "We've a couple of minutes left on this, so let's start wrapping it up."


INTRO = Stage(
    name="intro",
    budget_s=180,
    max_turns=2,
    opening=OPENING,
    bridge="Good - that gives me a picture.",
)

DEEP_DIVE = Stage(
    name="deep_dive",
    budget_s=600,
    max_turns=12,
    opening="Let's get into the detail.",
    bridge="Right, I think I have what I need there.",
)

WRAP = Stage(
    name="wrap",
    budget_s=120,
    max_turns=1,
    opening="Last thing - is there anything you wanted to cover that I didn't ask about?",
    bridge=CLOSING,
)

# The voice-only interview. Phase 10 inserts the coding stages between the
# intro and the deep dive.
STAGES: list[Stage] = [INTRO, DEEP_DIVE, WRAP]


def by_name(name: str) -> Stage | None:
    return next((s for s in STAGES if s.name == name), None)
