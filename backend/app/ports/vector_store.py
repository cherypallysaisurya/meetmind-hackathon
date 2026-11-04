"""VectorStore port: stores vectors with metadata and finds the nearest ones.

Collections keep things apart: one per user for document chunks, one per session for prepared questions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Match:
    id: str
    score: float        # higher is closer
    metadata: dict


class VectorStore(ABC):
    @abstractmethod
    async def add(self, collection: str, ids: list[str], vectors: list[list[float]], metadata: list[dict]) -> None:
        """Store vectors with their ids and metadata. Adding an existing id replaces it."""

    @abstractmethod
    async def search(self, collection: str, vector: list[float], limit: int) -> list[Match]:
        """Nearest first. An unknown collection gives an empty list."""

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> None:
        """Remove these ids. Unknown ids are ignored."""

    @abstractmethod
    async def delete_collection(self, collection: str) -> None: ...
