"""Question predictor: before the meeting, guess what will be asked to the user (Phase 2P, step P.2).

The model reads the meeting's agenda, who attends, the user's profile and, for every agenda line, the few
pieces of the user's documents that match it. Feeding it every document would be thousands of words and
slow on the local model; the pieces that match the agenda are what the meeting will be about. It replies
with the questions most likely to be put to the user, each with a few other phrasings, as strict JSON.
"""

from dataclasses import dataclass

from ..ports import LLM, Embeddings, Message, Profile, VectorStore
from .documents import collection_for

PIECES_PER_AGENDA_LINE = 3
MAX_CONTEXT_CHARS = 6000
MAX_QUESTIONS = 40
MAX_VARIANTS = 3

SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "variants": {"type": "array", "items": {"type": "string"}}},
                "required": ["question", "variants"],
            },
        },
    },
    "required": ["questions"],
}

INSTRUCTIONS = (
    "You prepare one person, the user, for a meeting. From the agenda, who attends, the user's profile and "
    "excerpts of the user's documents, list the questions most likely to be asked TO the user in this meeting: "
    "about their work, status, numbers, decisions and the reasons behind them, plans, dates, risks, and the "
    "what-if questions a manager or colleague would raise about the agenda items. Write each question the way "
    "someone in the room would say it out loud: short, spoken, addressed to the user as 'you'. For each, give 2 or "
    "3 other phrasings with different words and the same meaning. Leave out questions the user would ask others, "
    "small talk, and duplicates. Give between 20 and 30 questions, the most likely first. Reply only with the JSON "
    "asked for."
)


@dataclass
class PredictedQuestion:
    question: str
    variants: list[str]


class QuestionPredictor:
    def __init__(self, llm: LLM, embeddings: Embeddings, vectors: VectorStore, model: str):
        self.llm = llm
        self.embeddings = embeddings
        self.vectors = vectors
        self.model = model

    async def excerpts(self, user_id: str, agenda: str) -> list[str]:
        """The document pieces that match the agenda lines, best first, without repeats, within a size budget."""
        lines = [line.strip(" -*\t") for line in agenda.splitlines() if line.strip(" -*\t")]
        if not lines:
            return []
        seen, picked, size = set(), [], 0
        for vector in await self.embeddings.embed(lines):
            for match in await self.vectors.search(collection_for(user_id), vector, PIECES_PER_AGENDA_LINE):
                text = f"{match.metadata['document']}, {match.metadata['location']}: {match.metadata['text']}"
                if match.id in seen or size + len(text) > MAX_CONTEXT_CHARS:
                    continue
                seen.add(match.id)
                picked.append(text)
                size += len(text)
        return picked

    @staticmethod
    def prompt(profile: Profile, title: str, agenda: str, participants: list[str], excerpts: list[str]) -> list[Message]:
        context = (
            f"THE USER: {profile.display_name}, {profile.role or 'role not given'}. Topics: {', '.join(profile.topics) or 'not given'}. "
            f"About: {profile.bio or 'not given'}. Current projects: {profile.current_projects or 'not given'}\n\n"
            f"MEETING: {title}\nWHO ATTENDS: {', '.join(participants) or 'not given'}\nAGENDA:\n{agenda}\n\n"
            "EXCERPTS OF THE USER'S DOCUMENTS:\n" + ("\n\n".join(excerpts) or "(none)")
        )
        return [Message("system", INSTRUCTIONS), Message("user", context)]

    async def predict(self, user_id: str, profile: Profile, title: str, agenda: str, participants: list[str]) -> list[PredictedQuestion]:
        excerpts = await self.excerpts(user_id, agenda)
        reply = await self.llm.complete_json(self.model, self.prompt(profile, title, agenda, participants, excerpts), SCHEMA)
        return clean(reply.get("questions", []))


def clean(raw: list[dict]) -> list[PredictedQuestion]:
    """Drop empty and repeated questions, keep a few distinct phrasings each, cap the list."""
    questions, seen = [], set()
    for item in raw:
        question = str(item.get("question", "")).strip()
        if not question or question.lower() in seen:
            continue
        seen.add(question.lower())
        variants = []
        for variant in item.get("variants", []):
            variant = str(variant).strip()
            if variant and variant.lower() not in seen and variant.lower() not in {v.lower() for v in variants}:
                variants.append(variant)
        questions.append(PredictedQuestion(question, variants[:MAX_VARIANTS]))
        if len(questions) == MAX_QUESTIONS:
            break
    return questions
