# Greenroom

A candidate-side AI voice interviewer. It runs a full technical interview —
intro, approach, coding, code review, resume deep-dive — and returns a scored
report with transcript evidence, upgraded versions of your own answers, and a
replay.

The green room is where you wait before you go on.

> **Status: phase 0 of 13.** Scaffolding only. Nothing works yet.

## Why this exists

Practice tools read questions off a list. A real interviewer hears a vague
answer and probes it. The routing decision behind that probe — drill, chase,
pivot, rescue — is explicit, logged and inspectable here, which is the point of
the project.

## Architecture in one line

Two loops at different speeds: a voice conversation that must answer inside
800 ms, and an evaluation loop that runs asynchronously on completed turns and
never blocks it.

```
Browser ──WebRTC──► LiveKit ──► agent (fast loop) ──► Redis ──► Celery (slow loop) ──► Postgres
```

## Running it locally

```bash
make up       # postgres, redis, minio, livekit
make api      # FastAPI
make worker   # Celery
make text     # the interview in text mode — no audio, no cost
```

Copy `.env.example` to `.env` first.

## Layout

| Path | What |
| --- | --- |
| `greenroom/` | All server code. Three processes, one package. |
| `greenroom/stages/` | The interview state machine — transport-agnostic |
| `greenroom/adapters/` | Voice (LiveKit) and text drivers for that machine |
| `greenroom/prompts/` | Prompts as `.md` files, so `prompt_version` is a git hash |
| `web/` | Next.js client (phase 9) |
| `problems/` | Coding problem bank, YAML, tests verified offline |
| `evals/` | Hand-scored transcripts and the agreement harness |

## License

MIT
