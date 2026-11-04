"""SpeechToText port: turns the stereo audio stream into labeled transcripts.

Audio arrives as 100 ms frames of interleaved stereo 16-bit PCM at 16 kHz.
The left channel is the user ("me"), the right channel is everyone else ("them").
An adapter returns partial results (the words may still change) and final results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

ME = "me"
THEM = "them"


@dataclass
class Transcript:
    channel: str        # ME or THEM
    text: str
    is_partial: bool    # True while the words may still change
    start_s: float      # seconds of audio since the session started
    end_s: float


class SpeechToText(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Open the engine or the remote stream. Called once before any audio is fed."""

    @abstractmethod
    async def feed(self, frame: bytes) -> None:
        """Give the engine one frame of interleaved stereo 16-bit PCM at 16 kHz."""

    @abstractmethod
    def transcripts(self) -> AsyncIterator[Transcript]:
        """Yield partial and final transcripts as they become available, until stop() has run."""

    @abstractmethod
    async def stop(self) -> None:
        """Flush what is left, emit the last finals, then end the transcripts() iterator."""
