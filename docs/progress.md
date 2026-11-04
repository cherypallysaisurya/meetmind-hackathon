# Progress log

One entry per step: date, step, what changed, verification result.

## 2026-10-22, Step 0.1: repo and folder layout

What changed:
- Spec update 1 arrived before this step was built, so it was applied directly here instead of as a rework.
- Created the git repo and the folder layout. `desktop/` replaces the planned `frontend/`. `backend/app/prep/` added. Empty folders hold a `.gitkeep` so git tracks them.
- `.gitignore` and `.env.example` with seven adapter switches (model names come in Step 0.2).
- README with the positioning line, the two stages, the repo map and the updated timeline.
- `docs/01-problem-statement.md` and `docs/03-architecture.md` with both diagrams updated for the desktop app, the prep pipeline, the cache matcher, the vector store and the two new tables.
- Decision records 0001 (local first with adapters), 0002 (desktop app), 0003 (prep, cache, grounding).
- Original spec moved to `docs/00-build-prompt.md`, update saved as `docs/00-spec-update-1.md`.

Verification: see the commit for this step. Both Mermaid diagrams present, no em dashes in the files we wrote, clean working tree after commit.

## 2026-10-22, Step 0.2: Mac check, tools, models

Mac: Apple M3 Pro, 12 cores, 36 GB RAM, 75 GB free, macOS 26.6.2.

Tools: Docker Desktop 28.3.2 and Node 22.16.0 were already installed. Installed with Homebrew: Ollama 0.40.8 (running as a brew service), ffmpeg 9.0.2, Python 3.12.15. Backend virtual environment created at `backend/.venv`. Swift 6.3 is available through the Command Line Tools, which Step 0.6 may need.

Finding: on Apple silicon the default `qwen3.5:4b` and `qwen3.5:9b` tags resolve to Ollama's MLX builds (safetensors, nvfp4). The MLX runner answers HTTP 501 "structured output is unavailable" when `format` is set, so it cannot do schema-constrained JSON. The GGUF builds (`-q4_K_M` tags) run on llama.cpp and support it. The two MLX builds were removed; `ollama pull qwen3.5:9b` brings one back if ever wanted for its 20 percent faster streaming.

Time to first token, measured with `scripts/measure_ttft.py` (cold = model not loaded, warm = loaded; the two 9b rows were measured with `temperature 0`, 200 token cap):

| Model | Role | Cold TTFT | Warm TTFT | tok/s | JSON schema |
|---|---|---|---|---|---|
| qwen3.5:4b-q4_K_M | classifier | 10.1 s | 0.05 s | 33.5 | ok |
| llama3.2:3b | classifier | 2.5 s | 0.03 s | 47.8 | ok |
| qwen3.5:9b (MLX nvfp4) | answer | 4.6 s | 0.14 s | 26.5 | unavailable (HTTP 501) |
| qwen3.5:9b-q4_K_M | answer | 5.6 s | 0.07 s | 22.5 | ok |
| llama3.1:8b | answer | 5.3 s | 0.04 s | 26.8 | ok |
| nomic-embed-text | embeddings | 0.5 s | 0.02 s | | 768 dimensions |

Picks, written to `.env.example`: classifier `qwen3.5:4b-q4_K_M`, answer and doubt `qwen3.5:9b-q4_K_M`, embeddings `nomic-embed-text`. Llama alternatives kept on disk: `llama3.2:3b`, `llama3.1:8b`. Cold loads are seconds, so `OLLAMA_KEEP_ALIVE=30m` keeps the models resident. About 11 GB of models stay loaded, leaving room for the STT engine, Docker and the desktop app in 36 GB.

Caveat for Step 1.8: on a bare one-line prompt each small classifier got one field wrong (qwen said the question was not directed to the user, llama called it small talk). The real Detector B prompt and the eval decide which one stays.

Verification: all five picked or alternate models return valid JSON under the Detector B schema where required, warm first token under 0.15 s on every model.

## 2026-10-22, Step 0.3: Docker Compose with DynamoDB Local, five tables

What changed:
- `docker-compose.yml` runs `amazon/dynamodb-local:latest` (reports version 3.3.2) on 127.0.0.1:8000 only, with `-sharedDb` and its data persisted in `.dynamodb/` (git-ignored).
- `scripts/create_tables.py` creates `meetmind_profiles`, `meetmind_sessions`, `meetmind_session_items`, `meetmind_documents`, `meetmind_prep_cards` with on-demand billing and a `ttl` attribute on sessions, session_items and prep_cards. Rerunning it leaves existing tables alone. With `DYNAMODB_ENDPOINT` empty it talks to real DynamoDB with the CLI profile, which is the Phase 4 switch.
- `backend/requirements.txt` starts with boto3 1.43.118. `.env.example` gains `TABLE_PREFIX=meetmind_`.

Verification: first run printed five "created" lines and "write and read ok". Second run printed five "already exists" lines and "write and read ok" again. `shared-local-instance.db` exists in `.dynamodb/`, so data survives a container restart.

## 2026-10-22, Step 0.4: STT spike, engine chosen

What changed:
- `scripts/benchmark_stt.py` builds a 42 s test clip (ten meeting sentences, macOS `say`, one second gaps), feeds it to each engine in 100 ms chunks at real-time pace, and reports word error rate, real-time factor, final delay per sentence, partial update cost, CPU cores and memory. Each engine runs in its own subprocess.
- Model files: `models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-26` and `models/stt/silero_vad.onnx` (git-ignored). Whisper weights live in the Hugging Face cache.
- `backend/requirements.txt` adds mlx-whisper 0.4.3 and sherpa-onnx 1.13.8. `.env.example` adds `STT_MODEL`, `VAD_MODEL_PATH`, `STT_SILENCE_MS`, `STT_PARTIAL_EVERY_MS`.
- Decision record 0004 picks mlx-whisper small segmented by Silero VAD. Architecture doc adapter table updated.

Results (full table and reasoning in the decision record):

| Engine | WER | RTF | Final delay p50 | CPU cores |
|---|---|---|---|---|
| sherpa-onnx streaming zipformer int8 | 17.3% | 0.07 | 1.12 s | 0.25 |
| mlx-whisper small + VAD | 2.9% | 0.16 | 0.78 s | 0.09 |
| mlx-whisper large-v3-turbo + VAD | 1.9% | 0.49 | 1.16 s | 0.10 |
| faster-whisper small int8 + VAD | 2.9% | 0.80 | 1.59 s | 3.21 |

Verification: the benchmark computed the word error rate against the known sentences for all four rows, every whisper row produced one final per sentence (10 of 10), and the chosen engine's transcript is in the log above the table. Caveat carried forward: "Surya" came out as "Suria" on the small model, so Detector A's alias match must be fuzzy.

## 2026-10-22, Step 0.5: the seven interfaces and their contract tests

What changed:
- `backend/app/ports/`: SpeechToText (takes the stereo frame, returns transcripts labeled me or them with audio-time stamps), LLM (streaming text and schema-bound JSON), Embeddings, Store (the five record types as dataclasses and 14 read and write methods), Auth (mode plus authenticate), DocumentParser (chunks that remember document and location), VectorStore (add, search nearest first, delete collection). All abstract base classes, so a missing method fails at construction.
- `backend/tests/contract/`: one `...Contract` class per port. An adapter's test file subclasses it, names the class `Test...` and implements `make_adapter()`. The classes are not collected on their own.
- Fixtures: `stereo-two-speakers.wav` (8.3 s, Samantha on the left channel saying "left", Daniel on the right saying "right", silence on the other channel), and the same short document as `notes.txt`, `notes.pdf` (cupsfilter) and `notes.docx` (textutil).
- `backend/tests/test_ports.py` proves every port is abstract and every port has a contract with tests. `pytest.ini` sets asyncio auto mode. `requirements-dev.txt` pins pytest 9.1.1 and pytest-asyncio 1.4.0.

Verification: `pytest -q` in `backend/` gives 14 passed. Collecting `tests/contract` alone gives 0 tests, as intended until adapters exist.

## 2026-10-22, Step 0.6: desktop shell and audio spike

What changed:
- `desktop/package.json` with Electron 45.0.0 as the only dependency and `npm run spike`.
- `desktop/spike/`: `main.js` (always-on-top window, display media handler answering with the app's own frame as video plus `audio: "loopback"`, writes WAV and report), `preload.js`, `index.html`, `capture.js` (mic + system audio into one 16 kHz AudioContext, ten second recording, per-second levels), `frame-builder.js` (AudioWorklet: mono mix, downsample if needed, interleave left = mic and right = system into 100 ms frames).
- Decision record 0005: Electron with built-in loopback, no native helper. Architecture doc and README updated.

What was learned on the way:
- `desktopCapturer.getSources` fails without Screen Recording permission. Returning the app's own window frame as the video source avoids that permission entirely.
- Run from the shell under the editor, the loopback track is live but silent, as the Electron docs warn: the responsible process must hold "System Audio Recording". Launched with `open -n ... --args <app dir>` Electron is responsible and the audio flows. Plain `open --args` without `-n` left a stale default Electron window running, which later made `open -W` hang.
- Chromium applies echo cancellation, noise suppression and gain control to the loopback track and downmixes it to mono unless told not to. With the three constraints false the track is raw stereo.
- This shell sets `ELECTRON_RUN_AS_NODE=1`, which makes the Electron binary act as plain Node (`--version` printed the Node version). The variable has to be unset or avoided with `open`.

Verification, from `desktop/spike/out/report.json` of the final run (16 kHz context, 99 frames of 3200 samples):

| Second | Left (mic) | Right (system) |
|---|---|---|
| 0 to 1 | -59 dB | silence |
| 2 to 6 (`say` speaking) | -30 to -34 dB | -18 to -21 dB |
| 7 to 9 | -59 dB | silence |

The chosen STT model (mlx-whisper small) transcribed the right channel as exactly "This is system audio from the say command. It should appear on the right channel." and the left channel the same, heard through the speakers.

Left for the owner, needs a person at the Mac: run `npm run spike` while Zoom desktop, Teams desktop and Google Meet in Chrome each play audio, and approve the microphone and system audio prompts for Electron if they appear.

Phase 0 is complete. Target was Mon Oct 26, done Thu Oct 22.

## 2026-10-22, Step 1.1: desktop app shell

What changed:
- `desktop/` is now an electron-vite project: TypeScript main process, preload bridge and React renderer, built to `out/`. Pinned: Electron 45.0.0, electron-vite 6.0.0, Vite 8.3.5, React 19.3.1, TypeScript 7.0.2.
- Main process (`src/main/index.ts`): always-on-top panel (380 by 600, resizable, hidden title bar with a drag strip), visible over full screen apps and on every Space, three global shortcuts (Cmd Shift A attention, Cmd Shift D dismiss card, Cmd Shift N next card) forwarded to the page, and a `--smoke` flag that clicks through the tabs, prints the screen text and quits.
- Preload (`src/preload/index.ts`): the page gets exactly one bridge, `window.meetmind.onShortcut`.
- Renderer: local-mode banner, Meeting screen (consent notice "MeetMind is transcribing", copy button for the participant message, Attention button that stays armed for 15 s, shortcut status), Profile screen (name, aliases, role, topics, bio with 2,000 limit, projects with 4,000 limit) saved to this Mac's local storage until Step 1.6 moves it to the service. Plain CSS, light and dark.
- The spike stays runnable with `npm run spike` (own `spike/package.json`).

Verification: `npm run build` and `npm run typecheck` pass. `npm run smoke` printed all three shortcuts as registered, the window title "MeetMind", and both tabs' text including the banner, the consent notice, the participant message, the Attention button and all six profile fields.

Note for anyone running from this editor's shell: it sets `ELECTRON_RUN_AS_NODE=1`, so the npm scripts unset it.

## 2026-10-22, Step 1.2: audio capture behind AudioSource, level meters

What changed:
- `desktop/src/renderer/audio/AudioSource.ts`: the interface (start with a frame callback, stop) and `createAudioSource()`. A frame is 100 ms of interleaved stereo 16-bit PCM at 16 kHz, left me, right them.
- `MacAudioSource.ts`: the spike's capture as the macOS implementation. Mic through getUserMedia, system audio through Chromium's loopback, both unprocessed, mixed by the `frame-builder.js` worklet in one 16 kHz AudioContext.
- `levels.ts`, `useCapture.ts`, `LevelMeter.tsx`: dB per channel from each frame, Start and Stop listening, frame counter, error line. The consent notice shows while listening.
- Main process answers display media requests with the page's own frame plus `audio: "loopback"`. The smoke check now starts listening, speaks a sentence with `say`, prints the meters each second and stops. Its log goes to `desktop/out/smoke.log` because the app is launched through `open`.
- Build config sets `assetsInlineLimit: 0`, otherwise Vite inlined the 1.8 kB worklet as a data URL. The spike folder is removed; decision 0005 and commit af59f1a keep its findings.

Verification, from `npm run smoke`:

| Time | Me (mic) | Them (system) |
|---|---|---|
| 1 s | -28 dB | -14 dB |
| 2 s | -40 dB | -23 dB |
| 3 s | -46 dB | -35 dB |
| 4 s | -30 dB | -15 dB |
| 5 s | -50 dB | silence |

12 frames after 1.5 s of listening, 62 after about six seconds, "not listening" after Stop. The mic hears the speakers at about 15 dB below the loopback, which is the crosstalk noted in decision 0005.

## 2026-10-22, Step 1.3: backend WebSocket server

What changed:
- `backend/app/config.py`: every setting as a pydantic-settings class reading the root `.env`, with the same defaults as `.env.example`.
- `backend/app/audio/frames.py`: frame size (6,400 bytes), channel split (left me, right them), level in dB.
- `backend/app/session/orchestrator.py`: the session owns one WebSocket client. `start` with the profile, binary frames counted and measured, `stats` once per second of audio, `stop`, `attention` recorded for Step 1.7, clear `error` events for bad input.
- `backend/app/main.py`: FastAPI app, `/api/health`, `/ws`, run with `python -m app.main` on 127.0.0.1:8080.
- Desktop: `session/ServiceConnection.ts` (one WebSocket for JSON and binary), `useSession.ts` replaces `useCapture.ts` (connect, send the profile, then stream frames), the meeting screen shows the service's own counts next to the local ones, Attention is sent to the service.
- Protocol section of the architecture doc gains `started`, `stats`, `stopped`.
- Pinned: fastapi 0.161.1, uvicorn 0.54.0, websockets 17.3, pydantic-settings 2.16.1, numpy 2.5.4, httpx 0.28.1 (tests).

Verification:
- `pytest -q`: 20 passed. The WebSocket test sends ten frames with a tone on the left channel only and the service reports 10 frames, 1.0 s, me above -20 dB, them at the silence floor. Bad frame sizes, audio before start and non-JSON control messages come back as `error` events.
- `npm run smoke` with the service running: the desktop sent 62 frames; the service reported 20, 30, 40, 50, 60 frames at one second steps with them at -17 to -27 dB while the Mac spoke and me at -29 to -40 dB, matching the local meters. Service log shows the health call and one accepted WebSocket.

## 2026-10-22, Step 1.4: local SpeechToText adapter, live transcript

What changed:
- `backend/app/adapters/local/stt_mlx_whisper.py`: the first adapter. One `ChannelStream` per channel runs Silero VAD (600 ms silence window, 15 s maximum segment) and decides what to transcribe: every finished segment becomes a final, and while speech is running the audio so far becomes a partial about once a second, starting 300 ms before the VAD noticed the speech. One worker thread runs mlx-whisper jobs one at a time; stale partials are skipped when a newer partial or the final for that speech is already queued. Timestamps are seconds of audio since the session started.
- `backend/app/adapters/factory.py`: `make_speech_to_text()` picks the adapter from `STT_PROVIDER`; anything but `local` says plainly that the AWS adapters arrive in Phase 4.
- `config.py` gains `STT_LANGUAGE` (also in `.env.example`) and `settings.path()` so model paths resolve from the repo root whatever the working directory.
- Session: `start` builds the adapter, loads the model and forwards every transcript as a `transcript` event; `stop` flushes the last words before `stopped`; a client that disconnects mid-session stops the pipeline quietly. Sends to a client that already left are ignored in `main.py`.
- Desktop: `Transcript.tsx` shows final lines (Me in blue, Them in orange, with a clock) and the in-progress partial per channel in italics. Stop now waits for the service's `stopped` so the last transcripts arrive, with a 5 s timeout, and the transcript stays readable after stopping.
- Tests: `tests/adapters/test_local_stt.py` applies the Step 0.5 contract to the real adapter on the two-voice clip. `tests/fakes.py` holds two tiny stand-ins used only by the session tests. A new session test checks transcripts are forwarded in order and before `stopped`.

Verification:
- `pytest -q`: 22 passed in 11 s, including the real-audio contract test (left voice under me, right voice under them, timestamps inside the clip).
- `npm run smoke` with the service running: the spoken sentence appeared under Them at 0:01 as "This is system audio from the say command. It should appear under the meter." (the sentence says "on the them meter"). The Me channel heard the same sentence through the speakers, with "SEI" for "say". 92 frames sent, service counted them in steps of ten. Service log clean after the stop fix.

Carried forward: with speakers instead of headphones, the mic hears the meeting and both channels transcribe the same words. Step 1.5 or 1.7 should drop a me transcript that repeats what them just said.

## 2026-10-22, Step 1.5: end-of-turn detector with a tunable silence window

What changed:
- `backend/app/turns/end_of_turn.py`: every final transcript becomes a `Turn` with `delay_s`, the audio seconds between the speaker's last word and the moment the service knew the turn had ended. The detector also knows who is speaking right now (partials), keeps the last five minutes of turns, and answers `last_turn(channel)` and `recent(seconds)` for the detectors in Steps 1.7 and 1.8.
- The silence window setting is now `TURN_SILENCE_MS` (default 600). The VAD inside the STT adapter applies it; the detector measures the result.
- Session sends a `turn` event after each final. Desktop shows "Last turn: them, known 0.76 s after the last word" in the status area.
- `scripts/measure_turn_delay.py` plays the Step 0.4 clip into the them channel at real-time pace through the real adapter and detector, for any silence window.
- Tests: `test_end_of_turn.py` (partials mark the speaker, finals make turns with their delay, recent window, forgetting), and the session test now expects a `turn` after each `transcript`.

Measured on the ten-sentence clip, all ten sentences intact at both windows:

| Silence window | Delay p50 | Delay p90 |
|---|---|---|
| 600 ms (default) | 0.76 s | 0.79 s |
| 500 ms | 0.66 s | 0.68 s |

The spec's target for this stage is 400 to 700 ms. 500 ms meets it on the clip, but the synthetic voice pauses more cleanly than people do, so the default stays at 600 ms until the Step 1.10 eval with scripted meetings shows whether 500 ms splits real sentences. One line in `.env` changes it.

Verification: `pytest -q` 25 passed. `npm run smoke` showed the turn line with a 0.96 s delay while the test suite was also using the GPU and both channels had speech, which is the contention case Step 1.9 will measure properly.

## 2026-10-22, Step 1.6: Store adapter on DynamoDB Local, profile through the service, local auth

What changed:
- `backend/app/adapters/local/store_dynamodb.py`: the Store port on boto3's thread safe low-level client, every call in a thread. Dataclass records in, camelCase items out, floats to Decimal and back, the session item sort key `timestamp#type` zero padded so string order is time order, paged queries, cascading session delete. The same class serves real DynamoDB in Phase 4 with an empty endpoint.
- `auth_local.py`: mode "local", everyone is the one local user. The factory gains `make_store()` and `make_auth()`.
- `main.py`: `GET /api/health` now reports the auth mode; `GET` and `PUT /api/profile` with the data model's limits (name required, bio 2,000, projects 4,000); the WebSocket and the HTTP routes authenticate through the Auth port (401 or close code 4401 when rejected).
- Session: `start` loads the profile from the store (refused with a clear message when none is saved), writes a session record with a title and a 30-day TTL (`RETENTION_DAYS`), stores every final turn as a `final_turn` item with the same TTL, and closes the record on stop or disconnect.
- Desktop: the profile is read and saved through the service (`session/api.ts`), local storage is gone, the banner shows the mode the service reports or a "service not reachable" notice with the start command, `start` no longer carries the profile. The smoke fills and saves a profile when none exists.
- Tests: `InMemoryStore` in `tests/fakes.py` passes the Store contract itself, so the session and API tests can lean on it. The DynamoDB adapter passes the same contract against the running container (skipped with a message when DynamoDB Local is down). Local auth passes the Auth contract. API round trip and limits. Session tests check the stored record and items.

Verification:
- `pytest -q`: 39 tests, 38 passed and 1 skipped (local auth has no invalid tokens, by design).
- `npm run smoke`: with no profile saved, the smoke saved one through the API and the service accepted `start`; on the next run the profile loaded at launch. DynamoDB Local afterwards held the profile (Surya, aliases Sur and Suria), one session "Meeting on Oct 22, 2026 at 19:49" marked ended with a 30-day TTL, and two `final_turn` items, one per channel.
- The smoke script itself failed once at the sixth second without detail and passed on the next run; it now logs renderer console errors and names the failing snippet. The Store contract now deletes the sessions and documents it creates.

## 2026-10-22, Step 1.7: Detector A (rules), Attention button, alert card

What changed:
- `backend/app/detect/rules.py`: the rules detector. Scores on every them transcript: the user's name or an alias (fuzzy, 0.6), the Attention button armed (0.6), a question cue (0.3), "you" or a topic word within ten seconds after the user spoke (0.3), a topic word (0.2). Fires at 0.6: a name or the button alone, or a question with company. A question to someone else, small talk, or a topic word alone stays quiet. Reasons travel with the alert.
- Session: one alert per utterance, opened on the first partial that fires and updated once with the final text; alerts stored as `alert` items. Attention pressed within ten seconds after a them turn alerts that turn; otherwise it arms the next one for `ATTENTION_WINDOW_S` and is used up by the first alert it helps.
- `turns/end_of_turn.py`: a me turn that repeats what them said within three seconds is flagged as echo (the mic hearing the speakers) and no longer counts as the user speaking, also when the mic's copy was transcribed first.
- Settings `ATTENTION_WINDOW_S` (15) and `AFTER_YOU_SPOKE_WINDOW_S` (10) in `.env.example`.
- Desktop: `AlertCard` ("Question for you", the question in italics until final, reason chips, Dismiss, a "+n more" count), the session hook now lives in `App` so Cmd Shift A, D and N reach it: attention is sent to the service, dismiss drops the current card, next rotates the queue. The smoke speaks "Surya, what batch size did you end up using for the last training run?" and prints the card.
- Tests: `test_rules.py` (fuzzy name, cues, each rule's window, quiet cases), echo flag tests, session tests for the alert flow (alert before turn, one alert per utterance with the same id, stored item) and for Attention after a turn.

Verification:
- `pytest -q`: 48 tests, 47 passed and 1 skipped.
- `npm run smoke`: the alert card showed "Question for you | Saria, what batch size did you end up using for the last training run?" with reasons "your name", "a question". Whisper heard "Saria"; the match came through the alias "Suria" saved in the profile, which is what the alias list is for. The mic heard the question through the speakers; the echo flag now catches that copy even when it is transcribed first.

## 2026-10-22, Step 1.8: Ollama LLM adapter, Detector B (classifier), small talk filtered

What changed:
- `backend/app/adapters/local/llm_ollama.py`: the LLM port on Ollama's HTTP API with an async httpx client. `stream()` yields reply pieces and stops Ollama when the consumer stops iterating; `complete_json()` sends the schema as `format` with temperature 0. Models that can think are told not to. `make_llm()` in the factory, one shared instance in `main.py`.
- `backend/app/detect/classifier.py`: Detector B. Prompt = the profile summary, the last minute of transcript without echo lines, the last thing said, and Detector A's reasons. Strict JSON reply: is_question, directed_to_user, question_text, category (each category defined in plain words in the instructions), confidence. Confirms only a question, for the user, not small talk, at or above `CLASSIFIER_MIN_CONFIDENCE` (0.5).
- Session: when an alerted utterance's final text arrives, the classifier runs as a background task and the alert goes out again with status confirmed or retracted, the category and the confidence; confirmed alerts take the classifier's cleaned question. Alerts are stored once classified. The misheard name is replaced by the real one before the card and the classifier see it (`with_real_name`). A me turn that overlaps the them utterance no longer counts as "you just spoke".
- Desktop: alert status on the card (a "checking" chip, then the category), retracted cards disappear.
- Tests: LLM contract on the classifier model, five real-model cases (name question, name without question, greeting, question to Alex, topic question after the user spoke), classifier prompt and decision rules, session confirm and retract flows, name replacement, overlap rule. 66 tests, 65 passed, 1 skipped.

Model check for the classifier slot, five cases with the defined categories: qwen3.5:4b-q4_K_M 5 of 5 right at about 2 s a call; llama3.2:3b 4 of 5 (never picks technical) at about 1 s. The slot stays on qwen. The 2 s land after the alert is already on screen; Step 1.9 measures it and the eval decides whether the prompt or output needs trimming.

Verification: `npm run smoke` with the service running: the card went from "checking" to "Question for you | What batch size did you end up using for the last training run? | your name | a question | technical". The STT had heard "Saria"; the card shows the real name.

## 2026-10-22, Step 1.9: latency telemetry and the debug panel

What changed:
- `backend/app/telemetry/latency.py`: one `QuestionTiming` per alert, every stage stamped on the audio clock: alert fired, last word spoken, turn known, classified, plus the classifier's wall-clock milliseconds. Stages are reported relative to the last word, so they compare directly with the spec's targets. A `latency` event goes to the client once Detector B has answered.
- `telemetry/log.py`: one JSON object per line on stdout for session start and stop, every turn, every alert, every latency record and classifier failures. CloudWatch reads this format as it is in Phase 4.
- Desktop: a "Show debug" toggle on the meeting screen opens a table per question (alert, turn known, classified, classifier ms, result) with medians and the targets, plus connection and frame counts.
- STT adapter: a final segment is now padded with the 300 ms of audio before the VAD's detected start, because the VAD notices speech a little late and the them final in one run had lost its first word (the user's name) while the partial still had it.
- The question fake in the tests now delivers its final later than its partial, like real speech, so the timing test can check the arithmetic end to end.

Verification: `pytest`: 54 unit and session tests plus the real-audio STT contract pass. The smoke's debug panel for the spoken question: alert -3.04 s (fired on the partial "Surya." three seconds before the last word), turn known +0.96 s, classified +3.56 s, classifier 2551 ms, confirmed. The service log carried seven JSON lines for the run: session_started, alert, three turns, latency, session_stopped.

Observations carried into the Step 1.10 eval: the turn delay was 0.96 s here against 0.76 s on the clean clip, because the mic heard the speakers and the GPU was transcribing both channels and running the classifier at once; with headphones the me channel stays quiet. The classifier's 2.5 s is after the alert is on screen, but a shorter prompt or output could halve it.

## 2026-10-22, Step 1.10: eval harness v1 and the M1 gate

What changed:
- `eval/scenarios/`: six scripted meetings as YAML with a fictional user, a voice per speaker and a label per line (`question_for_user`, `question_for_other`, `small_talk`, `name_without_question`, `open_floor`, `handoff`, or a plain statement). A line can press Attention after it. Together: 12 questions to the user in 5.5 minutes of audio.
- `eval/synth.py` and `eval/generate_audio.py`: every line spoken by macOS `say`, converted with ffmpeg, laid out in time with the user on the left channel and everyone else on the right, plus a timeline JSON with each line's start and end.
- Replay mode in the service: `start` with `replay_file` plays a test meeting from `REPLAY_DIR` into the session at real-time pace and stops at its end. `GET /api/replays` lists the playable files. The desktop has a "Replay test meeting" control, which is also the demo fallback.
- `eval/run_eval.py`: saves the scenario's profile, replays it, presses Attention where scripted, scores alerts against the labels (recall, false alarms per 30 minutes, alert latency from the end of speech, duplicates), restores the owner's profile, and writes `docs/eval-results.md` plus the raw events to `eval/results/latest.json`.
- Detection fixes the first run called for: fuzzy name threshold 0.7 with the system dictionary refusing real words ("surely" no longer looks like Surya, "Siraia" and "Sereya" now do); topic words matched by word ("pipeline" matches "data pipelines"); a plain question right after the user's own turn, or a topic question, is a weak candidate that Detector B judges before any card appears; an Attention alert is never retracted; Detector B's instructions cover dropped punctuation, questions handed to the user and questions to the whole room.
- Tests: scenario files are checked for shape, replay mode has unit and session tests, the new rules and session paths are covered. 84 tests, 83 passed, 1 skipped.

The three runs:

| Run | Detected | False alarms per 30 min | Alert latency p50 / p90 | Note |
|---|---|---|---|---|
| 1 | 4 of 12 | 11.0 | -0.85 s / -0.16 s | misheard names, plain follow-ups, Detector B retracting Attention and handoffs |
| 2 | 11 of 12 | 11.0 | 0.78 s / 3.3 s | after the fixes above; one "false alarm" was a duplicate card |
| 3 | 11 of 12 | 5.5 | 0.78 s / 3.39 s | same pipeline, duplicates scored separately. This is the written record |

**M1 gate: passed.** 11 of 12 questions detected (gate at least 8 of 10), 5.5 false alarms per 30 minutes (gate 15), alert latency p50 0.78 s from the end of speech (gate 1 s). Turn known 0.76 s after the last word (p90 0.83 s). Classifier 2.46 s per call.

The gap to 10 of 10: "Thanks. Surya, how about you?" in the standup. Detector A fired on the name, Detector B retracted it as small talk. "How about you" after a thank-you is a standup handoff, and the classifier needs an example of that. The one false alarm is "Anything else? Thoughts on the evaluation approach?" in the Q and A: a question to the room right after the presenter, who is the user, had spoken.

Carried forward:
- Step 2.4, one card per question: the host's handoff produced a second card for a question already alerted on. Dedupe by text and time.
- Alerts the classifier promotes arrive about 3.3 s after the last word (0.76 s turn plus 2.5 s classifier). A shorter prompt or output for Detector B would pull the p90 down; the p50 target is met.
- The eval user has clean channels. The desktop smoke, with speakers instead of headphones, still shows the mic echo case the echo flag handles.

Phase 1 is complete. Target was Sun Nov 1, done Thu Oct 22. Cut line 1 (prep and cache gate) is Wed Nov 11.

## 2026-10-22, Step 2.1: documents in, chunks and vectors out

What changed:
- Three adapters: `document_parser_local.py` (pypdf for PDF, python-docx for DOCX, plain code for Markdown and text; every passage keeps a location such as "page 3" or "section: Results"), `embeddings_ollama.py` (nomic-embed-text through Ollama, batches of 32), `vector_store_sqlite.py` (sqlite-vec: one file, cosine distance, partitioned by collection, metadata as JSON next to each vector). Decision 0006 picks sqlite-vec over LanceDB on a measured comparison (5 ms versus 13 ms per query, 168 KB versus 276 MB installed).
- `prep/chunking.py`: passages pack into chunks of about 1,200 characters; a new location always starts a new chunk; a full chunk carries its last words into the next so a sentence cut in two is still found. `prep/documents.py`: parse, chunk, embed, store vectors in `docs:{userId}` with the chunk text and location in the metadata, save the record; removing a document removes its vectors.
- The VectorStore port gains `delete(collection, ids)`; the contract covers it.
- API: `GET`, `POST` (multipart, 20 MB limit, pdf, md, txt, docx) and `DELETE /api/documents/{id}`.
- Desktop: a Documents tab with a file picker, the list with chunk counts, and Remove.
- Settings: `VECTOR_DB_PATH`, `CHUNK_CHARS`, `CHUNK_OVERLAP_CHARS`, `MAX_DOCUMENT_MB`. The `data/` folder is git-ignored.
- Sends to a client that vanished mid-session now also cover uvicorn's own disconnect exception, which had left a traceback in the log.
- Tests: contracts for all three adapters on real data (the sqlite file reopened, Ollama embeddings, the parser on the text, PDF and DOCX fixtures), chunking rules, the documents API round trip with in-memory stand-ins (the in-memory vector store passes the contract too). 94 tests, 93 passed, 1 skipped.

Verification: `npm run smoke` added a Markdown file through the Documents tab; the service reported 2 chunks and the sqlite-vec file held two vectors in `docs:local` with locations "section: Results" and "section: Next". Alert card and replay still pass in the same run.

## 2026-10-22, Step 2.2: grounded answer agent with sources

What changed:
- `backend/app/agents/answer.py`: retrieve the top chunks of the user's documents for the question (cosine similarity at least `RETRIEVAL_MIN_SCORE`, up to `RETRIEVAL_TOP_K`), then stream a cue card from the answer model as plain lines: the cue (one sentence, 20 words), dash points with [S1] markers for their sources, a confidence line. A `CardBuilder` turns the stream into a card line by line, so the cue is sent the moment its newline arrives; markers become source numbers on each point; a quoted cue loses its quotes. Facts about the user's work may come only from the sources and the profile; otherwise the cue starts with "Not in your docs".
- Session: the card starts at the final text when Detector A saw a question cue or Attention was pressed; a bare name mention or a weak candidate waits for Detector B. A retraction cancels the card. `answer_delta` events carry the card as it grows, `answer_done` adds the cited sources and the Live label; the answer is stored as a session item; the latency record gains first answer and answer done stages and is sent again when the card finishes.
- The service warms the embedding, answer and classifier models at startup, because the first use of the 9B model in a fresh process cost several seconds in the smoke.
- Desktop: the alert card grows into the cue card: big line, points with source numbers, source chips, Live label, confidence chip.
- Tests: card builder and marker rules, retrieval and prompt with the in-memory stand-ins, session flow (deltas, done, sources, storage, cancellation on retraction), and a real-model test on three seeded notes. 96 tests pass; the real model answered "Batch size was 32." with two grounded points at high confidence, and "Not in your docs about revenue" at low confidence for a question the notes cannot answer.

Verification: `npm run smoke` showed the card "Thirty-two. | Batch size 32 | Gradient accumulation of 4 | One GPU used | Live | high confidence" for the spoken question, grounded in the note the smoke uploaded, and removed its document afterwards.

Not good yet: the first line arrived 9.85 s after the question ended (target 3 s). The model's prompt reading time, running at the same time as the classifier on one GPU, is the suspect; Step 2.4 (start early, cancel and restart) and a measured prompt diet are next. In this run the model also left out the source markers, so no chips showed; the Step 2.7 eval measures source accuracy.

## 2026-10-22, Step 2.3: pinned cue cards and the queue

What changed:
- One card per question: a new alert whose question matches an open card from the last 45 s of audio is folded into it, and when Detector B's cleaned question matches an earlier card (the host handing a question over, the eval's duplicate case) the later alert is folded too.
- A card never disappears while it is being read: a retraction removes a card only while nothing of it is on screen; once the cue line shows, the card stays with a "Probably not for you" title and its generation finishes. A card never changes once its answer is done.
- Queued cards are listed under the current one by question, with a Next button; Cmd Shift D dismisses, Cmd Shift N moves on.
- Tests: the same question asked twice yields one card and one answer. 84 unit and session tests pass.

## 2026-10-22, Step 2.4: start-early drafts with cancel-and-restart

What changed:
- When Detector A fires with a question cue and the partial already looks like a whole question (eight words, or four ending in a question mark), the card is drafted right away against the partial text, buffered, not shown. When the final text arrives, a draft whose question matches it (similarity 0.8 or more) is shown at once with everything written so far; otherwise it is cancelled and restarted with the final. At most two drafts per question, because drafts share the GPU with the speech-to-text and a third draft was seen delaying the final transcript.
- The reasons of an alert are re-scored as its utterance grows, so a question cue that appears after the name counts: the card no longer waits for the classifier when the question arrives after "Surya,".
- The classifier runs after the cue line is on screen instead of alongside the answer model; measured alone, it had been tripling the time to the first line.
- The answer model's cache is primed with the stable prompt prefix (instructions and profile) at session start, about 1 s, so the first question of a meeting pays only for its own tokens. `RETRIEVAL_TOP_K` is 4.
- Card robustness: a cue that holds several sentences is split into cue and points; points the model forgot to mark are attributed to the source they share a number or distinctive word with, so the chips still show where a fact came from.
- A cancelled draft no longer drops its successor from the task table (it had let two drafts run and finish for one question).
- Tests: growing partials yield one card shown only after the final, draft bookkeeping, cue split, attribution, priming. 88 unit and session tests pass.

Measured in the smoke (the spoken question "Surya, what batch size did you end up using for the last training run?", mic hearing the speakers, so whisper transcribes two channels), time from the last word to the cue line on screen:

| Run | What happened | First line |
|---|---|---|
| before 2.4 | card at the final, classifier alongside, cold 9B model | 9.85 s |
| classifier after the line | card at the final | 5.76 s |
| draft kept | partial alert, draft matched the final | 1.96 s |
| no partial alert | whisper did not surface the name in partials | 3.2 s |
| draft kept, third draft running | the transcript itself came 2.66 s late | 3.16 s |

The GPU is the bottleneck: whisper on two channels, the 9B answer model and the 4B classifier all share it. With headphones the mic channel is quiet, which halves the whisper load. The Step 2.7 eval gives the p50 and p90 that the gate needs.

## 2026-10-22, Step 2.5: notes agent, follow-ups build on previous cards

What changed:
- `backend/app/agents/notes.py`: every `NOTES_EVERY_S` (75) seconds of audio, and once more at stop, the answer model rewrites the running notes from the new final turns (echo lines excluded): at most 12 bullets of 15 words, decisions, numbers, names, deadlines, open questions, nothing that was not said. An empty reply keeps the old notes. The update waits while a card is being written, so it never competes with an answer for the GPU.
- Session: `notes_update` events, notes stored as session items, notes and the last two finished cards fed into every answer prompt after the sources, so a follow-up question is answered in context. The stable profile prefix stays first for the cache.
- Desktop: a "Notes so far" block under the transcript.
- Tests: notes parsing and prompt, prompt order with notes and previous cards, notes at stop and on the audio clock. 94 unit and session tests pass.

Verification: `npm run smoke` showed the card at 2.93 s after the last word (alert on the final this time) and, after the stop, three notes. Because the smoke's microphone hears the speakers, the notes treated the spoken question as the user's own words: the crosstalk case again, absent with headphones.

## 2026-10-22, Step 2.6: low-confidence behavior and the "never invent user facts" guard

What changed:
- The card format puts the confidence line first, decided from the sources before the cue is written. The service withholds the cue line until the confidence is known, and at low confidence never sends it: the card shows key points only under a "Low confidence: key points only" warning.
- A cue that starts with "Not in your docs" is tagged and shown in the warning color. A card built with no matching document chunk is tagged "no documents matched" and capped at medium confidence, so a card that leans on the profile or general knowledge is never presented as certain.
- The classifier starts once something readable of the card is on screen, and as a fallback when the card finishes, so an alert whose card never shows a line (low confidence) is still confirmed or retracted.
- Tests: line withheld until confidence is known and at low confidence, not-in-docs tag, ungrounded cap, session flow for a low-confidence card. 98 unit and session tests pass.

Verification: `npm run smoke` showed "It was 32." with three grounded points, high confidence and the source chip, first line 3.23 s after the last word (the alert fired on the final; no draft possible), notes after stop.


## 2026-10-22, Step 2.7: eval with prep packs, answer quality scoring and the M2 gate check

What changed:
- Every eval scenario has a prep pack in `eval/scenarios/<name>/`: an agenda (kept for Phase 2P) and three documents that hold the answers the user gives in the script. `eval/run_eval.py` uploads the pack before each replay and removes it after, grades every card with a judge (the local answer model, given the question, what the user actually said, the documents and the transcript), checks each cited source against its point, counts invented personal facts and cue lines over 20 words, and writes the M2 table and every card into `docs/eval-results.md` for manual review.
- Handoffs. "Surya, do you want to take that one?" is answered as the question somebody asked just before it (`is_handoff` in the rules, `_question_in` in the session). An alert keeps what was heard and the question it puts to the user separately: Detector B judges the heard sentence, the card answers the question. Before this, the card was written for the handoff sentence and the model answered the real question from general knowledge with a wrong source attached; that was all four invented facts of the first run.
- Markdown headings reach the embeddings (`document, location: text`), so "what's the plan for next week" finds the "Plan for next week" document. The right document scores 0.81 for the handoff question; retrieval was never the problem.
- The stop sequence waits for work spawned by other work (a classifier verdict can start a redone card), so the last `answer_done` is sent before `stopped`. The notes agent yields to a card. The answer prompt uses the last 30 s of transcript.
- Two prompt sentences: a status-round "how about you?" is a question to the user, not small talk; points state something to say, never where the facts come from. The card builder strips list numbers from points and drops bare numbers, after a card showed "1", "2", "3" as points for a numbered-list document.
- `scripts/start_local.sh` and `scripts/stop_local.sh` start and stop the whole stack. The README has the real-meeting checklist.
- Tests: handoff rule, a handoff answered as the real question from the start with Detector B given the handoff sentence, a vague handoff redone from the classifier's question, numbered points, prep pack presence. 110 unit and session tests pass.

M2 gate check, three full runs tonight (6 scenarios, 12 questions, prep packs uploaded; `docs/eval-results.md` holds run 3):

| Measure | Gate | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| First cue line from end of speech, p50 / p90 | 3 s / 4 s | 3.44 / 6.68 s | 3.65 / 6.38 s | 3.54 / 6.19 s |
| Cards good enough to say out loud | 7 of 10 | 10 of 11 | 10 of 10 | 10 of 10 |
| Cited sources that support their point | 9 of 10 | 26 of 28 | 25 of 28 | 26 of 31 |
| Invented personal facts | 0 | 4 | 0 | 0 |
| M1 again: detected, false alarms per 30 min, alert p50 | 8 of 10, 15, 1 s | 11 of 12, 5.5, 0.78 s | 10 of 12, 5.5, 0.76 s | 10 of 12, 5.5, 0.76 s |

M2 gate: **not passed**. Card quality and invented facts pass. Two measures fail:
- First cue line. In run 3, 6 of 10 cards arrived within 1.9 to 3.8 s. The four slow ones (5.9 to 6.6 s) have two causes. Two were weak candidates with no name heard ("And what would the bigger index cost us per month?", "That's quick. What changed to make it that fast?"): the card waits for Detector B, 3.9 s median on this Mac while the GPU also runs whisper on two channels and the 9B model, and then takes about 2.5 s itself. Two had early alerts but shared the GPU with a false-alarm card that Detector B retracted only after that card's first line (the order chosen in Step 2.4). With a classifier under 1 s (AWS, Phase 4) all four would land near 3 s. The design change that would help on this Mac is writing the card for a weak candidate while the classifier runs and showing it only on confirmation, at the cost of wasted generations for the candidates that are dropped (2 of 4 per run). This is the owner's decision, as the spec asks for latency gates that fail on hardware.
- Cited sources: 84 to 93 percent across the runs against 90. The rejected citations are filler points the model adds to reach the point count ("This handles day-time document changes effectively") and the "1, 2, 3" card. The judge is the 9B model, so its verdicts move between runs. The bare-number guard landed after run 3 and is covered by a unit test, not re-measured.
- M1 variance. "Thanks. Surya, how about you?" is retracted in every run; asked directly, the classifier confirms it three times out of four and labels the fourth small_talk, so the category is the unstable part. "Sur, how does the pipeline handle ..." was heard as "So, how does ..." in run 3 and dropped as a question to the room.

Verification: the three eval runs above; every card is listed in `docs/eval-results.md`; 110 tests pass.


## 2026-10-23, Step 2.7 follow-up: reasoning questions get reasoned answers

What changed:
- The owner clarified the intent: this is not a documents-only answer system. Any question to the user gets an answer; the documents are used when they match. A live check showed the gap. Asked "what would happen if we used chunks of a thousand tokens instead of three hundred?", the card said "Not in your docs" at low confidence, hid the cue and recited the current numbers.
- The card prompt now separates fact questions (what was done, measured or decided: facts about the user's work come only from the documents, profile and transcript, "Not in your docs" when missing) from reasoning questions (what would happen, is it worth it, why, how do two options compare: reason from the current setup in the documents plus general knowledge; the cue is the position to state; never "Not in your docs"). The confidence rule moved to the first line of the prompt: high when the documents answer a fact question directly, medium for reasoning and general knowledge, low only for guesses or a missing fact about the user's work.
- Files: `backend/app/agents/answer.py`, the INSTRUCTIONS text only. No code path changed.

Verification: live check through the real answer agent with the research-lab pack uploaded, four questions.

| Question | Before | After |
|---|---|---|
| What would happen with chunks of a thousand tokens? | low, "Not in your docs", cue hidden, current numbers recited | medium, cue "Smaller retrieval context and faster processing; trade-off between coverage and latency.", points on recall and what to test, two of them from the documents |
| Would a reranker be worth it for us? | low, cue hidden, numbers recited | medium, cue "Yes, it improves ranking but increases latency; test with 20% traffic first." |
| Which evaluation set did you measure the recall gain on? (fact, in the documents) | high, correct | high, correct, two sourced points |
| What batch size did you use? (fact, not in these documents) | low, "Not in your docs" | low, "Not in your docs", cue hidden, key points only |

A stray marker is still possible: one reasoning point was tagged with a document that does not say it ("re-ranking top 100 candidates"); the eval's source check counts those. 110 tests pass. Not re-run through the full eval, whose questions are all fact questions with the answer in the documents; a reasoning scenario is the candidate for the next eval update.


## 2026-10-23, Step 2.7 follow-up: the meeting screen became two tabs

What changed, after the owner's first real look at the app ("lots of buttons, lots of stuff on screen, hard to find the answer"):
- Answers tab: one bar (Start listening or Stop, a listening dot, two sound dots for you and them, Attention) and the card. Nothing else. With no card, one quiet line says what will happen.
- Conversation tab: the same bar, the consent message while listening, the conversation as a chat (You and Them, newest line kept in view), the notes folded, and a "More" fold with the test replay, the status lines, the shortcuts, the local-mode statement and the debug panel.
- The card: the title says "Say this" once the line is there ("Key points only" at low confidence, "Question for you" while writing), the question in small grey, the line in large type, the points with source numbers, a confidence chip and the document names. The reason chips, the Live label and the shortcut hints are gone from the card.
- The yellow local-mode banner is gone; a problem with the service still shows a banner.
- `npm run start` and `npm run smoke` clear ELECTRON_RUN_AS_NODE before `open`, so they work from a shell that sets it (Claude Code's does; the owner's terminal does not). The smoke test follows the new tabs.
- Files: desktop/src/renderer/screens/AnswersScreen.tsx and ConversationScreen.tsx (new, replacing MeetingScreen.tsx), components/Toolbar.tsx (new), components/AlertCard.tsx, Transcript.tsx, LocalModeBanner.tsx, App.tsx, styles.css, desktop/src/main/index.ts (smoke test), desktop/package.json.

Verification: `npm run smoke` through the normal launch path on the two-tab screen: listening with both sound dots moving, the conversation on its tab, the card on the Answers tab reading "Say this" with the line, two sourced points, high confidence and the document name, the debug panel, stop, replay with transcript lines, all as expected. The smoke's cleanup step was corrected afterwards (it opened the wrong tab) and that last step is verified by reading, not by a full run: the next run's window was closed by hand before it finished. The notes line reads "none" six seconds after Stop because the stop sequence now waits for the notes agent; the notes arrive a few seconds later. No backend change in this step.


## 2026-10-23, Step 2.7 follow-up: one-on-one switch and Export notes

What changed, two asks from the owner before their manager meeting:
- One-on-one switch on the Answers tab ("One-on-one: every question is for me"). In a meeting of two, every question from the other side is for the user, so the rules fire on any question at once instead of waiting for a name, a "you" after the user spoke, or a topic word. Detector B still checks each one, so small talk is still dropped. The desktop sends `{"type": "one_on_one", "on": true}` when the box is ticked and again after every start; the service accepts the flag in the start message too.
- Export notes on the Conversation tab. One Markdown file, saved where the user chooses (macOS save dialog through a small preload bridge): the notes, every card of the session that got an answer (question, line, points with document names, confidence), then the conversation. Dismissed cards are included; the session keeps every card it has seen for this.
- Files: backend/app/detect/rules.py (the switch), backend/app/session/orchestrator.py (the message), desktop/src/renderer/useSession.ts, export.ts (new), screens/AnswersScreen.tsx, screens/ConversationScreen.tsx, preload/index.ts, main/index.ts (save-file handler), styles.css, README.

Verification: 113 backend tests pass, three new (the rule fires only when the switch is on and the text is a question; a session with the flag answers a nameless question; without it nothing shows before Detector B). Desktop typecheck and build pass. The export dialog is a manual check for the owner: press Export notes after a session and open the file.


## 2026-10-25, decision 0007 and the fixes from the first real meeting

What changed (decision 0007, docs/decisions/0007-complete-sentences-only.md):
- Cards only on complete sentences. Detector A ignores partial transcripts; the start-early drafts from Step 2.4 are removed. In the real call, drafts were written for fragments like "you have your repost." and for statements.
- One-on-one switch: a sentence that reads as a question is confirmed by the rules and Detector B is skipped; when Detector B does run, it can drop small talk but cannot say "not for you". The desktop remembers the switch. A retracted card fades after six seconds.
- Notes every 180 s instead of 75 s, still yielding to any card.
- Tag questions: speech-to-text writes "right?" as "Right." and the rules missed Dana's "I don't think you're calling the API. Right." Now a tag closing a sentence counts as a question; "Right, so ..." opening a sentence does not.
- The after-you-spoke window is measured from when the sentence started, so a long question no longer falls out of it.
- The cue is written in the user's own voice; at most four points per card.
- Confirm-a-claim questions ("you're just querying the database directly, right?"): the card never shows a line to read out. It is low confidence, titled "Your call", with the warning "You are asked to confirm something about your own work. The app cannot check it: answer from what you know." and the points for reference. Reason: in the real call and in five tries afterwards with the real knowledge base, the 9B model got this question wrong every time, agreeing, then disagreeing, once with a citation to a section that said neither. The knowledge base answers it only indirectly ("Why the demo stores files, not a database"); the lookup ranks that section 11th for this question, outside the four it keeps and outside the 16 nearest, so neither a keyword boost nor nomic's query and document prefixes (tested) bring it in.
- A new eval scenario, manager-one-on-one, built from the real call's transcript with the real knowledge base as its pack and the one-on-one switch on.

Eval (seven scenarios, 15 questions, run before the confirm-a-claim guard and the four-point cap; docs/eval-results.md holds this run):

| Measure | Gate | Run 3 (Step 2.7, drafts on) | This run (complete sentences) |
|---|---|---|---|
| Questions detected | 8 of 10 | 10 of 12 | 14 of 15 |
| Manager scenario, detected | | | 3 of 3 |
| False alarms per 30 min | 15 | 5.5 | 12.3 (2 of the 3 are Dana's rhetorical "right?" in one-on-one mode) |
| Alert latency p50 | 1 s | 0.76 s | 0.87 s |
| Alerts before the speaker finished | | 4 of 10 | 0 of 14 |
| First cue line p50 / p90 | 3 s / 4 s | 3.54 / 6.19 s | 4.94 / 6.68 s |
| Cards good enough to say out loud | 7 of 10 | 10 of 10 | 12 of 14 |
| Cited sources that support their point | 9 of 10 | 26 of 31 | 32 of 35 |
| Invented personal facts | 0 | 0 | 4 (3 on the database card, now covered by the guard; 1 "Owner is me" on the sprint card) |

The first cue line is about 1.4 s slower at the median, as decision 0007 expected: nothing starts before the sentence is complete. That is the cost of not answering fragments; on the real call the fragment cards were the main complaint. M2 gate still not passed on latency and invented facts.

Verification: 120 backend tests pass (new: tag questions, sentence-start window, one-on-one confirmation without Detector B, four-point cap, confirm-a-claim card never shows a line and keeps its points, ordinary questions still stream their line). Real-model check after the guard: the database question gave no line at any moment, tags low_confidence and asks_to_agree; "How long until the OpenPlaces places are in?" still gave its line ("It will take at least half a day to add OpenPlaces places."). Desktop typecheck and build pass. The owner's six knowledge base files are loaded in the service.


## 2026-10-26, general questions and the "Use my documents" switch

Ask from the owner, after an AWS re:Invent session: answers must not depend on the uploaded documents only; the model's own answers matter as much.

What was measured, on the owner's six knowledge base files:
- General questions (Lambda vs Fargate, Bedrock caching, RAG, Amazon Q, eight more) matched unrelated Harbor pieces at 0.49 to 0.59, above the 0.45 cut-off. The 9B model then answered them about Harbor ("Fargate scales well for our existing traffic patterns", Bedrock caching answered with the Harbor data map).
- Document questions on the same files scored 0.59 to 0.86; in the eval packs some real ones score 0.52 to 0.54 (follow-ups like "which evaluation set did you measure that on?").
- A cut-off of 0.60 kept general questions clean but cost the weak document matches: in the eval, cards good enough to say out loud fell from 12 of 14 to 7 of 14 and invented facts rose from 4 to 13, the model inventing facts about the user's work when its documents were cut. A first prompt that told the model the sources were "often unrelated, ignore them" made it distrust even the right ones ("fifty-two dollars a month" where the document says forty).
- No single cut-off separates the two with nomic-embed-text. The owner has two kinds of meeting anyway: work meetings, where the documents matter, and talks, where they do not.

What changed:
- "Use my documents" checkbox on the Answers tab, remembered on this Mac. Off: no document piece reaches the model; the card is the model's own answer. On: as before, with the cut-off back at 0.45. The service accepts `{"type": "use_documents", "on": false}` and the flag in the start message.
- The card prompt names a third kind of question, general (technology or practice in general, not the user's own work): answered from the model's own knowledge with a clear position, at medium confidence, never "Not in your docs". Sources "may be unrelated"; if one answers the question the answer comes from it and never contradicts it. The profile is for speaking as the user and for questions about their own work. The model must not state what the user has or has not tried unless something says so.
- A source marker that points at no source given to the model is dropped.

Eval with documents on (seven scenarios, 15 questions; docs/eval-results.md holds this run):

| Measure | Gate | Before today | Cut-off 0.60 | Now (0.45, switch, softened prompt) |
|---|---|---|---|---|
| Questions detected | 8 of 10 | 14 of 15 | 14 of 15 | 14 of 15 |
| First cue line p50 / p90 | 3 s / 4 s | 4.94 / 6.68 s | 3.68 / 5.68 s | 3.95 / 6.09 s |
| Cards good enough to say out loud | 7 of 10 | 12 of 14 | 9 of 14 | 11 of 14 |
| Cited sources that support their point | 9 of 10 | 32 of 35 | 20 of 21 | 30 of 32 |
| Invented personal facts | 0 | 4 | 13 | 6 |

Of the 6: four are on the repo card, where the judge flagged facts that are in project-overview.md (demo address, port 8010, release path); two are on the database card, shown under the "Your call" warning with no line. One more card failed only on length (a 26-word cue).

Real-model check with the six files loaded: documents off, Lambda vs Fargate gave "For a stateless search API, I recommend AWS Lambda for cost-efficiency and quick scaling." and RAG a general explanation, no document pieces in the prompt; Bedrock caching still mentions the Harbor bot once (from the profile). Documents on, "What does a search cost?" came from results-and-numbers.md at high confidence. 122 backend tests pass; desktop typecheck and build pass.


## 2026-10-26, Step P.1: Prepare tab, meetings prepared ahead of time

Phase 2P started on the owner's go ("whats next in phase? proceed with that"), with the M2 latency gate still open: prepared cards are the planned answer to it.

What changed:
- A session record can be prepared before the meeting: it gets an agenda and participants, and started_at 0 until it is held. The DynamoDB adapter now keeps a field's default when an older item lacks it (agenda on an older session reads as "", not None).
- Endpoints: GET /api/prep (prepared meetings, the ones not held yet first), POST /api/prep {title, agenda, participants}, PUT and DELETE /api/prep/{sessionId}. An agenda is required.
- A live start may name "prep_session_id": the session then is that prepared record (same id, its title and agenda), now held. An unknown id is an error naming the Prepare tab.
- Desktop: a Prepare tab between Conversation and Documents. Prepare a meeting (title, agenda pasted as it is, who attends), edit, remove, and pick the one the next Start listening uses; the pick is remembered on this Mac and shown on the Answers tab. Documents stay on the Documents tab; the form says how many will be used.
- Files: backend/app/ports/store.py, adapters/local/store_dynamodb.py, main.py, session/orchestrator.py, tests/test_prep_api.py (new), tests/contract/store_contract.py; desktop/src/renderer/screens/PrepareScreen.tsx (new), session/api.ts, session/ServiceConnection.ts, useSession.ts, App.tsx, screens/AnswersScreen.tsx, main/index.ts (smoke tab positions).

Verification: 127 backend tests pass (new: prepare, list, update, delete; agenda required; a start with a prepared id holds that record; an unknown id is an error). The store contract's new prepared-session round trip passes on DynamoDB Local. The real service created, listed and deleted a prepared meeting. `npm run smoke` passed end to end with the new tab, including its cleanup. Desktop typecheck and build pass.


## 2026-10-26, Step P.2: question predictor

What changed:
- backend/app/prep/predictor.py: QuestionPredictor reads the meeting's title, agenda, who attends, the user's profile and, for every agenda line, the three document pieces that match it best (without repeats, within 6,000 characters; feeding every document would be about 10,000 words, too slow for the local model). The answer model (qwen3.5 9B) replies in strict JSON, like the classifier: 20 to 30 questions most likely to be asked to the user, each with 2 or 3 other phrasings. clean() drops empty and repeated questions and phrasings, keeps at most 3 phrasings, caps the list at 40.
- Not wired into the app yet: Step P.3 runs it as the first half of the prep job.
- Tests: tests/test_predictor.py (the prompt carries the agenda, the attendees, the profile and the matching piece but not an unrelated one; the excerpt budget and no repeats; clean(); the schema).

Verification, on the real model with the owner's six knowledge base files and the agenda of the Dana one-on-one (eval/scenarios/manager-one-on-one/agenda.md): 10 excerpts, 5,783 characters; 26 questions with 2 phrasings each in 90.6 s. They follow the agenda and the documents: Dana's eight points, the next release without OpenPlaces, the data map start and owners, the round-6 leftovers, nearest-first ordering, "Is the search bot calling the API or reading from CSV exports now?" (close to what Dana asked in the real call), the Staylane location error, the age wording, the arcade spot-check, rollback. The real call's "You have your repo somewhere else, right?" was not among them. Some questions name Dana in the third person ("Dana's eight points") where he would say "my"; matching is by meaning, so this matters less than it reads. 131 backend tests pass.


## 2026-10-26, Step P.3: prepared cards, the background job and the review screen

What changed:
- backend/app/prep/cache.py: AnswerCache. build() runs the predictor, then writes a card for each predicted question with the same answer agent and prompt as a live card, saves it in prep_cards and indexes the question plus its phrasings in the VectorStore under the meeting's own collection (prep:<sessionId>), ready for the live matcher in P.4. Preparing again replaces the model's cards and keeps the ones the user edited. edit() rewrites the line and points, marks the card approved (userEdited) and lets its line show whatever the model's confidence was. remove() and forget() clear the index too.
- Endpoints: POST /api/prep/{id}/build starts the job in the background (a second press while it runs returns its progress); GET /api/prep/{id}/status (predicting, writing card n of m, done with seconds, failed with the error); GET /api/prep/{id}/cards (edited first); POST /api/prep/{id}/cards {question} writes a card for a question the user expects; PUT and DELETE /api/prep/{id}/cards/{cardId}. Deleting a prepared meeting drops its index. A profile is required to build.
- Desktop: each prepared meeting has "Cards": Prepare cards (or Prepare again) with a progress bar polled every 1.5 s, add a question, and every card with its question, line, points, sources and confidence, Edit (line and one point per line) and Delete. Cards with no line say why: low confidence, or "Your call" for a claim about the user's own work.
- Files: backend/app/prep/cache.py (new), backend/app/main.py, tests/test_cache.py (new), tests/test_prep_api.py; desktop/src/renderer/screens/PreparedCardsScreen.tsx (new), screens/PrepareScreen.tsx, session/api.ts, styles.css.

Verification: 136 backend tests pass (new: a card per predicted question with every phrasing indexed; preparing again keeps edited cards without indexing anything twice; removing a card and forgetting a meeting clear the index; the endpoints build in the background to "done", list, edit, add, delete, and deleting the meeting drops its index; building needs a profile). Desktop typecheck and build pass. Real run through the service with the owner's six files and the Dana one-on-one agenda: 27 cards in 281.6 s (90.6 s predicting, then about 7 s per card). The spec asks for a few minutes for a normal agenda with about ten documents; this is about five. Card quality is the live card's: most are grounded, some are wrong and need the review screen, for example "Did you finish Dana's eight points?" answered "Not entirely; we finished most" where status-this-week.md says not started. The prepared meeting "Dana 1:1 (prep check)" is kept in the owner's list for P.4.


## 2026-10-26, Step P.4: the cache matcher in the live path

What changed:
- When a card is due in a prepared meeting, the session first embeds the question and searches the meeting's prepared phrasings (prep:<sessionId>, top 5). The closest card wins, an edited card getting a 0.03 edge over a close one. A score of CACHE_HIT_SCORE (0.75) or more shows the prepared card at once, labeled Prepared; anything less writes the live card as before. Every decision is logged as cache_match with the score, the prepared question and the phrasing it matched. A failed lookup falls back to the live card.
- The end of a card (answered, remembered for follow-ups, answer_done, stored, timed) is one method, _finish_card, for both paths; the answer log line carries the label.
- The session keeps the prepared meeting's cards from the start; the embeddings and vector store are kept on the session for the matcher.
- Files: backend/app/session/orchestrator.py, backend/app/config.py, .env.example (CACHE_HIT_SCORE), tests/test_prep_api.py.

Why 0.75, measured on the owner's 27 prepared cards for the Dana one-on-one: correct matches scored 0.948 ("How long will the small release take you without OpenPlaces?"), 0.895 (the Staylane fix), 0.814 ("Are you calling the API or just using the CSV I sent?") and 0.777 ("And how long would the OpenPlaces places take you?"). The highest wrong match was 0.720 ("hours for Dana's eight points" against the OpenPlaces card); unrelated questions scored 0.44 to 0.61. 0.75 has no wrong hits on this set and misses one right card: the real call's "you're just querying the database directly, right?" at 0.655. Step P.5 checks it on the full eval.

Verification: 138 backend tests pass (new: a question matching a prepared card shows it and writes no live card; a question far from every card gets a live card). Real replay of the scenario built from the call, held as the prepared Dana meeting with the real models: "And how long would the OpenPlaces places take you?" hit at 0.777 and showed "It takes more than a day for the OpenPlaces integration." 0.83 s after the last word (a live card takes 4 to 6 s). The four other questions missed (0.741, 0.568, 0.533, 0.658) and got live cards; all four end in "right?" about the user's work, so they show "Your call" with no line. The rhetorical "This is our GitHub, and we have two projects, right?" at 0.741 would have shown a wrong card at a threshold of 0.74.


## 2026-10-26, Step P.5: eval with preparation, the Phase 2P gate check

What changed:
- eval/run_eval.py --prep: every scenario is prepared like a real meeting (its agenda.md and the speakers other than the user as attendees), its cards are built through the service, and the replay holds that prepared meeting. Every detected question's best prepared match is judged by the local model (does the prepared question ask for the same information?), which gives the wrong-hit count and a threshold sweep over the same matches. The judge retries once after a timeout (the first full run lost one judge call to the 120 s client limit on the scenario that carries the owner's six files). A --prep run writes docs/eval-results-prep.md and eval/results/latest-prep.json and leaves the live report alone.
- The service sends each match decision to the client as a cache_match event, before the card. The architecture doc now lists the prep flow, the prep endpoints and the new messages.
- Files: eval/run_eval.py, backend/app/session/orchestrator.py, docs/03-architecture.md, docs/eval-results-prep.md (new).

Prep gate (seven scenarios, 15 questions, 14 detected, real models, CACHE_HIT_SCORE 0.75):

| Measure | Gate | Local |
|---|---|---|
| Cache hit rate on detected questions | aim for at least half | 7 of 14 (the right prepared card existed for 9) |
| Card latency on a hit, p50 from end of speech | 1 s or less | 0.89 s |
| First cue line on a miss, p50 | 3 s or less | 3.9 s |
| Wrong cache hits | report it | 0 of 7 |
| Cards good enough to say out loud, hits / misses | 7 of 10 | 6 of 7 / 4 of 7 |
| Invented personal facts, all cards | 0 | 7 |
| Preparation time per scenario | a few minutes | 151 to 279 s, 20 to 28 cards |

Prep gate: **passed** (hit rate, hit latency, no wrong hits). Across all cards the first line now arrives at p50 3.53 s, p90 5.63 s (live only, same day: 3.95 / 6.09 s).

Threshold sweep, the same 14 matches: 0.60 gives 13 hits with 4 wrong; 0.65, 12 with 3 wrong; 0.70, 8 with 1 wrong; 0.75, 7 with none; 0.80, 6; 0.85, 3; 0.90, 2. 0.75 is the lowest threshold with no wrong hit, so it stays. Two right cards existed below it: "You have your repo somewhere else, right?" against "Where exactly does the code for the empty repos live today?" at 0.681, and "Which evaluation set did you measure that on?" against "Which evaluation set are these numbers based on?" at 0.663; both got live cards.

Still open, carried from Phase 2: invented facts are not 0. One of the 7 is on a prepared card ("Word documents: supported after PDF support" where the document says Word follows PDF); prepared cards can be fixed on the review screen before the meeting, live ones cannot. The M2 first-line gate (p50 3 s, p90 4 s) is still above target on misses.


## 2026-10-26, check: Meta's Llama models in place of Qwen (no change made)

The owner asked whether the Meta models on the Mac (llama3.2:3b, llama3.1:8b, already pulled in Ollama) would make MeetMind more accurate or faster.

Question checker (Detector B), on all 71 sentences from others in the seven eval scenarios, 17 of them questions for the user:

| Model | Right | Questions for the user missed | False alarms | Median time |
|---|---|---|---|---|
| qwen3.5:4b-q4_K_M (current) | 64 of 71 | 5 | 2 | 1.9 s |
| llama3.2:3b | 58 of 71 | 12 | 1 | 1.0 s |
| llama3.1:8b | 62 of 71 | 5 | 4 | 2.2 s |

Card writer, four questions on the owner's six files: qwen3.5:9b-q4_K_M first line 4.8 s, done 7.0 s (medians), all four cards grounded and correct. llama3.1:8b first line 2.7 s, done 4.5 s, but three of four cards carry wrong facts ("We charge a small fee for each search", "0.1 cent per character" where the document says per sentence, "11 to 17 dollars for an Lisbon search" where that is the cost of rating Lisbon), one card has no points and a 30-word cue, and it names the user in the third person.

Decision: keep Qwen for both. The 3B checker would miss most questions; the 8B writer is faster but invents facts, which the spec ranks above speed. Larger Meta models on AWS are worth testing in Phase 4 together with the other options there.


## 2026-10-26, Meta's Muse Spark adapter for the Meta AI hackathon (decision 0008)

The owner: this project is for this week's Meta AI hackathon, which needs Meta models; afterwards MeetMind goes back to the local models.

What changed:
- backend/app/adapters/meta/llm_meta.py: MetaLLM on Meta's Model API (Chat Completions at https://api.meta.ai/v1, bearer key, OpenAI-compatible, checked against Meta's docs: create-chat-completion, schemas, structured-output, reasoning). stream() yields only delta.content and skips delta.reasoning_content; complete_json() asks for response_format json_schema at temperature 0; reasoning_effort "minimal" (Muse Spark cannot switch reasoning off). API errors name the status and Meta's reason.
- The factory builds it for LLM_PROVIDER=meta and refuses to start without META_API_KEY. Settings META_API_URL, META_API_KEY, META_REASONING_EFFORT; .env.example documents them; the key goes only in .env (git-ignored).
- /api/health reports where the language model runs. With the Meta model on, the consent message says text from the call is sent to Meta's model, and the status line says speech stays on the Mac while questions and answers go to Meta.
- The Ollama adapter test builds Ollama directly, so it keeps testing the local model whatever LLM_PROVIDER says. The real-API contract test (tests/adapters/test_meta_llm.py) skips until META_API_KEY is set.
- Decision record 0008.

Verification: 141 backend tests pass (new: the stream yields "ban", "ana" and skips the reasoning chunks; complete_json sends the schema and parses the reply; a 402 names the status and "No payment method on file"; health reports the model). Desktop typecheck and build pass. Not yet run against the real API: it needs the owner's key in .env. The owner's billing page shows "No payment method on file. Add one to make API requests.", so requests may be refused until a card is added, even with free credits.


## 2026-10-27, Step H.1: claim check (decision 0009, hackathon feature 1)

The owner approved four hackathon features ("proceed doing all features"); decision 0009 records them.

What changed:
- backend/app/agents/claims.py (new): the claim checker. It reads the user's document pieces whole, nearest to the claim first until CLAIM_CONTEXT_CHARS (40,000) is full, then in document order, and asks the answer model for strict JSON: supports, contradicts or not_found, a quote and a line to say. A verdict counts only when the quote (letters and digits, at least four words) is in one of the pieces; otherwise it is not found.
- backend/app/agents/answer.py: for a question that asks the user to agree with something about their work, the card is written as before ("Your call", no line); then, with documents on, the claim checker runs and a verdict replaces the card: the line to say, the quote as the only point, its source, high confidence, tag claim.
- backend/app/main.py: the documents are read into the model's prompt cache when the service starts and after every upload or removal, in the background; a newer change cancels the older read.
- Desktop: the card's title says "Your docs say otherwise" or "Your docs agree", and the quote shows as a quote. While the check runs, the warning says the documents are being checked.
- CLAIM_CONTEXT_CHARS in config and .env.example; the architecture doc lists the claim checker.

Why read the documents whole: for the real call's "I don't think you're actually calling the API, right? You're just querying the database directly." the piece that settles it ("There is no database yet; that is what the data map adds.") ranks 32nd of 66 by similarity, so no top-k search can reach it. The owner's six files are 31,722 characters, about 9,000 tokens.

Measured on the local model (qwen3.5:9b-q4_K_M, the owner's six files, four claims):

| | First prompt | Pieces by score, numbered sources | Pieces in document order, prompt for claims with several parts |
|---|---|---|---|
| Right verdicts with a quote really in the documents | 2 of 4 | | 4 of 4 |
| Time per check | 33 to 35 s each | | 35 s for the first, 2.9 to 5.8 s after it (Ollama keeps the read documents) |

The first prompt's answer to the database claim was wrong ("We do call the API") with a quote that is not in the documents; the quote check alone would have turned it into "Your call". An answer card between two checks did not empty the cache (5.8 s for the next check).

Verification: 149 backend tests pass (new: a verdict counts only with its quote in a document; a short quote or an empty line is no verdict; pieces come in document order so every prompt starts the same; a small budget keeps the nearest pieces; a contradicted claim becomes the correction with its source; an unsettled claim stays the user's call; no check for an ordinary question or with documents off). Real replay of the scenario built from the owner's first call: the database question's card became "We use plain files (CSV, JSONL) instead of a database for the demo." with the quote and the source "decisions-and-reasons.md, section: Why the demo stores files, not a database"; the judge rated it good, where the committed run had a withheld line and invented points ("Direct queries replace separate API calls").

Cost on the local model: the first read of the documents takes 35 to 49 s of the GPU and holds up every card behind it. In the first replay it ran at the start of the meeting and the first questions waited (a card finished 49 s after the question), so it now runs when the service starts and when documents change, not when a meeting starts. When the cache has been emptied in between (in the second replay the eval's judge had used the model, and the documents were uploaded just before the replay), the first claim check of the meeting pays the full read: the database card's line came 34 s after the question. On Meta's hosted model the same read is a normal-sized prompt with prompt caching; to be measured once the key is in .env.


## 2026-10-27, Step H.2: screen-aware answers (decision 0009, hackathon feature 2)

What changed:
- backend/app/ports/llm.py: a message may carry JPEG pictures. The Ollama adapter sends them as base64 in images; the Meta adapter as an image_url part with a base64 data URL (Meta's chat completions schema page).
- backend/app/detect/rules.py: refers_to_screen, for questions that point at something shown ("this chart", "these numbers", "on the screen", "I'm sharing").
- backend/app/session/orchestrator.py: with See my screen on, such a question sends screen_request to the app and waits up to 1.5 s for the picture; without one the card is written as before. The picture lives only for that card.
- backend/app/agents/answer.py: the picture goes with the question, plus a note that it is the user's screen and that the MeetMind panel is to be ignored. The note is only in prompts that carry a picture, so the cached start of every other prompt stays the same. Tag screen on the card.
- Desktop: a "See my screen" switch on the Answers tab (off by default, remembered); the main process takes one picture of the display under the mouse pointer with desktopCapturer (1,440 pixels wide, JPEG) and returns nothing without Screen Recording permission; the card shows "Read your screen"; the consent message says the screen may be read when the switch is on.

Verification: 156 backend tests pass (new: the rule; the Ollama and Meta message shapes; the agent sends the picture and the note only when given one; over the WebSocket a chart question with the switch on asks for the picture and the card is written with it; with the switch off nothing is asked; when no picture comes the card goes ahead without it). Desktop typecheck and build pass. Real model: a bar chart ("answers within 3 seconds, by week": 88, 85, 46, 81 percent) and "Surya, what do you make of this chart?" gave "Week 3 dropped to 46% due to a bridge outage; we're back to 81% now." with the three other weeks as points (the label in the test picture was cut to "dge outage"). Without the picture the card had no line and said no chart was reviewed. First line 12.6 s with the picture against 6.5 s without, while the eval's judge shared the GPU. Not checked yet: a picture taken by the app itself, which needs the owner to allow Screen Recording for MeetMind once.


## 2026-10-27, Step H.3: suggest a question to ask (spec steps 3.1 to 3.3 brought forward, decision 0009, hackathon feature 3)

What changed:
- backend/app/detect/rules.py: is_open_floor, the open-floor detector (3.1): "any questions", "anything else,", "thoughts?" or "questions about" at a sentence start, "does anyone have questions", "open the floor", "Q&A". "If there are no more questions, let's wrap up" and "Surya, thoughts on that?" (a handoff asking the user's opinion) are not open floors.
- backend/app/agents/doubts.py (new), the doubt agent (3.2): one question in the user's topics from the last three minutes of the conversation, the notes, the questions already suggested and the user's document pieces nearest to what others said; strict JSON with the question, why it is worth asking and the sources it uses. The speakers have never seen the user's documents, so the question may state the user's own practice and then ask. Checks before the model is asked: nothing when others have said under 40 words (outside open-floor sentences), and nothing automatic when the user did most of the talking (they are taking the questions). No-repeat check (3.3): a suggestion within 0.72 (nomic-embed-text) of a question already asked or suggested is dropped.
- backend/app/session/orchestrator.py: an open-floor sentence starts the doubt agent instead of an answer card; at most one suggestion on its own every 3 minutes of audio; the control message doubt (the Suggest a question button) asks at any time and gets "nothing to ask" back when there is nothing. Suggestions are sent as doubt events and stored as doubt items.
- Desktop: a "Suggest a question" button on the Answers tab while listening; an "Ask this" card with the question, why, and the documents it draws on; the exported notes list the questions suggested.
- eval/scenarios/talk-open-floor (new): a speaker presents in the user's topic area, the host opens the floor, the speaker then asks the user a question. Three short documents about the user's own evaluation setup. Audio generated with eval/generate_audio.py.

Tuning on real replays (local models):

| Replay | First try | After the fixes |
|---|---|---|
| Talk, the user in the audience, "Any questions?" | A question in 4.0 s, no document link | "You use an LM judge for live queries; what threshold do you use to block a release?" in 5.1 s, citing the user's eval-setup.md |
| Q and A where the user presents, "Any questions from the room?" before anything is said | A question that invented "You mentioned rebuilding the index nightly" | Quiet ("nothing said yet to ask about") |
| Same, "Anything else, thoughts on the evaluation approach?" | Missed (the comma), became an answer alert | Recognised as an open floor; quiet, the user is the one presenting |

Fixes in between: the 40-word and user-talking checks; the no-repeat check compares with questions only, because a good follow-up ("How do you handle the 20% disagreement between your live LLM judge and human raters?") scored 0.81 against the statement it asked about and was dropped; the prompt says the speakers never saw the user's documents and forbids source markers in the text (one suggestion had turned the user's release threshold into the speaker's "2-point recall drop" and printed "S2"). Similarity measured for the no-repeat threshold: the same question rephrased 0.73 to 0.94, different questions on one subject 0.41 to 0.67.

Verification: 166 backend tests pass (new: the open-floor rule on the replay sentences; the agent keeps only the sources it was given; nothing for an empty answer or a speech; the two checks; an open floor gives one suggestion and no answer card, a second one within 3 minutes gives none; the button asks inside the 3 minutes; asking with nothing to ask says so). The desktop smoke test, in the real app: the Suggest a question button returned "No question yet: nothing said yet to ask about." after one spoken sentence; with See my screen on, "Surya, what do you make of what is on the screen?" spoken through the speakers got a card describing the Harbor demo page that was on the owner's screen ("Guest input: '4 bedrooms near the old town'", "651 Lisbon homes"), which closes the check left open in Step H.2.

Not done (spec 3.4 and 3.5): the summary and to-dos screen, and doubt scoring in the eval report with the M3 gate.


## 2026-10-27, Step H.4: rehearsal before the meeting (decision 0009, hackathon feature 4)

What changed:
- backend/app/prep/rehearsal.py (new): transcribe() feeds a recording of frames through the SpeechToText port and keeps the user's final words, in memory. Rehearsal.review() asks the answer model for the answer as a card in the user's own words (one sentence, two or three points, nothing added, nothing corrected) and, at the same time, checks the answer with the claim checker.
- backend/app/main.py: POST /api/prep/{sessionId}/cards/{cardId}/rehearse takes the raw frames (one second to two minutes) and returns heard, line, points and the check; nothing is saved. Keeping the card is the existing edit, so it counts as approved by the user.
- backend/app/agents/claims.py: a quote shortened with "..." counts when every part is in the documents word for word; the source shown is the piece with the longest part. The local model joined two sections of status-this-week.md that way and both verdicts were dropped before this change.
- backend/app/main.py: a meeting that starts stops a running first read of the documents (its cards come first), and the read runs again when the meeting ends. Found by the smoke test: it uploads a document and starts listening at once, and the question's card waited behind a read of seven documents.
- Desktop: the microphone alone as an audio source (the right channel stays silent); a Rehearse button on a prepared meeting's cards; the Rehearse screen reads the question with the Mac's speech synthesis, records the answer, shows what was heard, "Your docs say otherwise" with the quote, source and a line closer to the documents, or "Matches your docs", or "Your docs do not cover this", and the answer as a card with "Keep my words as the card".

Verification: 172 backend tests pass (new: only the user's final words are kept and whole frames only; the review returns the card and the check; without the claim checker nothing is checked; the endpoint answers and saves nothing; a recording under a second or without speech, and an unknown card, are refused; a shortened quote counts only when every part is in the documents). Real models, the owner's prepared Dana meeting, the card "What is the timeline for the OpenPlaces places integration?", answers spoken by the Mac's voice:

| Spoken answer | Check | Line suggested | Time |
|---|---|---|---|
| "The OpenPlaces places integration will take about two hours. It is a small change and I can fit it into the small release." | Your docs say otherwise (status-this-week.md, What is blocked and by whom) | "It takes at least half a day and is proposed to be kept out of this small release." | 10.7 s |
| "OpenPlaces is a new data source, so it takes more than a day. I would keep it out of the small release." | Matches your docs (same section) | "I would keep OpenPlaces out of this small release because it takes more than a day." | 8.7 s |

The transcript was word for word both times, and the card kept the owner's wording ("OpenPlaces is a new data source, so it takes more than a day."). Desktop smoke test in the real app: Rehearse opened on the first prepared card, read it, recorded three seconds from the microphone, sent them, and showed the service's reply ("no speech was heard in the recording"; the Mac's microphone hears the speakers at about -55 dB, so the spoken check above went straight to the service). The same run passed every earlier check: the batch size card (back after the priming fix), Suggest a question, a picture of the screen, and a screen question answered from the picture ("The screen shows our Searchbot open on GitHub, with three open issues visible.").

Not built: a Muse Voice Transcribe adapter for the SpeechToText port. Meta's chat schema also takes audio parts (input_audio, wav or mp3); either needs the owner's key to be checked.


## 2026-11-04, MeetMind on Muse Spark for the Meta AI hackathon (decisions 0008 and 0009)

The owner added the Meta Model API key and a card; submissions close today at 9 PM ET. The owner chose to submit MeetMind and to publish a snapshot without git history (client names replaced, the test meeting from the real call removed).

What changed:
- `.env`: LLM_PROVIDER=meta and muse-spark-1.3 in the classifier, answer and doubt slots (the Qwen names kept as comments). The key's model list was checked first (GET /v1/models): muse-spark-1.3 is there.
- backend/app/session/orchestrator.py: a question that asks the user to agree with something about their work ("Your pipeline handles PDFs now, right?") is never answered by a prepared card; the claim checker settles it from the documents. Found by the demo dry run: a card prepared for "When's PDF support landing?" matched at 0.76 and the check never ran.
- docker-compose.yml: the host port comes from DYNAMODB_PORT (default 8000); this Mac now uses 8001 because another project's service holds 8000. scripts/start_local.sh passes DYNAMODB_ENDPOINT from .env to create_tables.py.
- README: the hackathon section (Meta models used, what was built during the event and before it, numbers on Muse Spark); the line promising an end-of-meeting summary is gone (not built, spec 3.4).
- demo/meeting-voices.sh (the other people of the demo meeting as macOS voices through the Mac's output, one line per Enter), demo/index-build-chart.html (the chart for the screen question), docs/demo-script.md (the 3-minute video).
- The app's profile, documents and prepared meetings were backed up to data/backup-before-hackathon-demo/ and replaced by the fictional ML standup (eval/scenarios/ml-standup) for the video.

Verification: the Meta contract test passes on the real API (stream and strict JSON). 200 backend tests pass, 1 skipped (new: a claim question skips a matching prepared card; it fails without the change). Muse Spark first piece 1.1 to 1.6 s; a picture of the demo chart was read correctly. The demo meeting replayed through the service with the prepared standup and See my screen on: prepared cards at 0.96 s and 0.86 s, the PDF claim "contradicts" with the quote from document-formats.md at 5.9 s, the chart answered from the picture at 3.2 s, and a suggested question on "Any questions before we wrap up?". Preparing the standup: 22 cards in 82.5 s. Rehearsal: a wrong spoken answer "contradicts" in 4.2 s, a right one "supports" in 9.3 s.
