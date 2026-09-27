# Greenroom

A candidate-side AI voice interviewer. It runs a full technical interview —
intro, approach, coding, code review, resume deep-dive — and returns a scored
report with transcript evidence, upgraded versions of your own answers, and a
replay.

The green room is where you wait before you go on.

> **Status: phase 1 of 13.** A three-question interview runs end to end in text
> mode. Voice is wired but unverified — it needs an `OPENAI_API_KEY`.

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
make up       # postgres, redis, s3, livekit
make text     # the interview in text mode — no audio, no API key needed
```

`make text` falls back to a stub model when `OPENAI_API_KEY` is unset, so the
interview logic runs on an empty `.env`. Copy `.env.example` to `.env` first.

For voice, add your key and run two processes, then open
<http://localhost:8000/dev>:

```bash
make api      # FastAPI — mints LiveKit tokens, serves the throwaway client
make agent    # the LiveKit worker
```

The client at `/dev` is deliberately one throwaway HTML file. The real one is
phase 9.

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
