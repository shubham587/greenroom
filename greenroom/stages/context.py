"""What the model is told each turn, and in what order.

Two rules, both load-bearing.

Static content goes FIRST. Providers cache repeated prefixes automatically,
and a conversational turn happens forty times a session - putting the rubric
and the resume after the recent turns means paying full price for all forty.

Context must stop growing. Sending the whole transcript makes a session
quadratically expensive and slower every turn, so earlier stages collapse
into a rolling summary and only the last few turns are sent verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# how many turns are sent word for word before the summary takes over
VERBATIM_TURNS = 6


@dataclass
class Context:
    """The assembled prompt, and the accounting that proves it stays bounded."""

    static: str = ""
    summary: str = ""
    recent: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        if self.static:
            parts.append(self.static)
        if self.summary:
            parts.append(f"Earlier in this interview:\n{self.summary}")
        if self.recent:
            parts.append("Just now:\n" + "\n".join(self.recent))
        return "\n\n".join(parts)

    def size(self) -> int:
        return len(self.render())


def build_static(resume: dict | None, jd: dict | None, problem_title: str | None) -> str:
    """The part that never changes, so the provider can cache it."""
    bits = []
    if jd:
        bits.append(f"Role: {jd.get('title', 'unspecified')} ({jd.get('level', 'mid')})")
        if jd.get("required"):
            bits.append("Required: " + ", ".join(jd["required"]))
    if resume:
        if resume.get("years_experience"):
            bits.append(f"Candidate experience: {resume['years_experience']} years")
        if resume.get("skills"):
            bits.append("Stated skills: " + ", ".join(resume["skills"][:12]))
    if problem_title:
        bits.append(f"Coding problem: {problem_title}")
    return "\n".join(bits)


def recent_lines(transcript: list, limit: int = VERBATIM_TURNS) -> list[str]:
    return [f"{t.speaker}: {t.text}" for t in transcript[-limit:]]


def summarise_locally(transcript: list, stage_name: str) -> str:
    """A summary of one finished stage, without a model call.

    Deliberately not an LLM call. The summary is needed at a stage boundary,
    a model call there is either dead air or a race, and what the next stage
    needs is a reminder of ground covered rather than prose. If this turns
    out to be too thin, a model summary can be fired asynchronously and swapped
    in when it lands - the shape here already allows for that.
    """
    said = [t.text for t in transcript if t.speaker == "candidate"]
    if not said:
        return f"{stage_name}: nothing recorded."
    joined = " ".join(said)
    clipped = joined[:400] + ("…" if len(joined) > 400 else "")
    return f"{stage_name} ({len(said)} answers): {clipped}"
