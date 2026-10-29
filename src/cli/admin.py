"""Operator commands: books, people, membership and channel links.

Not migrations: data about who is on a trip changes with each trip, and this is
the same mechanism that will register the real people in production. Every
command can be run twice without duplicating anything. Output is for the
operator, in English; nothing here is said to the group.

Usage: python -m cli.admin <command> ...   (reads DATABASE_URL)
"""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date

import psycopg

from store import books


def main(argv: Sequence[str], conn: psycopg.Connection | None = None) -> int:
    args = _parser().parse_args(argv)
    if conn is None:
        with psycopg.connect(os.environ["DATABASE_URL"]) as own:
            return _run(own, args)
    return _run(conn, args)


def _run(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    try:
        with conn.transaction():
            args.handler(conn, args)
    except (books.BookNotFoundError, books.AmbiguousBookError) as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except psycopg.errors.ForeignKeyViolation as e:
        print(f"error: {e.diag.message_detail}", file=sys.stderr)
        return 1
    return 0


def _create_book(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    book_id = books.create_book(
        conn, name=args.name, starts_on=args.starts, ends_on=args.ends
    )
    print(f"created book {args.name!r} {book_id}")


def _add_participant(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    added = books.add_participant(
        conn, participant_id=args.id, display_name=args.display_name
    )
    print(f"{'added' if added else 'already exists:'} participant {args.id}")


def _add_member(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    book_id = books.find_book(conn, args.book)
    for pid in args.participants:
        added = books.add_member(conn, book_id=book_id, participant_id=pid)
        print(f"{'added' if added else 'already a member:'} {pid}")


def _link_identity(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    linked = books.link_identity(
        conn,
        channel=args.channel,
        external_id=args.external_id,
        participant_id=args.participant,
    )
    state = "linked" if linked else "already linked, left as it was:"
    print(f"{state} {args.channel}:{args.external_id}")


def _link_conversation(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    linked = books.link_conversation(
        conn,
        channel=args.channel,
        external_id=args.external_id,
        book_id=books.find_book(conn, args.book),
        kind=args.kind,
    )
    state = "linked" if linked else "already linked, left as it was:"
    print(f"{state} {args.channel}:{args.external_id}")


def _show(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    o = books.book_overview(conn, books.find_book(conn, args.book))
    print(f"{o.name}  {o.starts_on} to {o.ends_on}")
    print("members:")
    for pid, name in o.members:
        print(f"  {pid}  {name}")
    print("identities:")
    for channel, external_id, pid in o.identities:
        print(f"  {channel}:{external_id} -> {pid}")
    print("conversations:")
    for channel, external_id, kind in o.conversations:
        print(f"  {channel}:{external_id} ({kind})")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.admin", description=__doc__)
    commands = parser.add_subparsers(required=True)

    c = commands.add_parser("create-book", help="a new trip")
    c.add_argument("name")
    c.add_argument("--starts", type=date.fromisoformat, required=True)
    c.add_argument("--ends", type=date.fromisoformat, required=True)
    c.set_defaults(handler=_create_book)

    c = commands.add_parser("add-participant", help="a person")
    c.add_argument("id", help="short, stable, sorts the remainder rotation")
    c.add_argument("display_name")
    c.set_defaults(handler=_add_participant)

    c = commands.add_parser("add-member", help="put people in a book")
    c.add_argument("book", help="name or id")
    c.add_argument("participants", nargs="+")
    c.set_defaults(handler=_add_member)

    c = commands.add_parser("link-identity", help="who a channel id is")
    c.add_argument("channel", choices=["cli", "whatsapp_unofficial"])
    c.add_argument("external_id")
    c.add_argument("participant")
    c.set_defaults(handler=_link_identity)

    c = commands.add_parser("link-conversation", help="which book a chat writes to")
    c.add_argument("channel", choices=["cli", "whatsapp_unofficial"])
    c.add_argument("external_id")
    c.add_argument("book", help="name or id")
    c.add_argument("--kind", choices=["group", "direct"], default="group")
    c.set_defaults(handler=_link_conversation)

    c = commands.add_parser("show", help="members, identities and chats of a book")
    c.add_argument("book", help="name or id")
    c.set_defaults(handler=_show)
    return parser


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
