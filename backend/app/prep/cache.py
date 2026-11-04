"""Answer cache: prepared cue cards for a meeting's predicted questions (Phase 2P, step P.3).

Building runs in two parts: the predictor guesses the questions, then each gets a card written exactly like a
live card (same agent, same prompt, same grounding). A card is stored in prep_cards and its question plus
phrasings go into the VectorStore under the meeting's own collection, so the live matcher (step P.4) can find it
by meaning. Cards the user edited are kept when the meeting is prepared again.
"""

import time
from dataclasses import dataclass
from uuid import uuid4

from ..agents.answer import AnswerAgent
from ..ports import Embeddings, PrepCard, Profile, Session, Store, VectorStore
from .predictor import QuestionPredictor


def prep_collection(session_id: str) -> str:
    return f"prep:{session_id}"


@dataclass
class PrepProgress:
    """What the Prepare tab's progress bar shows."""
    state: str = "idle"        # idle, predicting, writing, done or failed
    done: int = 0
    total: int = 0
    seconds: float = 0.0
    error: str | None = None


class AnswerCache:
    def __init__(self, store: Store, embeddings: Embeddings, vectors: VectorStore, answer_agent: AnswerAgent, predictor: QuestionPredictor):
        self.store = store
        self.embeddings = embeddings
        self.vectors = vectors
        self.answer_agent = answer_agent
        self.predictor = predictor

    async def build(self, profile: Profile, meeting: Session, progress: PrepProgress) -> None:
        started = time.perf_counter()
        progress.state = "predicting"
        questions = await self.predictor.predict(meeting.user_id, profile, meeting.title, meeting.agenda, meeting.participants)
        existing = await self.store.list_prep_cards(meeting.session_id)
        for card in existing:
            if not card.user_edited:
                await self.remove(card)   # replaced by this run's cards; edited ones are the user's and stay
        approved = {c.predicted_question.lower() for c in existing if c.user_edited}
        todo = [q for q in questions if q.question.lower() not in approved]
        progress.state, progress.total, progress.done = "writing", len(todo), 0
        for question in todo:
            await self.add(profile, meeting, question.question, question.variants)
            progress.done += 1
            progress.seconds = round(time.perf_counter() - started, 1)
        progress.seconds = round(time.perf_counter() - started, 1)
        progress.state = "done"

    async def add(self, profile: Profile, meeting: Session, question: str, variants: list[str] = ()) -> PrepCard:
        async def quiet(_snapshot):
            pass

        card, sources = await self.answer_agent.answer(meeting.user_id, profile, question, [], quiet)
        snapshot = card.snapshot()
        snapshot.pop("partial", None)
        prepared = PrepCard(
            session_id=meeting.session_id, card_id=uuid4().hex[:12], predicted_question=question, variants=list(variants),
            card=snapshot, sources=[{"number": s.number, "document": s.document, "location": s.location, "text": s.text} for s in sources],
            user_edited=False, created_at=int(time.time()), ttl=meeting.ttl,
        )
        await self.store.save_prep_card(prepared)
        await self._index(prepared)
        return prepared

    async def edit(self, card: PrepCard, line: str, points: list[str]) -> PrepCard:
        """The user rewrote the card. It now counts as approved: the line shows whatever the model's confidence was."""
        sources_of = {p["text"]: p["sources"] for p in card.card.get("points", [])}
        card.card = {
            **card.card,
            "line": line.strip() or None,
            "points": [{"text": p.strip(), "sources": sources_of.get(p.strip(), [])} for p in points if p.strip()],
            "tags": {**card.card.get("tags", {}), "low_confidence": False, "asks_to_agree": False},
        }
        card.user_edited = True
        await self.store.save_prep_card(card)
        return card

    async def remove(self, card: PrepCard) -> None:
        phrases = 1 + len(card.variants)
        await self.vectors.delete(prep_collection(card.session_id), [f"{card.card_id}:{n}" for n in range(phrases)])
        await self.store.delete_prep_card(card.session_id, card.card_id)

    async def forget(self, session_id: str) -> None:
        """The meeting is deleted: drop its phrasings from the VectorStore (the store drops the cards)."""
        await self.vectors.delete_collection(prep_collection(session_id))

    async def _index(self, card: PrepCard) -> None:
        phrases = [card.predicted_question, *card.variants]
        vectors = await self.embeddings.embed(phrases)
        await self.vectors.add(prep_collection(card.session_id), [f"{card.card_id}:{n}" for n in range(len(phrases))], vectors,
                               [{"card_id": card.card_id, "text": phrase} for phrase in phrases])
