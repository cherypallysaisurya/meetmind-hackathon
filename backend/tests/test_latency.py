from app.telemetry.latency import QuestionTiming


def test_stages_are_measured_from_the_last_word():
    timing = QuestionTiming("a1", "What batch size did you use?", alert_s=10.0, last_word_s=12.0,
                            turn_known_s=12.8, classified_s=14.9, classifier_ms=2050, status="confirmed")
    assert timing.stages() == {
        "last_word_to_alert_s": -2.0,
        "last_word_to_turn_s": 0.8,
        "last_word_to_classified_s": 2.9,
        "classifier_ms": 2050,
        "last_word_to_first_answer_s": None,
        "last_word_to_answer_done_s": None,
    }
    assert timing.event()["type"] == "latency" and timing.event()["status"] == "confirmed"


def test_missing_stages_are_none_not_errors():
    timing = QuestionTiming("a2", alert_s=10.0)
    assert timing.stages()["last_word_to_alert_s"] is None
    assert timing.stages()["classifier_ms"] is None
