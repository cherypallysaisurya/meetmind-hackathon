"""DocumentParser adapter with local libraries: pypdf for PDF, python-docx for DOCX, plain code for
Markdown and text. Each file becomes passages with a location, then chunks (prep/chunking.py)."""

import io
import re

import docx
from pypdf import PdfReader

from ...ports import Chunk, DocumentParser
from ...prep.chunking import Passage, chunk


def paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def from_text(text: str) -> list[Passage]:
    return [Passage(f"paragraph {i + 1}", p) for i, p in enumerate(paragraphs(text))]


def from_markdown(text: str) -> list[Passage]:
    passages, section = [], "top"
    for block in paragraphs(text):
        heading = re.match(r"^\s*#{1,6}\s+(.+)$", block.strip().split("\n")[0])
        if heading:
            section = heading.group(1).strip()
            rest = "\n".join(block.strip().split("\n")[1:]).strip()
            if rest:
                passages.append(Passage(f"section: {section}", rest))
        else:
            passages.append(Passage(f"section: {section}", block))
    return passages


def from_pdf(data: bytes) -> list[Passage]:
    passages = []
    for number, page in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
        for p in paragraphs(page.extract_text() or ""):
            passages.append(Passage(f"page {number}", p))
    return passages


def from_docx(data: bytes) -> list[Passage]:
    passages, section, count = [], None, 0
    for paragraph in docx.Document(io.BytesIO(data)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style is not None and paragraph.style.name.lower().startswith(("heading", "title")):
            section = text
            continue
        count += 1
        passages.append(Passage(f"section: {section}" if section else f"paragraph {count}", text))
    return passages


class LocalDocumentParser(DocumentParser):
    def __init__(self, target_chars: int, overlap_chars: int):
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def supported_types(self) -> set[str]:
        return {"pdf", "md", "txt", "docx"}

    async def parse(self, filename: str, data: bytes) -> list[Chunk]:
        extension = filename.rsplit(".", 1)[-1].lower()
        if extension == "pdf":
            passages = from_pdf(data)
        elif extension == "docx":
            passages = from_docx(data)
        elif extension == "md":
            passages = from_markdown(data.decode("utf-8", errors="replace"))
        elif extension == "txt":
            passages = from_text(data.decode("utf-8", errors="replace"))
        else:
            raise ValueError(f"{extension!r} files are not supported, use pdf, md, txt or docx")
        return chunk(passages, filename, self.target_chars, self.overlap_chars)
