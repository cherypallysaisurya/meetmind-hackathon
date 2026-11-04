import pytest

from app.detect.classifier import Classifier, Verdict
from app.ports import ME, THEM, Profile
from app.turns.end_of_turn import Turn
from tests.fakes import CONFIRMING_REPLY, CannedLLM

PROFILE = Profile("local", "Surya", ["Sur"], "Junior ML Engineer", ["retrieval", "evaluation"], "", "", 1)


def classifier(reply=CONFIRMING_REPLY):
    llm = CannedLLM(reply)
    return Classifier(llm, "test-model", min_confidence=0.5), llm


async def test_prompt_carries_profile_and_transcript_without_echoes():
    detector, llm = classifier()
    recent = [
        Turn(THEM, "Let's look at the eval numbers.", 0.0, 2.0, 0.7),
        Turn(ME, "Let's look at the eval numbers.", 0.1, 2.1, 0.7, echo=True),
        Turn(ME, "Recall went up to 0.84.", 3.0, 5.0, 0.7),
    ]
    verdict = await detector.classify(PROFILE, recent, "Surya, what batch size did you use?", ["your name", "question"])
    prompt = llm.prompts[0][1].content
    assert "flagged it because of: your name, question" in prompt
    assert "Surya (also called: Surya, Sur)" in prompt and "Junior ML Engineer" in prompt and "retrieval" in prompt
    assert "them: Let's look at the eval numbers." in prompt
    assert "me: Recall went up to 0.84." in prompt
    assert prompt.count("eval numbers") == 1, "the echo line must not be in the prompt"
    assert 'Last thing said by them: "Surya, what batch size did you use?"' in prompt
    assert verdict == Verdict(True, True, "What batch size did you use for the last run?", "technical", 0.9)


@pytest.mark.parametrize("verdict,expected", [
    (Verdict(True, True, "q", "technical", 0.9), True),
    (Verdict(True, True, "q", "logistics", 0.5), True),
    (Verdict(True, True, "q", "small_talk", 0.9), False),
    (Verdict(True, False, "q", "technical", 0.9), False),
    (Verdict(False, True, "", "technical", 0.9), False),
    (Verdict(True, True, "q", "technical", 0.4), False),
])
def test_confirms_only_real_questions_for_the_user_with_enough_confidence(verdict, expected):
    detector, _ = classifier()
    assert detector.confirms(verdict) is expected
