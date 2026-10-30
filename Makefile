# Developer shortcuts. Run `make <target>` from the project root.

# Load .env (if present) and export its variables to every command below,
# so DATABASE_URL reaches the migration runner and the tests.
-include .env
export

.PHONY: up down migrate admin chat bridge test fmt lint typecheck bridge-install bridge-check check

up:  ## start Postgres and wait until it is healthy
	docker compose up -d --wait

down:  ## stop Postgres (data stays in the named volume)
	docker compose down

migrate:  ## apply pending migrations to the dev database
	uv run python -m store.migrate

admin:  ## operator commands, e.g. make admin ARGS="show 'Trip'"
	uv run python -m cli.admin $(ARGS)

chat:  ## talk to the bot as a member, e.g. make chat CHAT=trip AS=lotti
	uv run python -m cli.chat --chat $(CHAT) --as $(AS)

test:  ## run the test suite against a throwaway test database
	uv run pytest

fmt:  ## format the code
	uv run ruff format .

lint:  ## check formatting and lint rules
	uv run ruff format --check .
	uv run ruff check .

typecheck:  ## strict type check of the pure modules (src/ledger, src/channel)
	uv run mypy

bridge: bridge-node  ## run the WhatsApp bridge (pairs on first run)
	cd bridge && node src/main.ts

bridge-install:  ## install the bridge's pinned dependencies (Node from bridge/.nvmrc)
	cd bridge && npm ci

bridge-check: bridge-node  ## typecheck and test the bridge
	cd bridge && npm run --silent typecheck && npm test

bridge-node:  # the Node on PATH must be the one pinned in bridge/.nvmrc
	@node -e 'const w = require("fs").readFileSync("bridge/.nvmrc", "utf8").trim(); if (process.versions.node !== w) { console.error(`bridge needs Node $${w}, found $${process.versions.node}: run nvm use in bridge/`); process.exit(1); }'

check: lint typecheck test bridge-check  ## everything, in order; stops at the first failure
