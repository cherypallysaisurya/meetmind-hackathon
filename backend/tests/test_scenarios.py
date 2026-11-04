"""The eval scenarios must stay well formed: every speaker has a voice, every line a known label,
and every scenario has at least one question for the user."""

from pathlib import Path

import pytest
import yaml

SCENARIOS = sorted((Path(__file__).resolve().parents[2] / "eval" / "scenarios").glob("*.yaml"))
LABELS = {"statement", "question_for_user", "question_for_other", "small_talk", "name_without_question", "open_floor", "handoff"}


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_is_well_formed(path):
    scenario = yaml.safe_load(path.read_text())
    assert scenario["title"] and scenario["user"]["displayName"]
    voices = scenario["speakers"]
    assert "me" in voices
    labels = []
    for line in scenario["lines"]:
        assert line["who"] in voices, f"{line['who']} has no voice"
        assert line["text"].strip()
        labels.append(line.get("label", "statement"))
        assert labels[-1] in LABELS, labels[-1]
    assert "question_for_user" in labels


def test_the_set_has_at_least_ten_questions_for_the_user():
    total = 0
    for path in SCENARIOS:
        total += sum(line.get("label") == "question_for_user" for line in yaml.safe_load(path.read_text())["lines"])
    assert total >= 10


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_has_a_prep_pack(path):
    """Spec update 1: every scenario carries an agenda and three to six short documents for its user."""
    folder = path.with_suffix("")
    assert (folder / "agenda.md").exists(), f"{folder.name} has no agenda.md"
    documents = [p for p in folder.glob("*.md") if p.name != "agenda.md"]
    assert 3 <= len(documents) <= 6, f"{folder.name} has {len(documents)} documents"
    for document in documents:
        assert 40 <= len(document.read_text()) <= 10000   # the real knowledge base files run to about 8,000 characters
