"""One WebSocket binary message is one audio frame: 100 ms of interleaved stereo 16-bit PCM at
16 kHz. Left is the user (me), right is everyone else (them)."""

import math

import numpy as np

RATE = 16000
CHANNELS = 2
FRAME_SECONDS = 0.1
SAMPLES_PER_CHANNEL = int(RATE * FRAME_SECONDS)          # 1600
FRAME_BYTES = SAMPLES_PER_CHANNEL * CHANNELS * 2         # 6400

SILENCE_DB = -100.0   # reported instead of minus infinity, which JSON cannot carry


def split_channels(frame: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Return (me, them) as int16 arrays."""
    samples = np.frombuffer(frame, dtype=np.int16)
    return samples[0::2], samples[1::2]


def sum_of_squares(samples: np.ndarray) -> float:
    return float(np.square(samples.astype(np.float64)).sum())


def level_db(sum_squares: float, sample_count: int) -> float:
    """Loudness in dB relative to full scale, from an accumulated sum of squares."""
    if sample_count == 0 or sum_squares == 0.0:
        return SILENCE_DB
    rms = math.sqrt(sum_squares / sample_count) / 32768.0
    return max(SILENCE_DB, 20 * math.log10(rms))
