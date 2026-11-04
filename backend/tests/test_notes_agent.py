from app.agents.notes import NotesAgent, parse_notes
from app.ports import ME, THEM, Profile
from app.turns.end_of_turn import Turn
from tests.fakes import CannedLLM

PROFILE = Profile("local", "Surya", [], "Junior ML Engineer", [], "", "", 1)


def test_parse_notes_takes_bullets_only_and_caps_them():
    text = "Notes:\n- Decided to move the review to Thursday\n* Recall is 0.84 now\n\nsome stray line\n" + "\n".join(f"- point {i}" for i in range(20))
    notes = parse_notes(text)
    assert notes[:3] == ["Decided to move the review to Thursday", "Recall is 0.84 now", "some stray line"]
    assert len(notes) == 12


async def test_update_sends_notes_so_far_and_new_turns_and_skips_echoes():
    llm = CannedLLM({}, text_reply="- Review moved to Thursday\n- Batch size 32")
    agent = NotesAgent(llm, "answer-model")
    turns = [Turn(THEM, "Let's move the review to Thursday.", 0, 2, 0.7), Turn(ME, "Let's move the review to Thursday.", 0.1, 2.1, 0.7, echo=True),
             Turn(ME, "We used batch size 32.", 3, 5, 0.7)]
    notes = await agent.update(PROFILE, ["Standup started"], turns)
    prompt = llm.prompts[0][1].content
    assert "NOTES SO FAR:\n- Standup started" in prompt
    assert prompt.count("move the review") == 1, "the echo line is not in the prompt"
    assert "me: We used batch size 32." in prompt
    assert notes == ["Review moved to Thursday", "Batch size 32"]


async def test_an_empty_reply_keeps_the_old_notes():
    agent = NotesAgent(CannedLLM({}, text_reply=""), "answer-model")
    assert await agent.update(PROFILE, ["kept"], [Turn(THEM, "x", 0, 1, 0.7)]) == ["kept"]
