.PHONY: install dev docker-up docker-down lint test

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

dev:
	. .venv/bin/activate && uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

docker-up:
	docker compose up --build

docker-down:
	docker compose down

lint:
	. .venv/bin/activate && ruff check backend

test:
	. .venv/bin/activate && pytest

