import pytest

from app.agents.answer import AnswerAgent, Card, CardBuilder, Point, Source, attribute_unmarked_points, split_markers
from app.ports import ME, THEM, Profile
from app.turns.end_of_turn import Turn
from tests.fakes import CannedLLM, HashEmbeddings, InMemoryVectorStore

PROFILE = Profile("local", "Surya", ["Sur"], "Junior ML Engineer", ["retrieval"], "Works on retrieval.", "MeetMind", 1)

CANNED_CARD = (
    "CONFIDENCE: high\n"
    "We used a batch size of thirty two with gradient accumulation of four.\n"
    "- Batch size 32, accumulation 4 [S1]\n"
    "- Rebuild time went from forty to twelve minutes [S1] [S2]\n"
    "- Recall at ten is 0.84 [S2]\n"
)


def test_markers_are_extracted_and_removed():
    assert split_markers("Batch size 32 [S1] [S3]") == ("Batch size 32", [1, 3])
    assert split_markers("No source here") == ("No source here", [])


def test_the_card_builder_reads_the_stream_line_by_line():
    builder = CardBuilder()
    assert builder.feed("CONFIDENCE: high\nWe used a batch") is True
    assert builder.card.confidence == "high" and builder.card.line is None, "the cue is not complete yet"
    assert builder.feed(" size of thirty two.\n- Batch") is True
    assert builder.card.line == "We used a batch size of thirty two."
    assert builder.card.snapshot()["line"] == "We used a batch size of thirty two.", "confidence is known and not low, so the line shows"
    assert builder.card.partial == "Batch"
    assert builder.feed(" size 32 [S1]\n") is True
    assert builder.card.points[0].text == "Batch size 32" and builder.card.points[0].sources == [1]
    card = builder.finish()
    assert card.partial == ""


def test_the_line_is_withheld_until_confidence_is_known_and_at_low_confidence():
    builder = CardBuilder()
    builder.feed("We think thirty two.\n- Maybe 32\n")
    assert builder.card.line == "We think thirty two." and builder.card.snapshot()["line"] is None, "confidence unknown: hold the line"
    builder.feed("CONFIDENCE: low\n")
    card = builder.finish()
    snapshot = card.snapshot()
    assert snapshot["line"] is None and snapshot["points"] == [{"text": "Maybe 32", "sources": []}]
    assert snapshot["tags"] == {"low_confidence": True, "not_in_docs": False, "ungrounded": False, "asks_to_agree": False, "claim": None, "screen": False}


def test_not_in_your_docs_is_tagged():
    builder = CardBuilder()
    builder.feed("CONFIDENCE: low\nNot in your docs about revenue; say what you can.\n- Project is MeetMind\n")
    assert builder.finish().snapshot()["tags"]["not_in_docs"] is True


def test_a_quoted_cue_loses_its_quotes():
    builder = CardBuilder()
    builder.feed('"Batch size was 32."\n- Accumulation 4 [S1]\nCONFIDENCE: high\n')
    assert builder.finish().line == "Batch size was 32."


def test_an_unknown_confidence_word_counts_as_low():
    builder = CardBuilder()
    builder.feed("Cue.\nCONFIDENCE: very sure\n")
    assert builder.finish().confidence == "low"


async def test_retrieval_keeps_only_relevant_chunks_and_the_prompt_cites_them():
    vectors = InMemoryVectorStore()
    embeddings = HashEmbeddings()
    texts = ["Last training run used batch size 32 with gradient accumulation of 4.", "The office moves in March."]
    await vectors.add("docs:local", ["d:0", "d:1"], await embeddings.embed(texts),
                      [{"doc_id": "d", "document": "notes.md", "location": "section: Training", "index": 0, "text": texts[0]},
                       {"doc_id": "d", "document": "notes.md", "location": "section: Office", "index": 1, "text": texts[1]}])
    llm = CannedLLM({}, text_reply=CANNED_CARD)
    # The hashing stand-in scores the unrelated office note at 0.69 and the training note at 0.77,
    # so a threshold in between shows the filter at work.
    agent = AnswerAgent(llm, embeddings, vectors, "answer-model", top_k=6, min_score=0.72)

    sources = await agent.retrieve("local", "what batch size did you use for the last training run")
    assert [s.location for s in sources] == ["section: Training"], [(s.location, s.score) for s in sources]

    updates = []
    recent = [Turn(THEM, "Surya, what batch size did you use?", 0.0, 2.0, 0.7), Turn(ME, "echo", 0.1, 2.1, 0.7, echo=True)]
    card, used = await agent.answer("local", PROFILE, "What batch size did you use?", recent, lambda snapshot: updates.append(snapshot) or _done())
    prompt = llm.prompts[0][1].content
    assert "[S1] notes.md, section: Training" in prompt and "Office" not in prompt
    assert "them: Surya, what batch size" in prompt and "echo" not in prompt
    assert "Junior ML Engineer" in prompt and 'QUESTION TO THE USER: "What batch size did you use?"' in prompt
    assert card.line == "We used a batch size of thirty two with gradient accumulation of four."
    assert [p.sources for p in card.points] == [[1], [1], []], "only S1 was given; the card's [S2] points at nothing and is dropped"
    assert card.confidence == "high" and card.grounded
    assert any(u["line"] for u in updates), "an update carried the cue line once confidence was known"


async def test_an_ungrounded_card_is_tagged_and_never_high_confidence():
    llm = CannedLLM({}, text_reply="CONFIDENCE: high\nGeneral knowledge answer.\n- A point\n")
    agent = AnswerAgent(llm, HashEmbeddings(), InMemoryVectorStore(), "m", 4, 0.45)
    card, sources = await agent.answer("local", PROFILE, "What is a load balancer?", [], _done_cb)
    assert sources == [] and card.grounded is False
    assert card.confidence == "medium" and card.snapshot()["tags"]["ungrounded"] is True


async def _done_cb(_):
    return None


async def _done():
    return None


def test_points_without_markers_are_attributed_by_shared_numbers_or_long_words():
    sources = [
        Source(1, "notes.md", "section: Training", "The last training run used batch size 32 with gradient accumulation of 4.", 0.8),
        Source(2, "notes.md", "section: Results", "Recall at ten went from 0.71 to 0.84.", 0.7),
    ]
    card = Card(line="Thirty two.", points=[Point("Batch size 32"), Point("Recall is now 0.84"), Point("Say it with confidence"),
                                            Point("Current spend is within the quarterly training budget")])
    attribute_unmarked_points(card, sources)
    assert [p.sources for p in card.points] == [[1], [2], [], []], "one shared word (training) is not enough to cite a source"


def test_a_cue_that_holds_the_whole_card_is_split_into_cue_and_points():
    builder = CardBuilder()
    builder.feed("32. Gradient accumulation was 4. One GPU was used.\nCONFIDENCE: high\n")
    card = builder.finish()
    assert card.line == "32."
    assert [p.text for p in card.points] == ["Gradient accumulation was 4.", "One GPU was used."]


async def test_priming_sends_only_the_stable_prefix():
    llm = CannedLLM({}, text_reply="ok")
    agent = AnswerAgent(llm, HashEmbeddings(), InMemoryVectorStore(), "answer-model", 4, 0.45)
    await agent.prime(PROFILE)
    assert llm.prompts[0][1].content == AnswerAgent.profile_block(PROFILE)
    full = agent.prompt(PROFILE, "q", [], [])[1].content
    assert full.startswith(AnswerAgent.profile_block(PROFILE)), "the real prompt begins with the primed prefix"


def test_the_prompt_carries_notes_and_previous_cards_for_follow_ups():
    agent = AnswerAgent(CannedLLM({}), HashEmbeddings(), InMemoryVectorStore(), "m", 4, 0.45)
    prompt = agent.prompt(PROFILE, "And the smaller one?", [], [], notes=["Index rebuild is 12 minutes"],
                          previous_cards=[{"question": "What batch size?", "line": "Thirty two.", "points": ["Accumulation 4"]}])[1].content
    assert "MEETING NOTES SO FAR:\n- Index rebuild is 12 minutes" in prompt
    assert "Q: What batch size?\nA: Thirty two.\n- Accumulation 4" in prompt
    assert prompt.index("PROFILE") < prompt.index("SOURCES") < prompt.index("MEETING NOTES") < prompt.index("QUESTION TO THE USER")


def test_unknown_bracket_tags_are_stripped_and_source_markers_kept():
    assert split_markers("Current spend is within budget [MEETING NOTES SO FAR]") == ("Current spend is within budget", [])
    assert split_markers("Batch size 32 [S1] [NOTES]") == ("Batch size 32", [1])


def test_numbered_points_lose_their_numbers_and_bare_numbers_are_not_points():
    from app.agents.answer import CardBuilder

    builder = CardBuilder()
    builder.feed("CONFIDENCE: high\nFinish PDF support in the pipeline.\n1. Run the public benchmark. [S1]\n2) Prepare the all hands talk. [S1]\n- 1\n2\n3.\n")
    card = builder.finish()
    assert card.line == "Finish PDF support in the pipeline."
    assert [p.text for p in card.points] == ["Run the public benchmark.", "Prepare the all hands talk."]
    assert all(p.sources == [1] for p in card.points)


def test_a_card_keeps_at_most_four_points():
    from app.agents.answer import CardBuilder

    builder = CardBuilder()
    builder.feed("CONFIDENCE: high\nThe line.\n" + "".join(f"- point {n}\n" for n in range(1, 8)))
    card = builder.finish()
    assert [p.text for p in card.points] == ["point 1", "point 2", "point 3", "point 4"]


AGREEING_CARD = "CONFIDENCE: high\nYes, I query the production database directly.\n- No API calls\n- Daily data\n"


async def run_card(question: str, reply: str):
    agent = AnswerAgent(CannedLLM({}, text_reply=reply), HashEmbeddings(), InMemoryVectorStore(), "answer-model", 4, 0.45)
    updates = []

    async def on_update(snapshot):
        updates.append(snapshot)

    card, _ = await agent.answer("local", PROFILE, question, [], on_update)
    return card, updates


async def test_a_claim_about_the_users_work_never_gets_a_line_to_read_out():
    card, updates = await run_card("I don't think you're calling the API, right? You're just querying the database directly.", AGREEING_CARD)
    assert card.confidence == "low"
    assert all(u["line"] is None for u in updates), "the agreeing line never reached the screen, not even while streaming"
    assert all(u["tags"]["asks_to_agree"] and u["tags"]["low_confidence"] for u in updates), "the warning shows from the first update"
    assert [p.text for p in card.points] == ["No API calls", "Daily data"], "the points still show"


async def test_an_ordinary_question_still_streams_its_line():
    card, updates = await run_card("What batch size did you use for the last run?", AGREEING_CARD)
    assert card.confidence == "medium", "no document cited caps it at medium, as before"
    assert any(u["line"] for u in updates), "the line shows while the card is written"


async def test_a_marker_for_a_source_that_was_never_given_is_dropped():
    card, _ = await run_card("How would you cache model responses?", "CONFIDENCE: medium\nCache by prompt hash.\n- Key on the prompt hash [1]\n- Expire after five minutes\n")
    assert [p.sources for p in card.points] == [[], []], "no documents were in the prompt, so [1] points at nothing"


async def test_with_documents_off_no_document_reaches_the_prompt():
    vectors = InMemoryVectorStore()
    embeddings = HashEmbeddings()
    text = "Last training run used batch size 32 with gradient accumulation of 4."
    await vectors.add("docs:local", ["d:0"], await embeddings.embed([text]),
                      [{"doc_id": "d", "document": "notes.md", "location": "section: Training", "index": 0, "text": text}])
    llm = CannedLLM({}, text_reply="CONFIDENCE: medium\nA general answer.\n- A point\n")
    agent = AnswerAgent(llm, embeddings, vectors, "answer-model", 4, 0.0)

    async def quiet(snapshot):
        pass

    _, used = await agent.answer("local", PROFILE, "what batch size did you use for the last training run", [], quiet, use_documents=False)
    assert used == [] and "(no relevant documents)" in llm.prompts[0][1].content and "batch size 32" not in llm.prompts[0][1].content
