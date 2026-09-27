.PHONY: up down agent api worker text seed eval lint test

COMPOSE := docker compose -f infra/docker-compose.yml

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

api:
	uv run uvicorn greenroom.api:app --reload --port 8000

worker:
	uv run celery -A greenroom.worker.app worker -Q scoring,reports -l info

agent:
	uv run python -m greenroom.agent

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
