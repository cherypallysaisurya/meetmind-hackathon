"""DocumentParser port: turns an uploaded file into text chunks that remember where they came from."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Chunk:
    document_name: str
    location: str       # where in the document, for example "page 2" or "section: Results"
    index: int          # position of this chunk in the document, from 0
    text: str


class DocumentParser(ABC):
    @abstractmethod
    def supported_types(self) -> set[str]:
        """Lowercase file extensions without the dot, for example {"pdf", "md", "txt", "docx"}."""

    @abstractmethod
    async def parse(self, filename: str, data: bytes) -> list[Chunk]:
        """Split the file into chunks in reading order."""
