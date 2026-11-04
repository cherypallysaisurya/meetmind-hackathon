"""Local SpeechToText adapter: Silero VAD cuts each channel into speech segments, mlx-whisper
transcribes them on the Apple GPU. Decision 0004.

Finals: one per speech segment, once the silence window has closed it.
Partials: while a segment is still running, the audio so far is transcribed about once a second.
All transcription happens on one worker thread, one job at a time, so the GPU is never asked to do
two things at once and the event loop never waits on it.
"""

import asyncio
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import mlx_whisper
import numpy as np
import sherpa_onnx

from ...audio.frames import RATE, split_channels
from ...ports import ME, THEM, SpeechToText, Transcript

LOOKBACK_S = 0.3       # the VAD notices speech a little late, so a partial starts this much earlier
MIN_PARTIAL_S = 1.0    # do not transcribe less than this much in-progress speech
MAX_SEGMENT_S = 15.0   # the VAD cuts longer speech into pieces


@dataclass
class Job:
    channel: str
    samples: np.ndarray
    start_s: float
    end_s: float
    is_partial: bool
    version: int = 0    # partials only: skipped if a newer partial or a final for the channel came after it


class ChannelStream:
    """Feeds one channel's audio to its VAD and decides what to transcribe."""

    def __init__(self, channel: str, vad_model_path: Path, silence_s: float, partial_every_s: float):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(vad_model_path)
        config.silero_vad.min_silence_duration = silence_s
        config.silero_vad.max_speech_duration = MAX_SEGMENT_S
        config.sample_rate = RATE
        self.vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
        self.window = config.silero_vad.window_size
        self.channel = channel
        self.partial_every = int(partial_every_s * RATE)
        self.fed = 0                                       # samples fed so far, the clock for timestamps
        self.pending = np.zeros(0, dtype=np.float32)       # not yet a whole VAD window
        self.recent = np.zeros(0, dtype=np.float32)        # audio since the last final, for partials
        self.recent_start = 0                              # absolute sample index of recent[0]
        self.in_speech = False
        self.speech_start = 0
        self.last_partial_at = 0
        self.version = 0

    def feed(self, samples: np.ndarray) -> list[Job]:
        """Take one frame of this channel (int16) and return the transcription jobs it triggers."""
        audio = samples.astype(np.float32) / 32768.0
        self.fed += len(audio)
        self.recent = np.concatenate([self.recent, audio])
        self.pending = np.concatenate([self.pending, audio])
        while len(self.pending) >= self.window:
            self.vad.accept_waveform(self.pending[:self.window])
            self.pending = self.pending[self.window:]

        jobs = self._finished_segments()
        speaking = self.vad.is_speech_detected()
        if speaking and not self.in_speech:
            self.in_speech = True
            self.speech_start = max(self.recent_start, self.fed - int(LOOKBACK_S * RATE))
            self.last_partial_at = self.speech_start
        if speaking and self.fed - self.last_partial_at >= self.partial_every:
            self.last_partial_at = self.fed
            so_far = self.recent[self.speech_start - self.recent_start:]
            if len(so_far) >= MIN_PARTIAL_S * RATE:
                self.version += 1
                jobs.append(Job(self.channel, so_far.copy(), self.speech_start / RATE, self.fed / RATE, True, self.version))
        if not speaking:
            self._forget_all_but_the_lookback()
        return jobs

    def flush(self) -> list[Job]:
        """Called at stop: whatever speech is still open becomes a final."""
        self.vad.flush()
        return self._finished_segments()

    def _finished_segments(self) -> list[Job]:
        jobs = []
        while not self.vad.empty():
            segment = self.vad.front
            samples = np.array(segment.samples, dtype=np.float32)
            start = segment.start
            self.vad.pop()
            end = start + len(samples)
            self.version += 1                      # any partial of this segment still queued is stale now
            self.in_speech = False
            # The VAD notices speech a little late and can clip the first word. Our own buffer still has the
            # audio just before the detected start, so the final gets the lookback in front of it.
            padded_start = max(self.recent_start, start - int(LOOKBACK_S * RATE))
            if padded_start < start and end - self.recent_start <= len(self.recent):
                samples = self.recent[padded_start - self.recent_start:end - self.recent_start].copy()
                start = padded_start
            jobs.append(Job(self.channel, samples, start / RATE, end / RATE, False))
            drop = max(0, min(len(self.recent), end - self.recent_start))
            self.recent = self.recent[drop:]
            self.recent_start += drop
        return jobs

    def _forget_all_but_the_lookback(self) -> None:
        keep = int(LOOKBACK_S * RATE) * 2
        drop = len(self.recent) - keep
        if drop > 0:
            self.recent = self.recent[drop:]
            self.recent_start += drop


class MlxWhisperSpeechToText(SpeechToText):
    def __init__(self, model: str, language: str, vad_model_path: Path, silence_ms: int, partial_every_ms: int):
        self.model = model
        self.language = language
        self.vad_model_path = vad_model_path
        self.silence_s = silence_ms / 1000
        self.partial_every_s = partial_every_ms / 1000
        self.streams: dict[str, ChannelStream] = {}
        self.jobs: queue.Queue[Job | None] = queue.Queue()
        self.results: asyncio.Queue[Transcript | None] = asyncio.Queue()
        self.worker: threading.Thread | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.streams = {
            channel: ChannelStream(channel, self.vad_model_path, self.silence_s, self.partial_every_s)
            for channel in (ME, THEM)
        }
        self.worker = threading.Thread(target=self._work, name="stt-worker", daemon=True)
        self.worker.start()
        # Load the model now, not when the first person speaks.
        await asyncio.to_thread(self._transcribe, np.zeros(RATE, dtype=np.float32))

    async def feed(self, frame: bytes) -> None:
        me, them = split_channels(frame)
        for channel, samples in ((ME, me), (THEM, them)):
            for job in self.streams[channel].feed(samples):
                self.jobs.put(job)

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.results.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        for stream in self.streams.values():
            for job in stream.flush():
                self.jobs.put(job)
        self.jobs.put(None)
        if self.worker:
            await asyncio.to_thread(self.worker.join)

    def _work(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                self.loop.call_soon_threadsafe(self.results.put_nowait, None)
                return
            if job.is_partial and job.version != self.streams[job.channel].version:
                continue   # a newer partial or the final for this speech made it pointless
            text = self._transcribe(job.samples)
            if text:
                transcript = Transcript(job.channel, text, job.is_partial, round(job.start_s, 2), round(job.end_s, 2))
                self.loop.call_soon_threadsafe(self.results.put_nowait, transcript)

    def _transcribe(self, samples: np.ndarray) -> str:
        result = mlx_whisper.transcribe(
            samples, path_or_hf_repo=self.model, language=self.language,
            temperature=0.0, condition_on_previous_text=False, verbose=None,
        )
        return result["text"].strip()
