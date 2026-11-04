from app.prep.predictor import SCHEMA, PredictedQuestion, QuestionPredictor, clean
from app.ports import Profile
from tests.fakes import CannedLLM, HashEmbeddings, InMemoryVectorStore

PROFILE = Profile("local", "Surya", ["Sur"], "Builds the search bot", ["release", "drive time"], "", "Release 6", 1)


async def store_with(texts: dict[str, str]) -> InMemoryVectorStore:
    vectors = InMemoryVectorStore()
    embeddings = HashEmbeddings()
    ids = list(texts)
    await vectors.add("docs:local", ids, await embeddings.embed([texts[i] for i in ids]),
                      [{"doc_id": "d", "document": "notes.md", "location": f"section: {i}", "index": n, "text": texts[i]} for n, i in enumerate(ids)])
    return vectors


async def test_the_prompt_carries_the_agenda_and_the_pieces_that_match_it():
    vectors = await store_with({"openplaces": "OpenPlaces places need at least half a day of work.",
                                "office": "The office plants are watered on Fridays."})
    llm = CannedLLM({"questions": [{"question": "How long will the OpenPlaces places take?", "variants": ["When is OpenPlaces in?"]}]})
    predictor = QuestionPredictor(llm, HashEmbeddings(), vectors, "answer-model")

    questions = await predictor.predict("local", PROFILE, "Dana 1:1", "- OpenPlaces places timing", ["Dana"])

    assert questions == [PredictedQuestion("How long will the OpenPlaces places take?", ["When is OpenPlaces in?"])]
    prompt = llm.prompts[0][1].content
    assert "AGENDA:\n- OpenPlaces places timing" in prompt and "WHO ATTENDS: Dana" in prompt and "Surya" in prompt
    assert "OpenPlaces places need at least half a day" in prompt, "the matching piece is in the prompt"


async def test_excerpts_stay_within_the_size_budget_and_do_not_repeat():
    vectors = await store_with({f"p{n}": f"Release note number {n}. " + "word " * 400 for n in range(10)})
    predictor = QuestionPredictor(CannedLLM({"questions": []}), HashEmbeddings(), vectors, "answer-model")
    excerpts = await predictor.excerpts("local", "Release notes\nRelease notes again\nMore release notes")
    assert len(excerpts) == len(set(excerpts)), "a piece matching two agenda lines appears once"
    assert sum(len(e) for e in excerpts) <= 6000


def test_clean_drops_empty_and_repeated_questions_and_extra_phrasings():
    raw = [
        {"question": " What is the plan? ", "variants": ["What's the plan?", "what is the plan?", "", "Plan?", "The plan?", "Next steps?"]},
        {"question": "what is the plan?", "variants": ["Again?"]},
        {"question": "", "variants": ["Nothing"]},
        {"question": "When does it ship?", "variants": []},
    ]
    assert clean(raw) == [PredictedQuestion("What is the plan?", ["What's the plan?", "Plan?", "The plan?"]),
                          PredictedQuestion("When does it ship?", [])]


def test_the_schema_asks_for_questions_with_variants():
    item = SCHEMA["properties"]["questions"]["items"]
    assert item["required"] == ["question", "variants"]
