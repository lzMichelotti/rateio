"""Import boundaries: src/ledger/ imports only the standard library and itself,
and nothing in src/ imports the test helpers in tests/support/."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
LEDGER_DIR = SRC_DIR / "ledger"
SUPPORT_DIR = ROOT / "tests" / "support"
ALLOWED = set(sys.stdlib_module_names) | {"ledger"}


def imported_top_level_modules(source: str) -> set[str]:
    """Top-level names of every absolute import, wherever it appears in the file."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_ledger_imports_only_the_standard_library():
    offenders = {}
    for path in sorted(LEDGER_DIR.rglob("*.py")):
        foreign = imported_top_level_modules(path.read_text()) - ALLOWED
        if foreign:
            offenders[path.name] = sorted(foreign)

    assert offenders == {}


def test_nothing_in_src_imports_the_test_support_modules():
    support = {path.stem for path in SUPPORT_DIR.glob("*.py")}
    offenders = {}
    for path in sorted(SRC_DIR.rglob("*.py")):
        imported = imported_top_level_modules(path.read_text()) & support
        if imported:
            offenders[str(path.relative_to(SRC_DIR))] = sorted(imported)

    assert "oracle" in support
    assert offenders == {}


def test_the_guard_catches_a_foreign_import():
    source = "import os\n\ndef save():\n    import psycopg\n"

    assert imported_top_level_modules(source) - ALLOWED == {"psycopg"}
