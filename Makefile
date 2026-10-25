# Developer shortcuts. Run `make <target>` from the project root.

# Load .env (if present) and export its variables to every command below,
# so DATABASE_URL reaches the migration runner and the tests.
-include .env
export

.PHONY: up down migrate test fmt lint typecheck check

up:  ## start Postgres and wait until it is healthy
	docker compose up -d --wait

down:  ## stop Postgres (data stays in the named volume)
	docker compose down

migrate:  ## apply pending migrations to the dev database
	uv run python -m store.migrate

test:  ## run the test suite against a throwaway test database
	uv run pytest

fmt:  ## format the code
	uv run ruff format .

lint:  ## check formatting and lint rules
	uv run ruff format --check .
	uv run ruff check .

typecheck:  ## strict type check of the domain (src/ledger)
	uv run mypy

check: lint typecheck test  ## everything, in order; stops at the first failure
