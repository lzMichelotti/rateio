# rateio

A WhatsApp bot that splits trip expenses among a group of friends, built as a
small financial system: an append-only double-entry ledger, two-sided
settlement confirmation, and multilateral netting.

Work in progress.

## Requirements

- Docker with Compose
- [uv](https://docs.astral.sh/uv/)
- make

## Setup

```bash
cp .env.example .env   # adjust POSTGRES_PORT if 5432 is taken
uv sync                # create .venv and install dependencies
make up                # start PostgreSQL 16
make migrate           # apply database migrations
make test              # run the test suite
```

## Commands

| Command        | What it does                                              |
|----------------|-----------------------------------------------------------|
| `make up`      | Start PostgreSQL and wait until it is healthy              |
| `make down`    | Stop PostgreSQL (data is kept in a named volume)           |
| `make migrate` | Apply pending migrations                                   |
| `make test`    | Run tests against a throwaway database (`rateio_test`)     |
| `make fmt`     | Format the code                                            |
| `make lint`    | Check formatting and lint rules                            |

## Layout

```
src/
  ledger/       domain logic, standard library only
  store/        the only module that talks to PostgreSQL
  channel/      command grammar and user-facing messages
  interpreter/  free text to structured command
  jobs/         daily close, backfill, report
  handlers/     thin entry points
migrations/     numbered SQL files, never edited once applied
tests/
```
