"""Measure the end-of-turn delay of the real pipeline on the Step 0.4 test clip.

Run from the repo root with the models in place:
    backend/.venv/bin/python scripts/measure_turn_delay.py --silence-ms 600

The clip (ten sentences, one second gaps) is played into the them channel at real-time pace through
the local SpeechToText adapter and the EndOfTurnDetector, exactly the code the service runs. For each
sentence we report how long after its last word the turn was known, and what the turn said.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from app.adapters.local.stt_mlx_whisper import MlxWhisperSpeechToText  # noqa: E402
from app.audio.frames import FRAME_SECONDS, RATE, SAMPLES_PER_CHANNEL  # noqa: E402
from app.config import settings  # noqa: E402
from app.ports import THEM  # noqa: E402
from app.turns.end_of_turn import EndOfTurnDetector  # noqa: E402
from benchmark_stt import AUDIO_DIR, CLIP_PATH, SENTENCES, make_clip, percentile, read_wav  # noqa: E402


def stereo_frames(mono: np.ndarray):
    """The clip on the right (them) channel, silence on the left, cut into 100 ms frames."""
    pcm = (mono * 32767).astype(np.int16)
    for offset in range(0, len(pcm) - SAMPLES_PER_CHANNEL + 1, SAMPLES_PER_CHANNEL):
        frame = np.zeros(SAMPLES_PER_CHANNEL * 2, dtype=np.int16)
        frame[1::2] = pcm[offset:offset + SAMPLES_PER_CHANNEL]
        yield frame.tobytes()


async def run(silence_ms: int):
    ends_file = AUDIO_DIR / "stt-test-clip.json"
    if CLIP_PATH.exists() and ends_file.exists():
        clip, ends = read_wav(CLIP_PATH), json.loads(ends_file.read_text())
    else:
        clip, ends = make_clip()
        ends_file.write_text(json.dumps(ends))

    stt = MlxWhisperSpeechToText(
        model=settings.stt_model, language=settings.stt_language, vad_model_path=settings.path("vad_model_path"),
        silence_ms=silence_ms, partial_every_ms=settings.stt_partial_every_ms,
    )
    detector = EndOfTurnDetector()
    frames_fed = 0
    turns = []

    async def feed():
        nonlocal frames_fed
        start = time.perf_counter()
        for frame in stereo_frames(clip):
            due = start + frames_fed * FRAME_SECONDS
            await asyncio.sleep(max(0.0, due - time.perf_counter()))
            await stt.feed(frame)
            frames_fed += 1
        await stt.stop()

    await stt.start()
    feeder = asyncio.create_task(feed())
    async for transcript in stt.transcripts():
        turn = detector.on_transcript(transcript, frames_fed * FRAME_SECONDS)
        if turn and turn.channel == THEM:
            turns.append(turn)
    await feeder

    print(f"\nsilence window {silence_ms} ms: {len(turns)} turns for {len(SENTENCES)} sentences\n")
    print(f"{'sentence ends':>14}{'turn known':>12}{'delay':>8}  text")
    delays = []
    for turn in turns:
        sentence_end = min(ends, key=lambda end: abs(end - turn.end_s))
        delays.append(turn.delay_s)
        print(f"{sentence_end:>13.2f}s{turn.end_s + turn.delay_s:>11.2f}s{turn.delay_s:>7.2f}s  {turn.text}")
    print(f"\ndelay p50 {percentile(delays, 0.5):.2f} s, p90 {percentile(delays, 0.9):.2f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--silence-ms", type=int, default=settings.turn_silence_ms)
    asyncio.run(run(parser.parse_args().silence_ms))
