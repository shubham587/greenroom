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
