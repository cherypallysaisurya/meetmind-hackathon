"""Replay mode: a stereo 16 kHz WAV plays into a session at real-time pace instead of live audio.

Used by the eval runner and as the demo fallback. Only files inside the replay folder can be played.
"""

import asyncio
import time
import wave
from pathlib import Path
from typing import AsyncIterator

from .frames import CHANNELS, FRAME_BYTES, FRAME_SECONDS, RATE


def is_playable(path: Path) -> bool:
    try:
        with wave.open(str(path)) as w:
            return (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, CHANNELS, 2)
    except (wave.Error, OSError):
        return False


def replay_files(folder: Path) -> list[str]:
    """Stereo 16 kHz WAV files in the folder, by name."""
    return sorted(path.name for path in folder.glob("*.wav") if is_playable(path))


def resolve(folder: Path, name: str) -> Path:
    """The file inside the replay folder, by bare name. Anything else is refused."""
    path = folder / Path(name).name
    if not path.exists() or path.suffix != ".wav":
        raise FileNotFoundError(f"no replay file named {name!r}")
    return path


async def frames_at_real_time(path: Path) -> AsyncIterator[bytes]:
    """Yield 100 ms frames, each one when its moment comes, like a live microphone would."""
    with wave.open(str(path)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, CHANNELS, 2):
            raise ValueError(f"{path.name} must be 16 kHz stereo 16-bit")
        audio = w.readframes(w.getnframes())
    start = time.perf_counter()
    for index, offset in enumerate(range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES)):
        due = start + index * FRAME_SECONDS
        await asyncio.sleep(max(0.0, due - time.perf_counter()))
        yield audio[offset:offset + FRAME_BYTES]
