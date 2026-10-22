"""Shared fixtures: a throwaway test database, migrated and seeded once per run."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

TEST_DBNAME = "rateio_test"
SEED_FILE = Path(__file__).parent / "fixtures" / "participants.sql"


@pytest.fixture(scope="session")
def database_url() -> str:
    """Recreate the test database from scratch, run the real migrations, seed it.

    The dev database named in DATABASE_URL is only used to issue CREATE/DROP;
    tests never touch its data.
    """
    dev_url = os.environ.get("DATABASE_URL")
    if not dev_url:
        pytest.fail("DATABASE_URL is not set (copy .env.example to .env)")
    test_url = make_conninfo(dev_url, dbname=TEST_DBNAME)

    # CREATE/DROP DATABASE cannot run inside a transaction, hence autocommit.
    with psycopg.connect(dev_url, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DBNAME}")
        admin.execute(f"CREATE DATABASE {TEST_DBNAME}")

    # Run the runner exactly as `make migrate` does, so tests exercise the real path.
    subprocess.run(
        [sys.executable, "-m", "store.migrate"],
        env={**os.environ, "DATABASE_URL": test_url},
        check=True,
    )

    with psycopg.connect(test_url) as conn:
        conn.execute(SEED_FILE.read_text(encoding="utf-8"))

    return test_url


@pytest.fixture
def conn(database_url: str):
    """A connection whose changes are rolled back after each test."""
    with psycopg.connect(database_url) as conn:
        yield conn
        conn.rollback()
