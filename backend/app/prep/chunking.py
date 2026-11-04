"""Cuts a parsed document into chunks of about `target_chars` characters that keep their location.

Parsers hand over passages (a paragraph, or a page) each with a location such as "page 3" or
"section: Results". Consecutive passages from the same location are packed into one chunk until it
is full. A new location always starts a new chunk, so a chunk never claims the wrong page.
"""

import re
from dataclasses import dataclass

from ..ports import Chunk


@dataclass
class Passage:
    location: str
    text: str


def split_long(text: str, target_chars: int) -> list[str]:
    """A single passage longer than a chunk is split at sentence ends."""
    if len(text) <= target_chars:
        return [text]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > target_chars:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def tail(text: str, overlap_chars: int) -> str:
    """The last few words of a chunk, carried into the next one so a sentence cut in two is still found."""
    if len(text) <= overlap_chars:
        return text
    cut = text.rfind(" ", 0, len(text) - overlap_chars)
    return text[cut + 1:] if cut != -1 else text[-overlap_chars:]


def chunk(passages: list[Passage], document_name: str, target_chars: int, overlap_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[str] = []
    location = ""

    def flush(carry: bool) -> None:
        nonlocal current
        text = " ".join(current).strip()
        if text:
            chunks.append(Chunk(document_name, location, len(chunks), text))
        current = [tail(text, overlap_chars)] if carry and text else []

    for passage in passages:
        text = " ".join(passage.text.split())
        if not text:
            continue
        for piece in split_long(text, target_chars):
            if current and location != passage.location:
                flush(carry=False)
            elif current and sum(len(c) for c in current) + len(piece) > target_chars:
                flush(carry=True)
            location = passage.location
            current.append(piece)
    flush(carry=False)
    return chunks
