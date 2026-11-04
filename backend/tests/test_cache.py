import time

from app.agents.answer import AnswerAgent
from app.ports import Profile, Session
from app.prep.cache import AnswerCache, PrepProgress, prep_collection
from app.prep.predictor import QuestionPredictor
from tests.fakes import CANNED_CARD, CannedLLM, HashEmbeddings, InMemoryStore, InMemoryVectorStore

PROFILE = Profile("local", "Surya", ["Sur"], "Builds the search bot", ["release"], "", "Release 6", 1)
PREDICTED = {"questions": [
    {"question": "How long will the OpenPlaces places take?", "variants": ["When is OpenPlaces in?", "OpenPlaces timing?"]},
    {"question": "Is release 6 live?", "variants": ["Did release 6 ship?"]},
]}


def meeting() -> Session:
    return Session("local", "m1", "Dana 1:1", started_at=0, ended_at=None, summary="", todos=[], ttl=int(time.time()) + 86400,
                   agenda="Release 6\nOpenPlaces", participants=["Dana"])


def cache_with(store: InMemoryStore, vectors: InMemoryVectorStore) -> AnswerCache:
    llm, embeddings = CannedLLM(PREDICTED, text_reply=CANNED_CARD), HashEmbeddings()
    agent = AnswerAgent(llm, embeddings, vectors, "answer-model", 4, 0.45)
    return AnswerCache(store, embeddings, vectors, agent, QuestionPredictor(llm, embeddings, vectors, "answer-model"))


async def test_building_writes_a_card_per_predicted_question_and_indexes_every_phrasing():
    store, vectors = InMemoryStore(), InMemoryVectorStore()
    progress = PrepProgress()
    await cache_with(store, vectors).build(PROFILE, meeting(), progress)

    cards = await store.list_prep_cards("m1")
    assert [c.predicted_question for c in cards] == ["How long will the OpenPlaces places take?", "Is release 6 live?"]
    assert cards[0].card["line"] == "Thirty two, with gradient accumulation of four." and "partial" not in cards[0].card
    assert len(vectors.rows[prep_collection("m1")]) == 3 + 2, "each question plus its phrasings"
    assert (progress.state, progress.done, progress.total) == ("done", 2, 2)


async def test_preparing_again_keeps_the_cards_the_user_edited():
    store, vectors = InMemoryStore(), InMemoryVectorStore()
    cache = cache_with(store, vectors)
    await cache.build(PROFILE, meeting(), PrepProgress())
    openplaces = next(c for c in await store.list_prep_cards("m1") if "OpenPlaces" in c.predicted_question)
    edited = await cache.edit(openplaces, "At least half a day, after the small release.", ["New data source", "Drive table rebuilt"])
    assert edited.user_edited and edited.card["tags"]["low_confidence"] is False

    await cache.build(PROFILE, meeting(), PrepProgress())
    cards = await store.list_prep_cards("m1")
    assert sorted(c.predicted_question for c in cards) == ["How long will the OpenPlaces places take?", "Is release 6 live?"]
    kept = next(c for c in cards if "OpenPlaces" in c.predicted_question)
    assert kept.card_id == openplaces.card_id and kept.card["line"] == "At least half a day, after the small release."
    assert len(vectors.rows[prep_collection("m1")]) == 3 + 2, "no phrasing indexed twice"


async def test_removing_a_card_and_forgetting_a_meeting_clear_the_index():
    store, vectors = InMemoryStore(), InMemoryVectorStore()
    cache = cache_with(store, vectors)
    await cache.build(PROFILE, meeting(), PrepProgress())
    first = (await store.list_prep_cards("m1"))[0]
    await cache.remove(first)
    assert len(await store.list_prep_cards("m1")) == 1 and len(vectors.rows[prep_collection("m1")]) == 2
    await cache.forget("m1")
    assert not vectors.rows.get(prep_collection("m1"))
