"""Shared text helpers."""


def truncate_middle(text: str, head: int = 4500, tail: int = 4500) -> str:
    """Keep the head and tail of long text while marking the omitted middle."""
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n... [truncated {omitted} chars] ...\n{text[-tail:]}"
