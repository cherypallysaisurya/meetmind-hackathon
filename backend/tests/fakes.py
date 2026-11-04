"""Small stand-ins for adapters, for unit tests of the session and the API. Never used by the app itself."""

import asyncio
from dataclasses import replace
from typing import AsyncIterator

import hashlib
import math

from app.ports import (LLM, THEM, Document, Embeddings, Match, Message, PrepCard, Profile, Session, SessionItem,
                       SpeechToText, Store, Transcript, VectorStore)


class SilentSpeechToText(SpeechToText):
    """Accepts audio and says nothing."""

    def __init__(self):
        self.frames = 0
        self.done = asyncio.Event()

    async def start(self) -> None: ...

    async def feed(self, frame: bytes) -> None:
        self.frames += 1

    async def transcripts(self) -> AsyncIterator[Transcript]:
        await self.done.wait()
        return
        yield  # makes this an async generator

    async def stop(self) -> None:
        self.done.set()


class ScriptedSpeechToText(SilentSpeechToText):
    """Emits one final transcript on the them channel for every ten frames fed."""

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames % 10 == 0:
            second = self.frames // 10
            self.queue.put_nowait(Transcript(THEM, f"sentence {second}", False, second - 1.0, float(second)))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)


class InMemoryStore(Store):
    """The Store port on plain dicts. Passes the Store contract, so session tests can trust it."""

    def __init__(self):
        self.profiles: dict[str, Profile] = {}
        self.sessions: dict[tuple[str, str], Session] = {}
        self.items: dict[str, list[SessionItem]] = {}
        self.documents: dict[tuple[str, str], Document] = {}
        self.cards: dict[tuple[str, str], PrepCard] = {}

    async def save_profile(self, profile):
        self.profiles[profile.user_id] = replace(profile)

    async def get_profile(self, user_id):
        return self.profiles.get(user_id)

    async def save_session(self, session):
        self.sessions[(session.user_id, session.session_id)] = replace(session)

    async def get_session(self, user_id, session_id):
        return self.sessions.get((user_id, session_id))

    async def list_sessions(self, user_id):
        mine = [s for (u, _), s in self.sessions.items() if u == user_id]
        return sorted(mine, key=lambda s: s.started_at, reverse=True)

    async def delete_session(self, user_id, session_id):
        self.sessions.pop((user_id, session_id), None)
        self.items.pop(session_id, None)
        for k in [k for k in self.cards if k[0] == session_id]:
            del self.cards[k]

    async def add_item(self, item):
        self.items.setdefault(item.session_id, []).append(replace(item))

    async def list_items(self, session_id):
        return sorted(self.items.get(session_id, []), key=lambda i: (i.timestamp, i.type))

    async def save_document(self, document):
        self.documents[(document.user_id, document.doc_id)] = replace(document)

    async def list_documents(self, user_id):
        return [d for (u, _), d in self.documents.items() if u == user_id]

    async def delete_document(self, user_id, doc_id):
        self.documents.pop((user_id, doc_id), None)

    async def save_prep_card(self, card):
        self.cards[(card.session_id, card.card_id)] = replace(card)

    async def list_prep_cards(self, session_id):
        return [c for (s, _), c in self.cards.items() if s == session_id]

    async def delete_prep_card(self, session_id, card_id):
        self.cards.pop((session_id, card_id), None)


class QuestionSpeechToText(SilentSpeechToText):
    """Them asks the user by name: a partial after one second of audio, the final (ending at 3.0 s)
    after four seconds, which is when a real adapter would have it."""

    QUESTION = "Surya, what batch size did you use for the last run?"

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 10:
            self.queue.put_nowait(Transcript(THEM, "Surya, what batch", True, 0.2, 0.9))
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, self.QUESTION, False, 0.1, 3.0))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)


class CannedLLM(LLM):
    """Answers every JSON request with the same dict and streams the same text, and remembers the prompts."""

    def __init__(self, json_reply: dict, text_reply: str = "banana"):
        self.json_reply = json_reply
        self.text_reply = text_reply
        self.prompts: list[list[Message]] = []

    async def stream(self, model, messages):
        self.prompts.append(messages)
        for piece in self.text_reply.split(" "):
            yield piece + " "
            await asyncio.sleep(0)   # let the event loop breathe, like a real stream would

    async def complete_json(self, model, messages, schema):
        self.prompts.append(messages)
        return dict(self.json_reply)


CONFIRMING_REPLY = {"is_question": True, "directed_to_user": True, "question_text": "What batch size did you use for the last run?",
                    "category": "technical", "confidence": 0.9}
RETRACTING_REPLY = {"is_question": False, "directed_to_user": False, "question_text": "", "category": "other", "confidence": 0.8}


class FollowUpSpeechToText(SilentSpeechToText):
    """The user speaks, then them asks a plain follow-up question with no name, "you" or topic word."""

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 20:
            self.queue.put_nowait(Transcript("me", "About a week for the rework.", False, 0.0, 1.5))
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, "And what would the bigger index cost us per month?", False, 2.0, 3.8))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)


class InMemoryVectorStore(VectorStore):
    """The VectorStore port on dicts with brute force cosine search. Passes the contract."""

    def __init__(self):
        self.rows: dict[str, dict[str, tuple[list[float], dict]]] = {}

    async def add(self, collection, ids, vectors, metadata):
        bucket = self.rows.setdefault(collection, {})
        for i, v, m in zip(ids, vectors, metadata):
            bucket[i] = (list(v), dict(m))

    async def search(self, collection, vector, limit):
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)
        bucket = self.rows.get(collection, {})
        ranked = sorted(((cosine(vector, v), i, m) for i, (v, m) in bucket.items()), key=lambda r: -r[0])
        return [Match(i, round(s, 4), m) for s, i, m in ranked[:limit]]

    async def delete(self, collection, ids):
        for i in ids:
            self.rows.get(collection, {}).pop(i, None)

    async def delete_collection(self, collection):
        self.rows.pop(collection, None)


class HashEmbeddings(Embeddings):
    """Deterministic 16-number vectors from the words of a text. Enough for tests of plumbing, not of meaning."""

    async def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * 16
            for word in text.lower().split():
                digest = hashlib.md5(word.encode()).digest()
                vector[digest[0] % 16] += 1.0
            vectors.append(vector or [1.0] + [0.0] * 15)
        return vectors


CANNED_CARD = "CONFIDENCE: high\nThirty two, with gradient accumulation of four.\n- Batch size 32 [S1]\n- Accumulation 4 [S1]\n"
LOW_CONFIDENCE_CARD = "CONFIDENCE: low\nProbably thirty two.\n- Batch size may be 32\n- Check the training log\n"


def canned_llm(json_reply):
    """A classifier verdict plus a streamed cue card, for session tests. Streams the same text for notes too,
    which the notes parser reads as bullets."""
    return CannedLLM(json_reply, text_reply=CANNED_CARD)


HANDOFF_REPLY = {"is_question": True, "directed_to_user": True, "question_text": "How do you keep the index fresh when documents change?",
                 "category": "technical", "confidence": 0.9}


class HandoffSpeechToText(SilentSpeechToText):
    """Someone asks the room a question; the host hands it to the user by name."""

    handoff = "Surya, do you want to take that one?"

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 10:
            self.queue.put_nowait(Transcript(THEM, "How do you keep the index fresh when documents change?", False, 0.0, 2.5))
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, self.handoff, False, 3.0, 4.0))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)
