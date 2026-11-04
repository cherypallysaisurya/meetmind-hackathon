"""Detector B: a small LLM confirms or retracts what Detector A fired.

It reads the last minute of transcript and a summary of the profile, and answers in strict JSON:
is the last thing said a question, is it aimed at the user, what is the question in clean words,
which category, how confident. Small talk and questions aimed at someone else are retracted.
"""

from dataclasses import dataclass

from ..ports import LLM, Message, Profile
from ..turns.end_of_turn import Turn

SCHEMA = {
    "type": "object",
    "properties": {
        "is_question": {"type": "boolean"},
        "directed_to_user": {"type": "boolean"},
        "question_text": {"type": "string"},
        "category": {"type": "string", "enum": ["small_talk", "technical", "logistics", "other"]},
        "confidence": {"type": "number"},
    },
    "required": ["is_question", "directed_to_user", "question_text", "category", "confidence"],
}

INSTRUCTIONS = (
    "You watch a live meeting on behalf of one participant, the user. Decide whether the last thing said "
    "by someone else is a question aimed at the user.\n"
    "is_question: true if it asks for an answer. Speech-to-text drops question marks and commas, so judge by "
    "the words: 'Surya is the set ready' means 'Surya, is the set ready?'. directed_to_user: true if the user is "
    "the one expected to answer: they are named, or it follows up on what they just said, or someone hands them a "
    "question asked a moment ago ('Surya, do you want to take that one?', 'that one is for you'); then "
    "question_text is that earlier question. In a round of updates, 'how about you?' or 'your turn' after "
    "someone's update asks the user for theirs: a question, not small talk. A question aimed at another named person, or at the whole room "
    "('any questions?', 'thoughts, anyone?'), is not directed to the user. Speech-to-text may misspell the user's "
    "name; a close spelling still counts as the user.\n"
    "category, pick one: technical = about the work itself (methods, systems, data, results, numbers); "
    "logistics = schedules, deadlines, who does what, cost, meetings; small_talk = greetings, thanks, "
    "pleasantries, chit-chat with no work content, like 'how are you'; other = anything else.\n"
    "question_text: the question in clean words, or an empty string if there is no question. "
    "confidence: between 0 and 1. Reply only with the JSON asked for."
)


@dataclass
class Verdict:
    is_question: bool
    directed_to_user: bool
    question_text: str
    category: str
    confidence: float


class Classifier:
    def __init__(self, llm: LLM, model: str, min_confidence: float):
        self.llm = llm
        self.model = model
        self.min_confidence = min_confidence

    def prompt(self, profile: Profile, recent: list[Turn], last_text: str, reasons: list[str]) -> list[Message]:
        names = ", ".join([profile.display_name, *profile.aliases])
        lines = "\n".join(f"{turn.channel}: {turn.text}" for turn in recent if not turn.echo) or "(nothing yet)"
        context = (
            f"The user: {profile.display_name} (also called: {names}). Role: {profile.role or 'not given'}. "
            f"Topics: {', '.join(profile.topics) or 'not given'}.\n\n"
            f"Recent transcript, oldest first (me is the user, them is everyone else):\n{lines}\n\n"
            f"Last thing said by them: \"{last_text}\"\n"
            f"A quick rules check flagged it because of: {', '.join(reasons) or 'nothing in particular'}."
        )
        return [Message("system", INSTRUCTIONS), Message("user", context)]

    async def classify(self, profile: Profile, recent: list[Turn], last_text: str, reasons: list[str] = ()) -> Verdict:
        reply = await self.llm.complete_json(self.model, self.prompt(profile, recent, last_text, list(reasons)), SCHEMA)
        return Verdict(
            bool(reply["is_question"]), bool(reply["directed_to_user"]), str(reply["question_text"]).strip(),
            str(reply["category"]), float(reply["confidence"]),
        )

    def confirms(self, verdict: Verdict, one_on_one: bool = False) -> bool:
        directed = verdict.directed_to_user or one_on_one   # a meeting of two: every question is for the user
        return (
            verdict.is_question and directed
            and verdict.category != "small_talk" and verdict.confidence >= self.min_confidence
        )
