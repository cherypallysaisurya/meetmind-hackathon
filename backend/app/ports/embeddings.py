"""Embeddings port: turns texts into vectors for similarity search."""

from abc import ABC, abstractmethod


class Embeddings(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per input text, all of the same length."""
