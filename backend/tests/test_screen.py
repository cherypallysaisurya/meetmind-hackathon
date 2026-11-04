"""Screen-aware answers (decision 0009): a question that points at the screen gets a picture of it."""

import base64
import json

import httpx
from fastapi.testclient import TestClient

from app import main
from app.adapters.local.llm_ollama import OllamaLLM
from app.adapters.meta.llm_meta import MetaLLM
from app.agents.answer import AnswerAgent
from app.detect.rules import refers_to_screen
from app.main import app
from app.ports import Message, Profile
from tests.fakes import CANNED_CARD, CONFIRMING_REPLY, CannedLLM, HashEmbeddings, InMemoryVectorStore, QuestionSpeechToText
from tests.test_websocket import quiet_pipeline, tone_frame   # noqa: F401  (the fixture is used by name)

PICTURE = b"\xff\xd8 a jpeg"
CHART_QUESTION = "Surya, what do you make of this chart?"


def test_questions_that_point_at_the_screen():
    assert refers_to_screen("What do you make of this chart?")
    assert refers_to_screen("Can you explain these numbers?")
    assert refers_to_screen("Looking at the dashboard on the screen, is that normal?")
    assert refers_to_screen("I’m sharing the plan now, thoughts?")
    assert not refers_to_screen("What batch size did you use?")
    assert not refers_to_screen("This is our GitHub, right?")


def test_ollama_sends_a_picture_as_base64_next_to_the_text():
    assert OllamaLLM._message(Message("user", "Look.", [PICTURE])) == {"role": "user", "content": "Look.", "images": [base64.b64encode(PICTURE).decode()]}
    assert OllamaLLM._message(Message("user", "Plain.")) == {"role": "user", "content": "Plain."}


async def test_meta_sends_a_picture_as_an_image_url_part():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}]})

    llm = MetaLLM("https://api.meta.ai/v1", "test-key", transport=httpx.MockTransport(handler))
    await llm.complete_json("muse-spark-1.3", [Message("system", "Rules."), Message("user", "Look.", [PICTURE])], {"type": "object"})
    system, user = seen["body"]["messages"]
    assert system == {"role": "system", "content": "Rules."}
    assert user["content"] == [{"type": "text", "text": "Look."},
                               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(PICTURE).decode()}}]


async def test_the_answer_agent_shows_the_model_the_screen_only_when_given_one():
    llm = CannedLLM({}, text_reply="CONFIDENCE: medium\nThe drop is in week three.\n- Bookings fall 20 percent\n")
    agent = AnswerAgent(llm, HashEmbeddings(), InMemoryVectorStore(), "answer-model", 4, 0.45)
    profile = Profile("local", "Surya", [], "", [], "", "", 1)

    async def quiet(_):
        pass

    card, _ = await agent.answer("local", profile, "What do you make of this chart?", [], quiet, screen=PICTURE)
    plain, _ = await agent.answer("local", profile, "What batch size did you use?", [], quiet)
    with_screen, without = llm.prompts[0][1], llm.prompts[1][1]
    assert with_screen.images == [PICTURE] and "SCREEN:" in with_screen.content and card.snapshot()["tags"]["screen"]
    assert without.images == [] and "SCREEN:" not in without.content and not plain.screen
    assert llm.prompts[0][0] == llm.prompts[1][0], "the system instructions are the same either way, so the cached prefix holds"


class ChartQuestion(QuestionSpeechToText):
    QUESTION = CHART_QUESTION


def run_chart_question(monkeypatch, see_screen: bool, reply_with_picture: bool = True) -> tuple[list[dict], CannedLLM]:
    llm = CannedLLM({**CONFIRMING_REPLY, "question_text": CHART_QUESTION}, text_reply=CANNED_CARD)
    monkeypatch.setattr(main, "llm", llm)
    monkeypatch.setattr(main, "make_speech_to_text", ChartQuestion)
    events = []
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "see_screen": see_screen})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        if see_screen and reply_with_picture:
            while not events or events[-1]["type"] != "screen_request":
                events.append(ws.receive_json())
            ws.send_json({"type": "screen", "alert_id": events[-1]["alert_id"], "jpeg": base64.b64encode(PICTURE).decode()})
        ws.send_json({"type": "stop"})
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    return events, llm


def answer_prompts(llm: CannedLLM) -> list[Message]:
    return [m[-1] for m in llm.prompts if "QUESTION TO THE USER" in m[-1].content]


def test_with_see_my_screen_on_the_card_is_written_with_the_picture_the_app_sends(monkeypatch, quiet_pipeline):
    events, llm = run_chart_question(monkeypatch, see_screen=True)
    request = next(e for e in events if e["type"] == "screen_request")
    alert = next(e for e in events if e["type"] == "alert")
    assert request["alert_id"] == alert["id"]
    assert [p.images for p in answer_prompts(llm)] == [[PICTURE]]
    assert next(e for e in events if e["type"] == "answer_done")["card"]["tags"]["screen"] is True


def test_with_see_my_screen_off_nothing_is_asked_for(monkeypatch, quiet_pipeline):
    events, llm = run_chart_question(monkeypatch, see_screen=False)
    assert not [e for e in events if e["type"] == "screen_request"]
    assert [p.images for p in answer_prompts(llm)] == [[]]


def test_when_the_app_sends_no_picture_the_card_is_written_without_one(monkeypatch, quiet_pipeline):
    events, llm = run_chart_question(monkeypatch, see_screen=True, reply_with_picture=False)
    assert any(e["type"] == "screen_request" for e in events)
    assert [p.images for p in answer_prompts(llm)] == [[]], "after 1.5 s the card goes ahead without the screen"
    assert next(e for e in events if e["type"] == "answer_done")["card"]["tags"]["screen"] is False
