# Greenroom

A candidate-side AI voice interviewer. It runs a full technical interview —
intro, approach, coding, code review, resume deep-dive — and returns a scored
report with transcript evidence, upgraded versions of your own answers, and a
replay.

The green room is where you wait before you go on.

> **Status: phase 9 of 13.** Upload a resume and a job description, talk to
> the interviewer in a browser, and it follows what you actually say. Scored
> with verified evidence afterwards. Still to come: the coding round, the
> report UI, and deployment.

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

For the real thing, add your `OPENAI_API_KEY` and run four processes, then
open <http://localhost:3000>:

```bash
make api      # FastAPI on :8010
make worker   # Celery - parsing, scoring, reports
make agent    # the LiveKit voice worker
make web      # Next.js on :3000
```

Port 8010, not 8000 — 8000 is crowded on a dev machine and the failure looks
like a 404 from whatever else already owns it. Override with
`make api API_PORT=9999`. Check you have the right server with
`curl localhost:8010/health`, which must return `{"status":"ok"}`.

Other things worth knowing:

```bash
make eval     # scorer agreement against the hand-scored cases
make seed     # verify the problem bank, including the mutation check
make types    # regenerate web/src/lib/api-types.ts from the OpenAPI schema
```

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
