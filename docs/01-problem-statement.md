# Problem statement

## Who this is for

A technically strong person who hesitates to speak up in meetings. The owner's own case is a Junior ML Engineer, but nothing in MeetMind is tied to ML. The user's role, name aliases and topic areas come from their profile.

The user does not need confidence coaching. They need content: a correct, short answer they can say right away when a question lands on them, and a good question to ask when the floor opens up. They must be able to trust what the app shows.

## The problem

When a question is aimed at you in a live meeting, you have a few seconds to answer. A good answer is short, correct, specific to your own work, and sounds like you.

Every existing copilot (ParakeetAI, Cluely, Final Round AI, Hedy, Granola, Ask Gemini, Zoom AI Companion) uses the same pipeline: capture audio, transcribe, send to a language model, show the text. Users report the same complaints across all of them:

- lag between the question and the answer
- poor detection of when a question actually ended
- small talk treated as a question
- answers too long to read while talking
- answers that change or jump before you finish reading
- generic, AI-sounding answers that are the same for everyone
- invented personal facts about the user
- no way to feed the tool your own material (the top feature request for Hedy)

## How MeetMind is different

> Other copilots start thinking when the question is asked and give everyone the same textbook answer. MeetMind prepares before the meeting, answers from your own work with the source, and only speaks when a question is aimed at you.

Three differences, each tied to a complaint above:

1. **When it helps.** Before the meeting, MeetMind reads the agenda and the user's documents, predicts the questions most likely to be asked to this user, and prepares a cue card for each. During the meeting, a detected question is matched against those prepared cards first. A hit shows the card at once. Only a miss goes to live generation.
2. **What it knows.** Answers are grounded in the user's own documents and profile. Every factual point about the user's work carries a source (document name and section or page). If a fact is not in the profile or documents, the card says "Not in your docs" instead of guessing.
3. **How it shows answers.** A cue card: one line to say out loud (max 20 words), two to four cue points, source chips, a Prepared or Live label and a confidence tag. A card never changes or disappears while the user reads it. New cards queue below. The app stays quiet on small talk and when it is unsure.

## What MeetMind does

1. **Detects** a question aimed at the user and alerts within 1 second. It knows a question is for the user when someone says their name or an alias, when the user presses the Attention button, or when the question is in the user's topic area and follows something the user just said.
2. **Answers** with a cue card. Prepared cards appear instantly. Live cards show their first line within 3 seconds.
3. **Suggests a doubt:** one meaningful question in the user's topic area when the room opens up for questions, at most one every 3 minutes, never repeating something already said.
4. **Takes notes** during the meeting and produces a summary with to-dos at the end.

## Where it works

In meetings running in desktop apps (Zoom, Microsoft Teams) and in the browser (Google Meet). MeetMind is a desktop app that captures the microphone and the system audio on the user's machine. It never joins the meeting and never adds a bot. macOS first, Windows later.

## Rules the product must follow

- Ignore small talk. Greetings and pleasantries never trigger a card.
- Staying quiet is a feature. When unsure, show less, not more.
- Low confidence is shown as such: only cue points and a clear tag, never a confident-sounding full answer.
- Never invent facts about the user. Personal facts come only from the profile or the documents.
- Nothing is hardcoded to a role or a field.
- A visible "MeetMind is transcribing" notice during every session, with a ready-to-paste consent message for other participants.
- Audio is never stored. Transcripts and cards expire after 30 days. The user can delete a session.

## Success targets

| Measure | Target | Minimum gate |
|---|---|---|
| Alert latency from end of speech | 1 s | p50 at or under 1 s on the eval set |
| Card latency on a cache hit, from end of speech | 1 s | p50 at or under 1 s |
| First cue line on a cache miss, from end of speech | 3 s | p50 at or under 3 s, p90 at or under 4 s |
| Detection of questions to the user | 10 of 10 | at least 8 of 10, gap reported |
| False alarms | at most 15 per 30-minute meeting | at most 15 per 30 min, aim much lower |
| Answer quality (good enough to say out loud) | 7 of 10 | 7 of 10 |
| Cache hit rate on questions asked to the user | at least half | report it |
| Source accuracy (the cited source supports the point) | 9 of 10 | at least 9 of 10 |
| Invented personal facts | 0 | 0 |
| Wrong cache hits (prepared card answers a different question) | report it | report it |

"Good enough to say out loud" means all of: correct, relevant to this meeting, first line at or under 20 words, no invented facts.

## Not in v1

- Joining the meeting as a bot
- Confidence coaching
- Your-voice mode (answers phrased the way the user speaks)
- Windows build
- Hiding the window from screen share (open decision for the owner, not built unless approved)
- File upload with a knowledge base beyond the per-session prep documents

## Why now

Showcase at AWS re:Invent 2026 in Las Vegas (owner arrives Nov 29) and submission to a Meta AI hackathon.
