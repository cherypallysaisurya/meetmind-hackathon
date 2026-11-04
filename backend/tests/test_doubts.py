"""A question for the user to ask (doubt agent, spec Phase 3 brought forward by decision 0009)."""

import asyncio
from typing import AsyncIterator

from fastapi.testclient import TestClient

from app import main
from app.agents.answer import Source
from app.agents.doubts import DoubtAgent, nothing_to_ask
from app.detect.rules import is_open_floor
from app.main import app
from app.ports import THEM, Profile, Transcript
from app.turns.end_of_turn import Turn
from tests.fakes import CannedLLM, HashEmbeddings, SilentSpeechToText
from tests.test_websocket import quiet_pipeline, tone_frame   # noqa: F401  (the fixture is used by name)

PROFILE = Profile("local", "Surya", ["Sur"], "Junior ML Engineer", ["retrieval", "evaluation"], "", "", 1)
SUGGESTION = {"question": "Did you measure recall on the rebuilt index before switching?", "why": "Tells us if the switch was safe.", "sources": [1, 7]}
SOURCE = Source(1, "metrics.md", "section: Recall", "Recall at ten is 0.84 on the rebuilt index.", 0.6)
TALK = ("Last quarter our search team moved from nightly index rebuilds to streaming updates. Every changed document is "
        "re-embedded within two minutes. The catch was evaluation, so we now sample live queries every day and grade them "
        "with a language model judge that agrees with our raters about eighty percent of the time.")


def test_open_floor_moments():
    assert is_open_floor("Thanks for the presentation. Any questions from the room?")
    assert is_open_floor("Anything else? Thoughts on the evaluation approach?")
    assert is_open_floor("So, thoughts?")
    assert is_open_floor("Does anyone have questions about the data map?")
    assert not is_open_floor("If there are no more questions, let's wrap up.")
    assert not is_open_floor("What are your thoughts on the release, Surya?")
    assert not is_open_floor("That answers my questions.")
    assert is_open_floor("Anything else, thoughts on the evaluation approach?"), "how speech-to-text wrote it in a replay"
    assert not is_open_floor("Surya, thoughts on that?"), "a handoff asking the user's opinion is a question to answer"


async def test_the_agent_returns_one_question_with_only_the_sources_it_cites():
    llm = CannedLLM(SUGGESTION)
    agent = DoubtAgent(llm, HashEmbeddings(), "doubt-model")
    recent = [Turn(THEM, "We switched to the rebuilt index last week.", 0.0, 3.0, 0.6)]
    doubt = await agent.write(PROFILE, recent, ["Index rebuilt nightly"], [SOURCE], ["How big is the index?"])
    assert doubt.question == SUGGESTION["question"] and doubt.why == SUGGESTION["why"]
    assert [s.number for s in doubt.sources] == [1], "source 7 was never given, so it is dropped"
    prompt = llm.prompts[0][1].content
    assert "[S1] metrics.md, section: Recall" in prompt and "- How big is the index?" in prompt and "them: We switched" in prompt


async def test_no_question_when_the_model_finds_nothing_or_writes_a_speech():
    empty = DoubtAgent(CannedLLM({"question": "", "why": "", "sources": []}), HashEmbeddings(), "m")
    speech = DoubtAgent(CannedLLM({"question": "word " * 40, "why": "", "sources": []}), HashEmbeddings(), "m")
    assert await empty.write(PROFILE, [], [], [], []) is None
    assert await speech.write(PROFILE, [], [], [], []) is None


def test_no_question_before_anything_was_said_or_while_the_user_takes_questions():
    open_floor = Turn(THEM, "Thanks for the presentation. Any questions from the room?", 0.0, 3.0, 0.6)
    talk = Turn(THEM, TALK, 4.0, 20.0, 0.6)
    long_answer = Turn("me", " ".join([TALK, TALK]), 21.0, 40.0, 0.6)
    assert nothing_to_ask([open_floor], asked=False) == "nothing said yet to ask about"
    assert nothing_to_ask([open_floor, talk], asked=False) is None
    assert nothing_to_ask([open_floor, talk, long_answer], asked=False) == "the user is the one taking questions"
    assert nothing_to_ask([open_floor, talk, long_answer], asked=True) is None, "the user's own request still gets a question"


async def test_closeness_to_what_was_already_said():
    agent = DoubtAgent(CannedLLM({}), HashEmbeddings(), "m")
    assert await agent.closest("How do you keep the index fresh?", ["How do you keep the index fresh?", "Thanks."]) > 0.99
    assert await agent.closest("Anything", []) == 0.0


class OpenFloorTwice(SilentSpeechToText):
    """A speaker talks for the first second, then the host opens the floor at 2 s and again at 4 s of audio."""

    def __init__(self):
        super().__init__()
        self.queue: asyncio.Queue[Transcript | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames += 1
        if self.frames == 10:
            self.queue.put_nowait(Transcript(THEM, TALK, False, 0.0, 0.9))
        if self.frames == 20:
            self.queue.put_nowait(Transcript(THEM, "Thanks everyone. Any questions?", False, 1.0, 1.8))
        if self.frames == 40:
            self.queue.put_nowait(Transcript(THEM, "Any other questions?", False, 3.0, 3.8))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while True:
            transcript = await self.queue.get()
            if transcript is None:
                return
            yield transcript

    async def stop(self) -> None:
        self.queue.put_nowait(None)


def run_meeting(monkeypatch, reply: dict, press_button: bool = False) -> tuple[list[dict], CannedLLM]:
    llm = CannedLLM(reply)
    monkeypatch.setattr(main, "llm", llm)
    monkeypatch.setattr(main, "make_speech_to_text", OpenFloorTwice)
    events = []
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start"})
        ws.receive_json()
        for _ in range(40):
            ws.send_bytes(tone_frame(0, 3000))
        while sum(e["type"] == "turn" for e in events) < 2:
            events.append(ws.receive_json())
        if press_button:
            ws.send_json({"type": "doubt"})
        ws.send_json({"type": "stop"})
        while not events or events[-1]["type"] != "stopped":
            events.append(ws.receive_json())
    return events, llm


def test_an_open_floor_suggests_one_question_and_opens_no_answer_card(monkeypatch, quiet_pipeline):
    events, _ = run_meeting(monkeypatch, SUGGESTION)
    doubts = [e for e in events if e["type"] == "doubt"]
    assert [d["question"] for d in doubts] == [SUGGESTION["question"]], "the second open floor came within 3 minutes"
    assert doubts[0]["reason"] == "open floor" and doubts[0]["why"] == SUGGESTION["why"]
    assert not [e for e in events if e["type"] == "alert"], "'any questions?' is not a question for the user to answer"
    stored = [i for items in quiet_pipeline.items.values() for i in items if i.type == "doubt"]
    assert [i.payload["question"] for i in stored] == [SUGGESTION["question"]]


def test_the_button_asks_for_a_question_even_inside_the_three_minutes(monkeypatch, quiet_pipeline):
    events, _ = run_meeting(monkeypatch, SUGGESTION, press_button=True)
    reasons = [e["reason"] for e in events if e["type"] == "doubt"]
    assert reasons[0] == "open floor" and "asked" in reasons


def test_asking_when_there_is_nothing_new_says_so(monkeypatch, quiet_pipeline):
    events, _ = run_meeting(monkeypatch, {"question": "", "why": "", "sources": []}, press_button=True)
    doubts = [e for e in events if e["type"] == "doubt"]
    assert [(d["question"], d["reason"]) for d in doubts] == [(None, "asked")], "the open floor alone stays quiet"
