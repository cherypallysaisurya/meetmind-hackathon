from fastapi.testclient import TestClient

from app import main
from app.main import app
from tests.test_websocket import quiet_pipeline, tone_frame   # noqa: F401  (the fixture is used by name)

AGENDA = "Release 6 review\nOpenPlaces timing\nThe data map"


def test_prepare_list_update_and_delete_a_meeting(quiet_pipeline):
    client = TestClient(app)
    assert client.get("/api/prep").json() == {"meetings": []}

    created = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": AGENDA, "participants": ["Dana", " "]})
    assert created.status_code == 200, created.text
    meeting = created.json()
    assert meeting["title"] == "Dana 1:1" and meeting["agenda"] == AGENDA
    assert meeting["participants"] == ["Dana"] and meeting["held"] is False

    updated = client.put(f"/api/prep/{meeting['sessionId']}", json={"title": "Dana one-on-one", "agenda": AGENDA, "participants": ["Dana", "Lee"]})
    assert updated.json()["participants"] == ["Dana", "Lee"]
    assert [m["title"] for m in client.get("/api/prep").json()["meetings"]] == ["Dana one-on-one"]

    assert client.delete(f"/api/prep/{meeting['sessionId']}").json() == {"deleted": meeting["sessionId"]}
    assert client.get("/api/prep").json() == {"meetings": []}
    assert client.delete(f"/api/prep/{meeting['sessionId']}").status_code == 404


def test_a_meeting_needs_an_agenda(quiet_pipeline):
    assert TestClient(app).post("/api/prep", json={"title": "Empty", "agenda": ""}).status_code == 422


def test_starting_a_prepared_meeting_holds_that_record(quiet_pipeline):
    client = TestClient(app)
    meeting = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": AGENDA, "participants": ["Dana"]}).json()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "prep_session_id": meeting["sessionId"]})
        started = ws.receive_json()
        assert started == {"type": "started", "session_id": meeting["sessionId"]}, "the live session is the prepared one"
        ws.send_json({"type": "stop"})
        while ws.receive_json()["type"] != "stopped":
            pass
    record = quiet_pipeline.sessions[("local", meeting["sessionId"])]
    assert record.agenda == AGENDA and record.started_at > 0 and record.ended_at is not None
    assert client.get("/api/prep").json()["meetings"][0]["held"] is True


def test_starting_with_an_unknown_prepared_meeting_is_an_error(quiet_pipeline):
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "prep_session_id": "nope"})
        assert "not found" in ws.receive_json()["message"]


def with_predictions(monkeypatch):
    from tests.fakes import CANNED_CARD, CannedLLM
    predicted = {"questions": [{"question": "How long will the OpenPlaces places take?", "variants": ["When is OpenPlaces in?"]},
                               {"question": "Is release 6 live?", "variants": []}]}
    monkeypatch.setattr(main, "llm", CannedLLM(predicted, text_reply=CANNED_CARD))


def test_build_review_edit_add_and_delete_prepared_cards(monkeypatch, quiet_pipeline):
    import time
    with_predictions(monkeypatch)
    with TestClient(app) as client:
        meeting = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": AGENDA, "participants": ["Dana"]}).json()
        base = f"/api/prep/{meeting['sessionId']}"
        assert client.get(f"{base}/status").json()["state"] == "idle"

        assert client.post(f"{base}/build").json()["state"] in ("predicting", "writing", "done")
        for _ in range(50):
            status = client.get(f"{base}/status").json()
            if status["state"] in ("done", "failed"):
                break
            time.sleep(0.05)
        assert status["state"] == "done" and status["done"] == status["total"] == 2, status

        cards = client.get(f"{base}/cards").json()["cards"]
        assert [c["question"] for c in cards] == ["How long will the OpenPlaces places take?", "Is release 6 live?"]
        assert cards[0]["card"]["line"] and cards[0]["userEdited"] is False

        edited = client.put(f"{base}/cards/{cards[1]['cardId']}", json={"line": "Yes, since 22 Oct.", "points": ["Live at the demo address"]}).json()
        assert edited["userEdited"] and edited["card"]["line"] == "Yes, since 22 Oct."
        assert client.get(f"{base}/cards").json()["cards"][0]["cardId"] == cards[1]["cardId"], "edited cards come first"

        added = client.post(f"{base}/cards", json={"question": "Who owns the data map?"}).json()
        assert added["question"] == "Who owns the data map?" and added["card"]["points"]

        assert client.delete(f"{base}/cards/{cards[0]['cardId']}").json() == {"deleted": cards[0]["cardId"]}
        assert len(client.get(f"{base}/cards").json()["cards"]) == 2

        vectors = main.vectors
        assert vectors.rows.get(f"prep:{meeting['sessionId']}")
        client.delete(base)
        assert not vectors.rows.get(f"prep:{meeting['sessionId']}"), "deleting the meeting drops its prepared phrasings"


def test_building_needs_a_profile(monkeypatch, quiet_pipeline):
    client = TestClient(app)
    meeting = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": AGENDA}).json()
    quiet_pipeline.profiles.clear()
    assert client.post(f"/api/prep/{meeting['sessionId']}/build").status_code == 409


def run_prepared_meeting(monkeypatch, quiet_pipeline, prepared_question: str, speech_to_text=None):
    """Prepare a meeting with one card, then hold it while them asks the speech-to-text's question
    (QuestionSpeechToText's unless another is given)."""
    import asyncio
    from tests.fakes import CANNED_CARD, CONFIRMING_REPLY, CannedLLM, QuestionSpeechToText
    from app.agents.answer import AnswerAgent
    from app.prep.cache import AnswerCache
    from app.prep.predictor import QuestionPredictor

    client = TestClient(app)
    meeting = client.post("/api/prep", json={"title": "Dana 1:1", "agenda": AGENDA}).json()
    record = quiet_pipeline.sessions[("local", meeting["sessionId"])]
    prepared_reply = "CONFIDENCE: high\nIt was thirty two, prepared.\n- Prepared point\n"
    cache = AnswerCache(quiet_pipeline, main.embeddings, main.vectors,
                        AnswerAgent(CannedLLM({}, text_reply=prepared_reply), main.embeddings, main.vectors, "m", 4, 0.45),
                        QuestionPredictor(CannedLLM({}), main.embeddings, main.vectors, "m"))
    asyncio.run(cache.add(quiet_pipeline.profiles["local"], record, prepared_question))

    asked = speech_to_text or QuestionSpeechToText
    llm = CannedLLM({**CONFIRMING_REPLY, "question_text": asked.QUESTION}, text_reply=CANNED_CARD)
    monkeypatch.setattr(main, "llm", llm)
    monkeypatch.setattr(main, "make_speech_to_text", asked)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "prep_session_id": meeting["sessionId"]})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    answer_prompts = [m for m in llm.prompts if "QUESTION TO THE USER" in m[-1].content]
    return events, answer_prompts


def test_a_question_matching_a_prepared_card_shows_it_without_writing_one(monkeypatch, quiet_pipeline):
    from tests.fakes import QuestionSpeechToText
    events, answer_prompts = run_prepared_meeting(monkeypatch, quiet_pipeline, QuestionSpeechToText.QUESTION)
    done = next(e for e in events if e["type"] == "answer_done")
    assert done["label"] == "prepared" and done["card"]["line"] == "It was thirty two, prepared."
    assert answer_prompts == [], "no live card was written"


def test_a_question_far_from_every_prepared_card_gets_a_live_card(monkeypatch, quiet_pipeline):
    events, answer_prompts = run_prepared_meeting(monkeypatch, quiet_pipeline, "Who waters the office plants on Fridays?")
    done = next(e for e in events if e["type"] == "answer_done")
    assert done["label"] == "live" and len(answer_prompts) == 1


def test_a_claim_about_the_users_work_is_checked_even_when_a_prepared_card_matches(monkeypatch, quiet_pipeline):
    from tests.fakes import QuestionSpeechToText

    class ClaimSpeechToText(QuestionSpeechToText):
        QUESTION = "Surya, your last run used a batch size of thirty two, right?"

    events, answer_prompts = run_prepared_meeting(monkeypatch, quiet_pipeline, ClaimSpeechToText.QUESTION, ClaimSpeechToText)
    done = next(e for e in events if e["type"] == "answer_done")
    assert done["label"] == "live" and done["card"]["tags"]["asks_to_agree"]
    assert not any(e["type"] == "cache_match" for e in events), "the prepared cards were not consulted"
