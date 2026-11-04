# MeetMind

A real-time meeting copilot that runs beside Zoom, Microsoft Teams or Google Meet. It never joins the meeting and never adds a bot.

> Other copilots start thinking when the question is asked and give everyone the same textbook answer. MeetMind prepares before the meeting, answers from your own work with the source, and only speaks when a question is aimed at you.

## What it does

1. **Detects** when someone asks you a question and shows an alert within 1 second.
2. **Answers** with a cue card: one short line you can say out loud, a few cue points, and the source. Most cards are prepared before the meeting from your agenda and documents, so they appear instantly. Unexpected questions get a live, grounded card within 3 seconds.
3. **Suggests one question** in your topic area when the room opens up for questions.
4. **Takes notes** during the meeting: short running notes the answers also draw on.

## How it is different

- **When it helps:** it prepares before the meeting. Likely questions are predicted and answered ahead of time, then matched live.
- **What it knows:** it answers from your own documents and profile, and every fact about your work carries a source. If something is not in your docs, the card says so instead of guessing.
- **How it shows answers:** small pinned cue cards that never change while you read them. New cards queue below. It stays quiet on small talk and when unsure.
- **When someone gets your work wrong:** "You're just querying the database, right?" is checked against your documents read whole. If they say otherwise, the card says "Your docs say otherwise" with the line to say and the exact quote.
- **What is on screen:** with See my screen on, "what do you make of this chart?" is answered from a picture of the screen.
- **Before the meeting:** rehearse. The app asks the likely questions out loud, checks your spoken answer against your documents, and keeps your own words as the card.

## Meta AI hackathon

MeetMind is entered under "Build for Your World". The problem is the author's own: in the first call with a new manager, the questions came fast, one of them got the author's work wrong, and the right answer was in documents the author had written.

**Meta models.** Every language step runs on Muse Spark through the Meta Model API (`LLM_PROVIDER=meta`, decisions [0008](docs/decisions/0008-meta-models-for-the-hackathon.md) and [0009](docs/decisions/0009-hackathon-features.md)):

- the question checker that decides whether a question is aimed at you, as strict JSON;
- the cue card, streamed so the line to say arrives first;
- the claim checker, which reads all your documents whole in one call and returns a verdict with a quote; the verdict counts only when the quote is really in a document;
- screen-aware answers: a picture of your screen goes to Muse Spark with the question;
- the question predictor, the suggest-a-question agent, the meeting notes and the rehearsal reviewer.

Embeddings and speech-to-text stay on the Mac. The local models remain the default outside the hackathon.

**Measured on Muse Spark** (Nov 4, a scripted team standup replayed through the service, times from the end of the question):

| What | Muse Spark | Local Qwen 9B, for comparison |
|---|---|---|
| Prepared card on screen | 0.86 to 0.96 s | 0.89 s (eval p50) |
| Claim check, "Your docs say otherwise" with the quote | 5.9 s | 3 to 6 s, after a first read of the documents of 35 to 49 s at the start of the meeting |
| Answer from a picture of the screen | 3.2 s | about twice a text card, whose first line takes 3.95 s (eval p50) |
| Preparing a meeting | 22 cards in 82.5 s | 27 cards in 281.6 s |
| Rehearsal check of a spoken answer | 4.2 to 9.3 s | 8.7 to 10.7 s |

**Built during the event** (kickoff Mon Oct 26, 12 PM ET, to Wed Nov 4):

| Date | What |
|---|---|
| Oct 26 | General questions answered by the model itself, and a "Use my documents" switch per meeting |
| Oct 26 | Prepare tab: the likely questions are predicted from the agenda, the attendees and your documents, answered ahead of time in the background, reviewed and edited by you, then matched live so a prepared card is on screen at once |
| Oct 26 | The Meta Model API adapter |
| Oct 27 | Claim check ("Your docs say otherwise"), screen-aware answers, suggest a question, rehearsal |
| Nov 4 | MeetMind switched to Muse Spark and measured on it |

**Built before the event** (Oct 18 to 25), the base the event work stands on: desktop audio capture (your microphone and the meeting as two channels), local speech-to-text, end-of-turn detection, the two detectors that decide whether a question is for you, live answer cards from your documents, running notes and the eval harness. The demo video shows the event work; the base appears in it only because a card needs a question to be heard first.

The public repository is a snapshot of the private one, whose commit history carries the dates above. The test meeting built from the author's real work call was removed and the names of the people and products in it were replaced.

## Two stages

1. **Local first (Phases 0 to 3):** the full app runs on one Mac for free. Desktop app, a local Python service, a local speech-to-text engine, Ollama models, DynamoDB Local and a local vector store. Everything is real, nothing is mocked.
2. **AWS later (Phases 4 to 5):** the same app with AWS adapters. Amazon Transcribe, Bedrock, DynamoDB, Cognito, one container on ECS Fargate. Switching is a configuration change plus new adapters, not a rewrite.

Why this order, and how the pieces fit, is in [docs/03-architecture.md](docs/03-architecture.md).

## Repo map

| Path | What it holds |
|---|---|
| `desktop/` | The desktop app: native audio capture and the React UI |
| `backend/` | The MeetMind service (FastAPI). All product logic lives here |
| `backend/app/ports/` | The interfaces every outside dependency sits behind |
| `backend/app/adapters/` | Local adapters now, AWS adapters in Phase 4 |
| `eval/` | Scripted test meetings, generated audio, the scorer |
| `infra/` | AWS CDK app (Phase 4) |
| `docs/` | Problem statement, architecture, decision records, progress log, eval results |

## Using it in a real meeting

1. Start everything: `scripts/start_local.sh` (DynamoDB Local, Ollama, the service, then the desktop app). The first start after a reboot takes longer while the models load.
2. Wear headphones. With speakers, the microphone hears the meeting too and both channels transcribe the same words.
3. In the app, fill the Profile once: the name people call you, nicknames and the spellings speech-to-text tends to produce, your role, your topics. Add your material under Documents: notes, reports, slides as PDF. Cards quote from these.
4. Join the meeting in Zoom, Teams or Meet as usual. In the app press Start listening. The first time, macOS asks for the microphone and for system audio recording; allow both.
5. Paste the consent message from the app into the meeting chat.
6. In a talk or conference session where your documents do not apply, untick "Use my documents": the cards are then the model's own answers. When a question comes your way, a card appears on the Answers tab with one line to say and a few points, with the source. In a meeting of two, tick "One-on-one: every question is for me" and every question from the other side gets a card. Otherwise Cmd Shift A tells the app a question is for you when nobody said your name. Cmd Shift D dismisses a card, Cmd Shift N shows the next one.
7. Stop listening at the end. The notes are on the Conversation tab; Export notes saves them with the cards and the conversation as a Markdown file. The transcript and cards are also kept for 30 days on this Mac.
8. If the live audio ever fails, Replay test meeting plays one of the scripted meetings through the whole pipeline.

Stop the stack with `scripts/stop_local.sh`.

## How to run

Grows step by step as the pieces land. Current state is tracked in [docs/progress.md](docs/progress.md).

Prerequisites (Step 0.2): Docker Desktop, Homebrew with `ollama`, `ffmpeg` and `python@3.12`, Node 22. Ollama runs as a service (`brew services start ollama`) with the models named in `.env.example` pulled.

```bash
cp .env.example .env                                   # once
python3.12 -m venv backend/.venv                       # once
backend/.venv/bin/pip install -r backend/requirements.txt
docker compose up -d                                   # DynamoDB Local on 127.0.0.1:8000
backend/.venv/bin/python scripts/create_tables.py      # once, creates the five tables
cd backend && .venv/bin/python -m app.main             # the service, on 127.0.0.1:8080
```

Tests: `cd backend && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest -q`.

Eval (Step 1.10): `backend/.venv/bin/python eval/generate_audio.py` builds six test meetings from `eval/scenarios/*.yaml` with macOS `say` (the user on the left channel, everyone else on the right). With the service running, `backend/.venv/bin/python eval/run_eval.py` replays them all with each scenario's prep pack uploaded, scores detection, false alarms, latency and answer quality, and writes [docs/eval-results.md](docs/eval-results.md). The same files appear in the desktop app under "Replay test meeting", which is also the demo fallback.

Desktop app: `cd desktop && npm install && npm run start` builds it and launches it as its own app. Launching through `open` matters for audio: macOS grants "System Audio Recording" to the app that asks, and from a plain shell that would be the terminal. `npm run dev` gives a live window with hot reload, fine for UI work; for audio from `dev` grant your terminal "System Audio Recording" in System Settings. `npm run smoke` builds, launches, starts listening while the Mac speaks a sentence, and prints the level meters to `desktop/out/smoke.log`.

## Timeline

| Phase | Where | Finish by |
|---|---|---|
| Phase 0: foundation + desktop audio spike | Local | Mon Oct 26, 2026 |
| Phase 1 (M1): detect | Local | Sun Nov 1 |
| Phase 2 (M2): grounded answers + cue cards | Local | Sat Nov 7 |
| Phase 2P: prep + answer cache | Local | Wed Nov 11 |
| Phase 3 (M3): doubts + notes + summary | Local | Sun Nov 15 |
| Phase 4: AWS migration + deploy | AWS | Fri Nov 20 |
| Phase 5: hardening + demo prep | AWS + local | Fri Nov 27 |

Priority if time runs short: M1 detect, then M2 grounded answers, then prep + cache, then M3 doubts. Cut from the end.

- **Cut line 1 (Wed Nov 11):** if prep + cache is not passing its gate, M3 moves to v2.
- **Cut line 2 (Sun Nov 22):** if the AWS version is not stable, the demo runs on the local version.

## Documents

- [docs/00-build-prompt.md](docs/00-build-prompt.md) and [docs/00-spec-update-1.md](docs/00-spec-update-1.md): the spec, as given
- [docs/01-problem-statement.md](docs/01-problem-statement.md): who this is for and why existing tools fall short
- [docs/02-research.md](docs/02-research.md): the competitor teardown and technical research that led to spec update 1
- [docs/drafts/](docs/drafts/): the Oct 20 problem statement draft, kept for the record
- [docs/03-architecture.md](docs/03-architecture.md): both architecture diagrams, adapters, components, protocol, data model
- [docs/decisions/](docs/decisions/): one file per decision
- [docs/progress.md](docs/progress.md): step log
