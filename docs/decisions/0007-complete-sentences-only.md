# 0007: Cards only on complete sentences, and a GPU budget for real calls

Status: accepted
Date: 2026-10-25

## Context

The first real meeting (a one-on-one with the owner's manager over Google Meet, 23 Oct 2026, two sessions of 6 and 3 minutes) showed three things the scripted eval could not:

- People speak in fragments. The manager paused every breath, so speech-to-text produced finals like "Um", "And, uh..." and partials like "you have your repost." The start-early design from Step 2.4 began writing a card as soon as a partial had eight words or a question mark, so cards were written for half sentences and for statements. Four of the six cards came from Attention presses that landed on the next fragment.
- The chip was shared with Meet in Chrome. Cards took 5.6 to 14.9 s to show a first line, the classifier 4.8 to 10.4 s, the notes agent 4.4 to 11.4 s every 75 s. In the eval, with nothing else running, those were 2 to 3.5 s, 2.4 to 4 s and 3 to 5 s.
- Without the one-on-one switch the classifier retracted a correct card as "Probably not for you", and one rewritten card contradicted what the owner had said ten seconds earlier.

## Options considered

1. Keep start-early drafts and tune the thresholds (more words, longer silence). Rejected: real speech has no safe threshold; a 20-word fragment is still a fragment, and every draft costs a 9B generation on a chip that is already saturated.
2. Write cards only on complete sentences (the final transcript, after the speaker pauses). Costs about one second against the draft path when the draft happened to be right, and nothing when it was wrong, which in the real call was most of the time.
3. Keep drafts behind a setting. Rejected: dead code in the live path and a second behavior to test.

## Decision

- Detector A runs only on final transcripts. Nothing is written on a partial. Attention answers the last complete sentence or the next one. The draft machinery (DRAFT_* constants, draft bookkeeping on the alert, the settle step) is removed.
- A GPU budget for real calls: the notes agent runs every 180 s instead of 75 s and still yields to any card; with the one-on-one switch on, a sentence that reads as a question is confirmed by the rules and Detector B is not called (it would only be weeding out small talk); with the switch on, Detector B, when it does run, may drop small talk but never say "not for you".
- The card prompt: if the user already answered in the transcript, the cue repeats their words; another participant's claim about the user's work is never turned into a fact. A card whose points cite no document is capped at medium confidence.
- The desktop remembers the one-on-one switch, and a card that was shown and then retracted fades after six seconds.

## Consequences

- The eval's first-line latency moves by about the turn delay (0.8 s median) for questions the draft used to catch early, and the "alert before end of speech" number goes to zero. The numbers after this change are in docs/eval-results.md.
- A new scenario built from the real call's transcript (manager-one-on-one) joins the eval set, with the one-on-one switch on, so rhetorical "right?" checks count as false alarms and the trade-off is measured rather than guessed.
- Phase 2P's prepared cards remain the real answer to latency: a prepared card needs no generation at all.
