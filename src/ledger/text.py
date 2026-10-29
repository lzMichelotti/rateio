"""Comparing what people typed, the way people mean it."""

import unicodedata


def fold(text: str) -> str:
    """Case and accents removed: a name with accents, in capitals or plain,
    folds to the same string. Whitespace is left as it is."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
