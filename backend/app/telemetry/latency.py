"""Latency telemetry: one timing record per alerted question.

Every stage is stamped on the audio clock (seconds of audio received so far), so the numbers compare
directly with the spec's targets, which are measured from the last word spoken. The classifier's time
is wall-clock because it is compute, not audio.
"""

from dataclasses import dataclass

# Spec targets, measured from the last word spoken. The answer target arrives with Phase 2.
TARGETS_S = {"last_word_to_alert_s": 1.0, "last_word_to_turn_s": 0.7, "last_word_to_first_answer_s": 3.0}


@dataclass
class QuestionTiming:
    alert_id: str
    question: str = ""
    alert_s: float | None = None          # Detector A fired
    last_word_s: float | None = None      # the utterance ended (from the final transcript)
    turn_known_s: float | None = None     # the final transcript arrived, so the turn was known
    classified_s: float | None = None     # Detector B answered
    classifier_ms: int | None = None
    first_answer_s: float | None = None   # the cue line was complete
    answer_done_s: float | None = None
    status: str = "candidate"

    def since_last_word(self, moment: float | None) -> float | None:
        if moment is None or self.last_word_s is None:
            return None
        return round(moment - self.last_word_s, 2)

    def stages(self) -> dict:
        return {
            "last_word_to_alert_s": self.since_last_word(self.alert_s),        # negative: the alert came before the last word
            "last_word_to_turn_s": self.since_last_word(self.turn_known_s),
            "last_word_to_classified_s": self.since_last_word(self.classified_s),
            "classifier_ms": self.classifier_ms,
            "last_word_to_first_answer_s": self.since_last_word(self.first_answer_s),
            "last_word_to_answer_done_s": self.since_last_word(self.answer_done_s),
        }

    def event(self) -> dict:
        return {"type": "latency", "alert_id": self.alert_id, "question": self.question, "status": self.status, **self.stages()}
