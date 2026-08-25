.PHONY: help install api web dev test lint typecheck check up down clean

help:
	@echo "make install    install backend + frontend dependencies"
	@echo "make api        run the API on :8000"
	@echo "make web        run the frontend on :3000"
	@echo "make test       run the backend test suite"
	@echo "make test-web   run the frontend test suite"
	@echo "make check      test + lint + typecheck (backend and frontend)"
	@echo "make up         run both services with docker compose"

VENV := .venv
PY := $(VENV)/bin/python

install:
	python3 -m venv $(VENV) 2>/dev/null || true
	$(VENV)/bin/pip install -q -e "apps/api[dev]"
	cd apps/web && npm install

api:
	$(VENV)/bin/uvicorn clinical_snapshot.main:app --reload --port 8000 --app-dir apps/api/src

web:
	cd apps/web && npm run dev

test:
	cd apps/api && ../../$(PY) -m pytest tests -q

test-web:
	cd apps/web && npm test

lint:
	cd apps/api && ../../$(PY) -m ruff check src tests

typecheck:
	cd apps/api && ../../$(PY) -m mypy
	cd apps/web && npx tsc --noEmit

check: test test-web lint typecheck

up:
	docker compose up --build

down:
	docker compose down

clean:
	rm -rf apps/web/.next apps/web/node_modules
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
