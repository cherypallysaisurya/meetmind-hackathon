from app.agents.answer import AnswerAgent
from app.agents.claims import ClaimChecker
from app.ports import Profile
from tests.fakes import CannedLLM, HashEmbeddings, InMemoryVectorStore

PROFILE = Profile("local", "Surya", ["Sur"], "Builds the search bot", ["search bot"], "", "Harbor", 1)
PIECES = [
    ("project-overview.md", 0, "section: What data the bot has", "All of it is plain files in one folder. There is no database yet; that is what the data map adds."),
    ("decisions.md", 0, "section: Why files", "The demo needed to change daily, so every fact lives in a CSV or JSONL file."),
    ("decisions.md", 1, "section: OpenPlaces", "OpenPlaces is free and can be kept with credit."),
]
CLAIM = "I don't think you're calling the API, right? You're just querying the database directly."
CONTRADICTS = {"verdict": "contradicts", "quote": "There is no database yet;", "line": "No, I work from the CSV files; there is no database yet."}


async def documents() -> tuple[HashEmbeddings, InMemoryVectorStore]:
    embeddings, vectors = HashEmbeddings(), InMemoryVectorStore()
    texts = [text for _, _, _, text in PIECES]
    await vectors.add("docs:local", [f"{d}:{i}" for d, i, _, _ in PIECES], await embeddings.embed(texts),
                      [{"doc_id": d, "document": d, "location": loc, "index": i, "text": text} for d, i, loc, text in PIECES])
    return embeddings, vectors


async def checker_replying(reply: dict, context_chars: int = 40000) -> tuple[ClaimChecker, CannedLLM]:
    llm = CannedLLM(reply)
    embeddings, vectors = await documents()
    return ClaimChecker(llm, embeddings, vectors, "answer-model", context_chars), llm


async def test_a_verdict_counts_when_its_quote_is_in_a_document():
    checker, llm = await checker_replying(CONTRADICTS)
    check = await checker.check("local", CLAIM)
    assert (check.verdict, check.document, check.location) == ("contradicts", "project-overview.md", "section: What data the bot has")
    assert check.line == "No, I work from the CSV files; there is no database yet."
    prompt = llm.prompts[0][1].content
    assert all(text in prompt for _, _, _, text in PIECES), "every piece fits, so the whole document set is read"
    assert prompt.endswith(f'CLAIM: "{CLAIM}"')


async def test_a_quote_found_in_no_document_is_not_a_verdict():
    checker, _ = await checker_replying({"verdict": "contradicts", "quote": "We call the live API for every search.", "line": "We do call the API."})
    assert (await checker.check("local", CLAIM)).verdict == "not_found"


async def test_a_quote_with_words_left_out_counts_when_every_part_is_in_the_documents():
    # Seen on the local model: "OpenPlaces places are not in; ... Dana decides whether ..." joined two sections.
    shortened, _ = await checker_replying({**CONTRADICTS, "quote": "every fact lives in a CSV ... There is no database yet; that is what the data map adds"})
    made_up, _ = await checker_replying({**CONTRADICTS, "quote": "There is no database yet ... we query the API daily"})
    check = await shortened.check("local", CLAIM)
    assert (check.verdict, check.document) == ("contradicts", "project-overview.md"), "the source of the longest part"
    assert (await made_up.check("local", CLAIM)).verdict == "not_found"


async def test_a_quote_of_a_few_words_or_a_missing_line_is_not_a_verdict():
    short, _ = await checker_replying({"verdict": "supports", "quote": "no database", "line": "Right."})
    no_line, _ = await checker_replying({**CONTRADICTS, "line": ""})
    assert (await short.check("local", CLAIM)).verdict == "not_found"
    assert (await no_line.check("local", CLAIM)).verdict == "not_found"


async def test_pieces_come_in_document_order_so_every_prompt_starts_the_same():
    checker, llm = await checker_replying({"verdict": "not_found", "quote": "", "line": ""})
    await checker.check("local", CLAIM)
    await checker.check("local", "So you use OpenPlaces for places, right?")
    first, second = llm.prompts[0][1].content, llm.prompts[1][1].content
    assert first.split("CLAIM:")[0] == second.split("CLAIM:")[0], "the documents part is the same, so the prompt cache keeps it"
    assert first.index("decisions.md, section: Why files") < first.index("decisions.md, section: OpenPlaces") < first.index("project-overview.md")


async def test_a_small_budget_keeps_only_the_nearest_pieces():
    checker, _ = await checker_replying(CONTRADICTS, context_chars=120)
    pieces = await checker.pieces("local", "no database yet data map plain files folder")
    assert [p["location"] for p in pieces] == ["section: What data the bot has"]


async def answer_with(reply: dict, question: str = CLAIM, use_documents: bool = True):
    llm = CannedLLM(reply, text_reply="CONFIDENCE: high\nYes, I query the database directly.\n- No API calls\n")
    embeddings, vectors = await documents()
    checker = ClaimChecker(llm, embeddings, vectors, "answer-model", 40000)
    agent = AnswerAgent(llm, embeddings, vectors, "answer-model", 4, 0.99, checker)
    updates = []

    async def on_update(snapshot):
        updates.append(snapshot)

    card, sources = await agent.answer("local", PROFILE, question, [], on_update, use_documents=use_documents)
    return card, sources, updates, llm


async def test_a_contradicted_claim_turns_the_card_into_the_correction_with_its_source():
    card, sources, updates, _ = await answer_with(CONTRADICTS)
    assert updates[-1]["tags"]["asks_to_agree"] and updates[-1]["line"] is None, "'Your call' shows while the documents are read"
    snapshot = card.snapshot()
    assert snapshot["line"] == "No, I work from the CSV files; there is no database yet."
    assert snapshot["tags"]["claim"] == "contradicts" and not snapshot["tags"]["low_confidence"] and card.confidence == "high"
    assert [(p.text, p.sources) for p in card.points] == [("There is no database yet;", [1])]
    assert [(s.number, s.document) for s in sources] == [(1, "project-overview.md")]


async def test_an_unsettled_claim_stays_the_users_call():
    card, _, _, _ = await answer_with({"verdict": "not_found", "quote": "", "line": ""})
    assert card.claim is None and card.snapshot()["line"] is None and card.snapshot()["tags"]["low_confidence"]


async def test_no_check_for_an_ordinary_question_or_with_documents_off():
    _, _, _, ordinary = await answer_with(CONTRADICTS, question="What batch size did you use?")
    card, _, _, documents_off = await answer_with(CONTRADICTS, use_documents=False)
    assert not [m for m in ordinary.prompts + documents_off.prompts if m[0].content.startswith("You check a claim")]
    assert card.claim is None
