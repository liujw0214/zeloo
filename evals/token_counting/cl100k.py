"""cl100k_base tokenizer wrapper — pure Python, no external dependency."""

from __future__ import annotations


def count_tokens(text: str | list[dict], model: str = "gpt-4o") -> int:
    """Count tokens using tiktoken (preferred) or character-based fallback.

    The character-based estimate (chars / 4) is used when tiktoken is not
    installed. This is accurate to within ~10% for typical English text.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        if isinstance(text, str):
            return len(enc.encode(text))
        elif isinstance(text, list):
            return sum(len(enc.encode(_msg_content(m))) for m in text)
        else:
            return 0
    except ImportError:
        return _char_estimate(text)


def _msg_content(msg: dict) -> str:
    if isinstance(msg, dict):
        return msg.get("content", "") or str(msg)
    return str(msg)


def _char_estimate(text: str | list[dict]) -> int:
    if isinstance(text, str):
        return max(1, len(text) // 4)
    elif isinstance(text, list):
        return max(1, sum(len(_msg_content(m)) for m in text) // 4)
    return 0
