"""Detector B with the real classifier model on four utterances. Slow (about a second each); Ollama must be running."""

import pytest

from app.adapters.factory import make_llm
from app.config import settings
from app.detect.classifier import Classifier
from app.ports import ME, THEM, Profile
from app.turns.end_of_turn import Turn
from tests.adapters.test_ollama_llm import ollama_is_up

PROFILE = Profile("local", "Surya", ["Sur", "Suria"], "Junior ML Engineer", ["retrieval", "evaluation", "data pipelines"], "", "", 1)
RECENT = [
    Turn(THEM, "Okay, let's go through the retrieval experiments.", 0.0, 3.0, 0.7),
    Turn(ME, "The new index cut the rebuild from forty minutes to twelve.", 4.0, 8.0, 0.7),
]

# (what them said as the session hands it over, Detector A's reasons, confirmed?, category)
CASES = [
    ("Surya, what batch size did you end up using for the last training run?", ["your name", "question"], True, "technical"),
    ("Surya did a great job on the pipeline, by the way.", ["your name"], False, None),
    ("Good morning everyone, how are you all doing?", ["attention"], False, "small_talk"),
    ("Alex, can you share the dashboard link after this call?", ["attention", "question"], False, None),
    ("And what would you suggest for the evaluation set?", ["question", "after you spoke", "your topic"], True, None),
]


@pytest.mark.skipif(not ollama_is_up(), reason="Ollama is not running: brew services start ollama")
@pytest.mark.parametrize("text,reasons,expected,category", CASES)
async def test_real_classifier(text, reasons, expected, category):
    classifier = Classifier(make_llm(), settings.llm_classifier_model, settings.classifier_min_confidence)
    verdict = await classifier.classify(PROFILE, RECENT, text, reasons)
    assert classifier.confirms(verdict) is expected, verdict
    if category:
        assert verdict.category == category, verdict
