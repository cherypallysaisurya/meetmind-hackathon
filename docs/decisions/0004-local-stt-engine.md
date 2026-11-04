# 0004: Local speech-to-text engine: mlx-whisper small, segmented by Silero VAD

Status: accepted
Date: 2026-10-22

## Context

The local SpeechToText adapter must return partial and final text for each audio channel with a short delay after the speaker stops, on the owner's M3 Pro, while the LLMs share the same chip. Step 0.4 benchmarked three engines (four configurations) with `scripts/benchmark_stt.py`: a 42 second clip of ten meeting style sentences spoken by macOS `say` with one second gaps, fed in 100 ms chunks at real-time pace, exactly like the live WebSocket will deliver audio.

## Options considered

| Engine | WER | RTF | Final delay p50 / p90 | Partials (cost each) | CPU cores | RSS |
|---|---|---|---|---|---|---|
| sherpa-onnx streaming zipformer int8 | 17.3% | 0.07 | 1.12 s / 1.17 s | 109 (25 ms) | 0.25 | 263 MB |
| mlx-whisper small + Silero VAD | 2.9% | 0.16 | 0.78 s / 0.83 s | 27 (164 ms) | 0.09 | 1.3 GB |
| mlx-whisper large-v3-turbo + Silero VAD | 1.9% | 0.49 | 1.16 s / 1.48 s | 27 (544 ms) | 0.10 | 2.5 GB |
| faster-whisper small int8 (CPU) + Silero VAD | 2.9% | 0.80 | 1.59 s / 2.24 s | 27 (907 ms) | 3.21 | 1.4 GB |

WER is word error rate against the known sentences. RTF is compute time divided by audio time. Final delay is measured from the end of a sentence to its final text. The whisper rows refresh a partial once a second by re-transcribing the segment so far.

1. **sherpa-onnx streaming zipformer.** The only true streaming engine: word by word partials, 25 ms per update, a quarter of a core. But 17.3 percent WER is far too high to trust: it heard "Syria" for Surya, "bad size" for batch size, "lagency" for latency, and merged two sentences because it missed an endpoint. Its final delay was 1.12 s even with a 600 ms silence rule, because the model itself looks ahead.
2. **mlx-whisper small, segmented by Silero VAD.** 2.9 percent WER (the two remaining errors were "stand up" for standup and "Suria" for Surya). Final text 0.78 s after the speaker stops: 0.6 s of silence wait plus about 0.16 s of transcription. Runs on the Apple GPU, so the CPU stays free. Partials cost 164 ms each.
3. **mlx-whisper large-v3-turbo.** Best accuracy and the only one that spelled Surya right, but three times the GPU time. Two channels would take about the whole GPU and starve the LLMs.
4. **faster-whisper small int8 on the CPU.** Same accuracy as option 2 but 3.2 cores busy and 1.6 to 2.2 s delays. It falls behind real time once partials are on.

## Decision

Option 2. The local SpeechToText adapter uses mlx-whisper with `mlx-community/whisper-small-mlx`. Silero VAD (through the sherpa-onnx runtime) cuts each channel into speech segments with a 600 ms silence window. Each finished segment is transcribed once for the final text. While a segment is still running, the audio so far is transcribed once a second for a partial. Model name, silence window and partial interval live in config.

## Consequences

- Final text arrives about 0.8 s after the last word. The spec's 400 to 700 ms target for "last word to end-of-turn" is slightly missed at 600 ms of silence. A 500 ms window would give about 0.68 s. Step 1.5 tunes this against false endpoints.
- Partials are not word by word. They refresh about once a second and cost about 160 ms of GPU each. Detector A sees a spoken name within about 1.2 s.
- Two channels double the load: about 0.32 RTF plus partials, which leaves GPU room for the LLMs. Measured for real in Step 1.9.
- Names are the weak spot (Surya became Suria). Detector A's fuzzy alias match must tolerate this. `large-v3-turbo` stays a one line config switch if the GPU budget allows it later.
- Whisper writes digits ("40 minutes"), which suits cue points.
- Dependencies: mlx-whisper 0.4.3 (brings mlx, torch, numba) and sherpa-onnx 1.13.8 for the VAD only. faster-whisper is not an app dependency, only an extra for the benchmark's fourth row.
- The whisper weights download from Hugging Face on first use (about 480 MB) into the user's Hugging Face cache. `silero_vad.onnx` lives in the git-ignored `models/stt/`. Step 1.4 adds the download to the run instructions.
- On AWS this adapter is replaced by Amazon Transcribe streaming. The VAD and segmenting logic is local only.
- If word level partials turn out to matter, the sherpa streaming engine can be added later for partials only, with whisper still producing the finals.
