def test_book_starts_empty(conn, book):
    count = conn.execute(
        "SELECT count(*) FROM journal_entry WHERE book_id = %s", (book,)
    ).fetchone()[0]

    assert count == 0


def test_each_command_is_distinct_and_belongs_to_the_book(conn, book, make_command):
    first, second = make_command(), make_command("luis")

    rows = conn.execute(
        "SELECT id, book_id, participant_id FROM command ORDER BY participant_id"
    ).fetchall()
    assert first != second
    assert rows == [(first, book, "lotti"), (second, book, "luis")]
