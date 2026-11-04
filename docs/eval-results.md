# Eval results

Written by `eval/run_eval.py`. Local column: the full pipeline on the owner's Mac. AWS column: filled in Phase 4.
Last local run: 2026-10-26, 7 scenarios, 7.3 minutes of meeting audio, 15 questions to the user, each scenario with its prep pack of documents uploaded.

## M1: detect

| Measure | Target | Local | AWS |
|---|---|---|---|
| Questions to the user detected | at least 8 of 10 (report the gap to 10 of 10) | 14 of 15 | |
| False alarms per 30 min | 15 or fewer (aim much lower) | 12.3 (3 in 7.3 min) | |
| Alert latency from end of speech, p50 / p90 | 1.0 s or less from the end of speech | 0.87 s / 3.29 s, 0 of 14 alerts fired before the speaker finished | |
| Turn known after the last word, p50 / p90 | 0.4 to 0.7 s | 0.8 s / 0.94 s | |
| Classifier time, p50 | report | 2590 ms | |
| Duplicate cards for an already detected question | 0 (one card per question) | 0 | |

M1 gate: **passed**. Questions to the user detected: 14 of 15 (ok); False alarms per 30 min: 12.3 (ok); Alert latency p50 from end of speech: 0.87 s (p90 3.29 s) (ok)

## M2: grounded answers (live path; prepared cards arrive with Phase 2P)

| Measure | Target | Local | AWS |
|---|---|---|---|
| First cue line from end of speech, p50 / p90 | p50 3 s or less, p90 4 s or less, from the end of speech | 3.95 s / 6.09 s | |
| Cards good enough to say out loud (judge: correct, relevant, cue at most 20 words, nothing invented) | 7 of 10 good enough to say out loud | 11 of 14 | |
| Cited sources that support their point | 9 of 10 cited sources support their point | 30 of 32 | |
| Invented personal facts | 0 | 6 | |
| Cue lines over 20 words | 0 | 1 | |

M2 gate: **not passed**. First cue line from end of speech: p50 3.95 s, p90 6.09 s (not ok); Cards good enough to say out loud: 11 of 14 (ok); Cited sources that support their point: 30 of 32 (ok); Invented personal facts: 6 (not ok)

The judge is the local answer model grading cards of its own kind, so its verdicts are a first pass. Every card is listed below for a human to review.

## Per scenario

| Scenario | Minutes | Questions | Detected | False alarms | Duplicates | Retracted by Detector B | Alert latencies from end of speech |
|---|---|---|---|---|---|---|---|
| Manager one-on-one, from the first real call | 1.88 | 3 | 3 | 2 | 0 | 0 | +0.87 s, +0.92 s, +0.87 s |
| ML team standup | 1.14 | 3 | 2 | 0 | 0 | 3 | +0.74 s, +1.71 s |
| Q and A, open floor session | 0.76 | 2 | 2 | 1 | 0 | 0 | +4.14 s, +1.96 s |
| Research lab meeting | 0.96 | 2 | 2 | 0 | 0 | 1 | +0.75 s, +0.86 s |
| Small talk heavy call | 0.77 | 1 | 1 | 0 | 0 | 2 | +0.78 s |
| Sprint planning, business heavy | 0.98 | 2 | 2 | 0 | 0 | 0 | +0.82 s, +3.29 s |
| Tricky cases | 0.84 | 2 | 2 | 0 | 0 | 1 | +3.10 s, +0.76 s |

### Misses, false alarms and duplicates

- Manager one-on-one, from the first real call, false alarm on "This is our GitHub. And we have two projects, right? One is just empty right now, it's just going to be your kanban board for all the items." [statement]: card said "This is our GitHub, and we have two projects, right? One is just empty right now. It's just going to be your Kanban board for all the items." because of question, one-on-one
- Manager one-on-one, from the first real call, false alarm on "Right, so each repo could have issues and tasks associated with them, and it's a good clean place to have everything organized." [statement]: card said "The other thing is like, you know, when you're excluding things with repetitive photos, you won't have to do that. That's going to be separated because we're going to deduplicate on ingestion, right?" because of question, after you spoke, your topic, one-on-one
- ML team standup, missed: "Thanks. Surya, how about you?" (alerted then retracted by Detector B; heard: Thanks, Siraia. How about you?)
- Q and A, open floor session, false alarm on "Makes sense, thank you." [small_talk]: card said "Are there any other thoughts on the evaluation approach?" because of question, after you spoke, your topic

Negative latencies mean the card appeared before the speaker had finished (Detector A fired on a partial). Latencies around 3 s are questions Detector A was unsure about and Detector B promoted after reading the final text.

### Cards, for manual review

- **Manager one-on-one, from the first real call**: "You have your repo somewhere else, right?" (not good; first line , confidence low, tags: low_confidence, asks_to_agree)
  - User actually said: Yes, the code is on the EC2 box under opt search bot, and I can move it into the new repos.
  - Card: **(line withheld)** | Live demo URL: https://3-141-221-86.nip.io | Local preview runs on my Mac port 8010 | Releases stored in /opt/search_bot/releases/ | Current release file name is search-bot-2026-10-22-release6.tgz
  - Sources: project-overview.md, section: Where the bot runs and how a release goes out; unsupported citations: 0 of 4
  - Judge: correct False, relevant True, invented: ['Live demo URL: https://3-141-221-86.nip.io', 'Local preview runs on my Mac port 8010', 'Releases stored in /opt/search_bot/releases/', 'Current release file name is search-bot-2026-10-22-release6.tgz']. The card contains specific technical details about the demo environment (URL, local Mac port, file paths) that are not present in the user's answer ('Yes, the code is on the EC2 box under opt search bot...') nor in the provided documents. While the documents mention an EC2 server and release boxes, they do not specify the exact URL 'https://3-141-221-86.nip.io', the local Mac port '8010', or the specific filename 'search-bot-2026-10-22-release6.tgz' as current facts. These appear to be invented personal facts about the user's specific setup that are not supported by the provided context.
- **Manager one-on-one, from the first real call**: "I don't think you're actually calling the API, right? You're just querying the database directly." (not good; first line , confidence low, tags: low_confidence, ungrounded, asks_to_agree)
  - User actually said: No, I'm not using the API, and I do not have access to query the production data directly. I took the CSV you sent me at the start and built the search bot from that.
  - Card: **(line withheld)** | Wimstay units load into our database daily. | Direct queries replace separate API calls. | This applies to both ingestion and search lookups.
  - Sources: none
  - Judge: correct False, relevant True, invented: ['Direct queries replace separate API calls.', 'This applies to both ingestion and search lookups.']. The card contains invented personal facts. The user explicitly stated in their answer: 'No, I'm not using the API, and I do not have access to query the production data directly. I took the CSV you sent me at the start and built the search bot from that.' The transcript also shows Dana questioning if the user is calling the API or querying the database directly. The card claims 'Direct queries replace separate API calls' and 'This applies to both ingestion and search lookups,' which contradicts the user's statement that they do not have access to query production data directly and are using CSVs. These statements about the system architecture (API vs direct DB) are presented as facts about the user's work/system but appear in none of the documents, the user's answer, or the transcript.
- **Manager one-on-one, from the first real call**: "And how long would the OpenPlaces places take you?" (good; first line , confidence low, tags: low_confidence)
  - User actually said: At least half a day, it is a new data source plus the monthly clean up and a rebuilt drive table, so I would keep it out of the small release.
  - Card: **(line withheld)** | OpenPlaces takes more than a day per Dana's list | The next release scope must be confirmed first | Drive times use roads without traffic and say "about"
  - Sources: plan-and-risks.md, section: Asks for Dana today, decisions-and-reasons.md, section: Why "near" is 15 minutes, "near the old town" 25, walking 1 mile, likely-questions.md, section: Can we keep Google's place data for internal use?; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card correctly states that OpenPlaces takes 'more than a day' (specifically 'at least half a day') based on Dana's list in the documents and transcript. It accurately reflects that drive times use roads without traffic and say 'about'. The statement about confirming the next release scope first is supported by the transcript where Dana asks to confirm the scope before including OpenPlaces. No invented facts are present.
- **ML team standup**: "Nice. What batch size did you end up using for the last training run?" (good; first line 3.74 s, confidence high)
  - User actually said: Thirty two, with gradient accumulation of four.
  - Card: **Batch size was 32, with gradient accumulation of 4 on one GPU.** | Used a single GPU for training. | Gradient accumulation steps were 4. | Batch size per device was 32
  - Sources: retrieval-pipeline-notes.md, section: Training run; unsupported citations: 1 of 2
  - Judge: correct True, relevant True. The card accurately reflects the user's actual answer and is fully supported by the 'retrieval-pipeline-notes.md' document which states: 'The last training run used batch size 32 with gradient accumulation of 4 on one GPU.' All points are factually correct and relevant to the question asked.
- **ML team standup**: "Agreed. Suria, does the pipeline handle the new document format yet?" (good; first line 5.66 s, confidence high)
  - User actually said: Not yet. Markdown and text work, PDF is next.
  - Card: **I'll add support for that format next.** | Markdown is already supported. | Plain text is also ready. | PDF is on our list but not done. | Word docs will come after PDF.
  - Sources: document-formats.md, section: Document formats supported by the pipeline; unsupported citations: 0 of 1
  - Judge: correct True, relevant True. The card accurately reflects the user's answer ('PDF is next') and aligns with the provided document '[document-formats.md]' which states 'PDF: next on the list, not supported yet'. The statements about Markdown and Plain text being ready are also consistent with both the documents and the context. No invented facts are present.
- **Q and A, open floor session**: "I have one. How do you keep the index fresh when documents change?" (good; first line 3.7 s, confidence high)
  - User actually said: We rebuild the index nightly, and changed documents are re-embedded on the fly.
  - Card: **We rebuild nightly and re-embed changed docs on the fly for searchable updates within a minute.** | Index rebuilt nightly | Changed documents re-embedded on the fly | Searchable within a minute | See index-freshness.md
  - Sources: index-freshness.md, section: Keeping the index fresh; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card accurately reflects the user's answer and the content of the 'index-freshness.md' document. It correctly states that the index is rebuilt nightly, changed documents are re-embedded on the fly, and this allows for searchable updates within a minute. No invented facts or personal details about the user were included.
- **Q and A, open floor session**: "Why did you pick recall at ten rather than mean reciprocal rank?" (good; first line 6.58 s, confidence medium)
  - User actually said: Because the answer agent reads the top ten chunks, so what matters is whether the right one is among them.
  - Card: **We chose recall at ten because our agent only reads the top ten chunks.** | Metric focuses on presence in top ten results | Mean reciprocal rank rewards rank order we don't use | See metrics-choice.md for reasoning | Current pipeline achieves 0.71 to 0.84 recall
  - Sources: metrics-choice.md, section: Why recall at ten, slides-summary.md, section: Slides, summary; unsupported citations: 0 of 2
  - Judge: correct True, relevant True. The card accurately reflects the user's answer and the content in 'metrics-choice.md'. It correctly states that the agent reads top ten chunks and explains why recall at ten is chosen over mean reciprocal rank. The mention of specific metrics (0.71 to 0.84) comes from the provided documents, not invented facts.
- **Research lab meeting**: "That is a big jump. Which evaluation set did you measure that on?" (good; first line 3.43 s, confidence high)
  - User actually said: The internal set, two thousand queries with graded relevance.
  - Card: **I measured that on the internal evaluation set with two thousand queries and graded relevance judgments.** | Internal evaluation set | Two thousand queries | Graded relevance judgments
  - Sources: results.md, section: Retrieval results; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card accurately reflects the information provided in the user's answer and documents. The statement 'I measured that on the internal evaluation set with two thousand queries and graded relevance judgments' is a direct paraphrase of the text found in [results.md] ('Measured on the internal evaluation set: two thousand queries with graded relevance judgments') and matches exactly what the user stated in their response.
- **Research lab meeting**: "Sur, how does the pipeline handle documents longer than the context window?" (good; first line 4.28 s, confidence high)
  - User actually said: They are split into chunks of about three hundred tokens with an overlap of fifty.
  - Card: **Surya, we chunk long docs into ~300-token pieces with 50-token overlap and keep their names.** | Split into ~300 tokens | 50 tokens overlap | Keep doc name and section
  - Sources: method.md, section: Method: chunking long documents; unsupported citations: 0 of 1
  - Judge: correct True, relevant True. The card accurately reflects the user's answer ('split into chunks of about three hundred tokens with an overlap of fifty') and is fully supported by the '[method.md]' document which states 'Documents longer than the model's context window are split into chunks of about three hundred tokens with an overlap of fifty tokens between consecutive chunks. Each chunk keeps its document name and section.' The card also correctly summarizes the key points from the documents.
- **Small talk heavy call**: "Surya, is the evaluation set ready for the review on Friday?" (not good; first line 3.95 s, confidence high)
  - User actually said: Yes, two thousand queries with graded relevance, it is ready.
  - Card: **Yes, it is. The set covers three product areas with two thousand graded queries and is fully prepared for Friday's review.** | Two thousand queries with graded relevance | Covers three product areas in proportion to query volume | Ready for the review on Friday
  - Sources: evaluation-set-status.md, section: Evaluation set, status; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card accurately reflects the user's answer ('Yes') and the specific details provided in both the user's answer (two thousand queries, graded relevance) and the documents (three product areas, ready for Friday). No invented facts are present.
- **Sprint planning, business heavy**: "Surya, how long will the pipeline rework take?" (good; first line 2.89 s, confidence high)
  - User actually said: About a week for the retrieval pipeline, plus two days for the evaluation set.
  - Card: **The rework will take about nine working days total.** | Retrieval pipeline rework is about one week | Evaluation set preparation takes two additional days | Total time is approximately nine working days
  - Sources: pipeline-rework-estimate.md, section: Pipeline rework, estimate; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card accurately reflects the user's answer and the documents. The document 'pipeline-rework-estimate.md' explicitly states the retrieval pipeline rework takes about one week, evaluation set preparation takes two additional days, and the total is nine working days with Surya as the owner. The user's answer matches these figures. No invented facts are present.
- **Sprint planning, business heavy**: "And what would the bigger index cost us per month?" (good; first line 6.09 s, confidence high)
  - User actually said: Roughly forty dollars a month at the current query volume.
  - Card: **The bigger index costs roughly forty dollars a month at our current volume.** | Cost is $40/month currently | Scales with query volume, not document count | Cap reached at first million chunks
  - Sources: index-cost.md, section: Cost of the bigger index; unsupported citations: 1 of 2
  - Judge: correct True, relevant True. The card accurately reflects the user's answer ('Roughly forty dollars a month') and is fully supported by the provided document '[index-cost.md]'. It does not invent any personal facts about the user.
- **Tricky cases**: "That's quick. What changed to make it that fast?" (good; first line 5.66 s, confidence high)
  - User actually said: The index is loaded once and shared across the query batch.
  - Card: **The index is loaded once and shared across the whole batch, not reloaded per query.** | Retrieval evaluation now runs in six minutes | Index loaded once instead of per query | Previously it was slower than this new speed
  - Sources: evaluation-speed.md, section: Evaluation speed; unsupported citations: 0 of 2
  - Judge: correct True, relevant True. The card accurately reflects the user's answer and the provided documents. The statement 'The index is loaded once and shared across the whole batch' matches the document [evaluation-speed.md] and the user's answer. The point about running in six minutes is supported by both the transcript and the document. The claim that it was previously slower is a logical inference from the context of 'what changed to make it that fast', which is not an invented fact but a reasonable summary of the improvement described.
- **Tricky cases**: "So what's the plan for next week then?" (good; first line 2.94 s, confidence high)
  - User actually said: Finish the PDF support, then the eval on the public benchmark.
  - Card: **Let's cover my three priorities for next week.** | Finish PDF support in the document pipeline | Run evaluation on public benchmark | Prepare all hands presentation
  - Sources: next-week-plan.md, section: Plan for next week; unsupported citations: 0 of 3
  - Judge: correct True, relevant True. The card accurately reflects the user's stated plan (finishing PDF support and running the evaluation) found in both the transcript and documents. It also correctly includes preparing the all hands presentation, which is mentioned as a future event for next week in the transcript ('Suria is also presenting at the all hands next week') and listed as a priority in the documents. The card does not invent facts about the user's work or decisions.
