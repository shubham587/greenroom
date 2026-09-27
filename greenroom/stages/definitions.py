"""Phase 1 script.

Three hardcoded questions. Phase 5 replaces this with stage configs that carry
a time budget, exit criteria and their own prompt; the machine's interface does
not change when it does.
"""

SYSTEM = (
    "You are a technical interviewer. You have just heard the candidate's answer. "
    "Reply with ONE short sentence that acknowledges something specific they said. "
    "Do not ask a question - the next question is appended for you. "
    "Do not praise. Do not summarise at length."
)

OPENING = "Thanks for making the time. To start - tell me a bit about what you've been working on."

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
