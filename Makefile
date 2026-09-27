.PHONY: up down agent api worker text seed eval lint test

COMPOSE := docker compose -f infra/docker-compose.yml

# 8000 is a crowded port on a dev laptop. Override with: make api API_PORT=9999
API_PORT ?= 8010

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

api:
	uv run uvicorn greenroom.api:app --reload --port $(API_PORT)

# --pool=threads: the prefork pool's billiard breaks on macOS under spawn
# ("not enough values to unpack"), and every task here is I/O bound anyway -
# a database write and, later, an API call. Production can use prefork.
worker:
	uv run celery -A greenroom.worker.app worker -Q scoring,reports -l info --pool=threads --concurrency=4

# Needs OPENAI_API_KEY (speech-to-text and text-to-speech). Talk to it at
# http://localhost:$(API_PORT)/dev with `make api` running alongside.
agent:
	uv run python -m greenroom.agent dev

# The dev loop. Drives the same stage machine as voice, with no STT or TTS cost.
text:
	uv run python -m greenroom.adapters.text

seed:
	uv run python scripts/seed.py problems/

eval:
	uv run python evals/run.py

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"
