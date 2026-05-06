"""Token counting.

Prefer Anthropic's tokenizer when available; fall back to tiktoken cl100k_base
(very close for English/markdown); fall back to chars/4.
"""

from __future__ import annotations

_strategy: str | None = None
_encoder = None


def _init() -> None:
    global _strategy, _encoder
    if _strategy is not None:
        return
    try:
        import tiktoken
        _encoder = tiktoken.get_encoding("cl100k_base")
        _strategy = "tiktoken-cl100k_base"
        return
    except Exception:
        pass
    _strategy = "chars/4"


def count(text: str) -> int:
    _init()
    if not text:
        return 0
    if _encoder is not None:
        return len(_encoder.encode(text, disallowed_special=()))
    return max(1, len(text) // 4)


def strategy() -> str:
    _init()
    return _strategy or "chars/4"
