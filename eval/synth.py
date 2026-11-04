"""Speech synthesis for the eval: macOS `say` and ffmpeg make 16 kHz clips, free and repeatable.

A scenario's lines become one stereo WAV: the user's lines on the left channel, everyone else on the
right, one after another with a pause between them. The timeline records where every line landed.
"""

import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import yaml

RATE = 16000
REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "eval" / "scenarios"
AUDIO = REPO / "eval" / "audio"


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def trim_silence(samples: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    loud = np.where(np.abs(samples) > threshold)[0]
    return samples[loud[0]:loud[-1] + 1] if len(loud) else samples


def speak(text: str, voice: str, rate_wpm: int = 185) -> np.ndarray:
    """One sentence as 16 kHz mono float32 with the leading and trailing silence removed."""
    with tempfile.TemporaryDirectory() as folder:
        aiff, wav = Path(folder) / "line.aiff", Path(folder) / "line.wav"
        subprocess.run(["say", "-v", voice, "-r", str(rate_wpm), "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", str(RATE), "-ac", "1", str(wav)], check=True)
        return trim_silence(read_wav(wav))


def write_stereo(path: Path, left: np.ndarray, right: np.ndarray) -> None:
    stereo = np.stack([left, right], axis=1).reshape(-1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def load_scenario(path: Path) -> dict:
    scenario = yaml.safe_load(path.read_text())
    scenario["name"] = path.stem
    return scenario


def build(scenario: dict) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Synthesize every line and lay them out in time. Returns left, right and the timeline."""
    gap = int(scenario.get("gap_s", 0.8) * RATE)
    voices = scenario["speakers"]
    left_parts, right_parts, timeline = [], [], []
    position = int(1.0 * RATE)                       # a second of silence to let everything start
    left_parts.append(np.zeros(position, dtype=np.float32))
    right_parts.append(np.zeros(position, dtype=np.float32))
    for line in scenario["lines"]:
        who = line["who"]
        audio = speak(line["text"], voices[who])
        silence = np.zeros(len(audio), dtype=np.float32)
        if who == "me":
            left_parts.append(audio)
            right_parts.append(silence)
        else:
            left_parts.append(silence)
            right_parts.append(audio)
        start, end = position / RATE, (position + len(audio)) / RATE
        timeline.append({
            "who": who, "text": line["text"], "label": line.get("label", "statement"),
            "start_s": round(start, 2), "end_s": round(end, 2), "attention_after": bool(line.get("attention_after", False)),
        })
        pause = int(line.get("pause_after_s", scenario.get("gap_s", 0.8)) * RATE)
        left_parts.append(np.zeros(pause, dtype=np.float32))
        right_parts.append(np.zeros(pause, dtype=np.float32))
        position += len(audio) + pause
    tail = np.zeros(int(1.5 * RATE), dtype=np.float32)   # let the last turn close
    left_parts.append(tail)
    right_parts.append(tail)
    return np.concatenate(left_parts), np.concatenate(right_parts), timeline


def save(scenario: dict, left: np.ndarray, right: np.ndarray, timeline: list[dict]) -> Path:
    AUDIO.mkdir(exist_ok=True)
    wav = AUDIO / f"{scenario['name']}.wav"
    write_stereo(wav, left, right)
    (AUDIO / f"{scenario['name']}.timeline.json").write_text(json.dumps({
        "name": scenario["name"], "title": scenario["title"], "user": scenario["user"],
        "one_on_one": bool(scenario.get("one_on_one", False)),
        "duration_s": round(len(left) / RATE, 2), "lines": timeline,
    }, indent=2))
    return wav
