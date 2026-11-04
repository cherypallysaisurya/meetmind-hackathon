# Demo video, Meta AI hackathon (3 minutes)

The video shows only what was built during the event (Oct 26 to Nov 4) and runs on Muse Spark. The meeting is a review of MeetMind itself: Priya and Dan are macOS voices played by `demo/meeting-voices.sh`, and the user's documents are MeetMind's own (`README.md`, `docs/01-problem-statement.md`, `docs/03-architecture.md`, decisions 0008 and 0009). No call is needed: MeetMind hears the Mac's own sound as the meeting.

## Before recording

1. `.env`: `LLM_PROVIDER=meta`, the Meta key, Muse Spark in the model slots, `CLAIM_CONTEXT_CHARS=200000`. The service runs.
2. Profile: Surya, builds MeetMind. Documents: the five files above, nothing else.
3. Prepare tab: the meeting "MeetMind review" with its 25 cards. Do not build it again: the demo lines match these cards.
4. A browser window with https://github.com/cherypallysaisurya/meetmind-hackathon scrolled to the table "Measured on Muse Spark", on the left of the screen; the MeetMind panel on the right, dragged taller.
5. Headphones on. A terminal outside the recorded area for the voices.
6. Cmd Shift 5, Record Selected Portion around the browser and the panel, Options, Microphone: the headset.

## Shots

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:20 | The panel beside the GitHub page | "In my first call with a new manager the questions came fast, and one of them got my work wrong. The answer was in documents I had written myself. MeetMind sits beside Zoom, Meet or Teams and hands me the line to say. Everything here runs on Meta's Muse Spark, and the documents are MeetMind's own." |
| 0:20 to 0:45 | Prepare tab: "MeetMind review", its predicted questions and cards; edit one card and save | "Before the meeting, Muse Spark reads my agenda, who is coming and my documents, predicts what I will be asked and writes each answer ahead of time. I can correct any card." |
| 0:45 to 1:15 | Rehearse on "Which Meta models are you actually running in the demo?". Answer wrong: "We run everything on Llama 3 on my Mac, nothing goes to Meta." It says "Your docs say otherwise" with the quote. Try again: "Muse Spark through the Meta Model API. Speech-to-text and embeddings stay on my Mac." It says "Matches your docs". Keep my words as the card | "Then I rehearse. It asks me out loud and checks what I say against my own documents." |
| 1:15 to 2:30 | Answers tab, See my screen ticked, Start listening; run `demo/meeting-voices.sh` in the terminal. The five lines play by themselves, 14 seconds apart; answer each one out loud in a few words | Let the meeting speak. One sentence at the screen question: "Muse Spark sees what I share." |
| 2:30 to 2:50 | The script now asks for your own question: type one nobody prepared, for example "Surya, what does MeetMind send to Meta during a call?", press Enter; Dan asks it and a live card appears | "Nothing here is scripted on MeetMind's side: any question gets a card." |
| 2:50 to 3:00 | The panel | "Built during this hackathon: preparation, rehearsal, the claim check, screen answers and suggested questions. MeetMind never joins the call." |

What each line should bring, measured on Muse Spark on Nov 4:

1. "Which Meta models are you running in the demo?": a prepared card, "We run the whole demo on Muse Spark 1.3." (under a second)
2. "Your app joins the call as a bot to listen in, right?": "Your docs say otherwise", quoting "It never joins the meeting and never adds a bot." (about 6 s)
3. "What do you make of this table?": the card reads the table on screen (about 5 s)
4. "How do you know it's answering from your docs and not inventing things?": a prepared card (under a second)
5. "Any questions before we wrap up?": a suggested question to ask

## If something goes wrong while recording

- No card after a line: the name was misheard; press Cmd Shift A (the last question was for me). That is a feature worth showing too.
- The table answer ignores the table: macOS needs Screen Recording permission for MeetMind; grant it and restart the app.
- Rehearsal hears nothing: the microphone input must be the headset.
- More time between lines: `PAUSE_S=20 demo/meeting-voices.sh`.
