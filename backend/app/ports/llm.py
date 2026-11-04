"""LLM port: streaming chat replies and strict JSON replies.

The model name is a slot chosen in config (classifier, answer, doubt).
Callers pass the slot's model name in, they never name an engine or a vendor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class Message:
    role: str       # "system", "user" or "assistant"
    content: str
    images: list[bytes] = field(default_factory=list)   # JPEG pictures the model looks at with this message


class LLM(ABC):
    @abstractmethod
    def stream(self, model: str, messages: list[Message]) -> AsyncIterator[str]:
        """Yield the reply piece by piece. Stopping the iteration early cancels the generation."""

    @abstractmethod
    async def complete_json(self, model: str, messages: list[Message], schema: dict) -> dict:
        """Return a reply that follows the JSON schema exactly, already parsed into a dict."""
