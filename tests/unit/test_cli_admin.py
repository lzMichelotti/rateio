from cli import admin
from store.books import book_members, conversation_book, participant_for


def run(conn, *argv):
    return admin.main(list(argv), conn)


def setup_trip(conn):
    assert (
        run(
            conn,
            "create-book",
            "Carnival",
            "--starts",
            "2027-02-15",
            "--ends",
            "2027-02-25",
        )
        == 0
    )
    assert run(conn, "add-participant", "ze", "Zé") == 0
    assert run(conn, "add-member", "Carnival", "lotti", "ze") == 0
    assert run(conn, "link-identity", "cli", "ze", "ze") == 0
    assert run(conn, "link-conversation", "cli", "carnival", "Carnival") == 0


def test_a_trip_is_set_up_without_a_migration(conn):
    setup_trip(conn)

    found = conversation_book(conn, "cli", "carnival")
    assert found is not None
    assert book_members(conn, found[1]) == ["lotti", "ze"]
    assert participant_for(conn, "cli", "ze") == "ze"


def test_running_the_setup_twice_duplicates_nothing(conn, capsys):
    setup_trip(conn)
    capsys.readouterr()

    assert run(conn, "add-member", "Carnival", "lotti") == 0
    assert run(conn, "link-identity", "cli", "ze", "lotti") == 0

    out = capsys.readouterr().out
    assert "already a member: lotti" in out
    assert "already linked, left as it was: cli:ze" in out
    assert participant_for(conn, "cli", "ze") == "ze"


def test_a_book_name_shared_by_two_books_is_refused(conn, capsys):
    for _ in range(2):
        run(
            conn,
            "create-book",
            "Twin",
            "--starts",
            "2027-01-01",
            "--ends",
            "2027-01-02",
        )

    assert run(conn, "add-member", "Twin", "lotti") == 1
    assert "AmbiguousBookError" in capsys.readouterr().err


def test_an_unknown_participant_is_refused(conn, capsys):
    run(conn, "create-book", "Solo", "--starts", "2027-01-01", "--ends", "2027-01-02")

    assert run(conn, "add-member", "Solo", "nobody") == 1
    assert "nobody" in capsys.readouterr().err


def test_show_lists_what_the_book_has(conn, capsys):
    setup_trip(conn)
    capsys.readouterr()

    run(conn, "show", "Carnival")

    out = capsys.readouterr().out
    assert "ze  Zé" in out
    assert "cli:ze -> ze" in out
    assert "cli:carnival (group)" in out
