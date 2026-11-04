"""The doubt agent: one good question the user could ask when the room opens up (spec Phase 3, decision 0009).

It reads what was said in the last minutes, the meeting notes, the user's topics and the pieces of their documents
nearest to the conversation, and suggests one specific question in the user's topics, linked to their own work when
the documents give a real link. A suggestion too close to a question already asked or suggested is dropped: in tests
with nomic-embed-text, the same question rephrased scored 0.73 to 0.94 and different questions on the same subject
0.41 to 0.67. Statements are left to the prompt, because a good follow-up sits close to the statement it asks about.
Staying quiet is the default: no question in the user's topics means no card.
"""

import math
from dataclasses import dataclass, field

from ..detect.rules import is_open_floor
from ..ports import LLM, Embeddings, Message, Profile
from ..turns.end_of_turn import Turn
from .answer import AnswerAgent, Source

REPEAT_SIMILARITY = 0.72
MAX_WORDS = 30
MIN_WORDS_HEARD = 40   # less than this from the others, and there is nothing yet to ask about

SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "why": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["question", "why", "sources"],
}

INSTRUCTIONS = (
    "You sit next to the user in a live meeting or talk. The room is open for questions. Suggest ONE question the user "
    "could ask now, in their own voice, at most 25 words. It must be about what the speakers just said and inside the "
    "user's topics. Make it specific: name the thing, the number or the choice it is about. Ask only about what the "
    "transcript contains, and never say that someone mentioned something the transcript does not contain. "
    "The SOURCES are the user's own documents, which the speakers have never seen: never present a fact from them as "
    "the speaker's. When a source gives a real link to the user's work, the question may state the user's own practice "
    "first and then ask, for example 'We block a release on a two point recall drop; what threshold do you use?', and "
    "that source's number goes in sources; otherwise sources is empty. Never write source markers like S1 or [S1] in "
    "the question or in why. Never ask something already asked or answered in the transcript or the notes. why: one "
    "short line, at most 15 words, on what the answer would tell the user. If nothing said touches the user's topics, "
    "or the user is the one taking the questions, return an empty question."
)


@dataclass
class Doubt:
    question: str
    why: str = ""
    sources: list[Source] = field(default_factory=list)


def nothing_to_ask(recent: list[Turn], asked: bool) -> str | None:
    """Why not to suggest a question now, decided before the model is asked, or None. The first replay showed the
    model inventing what a speaker had said when the floor opened before anything was said."""
    others = sum(len(t.text.split()) for t in recent if t.channel != "me" and not t.echo and not is_open_floor(t.text))
    mine = sum(len(t.text.split()) for t in recent if t.channel == "me" and not t.echo)
    if others < MIN_WORDS_HEARD:
        return "nothing said yet to ask about"
    if not asked and mine > others:
        return "the user is the one taking questions"
    return None


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a) * sum(y * y for y in b)) or 1.0)


class DoubtAgent:
    def __init__(self, llm: LLM, embeddings: Embeddings, model: str):
        self.llm = llm
        self.embeddings = embeddings
        self.model = model

    def prompt(self, profile: Profile, recent: list[Turn], notes: list[str], sources: list[Source], asked: list[str]) -> list[Message]:
        transcript = "\n".join(f"{t.channel}: {t.text}" for t in recent if not t.echo) or "(nothing yet)"
        source_lines = "\n".join(f"[S{s.number}] {s.document}, {s.location}: \"{s.text}\"" for s in sources) or "(none)"
        context = (
            AnswerAgent.profile_block(profile)
            + f"SOURCES (the user's documents nearest to the conversation, may be unrelated):\n{source_lines}\n\n"
            + "MEETING NOTES SO FAR:\n" + ("\n".join(f"- {n}" for n in notes) or "(none yet)") + "\n\n"
            + "QUESTIONS ALREADY SUGGESTED TO THE USER:\n" + ("\n".join(f"- {q}" for q in asked) or "(none)") + "\n\n"
            + f"RECENT TRANSCRIPT (me is the user, them is everyone else):\n{transcript}"
        )
        return [Message("system", INSTRUCTIONS), Message("user", context)]

    async def write(self, profile: Profile, recent: list[Turn], notes: list[str], sources: list[Source],
                    asked: list[str]) -> Doubt | None:
        """One question, or None when the model finds nothing worth asking in the user's topics."""
        reply = await self.llm.complete_json(self.model, self.prompt(profile, recent, notes, sources, asked), SCHEMA)
        question = str(reply.get("question", "")).strip()
        if not question or len(question.split()) > MAX_WORDS:
            return None
        cited = {n for n in reply.get("sources", []) if isinstance(n, int)}
        return Doubt(question, str(reply.get("why", "")).strip(), [s for s in sources if s.number in cited])

    async def closest(self, question: str, said: list[str]) -> float:
        """How close the question comes to the ones already asked or suggested; REPEAT_SIMILARITY or more is a repeat."""
        if not said:
            return 0.0
        vectors = await self.embeddings.embed([question, *said])
        return max(cosine(vectors[0], other) for other in vectors[1:])
