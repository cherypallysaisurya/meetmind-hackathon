# 0009: Four features for the Meta AI hackathon: claim check, screen-aware answers, a question to ask, rehearsal

Status: accepted (the owner, 27 Oct 2026: "proceed doing all features")
Date: 2026-10-27

## Context

The owner asked what would make MeetMind stand out in the Meta AI hackathon. Existing meeting copilots answer after the question is asked, give generic answers and invent facts about the user. MeetMind already prepares before the meeting, speaks only when a question is aimed at the user, and shows sources. Four additions were proposed and approved:

1. **Claim check.** In the first real call the manager said "You're just querying the database directly, right?" and the owner's documents say there is no database yet. The nearest-pieces search ranked the deciding piece 32nd of 66, so no card could find it. The current guard shows "Your call" with no line for every such question.
2. **Screen-aware answers.** "What do you make of this chart?" needs the shared screen.
3. **A question to ask.** Phase 3's doubt agent (spec steps 3.1 to 3.3), brought forward: when the room opens for questions, or when the user presses a button, suggest one question in the user's topics.
4. **Rehearsal.** Before the meeting, the app asks the predicted questions out loud, the user answers, the answer is checked against the documents, and the user's own words become the prepared card. The spec lists "your-voice mode" under v2; the owner moved it into the hackathon build.

## Decision

- **Claim check**: a new claim checker agent. When a question asks the user to agree with something about their work, the normal card is written first ("Your call", no line), then the checker reads the user's documents whole, up to `CLAIM_CONTEXT_CHARS`, and returns supports, contradicts or not found with a quote. A verdict counts only when its quote is really in a document; then the card becomes "Your docs say otherwise" (or "Your docs agree") with the line to say and the quote with its source. The documents go in a fixed order so the model's prompt cache keeps them: measured on the local 9B model, 35 s for the first read, 3 to 6 s per check after it, four of four verdicts right. The first read happens in the background when a meeting starts. Muse Spark's context of a million tokens holds far larger document sets than the local 32 thousand.
- **Screen-aware answers**: a "See my screen" switch, off by default. With it on, when a question points at something on screen ("this chart", "on the screen", "this slide"), the service asks the app for one picture of the main display; the app takes it with Electron's desktopCapturer and sends it over the WebSocket; the answer model gets it with the question. The picture is kept in memory for that card only and never stored. The LLM port's messages gain optional images. macOS asks once for Screen Recording permission. Hiding the MeetMind window from the picture would also hide it from screen share, which stays the owner's open decision, so the prompt tells the model to ignore the MeetMind panel.
- **A question to ask**: rules spot an open floor in what others say ("any questions?", "thoughts?"); the doubt agent writes one question in the user's topics from the recent transcript, the notes and the user's documents; a question too close to anything already said is dropped (embeddings); at most one automatic suggestion every 3 minutes. A "Suggest a question" button asks for one at any time.
- **Rehearsal**: on a prepared meeting's cards, "Rehearse" reads each predicted question aloud with the Mac's speech synthesis, records the user's answer from the microphone, sends it to the service as the same 16 kHz frames the live session uses, transcribes it with the SpeechToText port in memory, checks it with the claim checker, and offers the user's own words as the card. Keeping it saves the card as edited by the user. Audio is never written to disk.

## Consequences

- With the Meta model on, a picture of the screen and the user's whole document set may be sent to Meta. The consent message names the screen when the switch is on. For the hackathon demo, use demo material.
- Speech-to-text for rehearsal uses the local adapter. A Muse Voice Transcribe adapter behind the same port can follow once the owner's key is in `.env`; it is not built yet because it cannot be checked without the key.
- Phase 3 steps 3.4 (summary and to-dos screen) and 3.5 (doubt scenarios in the eval, M3 gate) are not part of this decision.
