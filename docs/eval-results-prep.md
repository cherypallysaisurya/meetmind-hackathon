# Eval results: prepared cards (Phase 2P)

Written by `eval/run_eval.py --prep` on 2026-10-26: 7 scenarios, 15 questions to the user. Each scenario was prepared from its agenda and attendees, its cards built by the real models, and the replay held that meeting. Hit threshold CACHE_HIT_SCORE = 0.75.

| Measure | Gate | Local |
|---|---|---|
| Cache hit rate on detected questions | report it; aim for at least half | 7 of 14 (the right prepared card existed for 9) |
| Card latency on a hit, p50 from end of speech | 1 s or less | 0.89 s |
| First cue line on a miss, p50 | 3 s or less | 3.9 s |
| Wrong cache hits (the prepared card answers a different question) | report it | 0 of 7 |
| Cards good enough to say out loud, hits / misses | 7 of 10 | 6 of 7 / 4 of 7 |
| Invented personal facts, all cards | 0 | 7 |
| Preparation time per scenario | a few minutes | 279 s, 151 s, 225 s, 208 s, 180 s, 207 s, 210 s (27, 20, 27, 26, 27, 28, 27 cards) |

Prep gate: **passed**. Cache hit rate on detected questions (aim: at least half): 7 of 14 (ok); Card latency on a hit, p50 from end of speech: 0.89 s (ok); Wrong cache hits: 0 of 7 (ok)

## Threshold sweep

Every detected question's best match was judged: does the prepared question ask the same thing? The same matches at other thresholds:

| Threshold | Hits | Wrong hits |
|---|---|---|
| 0.60 | 13 | 4 |
| 0.65 | 12 | 3 |
| 0.70 | 8 | 1 |
| 0.75 | 7 | 0 |
| 0.80 | 6 | 0 |
| 0.85 | 3 | 0 |
| 0.90 | 2 | 0 |

## Every match

- **Manager one-on-one, from the first real call**: "You have your repo somewhere else, right?" matched "Where exactly does the code for the empty repos live today?" at 0.681, miss, judged the same question; card live, first line , not good
- **Manager one-on-one, from the first real call**: "I don't think you're actually calling the API, right? You're just querying the database directly." matched "Is the search bot currently calling the API or pulling data from a CSV export?" at 0.668, miss, judged a different question; card live, first line , not good
- **Manager one-on-one, from the first real call**: "And how long would the OpenPlaces places take you?" matched "Are we shipping Release 6b with just Dana's eight points, or are we waiting for OpenPlaces?" at 0.698, miss, judged a different question; card live, first line 5.63 s, good
- **ML team standup**: "Nice. What batch size did you end up using for the last training run?" matched "What batch size and gradient accumulation did you use for the last training run?" at 0.887, hit, judged the same question; card prepared, first line 0.84 s, good
- **ML team standup**: "Agreed. Suria, does the pipeline handle the new document format yet?" matched "Which document formats are currently supported by your pipeline?" at 0.808, hit, judged the same question; card prepared, first line 2.06 s, not good
- **Q and A, open floor session**: "I have one. How do you keep the index fresh when documents change?" matched "What steps are you taking to ensure the nightly rebuild doesn't miss critical updates?" at 0.712, miss, judged a different question; card live, first line 3.9 s, good
- **Q and A, open floor session**: "Why did you pick recall at ten rather than mean reciprocal rank?" matched "Why did you choose recall at ten over mean reciprocal rank for this agent's evaluation?" at 0.928, hit, judged the same question; card prepared, first line 1.68 s, good
- **Research lab meeting**: "That is a big jump. Which evaluation set did you measure that on?" matched "Which evaluation set are these numbers based on?" at 0.663, miss, judged the same question; card live, first line 3.53 s, good
- **Research lab meeting**: "Sur, how does the pipeline handle documents longer than the context window?" matched "How do you handle documents that are longer than the model's context window?" at 0.782, hit, judged the same question; card prepared, first line 0.88 s, good
- **Small talk heavy call**: "Surya, is the evaluation set ready for the review on Friday?" matched "How is the evaluation set looking for Friday?" at 0.830, hit, judged the same question; card prepared, first line 0.85 s, good
- **Sprint planning, business heavy**: "Surya, how long will the pipeline rework take?" matched "How much time will the retrieval pipeline rework take?" at 0.803, hit, judged the same question; card prepared, first line 0.89 s, good
- **Sprint planning, business heavy**: "And what would the bigger index cost us per month?" matched "What is the current monthly cost of the bigger index?" at 0.956, hit, judged the same question; card prepared, first line 3.79 s, good
- **Tricky cases**: "That's quick. What changed to make it that fast?" matched "How confident are you that the six-minute eval time is stable?" at 0.632, miss, judged a different question; card live, first line 7.06 s, good
- **Tricky cases**: "So what's the plan for next week then?" matched "What happens if we can't finish PDF support before next week?" at 0.597, miss, judged a different question; card live, first line 3.64 s, not good
