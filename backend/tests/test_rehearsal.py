"""Rehearsal (decision 0009): the user's spoken answer to a prepared question becomes a card in their own words,
checked against their documents."""

import asyncio
import time
from typing import AsyncIterator

from fastapi.testclient import TestClient

from app import main
from app.agents.claims import ClaimChecker
from app.audio.frames import FRAME_BYTES
from app.main import app
from app.ports import ME, THEM, PrepCard, Profile, Transcript
from app.prep.rehearsal import Rehearsal, transcribe
from tests.fakes import CannedLLM, HashEmbeddings, InMemoryVectorStore, SilentSpeechToText
from tests.test_websocket import quiet_pipeline   # noqa: F401  (the fixture is used by name)

ANSWER = "Um, so the OpenPlaces places take at least half a day, it's a new data source, so I'd keep it out of the small release."
PROFILE = Profile("local", "Surya", ["Sur"], "Builds the search bot", ["OpenPlaces"], "", "", 1)
# One reply for both calls: the card reads line and points, the claim checker reads verdict, quote and line.
REPLY = {"line": "The OpenPlaces places take at least half a day; I'd keep them out of the small release.",
         "points": ["New data source", "Not in the small release", "", "A fourth point"],
         "verdict": "supports", "quote": "OpenPlaces places take at least half a day of work."}


class SpokenAnswer(SilentSpeechToText):
    """Hears the user's answer: a partial while they speak, the final when the recording ends, and a stray them line."""

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 5:
            self.queue.put_nowait(Transcript(ME, "Um, so the OpenPlaces", True, 0.0, 0.5))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(Transcript(THEM, "background noise", False, 0.0, 1.0))
        self.queue.put_nowait(Transcript(ME, ANSWER, False, 0.0, self.frames / 10))
        self.queue.put_nowait(None)


async def test_only_the_users_final_words_are_kept():
    stt = SpokenAnswer()
    assert await transcribe(stt, bytes(FRAME_BYTES * 30 + 100)) == ANSWER
    assert stt.frames == 30, "whole frames only; the stray bytes at the end are dropped"


async def test_the_review_gives_the_card_in_their_words_and_the_check():
    embeddings, vectors = HashEmbeddings(), InMemoryVectorStore()
    text = "OpenPlaces places take at least half a day of work."
    await vectors.add("docs:local", ["d:0"], await embeddings.embed([text]),
                      [{"doc_id": "d", "document": "plan.md", "location": "section: OpenPlaces", "index": 0, "text": text}])
    llm = CannedLLM(REPLY)
    rehearsal = Rehearsal(llm, "answer-model", ClaimChecker(llm, embeddings, vectors, "answer-model", 40000))
    result = await rehearsal.review("local", PROFILE, "How long will the OpenPlaces places take?", ANSWER)
    assert result.line == REPLY["line"] and result.points == ["New data source", "Not in the small release", "A fourth point"]
    assert (result.check.verdict, result.check.document) == ("supports", "plan.md")
    card_prompt = next(m for m in llm.prompts if m[0].content.startswith("The user rehearsed"))[1].content
    assert 'QUESTION: "How long will the OpenPlaces places take?"' in card_prompt and ANSWER in card_prompt


async def test_without_a_claim_checker_the_answer_is_not_checked():
    result = await Rehearsal(CannedLLM(REPLY), "m", None).review("local", PROFILE, "Q?", ANSWER)
    assert result.check.verdict == "not_found" and result.line == REPLY["line"]


def prepared_card_in(store) -> tuple[str, str]:
    client = TestClient(app)
    meeting = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": "OpenPlaces timing"}).json()
    card = PrepCard(meeting["sessionId"], "c1", "How long will the OpenPlaces places take?", [], {"line": "More than a day.", "points": []},
                    [], False, int(time.time()), int(time.time()) + 3600)
    asyncio.run(store.save_prep_card(card))
    return meeting["sessionId"], "c1"


def test_the_endpoint_answers_and_saves_nothing(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "llm", CannedLLM(REPLY))
    monkeypatch.setattr(main, "make_speech_to_text", SpokenAnswer)
    session_id, card_id = prepared_card_in(quiet_pipeline)
    response = TestClient(app).post(f"/api/prep/{session_id}/cards/{card_id}/rehearse", content=bytes(FRAME_BYTES * 40),
                                    headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heard"] == ANSWER and body["line"] == REPLY["line"] and len(body["points"]) == 3
    assert body["check"]["verdict"] == "not_found", "no documents in this test, so nothing settles it"
    stored = asyncio.run(quiet_pipeline.list_prep_cards(session_id))[0]
    assert stored.card["line"] == "More than a day." and not stored.user_edited, "keeping the answer is a separate edit"


def test_a_recording_too_short_or_without_speech_is_refused(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", SilentSpeechToText)
    session_id, card_id = prepared_card_in(quiet_pipeline)
    client = TestClient(app)
    url = f"/api/prep/{session_id}/cards/{card_id}/rehearse"
    assert client.post(url, content=bytes(FRAME_BYTES * 5)).status_code == 422
    silent = client.post(url, content=bytes(FRAME_BYTES * 20))
    assert silent.status_code == 422 and "no speech" in silent.json()["detail"]
    assert client.post(f"/api/prep/{session_id}/cards/nope/rehearse", content=bytes(FRAME_BYTES * 20)).status_code == 404
