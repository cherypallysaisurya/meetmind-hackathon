# 0008: Meta's Muse Spark for the language model during the Meta AI hackathon

Status: accepted
Date: 2026-10-26

## Context

MeetMind is the owner's entry in this week's Meta AI hackathon, which asks entries to use Meta models. The spec (section 2, rule 3) keeps Phases 0 to 3 free and on the Mac, with no paid API before Phase 4. The owner has a Meta Model API account with free credits and decided to use it for the hackathon, then return to the local models.

Measured the same day with the Meta models that run locally (progress, "check: Meta's Llama models in place of Qwen"): llama3.2:3b as the question checker missed 12 of 17 questions for the user; llama3.1:8b as the card writer was 2 s faster than Qwen but put wrong facts on three of four cards. The hosted Muse Spark models are far larger (Meta's open-weight Muse Spark has 816B parameters, 42B active) and do not compete with Meet and Whisper for the Mac's GPU.

## Options considered

1. Local Llama models through Ollama. Free and private, but measured less accurate than the current Qwen models.
2. Meta Model API, Muse Spark 1.3, for every language-model call (question checker, cards, notes, question prediction, the eval judge). One new adapter behind the existing LLM port.
3. Option 2 plus Muse Voice Transcribe for speech-to-text. More of the pipeline on Meta, more work; a second step if time allows.

## Decision

Option 2 now, option 3 later if time allows. `LLM_PROVIDER=meta` with `META_API_KEY` in `.env` (never in git) and `LLM_CLASSIFIER_MODEL` and `LLM_ANSWER_MODEL` set to `muse-spark-1.3`. Reasoning effort `minimal`: Muse Spark cannot switch reasoning off, and a live meeting needs the shortest pass. Embeddings stay local (nomic-embed-text): the Model API has no embeddings model. Going back is one line: `LLM_PROVIDER=local`.

## Consequences

- Meeting text, the user's profile and matching document pieces leave the Mac and go to Meta. The account's billing page says that while free credits are in use, content may be used for product improvement; Meta's docs say standard pay-as-you-go content is not used to train its models. The consent message and the status line in the app say where the text goes whenever the Meta model is on. For the hackathon demo, use demo or non-confidential material.
- Cost, estimated from Meta's published prices ($1.25 input, $4.25 output per million tokens for muse-spark-1.3): about 0.2 cents per card, about 7 cents to prepare a meeting, so the $150 credit covers far more than the hackathon.
- The spec's free-and-local rule is set aside for the hackathon only; the eval numbers on Meta are reported next to the local ones.
- The local adapters, tests and models stay in place and are the default in `.env.example`.
