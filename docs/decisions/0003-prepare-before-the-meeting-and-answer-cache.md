# 0003: Prepare before the meeting, match against an answer cache, ground every answer

Status: accepted
Date: 2026-10-22

## Context

Competitor research (ParakeetAI, Cluely, Final Round AI, Hedy, Granola, Ask Gemini, Zoom AI Companion) showed that every existing copilot starts thinking when the question is asked and runs the same pipeline: capture, transcribe, LLM, show. Users complain about lag, answers too long to read, answers that change while reading, generic answers, invented personal facts, and no way to feed the tool their own material.

MeetMind's positioning, now in the README: it prepares before the meeting, answers from the user's own work with the source, and only speaks when a question is aimed at the user.

## Options considered

1. **Live-only answers (original plan).** Every question waits for a full LLM generation. Latency is bounded by the model, and answers are not grounded in the user's documents.
2. **Prepare only, no live fallback.** Instant for predicted questions, but unexpected questions get nothing.
3. **Prepare before the meeting, match live, fall back to a live grounded answer on a miss.** Instant for the common case, still covers surprises, and both paths use the same grounding and card format.

## Decision

Option 3, in three parts.

**Before the meeting (prep).** The user adds documents (PDF, Markdown, text, DOCX if practical), pastes the agenda and optionally lists participants. Documents are chunked, embedded and stored in a vector store. An LLM predicts the 20 to 40 questions most likely to be asked to this user, with phrasing variants. A grounded cue card is built for each and stored with its question embeddings. A review screen lets the user read, edit, delete or add cards; edited cards rank higher. Prep runs as a background job with a progress bar and must finish within a few minutes for a normal agenda plus about 10 documents.

**Live match.** When the detector fires, even on a partial question, the question is embedded and searched against this session's cards. A hit above a tunable threshold shows the prepared card at once, labeled Prepared. A miss generates a grounded answer live, labeled Live. Every match decision is logged with its score. The starting threshold is proposed in Step P.4 and justified with eval data.

**Grounded answers and cue cards (both paths).** Retrieve the top relevant chunks plus meeting notes, then generate. Every factual point about the user's work carries a source (document name and section or page). Personal facts come only from the profile or documents; otherwise the card says "Not in your docs". The card format is one cue line (max 20 words), 2 to 4 cue points, and a footer with source chips, Prepared or Live label and confidence. A shown card never changes or disappears; new cards queue below.

## Consequences

- Two new interfaces with contract tests: DocumentParser (local parsing library, same code on AWS) and VectorStore (local embedded store chosen in Step 2.1 between two options with a decision record; AWS option chosen in Phase 4 among Bedrock Knowledge Bases, OpenSearch Serverless, S3 Vectors).
- Two new tables: `documents` (PK userId, SK docId) and `prep_cards` (PK sessionId, SK cardId). Vectors live in the VectorStore, not in DynamoDB.
- New backend module `backend/app/prep/` for chunking, question prediction, cache building and the cache matcher. The answer agent becomes the grounded answer agent.
- Phase 2 is replaced by the grounded answer and cue card steps. A new Phase 2P (prep + cache) follows it. The embeddings adapter moves forward from Phase 3 to Step 2.1.
- Eval gains a prep pack per scenario (agenda plus 3 to 6 short documents) and new measures: cache hit rate, hit latency, wrong-hit rate, source accuracy, invented personal facts.
- Priority order if time runs short: M1 detect, M2 grounded answers and cue cards, prep and cache, then M3 doubts. Cut line 1 on Wed Nov 11 drops M3 if the prep gate is not passed.
- Doubts in Phase 3 also use grounding and sources.
