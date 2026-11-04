# 01 – Problem Statement

_Status: v2 draft, Oct 20 2026. Items marked TODO are still open (see Parking lot)._

## 1. One-line description

Draft (my words):
> When people point a question at me in a meeting, the app should figure out it's for me and answer it with low latency, so I can reply on time. When people raise doubts or ask more questions, the app should take that chance and suggest a meaningful question, so I'm elevated in the room.

TODO: rewrite as two clear triggers:
- When someone asks **me** a question → ...
- When the room opens up for questions → ...

## 2. Target user

Someone like me: strong technical knowledge, but that alone isn't enough to stand out. Hesitates to speak up because of fear of saying or pronouncing something wrong, or not being sure the thought is relevant.

## 3. The painful moment

In an MLab meeting, my advisor gave an answer. I had something in mind to add, but I couldn't bring myself to say it. Other times I wish I had an interesting doubt to ask so I could contribute in the room.

If I'd had this app, I would have trusted the information and its relevance, and asked right away.

## 4. Core focus

- **The app gives content** (answers and questions to ask). It is **not** a communication or confidence coaching tool.
- The goal: help the user trust the suggestion and say it right away, instead of overthinking while the meeting moves on.

## 5. v1 scope

**v1 = the re:Invent demo version.** Built in three milestones, in order:

| Milestone | What it does | Target date |
|---|---|---|
| M1 | Detect when a question is asked **to me** | TODO |
| M2 | Generate an answer to that question | TODO |
| M3 | Suggest a meaningful question/doubt when the room opens up for questions | TODO |
| v1 | All three working together, deployed, demo-ready | Before Nov 30 |

**Cut line:** TODO (if behind by ___, M3 moves to v2).

## 6. Not in v1

- Communication / confidence coaching
- Answering small talk ("how are you?", basic pleasantries)
- Post-meeting notes as a main feature (secondary only)
- TODO: add more as decided

## 7. How the app knows a question is for me

Clues:
1. Someone says **my name**
2. I press an **"attention" button** (manual trigger — also a fallback for the demo)
3. The question is in **my topic area** (role-based)

Open question for research: match exact keywords or meaning? (People don't always use textbook terms.)

## 8. Rules

- **Answers:** for any question asked **to me**, regardless of topic.
- **Doubts:** only within my topic area, and only when the room opens up for questions (people asking questions or inviting them) — not on every statement.
- **No repeats:** never suggest a question or point that was already said earlier in the meeting. Asking something already covered makes the user look inattentive.

## 9. Meeting memory

The app keeps running bullet-point notes of the meeting as its own memory. Used to:
- generate better answers and doubts
- avoid suggesting things already said

## 10. User context (any role)

- Not hardcoded to one role. The user submits their context when they sign up / log in, so the same app works for different roles.
- TODO: decide exactly what the user submits in v1 (role, topics, resume, project notes?).
- Requirement: user data must be stored safely.

## 11. Speed (latency)

- **Start early:** once my name is heard or the attention button is pressed, the app starts preparing in parallel instead of waiting for the full question.
- Open question: what happens if the question changes after the app starts (e.g. it answers half a question)?

## 12. Success measures (starting targets — tune after real testing)

| Measure | Target | Notes |
|---|---|---|
| Alert latency | ≤ 1 s | From when the speaker stops talking |
| First line of answer | ≤ 3 s | From when the speaker stops talking |
| Detection | 10 / 10 questions to me | TODO: revisit — 100% isn't realistic; decide whether missing a question or a false popup is worse |
| False alarms | 15 | TODO: clarify — per 30-min meeting, or %? |
| Answer quality | 7 / 10 good enough to say out loud | TODO: define "good" |

## 13. Requirements so far

- Real-time is the main point (not record-and-summarize later)
- Trust: answers must be reliable enough to say out loud right away
- No repeating what was already said
- User data stored safely

## Parking lot (revisit after research)

- [ ] Milestone dates + cut line
- [ ] What the app does when it's not confident
- [ ] Detection and false-alarm numbers (revisit with the trade-off in mind)
- [ ] Definition of a "good" answer
- [ ] What the user submits at login for v1
- [ ] Handling a question that changes after the app starts answering
- [ ] 60-second demo script
- [ ] Fairness: "Fair when ___. Not okay when ___."
