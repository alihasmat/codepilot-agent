"""Token counting for the Repo Map budget.

The assignment requires the Repo Map to fit in a configurable token
budget (default 4000). We count with tiktoken when it's available, but
fall back to a character-based estimate so the app never hard-fails on
a blocked or slow model download. The estimate is deliberately slightly
conservative (assumes ~3.5 chars/token) so we under-fill rather than
overflow the real budget.
"""

from __future__ import annotations

from functools import lru_cache

_CHARS_PER_TOKEN = 3.5  # conservative; real English is ~4, code is denser


@lru_cache(maxsize=1)
def _encoder():
    """Load a tiktoken encoder once, or return None if unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(text))
    return int(len(text) / _CHARS_PER_TOKEN) + 1