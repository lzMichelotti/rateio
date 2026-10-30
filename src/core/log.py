"""One line per event, key=value, the same shape as the bridge's.

Every line about a message carries its inbound_message id (and the
outbound_message id of its reply), so `grep <id>` over the bridge's and the
worker's output follows one WhatsApp message to its ledger legs and back.

Never logged: message text, names, LIDs, phone numbers, group ids, the database
URL. Only our own database ids, kinds, reasons and counts: a uuid of ours means
nothing outside this database.
"""

import logging
import sys
from datetime import UTC, datetime

LOGGER = logging.getLogger("rateio")


def event(name: str, **fields: object) -> None:
    """Log `name k=v k=v`, skipping fields that are None."""
    pairs = " ".join(
        f"{key}={value}" for key, value in fields.items() if value is not None
    )
    LOGGER.info(f"{name} {pairs}".rstrip())


class _Formatter(logging.Formatter):
    def __init__(self, process: str) -> None:
        super().__init__()
        self.process = process

    def format(self, record: logging.LogRecord) -> str:
        at = datetime.fromtimestamp(record.created, UTC).isoformat(
            timespec="milliseconds"
        )
        return f"{at.replace('+00:00', 'Z')} {self.process} {record.getMessage()}"


def configure(process: str) -> None:
    """Send the events to stdout, each line stamped with the process name."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(process))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
