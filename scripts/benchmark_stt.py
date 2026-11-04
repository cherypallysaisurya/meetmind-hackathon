"""Benchmark local speech-to-text engines on one generated test clip.

Run from the repo root (whisper models download from Hugging Face on first run):
    backend/.venv/bin/python scripts/benchmark_stt.py

The faster-whisper row needs an extra package the app itself does not use:
    backend/.venv/bin/pip install faster-whisper

The clip is ten meeting-style sentences spoken by macOS `say`, with one second of
silence between them, so we know exactly when each sentence ends. Every engine
gets the same audio in 100 ms chunks at real-time pace, like the live app will.

Per engine we report:
- WER: word error rate of the final text against the known sentences (lower is better).
- RTF: compute time divided by audio time. Under 1.0 means the engine keeps up.
- final delay: end of a sentence to the final text for it (median and p90).
- partial cost: compute time of one in-progress update (median).
- cores: average CPU cores busy. MLX runs on the GPU, which does not show here.
- RSS: peak memory of the engine process.

Each engine runs in its own subprocess (this file called with --engine) so memory
and CPU are measured per engine and heavy imports do not mix.
"""

import json
import re
import resource
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "models" / "stt"
AUDIO_DIR = REPO / "eval" / "audio"
CLIP_PATH = AUDIO_DIR / "stt-test-clip.wav"
RATE = 16000
CHUNK = RATE // 10          # 100 ms, the frame size of the WebSocket protocol
GAP_SECONDS = 1.0
VOICE = "Samantha"

SENTENCES = [
    "Okay, let's get started with the standup.",
    "Yesterday I finished the data pipeline for the retrieval experiments.",
    "The new embedding model cut the index build time from forty minutes to twelve.",
    "Surya, what batch size did you end up using for the last training run?",
    "We still need to decide on the evaluation set before Friday.",
    "Does anyone have questions about the deployment plan?",
    "I think the latency numbers look fine, but the memory usage worries me.",
    "Let's move the design review to Thursday afternoon.",
    "Can you share the dashboard link in the channel after this call?",
    "Thanks everyone, that's all from my side.",
]

# Whisper writes digits, the clip says the words. Only the numbers in the clip are mapped.
DIGITS_TO_WORDS = {"40": "forty", "12": "twelve"}


# ---------------------------------------------------------------- clip building

def read_wav(path):
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())


def trim_silence(samples, threshold=0.01):
    loud = np.where(np.abs(samples) > threshold)[0]
    return samples[loud[0]:loud[-1] + 1]


def make_clip():
    """Speak each sentence with say, convert to 16 kHz mono, join with silence gaps.

    Returns the clip and the time (seconds) at which each sentence ends.
    """
    pieces, ends, position = [], [], 0.0
    gap = np.zeros(int(GAP_SECONDS * RATE), dtype=np.float32)
    for index, sentence in enumerate(SENTENCES):
        aiff = AUDIO_DIR / f"sentence-{index}.aiff"
        wav = AUDIO_DIR / f"sentence-{index}.wav"
        subprocess.run(["say", "-v", VOICE, "-o", str(aiff), sentence], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff),
                        "-ar", str(RATE), "-ac", "1", str(wav)], check=True)
        samples = trim_silence(read_wav(wav))
        aiff.unlink()
        wav.unlink()
        pieces += [samples, gap]
        position += len(samples) / RATE
        ends.append(position)
        position += GAP_SECONDS
    clip = np.concatenate(pieces)
    write_wav(CLIP_PATH, clip)
    return clip, ends


# ---------------------------------------------------------------- scoring

def normalize(text):
    words = re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()
    return [DIGITS_TO_WORDS.get(word, word) for word in words]


def word_error_rate(reference, hypothesis):
    """Classic word-level edit distance divided by the reference length."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            substitution = previous[j - 1] + (ref_word != hyp_word)
            current.append(min(previous[j] + 1, current[j - 1] + 1, substitution))
        previous = current
    return previous[-1] / len(ref)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


# ---------------------------------------------------------------- engines
# Every engine has feed(samples) -> list of (kind, text) and finish() -> list of (kind, text),
# where kind is "partial" (text may still change) or "final" (text is done).

class SherpaStreaming:
    """True streaming recognizer. Gives partial words while someone talks and detects endpoints itself."""

    def __init__(self):
        import sherpa_onnx
        folder = MODELS / "sherpa-onnx-streaming-zipformer-en-2023-06-26"
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(folder / "tokens.txt"),
            encoder=str(folder / "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx"),
            decoder=str(folder / "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx"),
            joiner=str(folder / "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx"),
            num_threads=2,
            sample_rate=RATE,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=1.5,    # silence with nothing decoded yet
            rule2_min_trailing_silence=0.6,    # silence after words: the 600 ms window from the spec
            rule3_min_utterance_length=300,    # effectively off
        )
        self.stream = self.recognizer.create_stream()
        self.last_text = ""

    def feed(self, samples):
        self.stream.accept_waveform(RATE, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        text = self.recognizer.get_result(self.stream)
        if self.recognizer.is_endpoint(self.stream):
            self.recognizer.reset(self.stream)
            self.last_text = ""
            return [("final", text)] if text else []
        if text != self.last_text:
            self.last_text = text
            return [("partial", text)]
        return []

    def finish(self):
        self.stream.accept_waveform(RATE, np.zeros(int(0.66 * RATE), dtype=np.float32))
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        text = self.recognizer.get_result(self.stream)
        return [("final", text)] if text else []


class VadChunked:
    """Base for whisper-style engines: Silero VAD cuts speech into segments, each segment is transcribed
    when it ends. While speech is in progress, the buffer so far is transcribed once a second as a partial."""

    partial_every = 1.0

    def __init__(self):
        import sherpa_onnx
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(MODELS / "silero_vad.onnx")
        config.silero_vad.min_silence_duration = 0.6
        config.sample_rate = RATE
        self.window = config.silero_vad.window_size
        self.vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=120)
        self.pending = np.zeros(0, dtype=np.float32)      # waiting to be fed to the VAD in whole windows
        self.in_progress = np.zeros(0, dtype=np.float32)  # speech of the current segment, for partials
        self.since_partial = 0.0

    def transcribe(self, samples):
        raise NotImplementedError

    def feed(self, samples):
        events = []
        self.pending = np.concatenate([self.pending, samples])
        while len(self.pending) >= self.window:
            self.vad.accept_waveform(self.pending[:self.window])
            self.pending = self.pending[self.window:]
        while not self.vad.empty():
            segment = np.array(self.vad.front.samples, dtype=np.float32)
            self.vad.pop()
            events.append(("final", self.transcribe(segment)))
            self.in_progress = np.zeros(0, dtype=np.float32)
            self.since_partial = 0.0
        if self.vad.is_speech_detected():
            self.in_progress = np.concatenate([self.in_progress, samples])
            self.since_partial += len(samples) / RATE
            if self.since_partial >= self.partial_every and len(self.in_progress) >= RATE:
                self.since_partial = 0.0
                events.append(("partial", self.transcribe(self.in_progress)))
        return events

    def finish(self):
        self.vad.flush()
        events = []
        while not self.vad.empty():
            segment = np.array(self.vad.front.samples, dtype=np.float32)
            self.vad.pop()
            events.append(("final", self.transcribe(segment)))
        return events


class MlxWhisper(VadChunked):
    """Whisper on the Apple GPU through MLX."""

    def __init__(self, repo):
        super().__init__()
        import mlx_whisper
        self.mlx_whisper = mlx_whisper
        self.repo = repo
        self.transcribe(np.zeros(RATE, dtype=np.float32))   # loads the weights now, not on the first segment

    def transcribe(self, samples):
        result = self.mlx_whisper.transcribe(
            samples, path_or_hf_repo=self.repo, language="en",
            temperature=0.0, condition_on_previous_text=False, verbose=None,
        )
        return result["text"].strip()


class FasterWhisper(VadChunked):
    """Whisper on the CPU through CTranslate2 (int8)."""

    def __init__(self, size):
        super().__init__()
        from faster_whisper import WhisperModel
        self.model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)

    def transcribe(self, samples):
        segments, _ = self.model.transcribe(
            samples, language="en", beam_size=1, temperature=0.0,
            condition_on_previous_text=False, vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments)


ENGINES = {
    "sherpa-zipformer-int8": lambda: SherpaStreaming(),
    "mlx-whisper-small": lambda: MlxWhisper("mlx-community/whisper-small-mlx"),
    "mlx-whisper-large-v3-turbo": lambda: MlxWhisper("mlx-community/whisper-large-v3-turbo"),
    "faster-whisper-small-int8": lambda: FasterWhisper("small"),
}


# ---------------------------------------------------------------- one engine run (child process)

def cpu_seconds():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def run_engine(name, clip, ends):
    started = time.perf_counter()
    engine = ENGINES[name]()
    load_seconds = time.perf_counter() - started

    finals, partials, compute = [], [], 0.0
    cpu_before, start = cpu_seconds(), time.perf_counter()

    def record(events, feed_time):
        for kind, text in events:
            (finals if kind == "final" else partials).append((time.perf_counter() - start, text, feed_time))

    for offset in range(0, len(clip), CHUNK):
        due = start + offset / RATE
        now = time.perf_counter()
        if due > now:
            time.sleep(due - now)
        before = time.perf_counter()
        events = engine.feed(clip[offset:offset + CHUNK])
        feed_time = time.perf_counter() - before
        compute += feed_time
        record(events, feed_time)
    before = time.perf_counter()
    events = engine.finish()
    compute += time.perf_counter() - before
    record(events, time.perf_counter() - before)

    wall = time.perf_counter() - start
    cores = (cpu_seconds() - cpu_before) / wall

    # Delay per sentence: the first final that arrives after the sentence ends and before the next one ends.
    delays = []
    for index, end in enumerate(ends):
        next_end = ends[index + 1] if index + 1 < len(ends) else float("inf")
        arrivals = [at for at, _, _ in finals if end < at < next_end]
        if arrivals:
            delays.append(arrivals[0] - end)

    return {
        "engine": name,
        "load_s": round(load_seconds, 2),
        "wer": round(word_error_rate(" ".join(SENTENCES), " ".join(text for _, text, _ in finals)), 3),
        "rtf": round(compute / (len(clip) / RATE), 3),
        "final_delay_p50": round(percentile(delays, 0.5), 2) if delays else None,
        "final_delay_p90": round(percentile(delays, 0.9), 2) if delays else None,
        "finals": len(finals),
        "sentences_with_final": len(delays),
        "partials": len(partials),
        "partial_cost_p50": round(percentile([cost for _, _, cost in partials], 0.5), 3) if partials else None,
        "cores": round(cores, 2),
        "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6),
        "transcript": " | ".join(text for _, text, _ in finals),
    }


# ---------------------------------------------------------------- parent process

def main():
    if "--engine" in sys.argv:
        name = sys.argv[sys.argv.index("--engine") + 1]
        clip = read_wav(CLIP_PATH)
        ends = json.loads((AUDIO_DIR / "stt-test-clip.json").read_text())
        print(json.dumps(run_engine(name, clip, ends)))
        return

    clip, ends = make_clip()
    (AUDIO_DIR / "stt-test-clip.json").write_text(json.dumps(ends))
    print(f"clip: {len(clip) / RATE:.1f} s, {len(SENTENCES)} sentences, saved to {CLIP_PATH.relative_to(REPO)}\n")

    chosen = sys.argv[1:] or list(ENGINES)
    results = []
    for name in chosen:
        print(f"running {name} ...", flush=True)
        done = subprocess.run([sys.executable, __file__, "--engine", name], capture_output=True, text=True)
        if done.returncode != 0:
            print(f"  FAILED\n{done.stderr[-1500:]}")
            continue
        results.append(json.loads(done.stdout.strip().splitlines()[-1]))

    header = f"{'engine':<28}{'load':>6}{'WER':>7}{'RTF':>7}{'delay p50':>11}{'p90':>6}{'finals':>8}{'partials':>9}{'part.cost':>10}{'cores':>7}{'RSS MB':>8}"
    print("\n" + header)
    for r in results:
        print(f"{r['engine']:<28}{r['load_s']:>5.1f}s{r['wer'] * 100:>6.1f}%{r['rtf']:>7.2f}"
              f"{str(r['final_delay_p50']) + 's':>11}{str(r['final_delay_p90']) + 's':>6}"
              f"{str(r['sentences_with_final']) + '/' + str(len(SENTENCES)):>8}{r['partials']:>9}"
              f"{str(r['partial_cost_p50']) + 's':>10}{r['cores']:>7.2f}{r['rss_mb']:>8}")
    print("\ntranscripts:")
    for r in results:
        print(f"  {r['engine']}: {r['transcript']}")


if __name__ == "__main__":
    main()
