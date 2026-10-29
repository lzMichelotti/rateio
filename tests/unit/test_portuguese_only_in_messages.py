"""Portuguese lives in src/channel/messages.py and nowhere else in src/.

An approximate check: any character outside ASCII. Portuguese without accents
would slip through, but real Portuguese sentences rarely lack an accent or a
cedilla, and nothing else in src/ has a reason to leave ASCII.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
MESSAGES = Path("channel") / "messages.py"


def non_ascii_lines(root: Path) -> list[str]:
    """file:line for every non-ASCII line under root, messages.py excepted."""
    return [
        f"{path.relative_to(root)}:{number}"
        for path in sorted(root.rglob("*.py"))
        if path.relative_to(root) != MESSAGES
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if not line.isascii()
    ]


def test_no_file_in_src_but_messages_leaves_ascii():
    assert non_ascii_lines(SRC) == []


def test_the_check_catches_portuguese_outside_messages(tmp_path):
    (tmp_path / "channel").mkdir()
    (tmp_path / "channel" / "messages.py").write_text('OK = "Lançado"\n', "utf-8")
    (tmp_path / "handler.py").write_text('reply = "Lançamento registrado"\n', "utf-8")

    assert non_ascii_lines(tmp_path) == ["handler.py:1"]
