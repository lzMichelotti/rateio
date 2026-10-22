"""Forward-only SQL migration runner.

Applies migrations/NNN_name.sql in order, each in its own transaction, and
records version and checksum in schema_migration. Refuses to run when an
applied migration was edited, removed, or a new one was added out of order.

Usage: python -m store.migrate   (reads DATABASE_URL)
"""

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

# The migrations/ folder at the project root, found relative to this file so it
# works from any working directory and any checkout location.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

# Valid migration filenames: three digits, an underscore, a lowercase name, .sql.
FILENAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

# The runner's own bookkeeping table: one row per applied migration. It is created
# here, not in a migration, because the runner needs it before it can apply any.
CREATE_CONTROL_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    checksum   text        NOT NULL
)
"""


# One migration file: its version, where it lives, and its content fingerprint.
# Frozen, so a fingerprint can't change after it is computed.
@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


# Reads the folder: validates filenames, rejects duplicate numbers, and
# fingerprints each file.
def discover(directory: Path) -> list[Migration]:
    """Every migration file in the directory, sorted by version."""
    migrations = []
    seen: dict[str, Path] = {}
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME.match(path.name)
        if not match:
            raise SystemExit(
                f"bad migration filename: {path.name} (expected NNN_name.sql)"
            )
        number = match.group(1)
        if number in seen:
            raise SystemExit(
                f"duplicate migration number {number}: {seen[number].name}, {path.name}"
            )
        seen[number] = path
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        migrations.append(Migration(version=path.stem, path=path, checksum=checksum))
    return migrations


# Compares the folder with what the database says was applied, and lists every
# reason to refuse: edited file, missing file, or a new file older than the last one.
def problems(on_disk: list[Migration], applied: dict[str, str]) -> list[str]:
    """Reasons to refuse running. Empty means it is safe to proceed."""
    found = []
    by_version = {m.version: m for m in on_disk}
    for version, checksum in applied.items():
        migration = by_version.get(version)
        if migration is None:
            found.append(f"{version}: applied but its file is missing")
        elif migration.checksum != checksum:
            found.append(f"{version}: edited after being applied (checksum changed)")
    last_applied = max(applied, default="")
    for migration in on_disk:
        if migration.version not in applied and migration.version < last_applied:
            found.append(
                f"{migration.version}: pending but older than applied {last_applied}"
            )
    return found


# Entry point: connect, create the control table, refuse if anything looks wrong,
# then apply the pending migrations one transaction each. Returns the exit code.
def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    on_disk = discover(MIGRATIONS_DIR)

    # Autocommit: nothing runs in an implicit transaction; each migration gets an
    # explicit one below, so a failure rolls back that migration and nothing else.
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(CREATE_CONTROL_TABLE)
        rows = conn.execute("SELECT version, checksum FROM schema_migration").fetchall()
        applied = dict(rows)

        refusals = problems(on_disk, applied)
        if refusals:
            print("refusing to migrate:", file=sys.stderr)
            for reason in refusals:
                print(f"  - {reason}", file=sys.stderr)
            return 1

        pending = [m for m in on_disk if m.version not in applied]
        for migration in pending:
            with conn.transaction():
                conn.execute(migration.sql)
                conn.execute(
                    "INSERT INTO schema_migration (version, checksum) VALUES (%s, %s)",
                    (migration.version, migration.checksum),
                )
            print(f"applied {migration.version}")

    print(f"{len(pending)} applied, {len(applied) + len(pending)} total, 0 pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
