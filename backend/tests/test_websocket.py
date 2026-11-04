import asyncio
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main
from app.audio.frames import SAMPLES_PER_CHANNEL
from app.main import app
from app.ports import THEM, Profile, Transcript
from tests.fakes import (CONFIRMING_REPLY, HANDOFF_REPLY, LOW_CONFIDENCE_CARD, RETRACTING_REPLY, CannedLLM, FollowUpSpeechToText,
                         HandoffSpeechToText, HashEmbeddings, InMemoryStore, InMemoryVectorStore,
                         QuestionSpeechToText, ScriptedSpeechToText, SilentSpeechToText, canned_llm)

PROFILE = Profile("local", "Surya", ["Sur"], "Junior ML Engineer", ["retrieval"], "", "", created_at=1)


@pytest.fixture(autouse=True)
def quiet_pipeline(monkeypatch):
    """The session tests are about the session, not the speech engine or the database."""
    monkeypatch.setattr(main, "make_speech_to_text", SilentSpeechToText)
    monkeypatch.setattr(main, "llm", canned_llm(CONFIRMING_REPLY))
    monkeypatch.setattr(main, "embeddings", HashEmbeddings())
    vectors = InMemoryVectorStore()
    monkeypatch.setattr(main, "vectors", vectors)
    store = InMemoryStore()
    store.profiles["local"] = PROFILE
    monkeypatch.setattr(main, "store", store)
    store.vectors = vectors
    return store


def tone_frame(left_amplitude: int, right_amplitude: int) -> bytes:
    """One frame with a 440 Hz tone at the given amplitude on each channel."""
    t = np.arange(SAMPLES_PER_CHANNEL) / 16000
    tone = np.sin(2 * np.pi * 440 * t)
    samples = np.empty(SAMPLES_PER_CHANNEL * 2, dtype=np.int16)
    samples[0::2] = (tone * left_amplitude).astype(np.int16)
    samples[1::2] = (tone * right_amplitude).astype(np.int16)
    return samples.tobytes()


def test_start_frames_stats_stop_and_the_session_record(quiet_pipeline):
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        started = ws.receive_json()
        assert started["type"] == "started"
        session_id = started["session_id"]

        frame = tone_frame(left_amplitude=8000, right_amplitude=0)
        for _ in range(10):
            ws.send_bytes(frame)
        stats = ws.receive_json()
        assert stats["type"] == "stats"
        assert stats["frames"] == 10
        assert stats["audio_seconds"] == 1.0
        assert stats["me_db"] > -20
        assert stats["them_db"] == -100.0

        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "stopped", "frames": 10, "audio_seconds": 1.0}

    record = quiet_pipeline.sessions[("local", session_id)]
    assert record.title.startswith("Meeting on")
    assert record.ended_at is not None and record.ended_at >= record.started_at
    assert record.ttl > time.time() + 29 * 24 * 3600


def test_transcripts_are_forwarded_before_stopped_and_final_turns_are_stored(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", ScriptedSpeechToText)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        session_id = ws.receive_json()["session_id"]
        for _ in range(20):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = [ws.receive_json() for _ in range(8)]
        kinds = [event["type"] for event in events]
        assert kinds == ["stats", "transcript", "turn", "stats", "transcript", "turn", "notes_update", "stopped"], \
            "every transcript and turn is sent, the notes catch up, then stopped"
        assert events[1] == {"type": "transcript", "channel": "them", "text": "sentence 1", "is_partial": False, "start_s": 0.0, "end_s": 1.0}
        assert events[2]["channel"] == "them" and events[2]["text"] == "sentence 1" and events[2]["delay_s"] >= 0.0

    items = [item for item in quiet_pipeline.items[session_id] if item.type == "final_turn"]
    assert len(items) == 2
    assert items[0].payload == {"channel": "them", "text": "sentence 1", "start_s": 0.0, "end_s": 1.0, "echo": False}
    assert items[0].timestamp < items[1].timestamp
    assert [item.type for item in quiet_pipeline.items[session_id]][-1] == "notes", "the notes are stored too"


def test_start_without_a_profile_is_refused(quiet_pipeline):
    quiet_pipeline.profiles.clear()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        assert ws.receive_json()["message"] == "no profile saved yet, fill in the Profile screen first"


def test_audio_before_start_and_wrong_frame_size_are_errors():
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_bytes(tone_frame(1000, 1000))
        assert ws.receive_json()["message"] == "audio received before start"

        ws.send_json({"type": "start"})
        ws.receive_json()
        ws.send_bytes(b"\x00" * 100)
        assert "expected 6400" in ws.receive_json()["message"]

        ws.send_text("not json")
        assert ws.receive_json()["message"] == "control message is not JSON"


def test_a_question_with_the_users_name_alerts_once_and_is_stored(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", QuestionSpeechToText)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        session_id = ws.receive_json()["session_id"]
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    alerts = [e for e in events if e["type"] == "alert"]
    assert [(a["is_final"], a["status"]) for a in alerts] == [(True, "candidate"), (True, "confirmed")], \
        "opened on the complete sentence, never on the partial, then confirmed by the classifier"
    assert len({a["id"] for a in alerts}) == 1
    assert alerts[0]["reasons"] == ["your name", "question"]
    assert alerts[0]["question"] == QuestionSpeechToText.QUESTION
    assert alerts[1]["question"] == CONFIRMING_REPLY["question_text"] and alerts[1]["category"] == "technical"
    kinds = [e["type"] for e in events]
    partial_index = next(i for i, e in enumerate(events) if e["type"] == "transcript" and e["is_partial"])
    assert kinds.index("alert") > partial_index, "the partial alone opens nothing"

    stored = [item for item in quiet_pipeline.items[session_id] if item.type == "alert"]
    assert len(stored) == 1 and stored[0].payload["status"] == "confirmed"

    latency = next(e for e in events if e["type"] == "latency")
    assert latency["alert_id"] == alerts[0]["id"] and latency["status"] == "confirmed"
    assert latency["last_word_to_alert_s"] == 1.0, "the alert fired on the final at 4.0 s of audio, the last word was at 3.0 s"
    assert latency["last_word_to_turn_s"] == 1.0, "the final arrived at 4.0 s of audio"
    assert latency["classifier_ms"] >= 0

    deltas = [e for e in events if e["type"] == "answer_delta"]
    done = next(e for e in events if e["type"] == "answer_done")
    first_with_line = next(d for d in deltas if d["card"]["line"])
    assert first_with_line["card"]["line"] == "Thirty two, with gradient accumulation of four."
    assert first_with_line["card"]["confidence"] == "high", "confidence was known before the line was shown"
    assert done["card"]["points"] == [{"text": "Batch size 32", "sources": []}, {"text": "Accumulation 4", "sources": []}], \
        "the canned card cites [S1], but no documents are indexed, so the marker points at nothing and is dropped"
    assert done["label"] == "live"
    assert done["sources"] == [], "no documents were indexed, so no source chips"
    assert done["card"]["confidence"] == "medium" and done["card"]["tags"]["ungrounded"], "nothing from the user's documents: never called certain"
    stored_answers = [item for item in quiet_pipeline.items[session_id] if item.type == "answer"]
    assert len(stored_answers) == 1 and stored_answers[0].payload["question"] == CONFIRMING_REPLY["question_text"]
    final_latency = [e for e in events if e["type"] == "latency"][-1]
    assert final_latency["last_word_to_first_answer_s"] is not None and final_latency["last_word_to_answer_done_s"] is not None


def test_the_classifier_can_retract_an_alert(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", QuestionSpeechToText)
    monkeypatch.setattr(main, "llm", CannedLLM(RETRACTING_REPLY))
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    statuses = [e["status"] for e in events if e["type"] == "alert"]
    assert statuses == ["candidate", "retracted"]


def test_attention_right_after_a_turn_alerts_that_turn(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", ScriptedSpeechToText)   # "sentence 1" has no name, no question
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(10):
            ws.send_bytes(tone_frame(0, 3000))
        assert [ws.receive_json()["type"] for _ in range(3)] == ["stats", "transcript", "turn"]
        ws.send_json({"type": "attention"})
        alert = ws.receive_json()
        assert alert["type"] == "alert" and alert["reasons"] == ["attention"] and alert["question"] == "sentence 1"
        ws.send_json({"type": "stop"})


def test_an_attention_alert_is_never_retracted(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", ScriptedSpeechToText)
    monkeypatch.setattr(main, "llm", CannedLLM(RETRACTING_REPLY))
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(10):
            ws.send_bytes(tone_frame(0, 3000))
        assert [ws.receive_json()["type"] for _ in range(3)] == ["stats", "transcript", "turn"]
        ws.send_json({"type": "attention"})
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    statuses = [e["status"] for e in events if e["type"] == "alert"]
    assert statuses == ["candidate", "confirmed"]


def test_a_plain_follow_up_question_shows_only_once_the_classifier_agrees(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", FollowUpSpeechToText)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(3000, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    alerts = [e for e in events if e["type"] == "alert"]
    assert [a["status"] for a in alerts] == ["confirmed"], "no candidate card was shown before Detector B agreed"
    assert alerts[0]["reasons"] == ["question", "follows your turn"]
    latency = next(e for e in events if e["type"] == "latency")
    assert latency["last_word_to_alert_s"] is not None and latency["last_word_to_alert_s"] > 0, "a promoted card comes after the last word"


def test_a_plain_follow_up_the_classifier_rejects_never_shows(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", FollowUpSpeechToText)
    monkeypatch.setattr(main, "llm", CannedLLM(RETRACTING_REPLY))
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(3000, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    assert not [e for e in events if e["type"] == "alert"]


def test_a_card_already_on_screen_survives_a_retraction(monkeypatch, quiet_pipeline):
    """Detector A saw a question, so the card is written first and the classifier runs after the cue line shows.
    When the classifier then retracts, the card stays (tagged by the desktop) instead of vanishing mid-read."""
    monkeypatch.setattr(main, "make_speech_to_text", QuestionSpeechToText)
    monkeypatch.setattr(main, "llm", canned_llm(RETRACTING_REPLY))
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    kinds = [e["type"] for e in events]
    first_line = next(i for i, e in enumerate(events) if e["type"] == "answer_delta" and e["card"]["line"])
    retracted = next(i for i, e in enumerate(events) if e["type"] == "alert" and e["status"] == "retracted")
    assert first_line < retracted, "the cue line was on screen before the classifier spoke"
    assert "answer_done" in kinds, "the card was finished, not cancelled"


async def test_the_answer_cites_the_indexed_document(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", QuestionSpeechToText)
    text = "Last training run used batch size 32 with gradient accumulation of 4."
    await quiet_pipeline.vectors.add("docs:local", ["d:0"], await HashEmbeddings().embed([text]),
                                     [{"doc_id": "d", "document": "notes.md", "location": "section: Training", "index": 0, "text": text}])
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    done = next(e for e in events if e["type"] == "answer_done")
    assert done["sources"] == [{"number": 1, "document": "notes.md", "location": "section: Training", "text": text}]


class RepeatedQuestionSpeechToText(SilentSpeechToText):
    """Them asks the user by name, then a second person hands over the same question."""

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 10:
            self.queue.put_nowait(Transcript(THEM, "Surya, what batch size did you use for the last run?", False, 0.1, 3.0))
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, "Surya, what batch size did you use for the last run again?", False, 5.0, 7.0))

    async def transcripts(self):
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)


def test_the_same_question_asked_again_does_not_open_a_second_card(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", RepeatedQuestionSpeechToText)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    ids = {e["id"] for e in events if e["type"] == "alert"}
    assert len(ids) == 1, "the repeat was folded into the first card"
    assert len([e for e in events if e["type"] == "answer_done"]) == 1


def test_notes_are_written_at_stop_and_stored(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", ScriptedSpeechToText)   # a them turn every ten frames
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        session_id = ws.receive_json()["session_id"]
        for _ in range(30):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    notes = [e for e in events if e["type"] == "notes_update"]
    assert len(notes) == 1, "the notes catch up once at stop (the 75 s timer never fired in 3 s of audio)"
    assert notes[0]["notes"][0] == "CONFIDENCE: high"   # the canned stream is a card; the notes parser keeps its lines
    stored = [item for item in quiet_pipeline.items[session_id] if item.type == "notes"]
    assert len(stored) == 1 and stored[0].payload["notes"] == notes[0]["notes"]


def test_notes_refresh_on_the_audio_clock_when_no_card_is_being_written(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", ScriptedSpeechToText)
    monkeypatch.setattr(main.settings, "notes_every_s", 2)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(50):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    assert len([e for e in events if e["type"] == "notes_update"]) >= 2


def test_a_low_confidence_card_shows_points_only(monkeypatch, quiet_pipeline):
    monkeypatch.setattr(main, "make_speech_to_text", QuestionSpeechToText)
    monkeypatch.setattr(main, "llm", CannedLLM(CONFIRMING_REPLY, text_reply=LOW_CONFIDENCE_CARD))
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    cards = [e["card"] for e in events if e["type"] in ("answer_delta", "answer_done")]
    assert cards and all(c["line"] is None for c in cards), "the cue line never reached the client"
    done = next(e for e in events if e["type"] == "answer_done")
    assert done["card"]["tags"]["low_confidence"] is True
    assert [p["text"] for p in done["card"]["points"]] == ["Batch size may be 32", "Check the training log"]


def run_handoff(monkeypatch, speech_to_text):
    llm = canned_llm(HANDOFF_REPLY)
    monkeypatch.setattr(main, "make_speech_to_text", speech_to_text)
    monkeypatch.setattr(main, "llm", llm)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    answer_prompts = [m for m in llm.prompts if "QUESTION TO THE USER" in m[-1].content]
    questions_asked = [p[-1].content.split('QUESTION TO THE USER: "')[1].rstrip('"') for p in answer_prompts]
    judged = [m[-1].content.split('Last thing said by them: "')[1].split('"')[0] for m in llm.prompts if "Last thing said by them" in m[-1].content]
    return events, questions_asked, judged


def test_a_handoff_is_answered_as_the_question_it_passes_on(monkeypatch, quiet_pipeline):
    events, questions_asked, judged = run_handoff(monkeypatch, HandoffSpeechToText)
    real_question = HANDOFF_REPLY["question_text"]
    first_alert = next(e for e in events if e["type"] == "alert")
    assert first_alert["question"] == real_question, "the alert names the question that was handed over, not the handoff"
    assert questions_asked == [real_question], "one card, written for the real question from the start"
    assert judged == ["Surya, do you want to take that one?"], "Detector B judges what was said to the user, not the room's question"
    assert len([e for e in events if e["type"] == "answer_done"]) == 1


class VagueHandoffSpeechToText(HandoffSpeechToText):
    handoff = "Surya, thoughts on that?"   # no handoff phrase the rules know; only the classifier sees the link


def test_a_card_written_for_a_vague_handoff_is_redone_for_the_real_question(monkeypatch, quiet_pipeline):
    events, questions_asked, _ = run_handoff(monkeypatch, VagueHandoffSpeechToText)
    real_question = HANDOFF_REPLY["question_text"]
    confirmed = next(e for e in events if e["type"] == "alert" and e["status"] == "confirmed")
    assert confirmed["question"] == real_question
    assert questions_asked[0] == "Surya, thoughts on that?" and questions_asked[-1] == real_question
    assert len([e for e in events if e["type"] == "answer_done"]) >= 1


class NamelessQuestionSpeechToText(QuestionSpeechToText):
    """Them asks a question with no name in it, as a manager does in a one-on-one."""

    QUESTION = "What would happen if we used bigger chunks?"

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, self.QUESTION, False, 0.1, 3.0))


def run_nameless_question(monkeypatch, one_on_one: bool):
    monkeypatch.setattr(main, "make_speech_to_text", NamelessQuestionSpeechToText)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "one_on_one": one_on_one})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        ws.send_json({"type": "stop"})
        events = []
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    return events


def test_one_on_one_answers_a_question_with_no_name_in_it(monkeypatch, quiet_pipeline):
    events = run_nameless_question(monkeypatch, one_on_one=True)
    alert = next(e for e in events if e["type"] == "alert")
    assert "one-on-one" in alert["reasons"]
    assert any(e["type"] == "answer_done" for e in events)


def test_without_one_on_one_a_question_with_no_name_waits_for_detector_b(monkeypatch, quiet_pipeline):
    events = run_nameless_question(monkeypatch, one_on_one=False)
    assert not [e for e in events if e["type"] == "alert" and e["status"] == "candidate"], "nothing shown before Detector B"


def test_one_on_one_confirms_a_question_mark_sentence_without_the_classifier(monkeypatch, quiet_pipeline):
    events = run_nameless_question(monkeypatch, one_on_one=True)
    confirmed = next(e for e in events if e["type"] == "alert" and e["status"] == "confirmed")
    assert confirmed["category"] == "question"
    assert not [m for m in main.llm.prompts if "Last thing said by them" in m[-1].content], "Detector B was not called"
    latency = next(e for e in events if e["type"] == "latency")
    assert latency["classifier_ms"] == 0
