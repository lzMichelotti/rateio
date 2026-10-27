import pytest
from psycopg import errors


def test_show_settlement_plan_is_an_accepted_command_kind(conn, make_command):
    command_id = make_command(kind="show_settlement_plan")

    assert conn.execute(
        "SELECT kind FROM command WHERE id = %s", (command_id,)
    ).fetchone() == ("show_settlement_plan",)


def test_close_book_is_no_longer_a_command_kind(make_command):
    with pytest.raises(errors.CheckViolation):
        make_command(kind="close_book")
