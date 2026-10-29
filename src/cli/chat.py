"""The command line as a channel: channel = 'cli', a chat like any other.

Not a test harness. Each line typed lands as an inbound_message, the same
processor reads the inbox, and the replies leave through outbound_message and
are marked sent, as the bridge will do for WhatsApp. If this works, WhatsApp is
one more channel.

Lines starting with / control the terminal and are never sent: /as <handle>
switches who you type as, which is changing phones, not something said in the
group; /quit leaves. Terminal text is English: only the bot speaks Portuguese.

Usage: python -m cli.chat --chat <external id> --as <cli handle>
"""

import argparse
import os
import random
import sys
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import psycopg

from core import processor
from store import books, inbox

CHANNEL = "cli"


class UnknownChatError(LookupError):
    pass


class Session:
    """One chat, typed into by whoever is at the keyboard."""

    def __init__(self, conn: psycopg.Connection, *, chat: str, rng: random.Random):
        found = books.conversation_book(conn, CHANNEL, chat)
        if found is None:
            raise UnknownChatError(chat)
        self.conn = conn
        self.chat = chat
        self.conversation_id = found[0]
        self.rng = rng

    def say(self, handle: str, text: str, at: datetime | None = None) -> list[str]:
        """Send a line as handle; process the inbox; deliver this chat's replies.

        Every line gets a fresh dedupe key: a terminal never redelivers, and two
        identical lines are two intentions (break 1), not one message twice.
        """
        inbox.receive(
            self.conn,
            channel=CHANNEL,
            conversation_external_id=self.chat,
            sender_external_id=handle,
            dedupe_key=f"cli:{uuid4()}",
            raw_payload={"text": text},
            received_at=at,
        )
        processor.process_pending(self.conn, rng=self.rng)
        return self.deliver()

    def deliver(self) -> list[str]:
        with self.conn.transaction():
            pending = inbox.pending_replies(self.conn, self.conversation_id)
            for outbound_id, _ in pending:
                inbox.mark_sent(self.conn, outbound_id)
        return [body for _, body in pending]


def run(
    read: Callable[[str], str | None],
    session: Session,
    *,
    handle: str,
    write: Callable[[str], None],
) -> None:
    """The terminal loop. read(prompt) returns a line, or None at end of input;
    both ends are passed in so the loop can be tested."""
    while (raw := read(f"{handle}> ")) is not None:
        line = raw.strip()
        if line == "/quit":
            return
        if line.startswith("/as "):
            handle = line.removeprefix("/as ").strip()
        elif line.startswith("/"):
            write("(terminal commands: /as <handle>, /quit)")
        elif line:
            for reply in session.say(handle, line):
                write("  bot: " + reply.replace("\n", "\n       "))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cli.chat", description=__doc__)
    parser.add_argument("--chat", required=True, help="the conversation's external id")
    parser.add_argument("--as", dest="handle", required=True, help="your cli handle")
    args = parser.parse_args(argv)
    try:
        import readline  # noqa: F401  (line editing and history for input())
    except ImportError:
        pass

    # Autocommit: each message's transaction commits on its own (see core.processor).
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        try:
            session = Session(conn, chat=args.chat, rng=random.Random())
        except UnknownChatError:
            print(
                f"no cli chat {args.chat!r}; link one with: make admin "
                f"ARGS=\"link-conversation cli {args.chat} '<book>'\"",
                file=sys.stderr,
            )
            return 1
        run(_read, session, handle=args.handle, write=print)
    return 0


def _read(prompt: str) -> str | None:
    try:
        return input(prompt)
    except EOFError:
        return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
