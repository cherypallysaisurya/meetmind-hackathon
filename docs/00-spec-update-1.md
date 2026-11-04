# MeetMind: Spec Update 1

Paste everything below this line as your next message to the AI.

---

## Spec update 1: read fully before continuing

This message updates the MeetMind spec I gave you. Where it conflicts with the original, **this update wins**. Everything not mentioned here stays the same, including the working rules, the step format, local first with AWS later, no AWS costs before Phase 4, real code only, and the adapter approach.

### What to do right now

1. Finish the current step only up to a clean, working point. Do not start a new step.
2. Tell me which step you're on and which completed steps (if any) are affected by this update, and how.
3. Write decision records in `docs/decisions/` for change A (desktop app) and change B (prep + answer cache).
4. Update `docs/03-architecture.md` (both diagrams), the README and `docs/01-problem-statement.md` to match.
5. Show me the revised step list (section 9 below applied to your plan) and wait for my approval before building anything new.

---

## Why we're changing: MeetMind's positioning

Competitor research showed that every existing copilot (ParakeetAI, Cluely, Final Round AI, Hedy, Granola, Ask Gemini, Zoom AI Companion) uses the same core pipeline: capture, speech-to-text, LLM, show. The real user complaints are: lag, bad detection of when a question ended, small talk treated as questions, answers too long to read, answers that jump before you finish reading, generic or AI-sounding answers, invented personal facts, and no way to feed the tool your own material (Hedy's top feature request).

MeetMind is different in **when it helps, what it knows, and how it shows answers**:

> Other copilots start thinking when the question is asked and give everyone the same textbook answer. MeetMind prepares before the meeting, answers from your own work with the source, and only speaks when a question is aimed at you.

Put this line in the README. Every change below serves it.

---

## Change A: desktop app instead of a web page

**New requirement:** MeetMind must work with meetings in **desktop apps (Zoom, Microsoft Teams) and in the browser (Google Meet)**. It never joins the meeting and never adds a bot. A web page can only hear a browser tab, so the client becomes a **desktop app**.

- **Platforms:** macOS first (my only machine). Windows later. Audio capture sits behind an `AudioSource` interface in the desktop app, with a macOS implementation now and a Windows one later.
- **Shape:** a desktop shell that hosts the existing React UI, plus native system audio capture. Default candidate: Electron. Before committing, check current official docs for how each option captures system audio on macOS (built-in loopback support vs a small native helper using Apple's ScreenCaptureKit or Core Audio taps) and what macOS version and permissions each needs. Write the choice as a decision record.
- **Audio:** same as before. Mic on the left channel (me), system audio on the right channel (them), stereo 16 kHz PCM, sent to the backend over the same WebSocket. Bluetooth headphones must not matter.
- **Backend:** unchanged. It still runs as a local Python service in Phases 0 to 3, and moves to AWS in Phase 4. The desktop app just connects to a different address.
- **Window:** a small always-on-top panel the user can move and resize. Keyboard shortcuts: Attention, dismiss card, next card.
- **Screen sharing:** in v1, the window is a normal visible window. Hiding it from screen share is an **open decision for me (the owner)**. Do not build it unless I approve it.
- **Distribution:** an unsigned local build is fine for development. Before the event, tell me what's needed to give a Mac build to someone else (signing, notarization), and how long it takes.

## Change B: prepare before the meeting, and an answer cache

This is MeetMind's headline feature. Most answers should be ready **before** the question is asked.

### New "Before the meeting" phase (runs when the user prepares a session)

1. **Add material:** the user adds files (PDF, Markdown, text, and DOCX if practical) plus a pasted agenda and optional participant names. Files are split into chunks, embedded, and stored in a vector store.
2. **Predict questions:** an LLM reads the agenda, the documents and the profile, and predicts the questions most likely to be asked **to this user** (target 20 to 40), with a few phrasing variants each.
3. **Build the answer cache:** for each predicted question, generate a cue card (format in Change C) grounded in the user's documents, with sources. Store each card with its question embeddings.
4. **Review screen:** the user can read, edit, delete or add prepared cards before the meeting. Edited cards count as user-approved and rank higher.
5. Prep runs as a background job with a progress bar. It must finish within a few minutes for a normal agenda plus about 10 documents. Measure and report the time.

### New live step: match against the cache

- When the detector fires (even on a partial question), embed the question text and search the session's cache.
- **Hit** (similarity above a tunable threshold; you propose the starting value and justify it with eval data): show the prepared card immediately, labeled "Prepared".
- **Miss:** generate a grounded answer live (Change C).
- Log every match decision with its score so we can tune the threshold.

### New adapters (add to the adapter table)

| Interface | Local adapter | AWS adapter (Phase 4) |
|---|---|---|
| DocumentParser | Local parsing library (verify the best current option for PDF and DOCX) | Same code, runs in the service |
| VectorStore | A local embedded vector store (compare 2 options, e.g. LanceDB, sqlite-vec, Chroma; write a decision record) | Decide in Phase 4 after checking current AWS options (for example Bedrock Knowledge Bases, OpenSearch Serverless, S3 Vectors) |

Both need contract tests, like the others.

### New data (DynamoDB Local now, DynamoDB later)

| Table | Keys | Fields |
|---|---|---|
| documents | PK userId, SK docId | name, type, addedAt, chunkCount, status |
| prep_cards | PK sessionId, SK cardId | predictedQuestion, variants, card, sources, userEdited, createdAt, ttl |

Vectors live in the VectorStore, not in DynamoDB.

## Change C: grounded answers and pinned cue cards

### Grounded answers (live path and prep path)

- Retrieve the top relevant chunks from the user's documents plus the meeting notes, then generate.
- Every factual point about the user's work carries a **source** (document name and section or page).
- Personal facts (projects, numbers, results, jobs) may **only** come from the profile or the documents. If something isn't there, the card says "Not in your docs" instead of guessing.
- Follow-up questions build on the previous card and the meeting notes.

### Cue card format (replaces the old answer format)

- **Line 1:** the cue, one short sentence you can say naturally (max 20 words).
- **Then:** 2 to 4 short cue points (key facts, numbers, names), not a paragraph.
- **Footer:** source chips, a "Prepared" or "Live" label, and confidence.
- Low confidence: show only cue points with a clear "low confidence" tag.

### Pinned card behavior

- A card **never** changes or disappears while the user is reading it.
- New cards queue below with a small counter. The user moves on with a shortcut or a click.
- One card per question. If the question changes while generating, cancel and restart before showing (as in the original spec), never swap a card that's already shown.

## Change D: priorities, timeline and cut lines

**Priority order (most important first):** M1 detect, M2 grounded answers + cue cards, Prep + cache, M3 doubts. If time runs short, cut from the end of this list.

| Phase | Where | Finish by |
|---|---|---|
| Phase 0: foundation + desktop audio spike | Local | Mon Oct 26 |
| Phase 1 (M1): detect | Local | Sun Nov 1 |
| Phase 2 (M2): grounded answers + cue cards | Local | Sat Nov 7 |
| Phase 2P: prep + answer cache | Local | Wed Nov 11 |
| Phase 3 (M3): doubts + notes + summary | Local | Sun Nov 15 |
| Phase 4: AWS migration + deploy | AWS | Fri Nov 20 |
| Phase 5: hardening + demo prep | AWS + local | Fri Nov 27 |

- **Cut line 1 (Wed Nov 11):** if Prep + cache isn't passing its gate, stop M3. Doubts move to v2. The demo is detect + grounded answers + prep.
- **Cut line 2 (Sun Nov 22):** if the AWS version isn't stable, the demo runs on the local version.
- **v2 (not now):** your-voice mode (answers phrased the way the user speaks), Windows build, hiding from screen share (if I approve it).

## Change E: evaluation additions

- Every eval scenario now includes a **prep pack**: an agenda and 3 to 6 short documents for that fictional user, so we can test prep and grounding.
- New measures, reported separately for cache hits and misses:

| Measure | Gate |
|---|---|
| Cache hit rate on questions asked to me | report it; aim for at least half |
| Card latency on a cache hit (from end of speech) | p50 ≤ 1 s |
| First cue line on a miss | p50 ≤ 3 s (same as before) |
| Source accuracy (cited source actually supports the point) | at least 9 out of 10 |
| Invented personal facts | 0 |

- Add a "wrong cache hit" check: the shown prepared card answers a different question. Report how often it happens.
- Test desktop audio capture with all three: Zoom desktop, Teams desktop, and Google Meet in Chrome.

## Section 9 changes (apply to the step list)

- **Phase 0, add 0.6:** desktop shell + audio spike. Prove on my Mac that we can capture mic + system audio as two channels while Zoom desktop, Teams desktop and Meet in Chrome are running. Decision record for the desktop framework.
- **Phase 1:** steps 1.1 and 1.2 now build the desktop app (always-on-top panel, shortcuts, consent notice, profile form) and native audio capture, instead of the browser page.
- **Phase 2 (M2), replace with:**
  - 2.1 Document parsing, chunking, embeddings adapter, VectorStore adapter; add-documents screen
  - 2.2 Grounded answer agent with sources and the "Not in your docs" rule
  - 2.3 Cue card UI with pinned behavior and queue
  - 2.4 Start-early drafts with cancel-and-restart
  - 2.5 Notes agent; follow-ups build on previous cards
  - 2.6 Low-confidence behavior
  - 2.7 Eval: prep packs added to scenarios, answer quality, source accuracy, invented facts. **M2 gate check.**
- **New Phase 2P (Prep + cache):**
  - P.1 Prep session screen (agenda, participants, documents)
  - P.2 Question predictor
  - P.3 Answer cache builder + review/edit screen
  - P.4 Cache matcher in the live path, with hit/miss logging
  - P.5 Eval: hit rate, hit latency, wrong-hit rate, threshold tuning. **Prep gate check.**
- **Phase 3 (M3):** doubts also use grounding and sources.
- **Phase 4:** add AWS adapters for VectorStore and embeddings; the desktop app points to the deployed backend; Mac build packaging.
- **Phase 5 demo script:** show the prep screen first (predicted questions and prepared cards), then a live meeting where a prepared question gets an instant card and an unexpected one gets a live grounded card with sources. Show the latency panel.

Start with the "What to do right now" list at the top.
