"""The answer agent with the real answer model and real embeddings on one seeded document. Slow; Ollama must be running."""

import pytest

from app.adapters.factory import make_embeddings, make_llm
from app.agents.answer import AnswerAgent
from app.config import settings
from app.ports import ME, THEM, Profile
from app.turns.end_of_turn import Turn
from tests.adapters.test_ollama_llm import ollama_is_up
from tests.fakes import InMemoryVectorStore

PROFILE = Profile("local", "Surya", ["Sur"], "Junior ML Engineer", ["retrieval", "evaluation"], "Works on the retrieval pipeline.", "MeetMind", 1)
NOTES = [
    ("section: Training", "The last training run used batch size 32 with gradient accumulation of 4 on one GPU."),
    ("section: Results", "The retrieval index rebuild now takes twelve minutes instead of forty. Recall at ten went from 0.71 to 0.84."),
    ("section: Office", "The team moves to the third floor in March."),
]


@pytest.mark.skipif(not ollama_is_up(), reason="Ollama is not running: brew services start ollama")
async def test_real_card_is_grounded_and_short():
    embeddings = make_embeddings()
    vectors = InMemoryVectorStore()
    await vectors.add("docs:local", [f"n:{i}" for i in range(len(NOTES))], await embeddings.embed([t for _, t in NOTES]),
                      [{"doc_id": "n", "document": "notes.md", "location": loc, "index": i, "text": t} for i, (loc, t) in enumerate(NOTES)])
    agent = AnswerAgent(make_llm(), embeddings, vectors, settings.llm_answer_model, settings.retrieval_top_k, settings.retrieval_min_score)
    recent = [Turn(THEM, "Let's look at the training setup.", 0.0, 2.0, 0.7)]

    async def ignore(_):
        return None

    card, sources = await agent.answer("local", PROFILE, "What batch size did you use for the last training run?", recent, ignore)
    print("\nCARD:", card.line, [p.text for p in card.points], card.confidence, [f"{s.document}, {s.location}" for s in sources])
    assert card.line and len(card.line.split()) <= 20
    assert "32" in card.line or any("32" in p.text for p in card.points)
    assert 2 <= len(card.points) <= 4
    assert card.confidence in ("high", "medium", "low")
    assert any(1 in p.sources for p in card.points), "the batch size point should cite the training note"

    card, _ = await agent.answer("local", PROFILE, "What was your team's revenue last quarter?", recent, ignore)
    print("CARD:", card.line, [p.text for p in card.points], card.confidence)
    assert card.line.lower().startswith("not in your docs"), card.line
