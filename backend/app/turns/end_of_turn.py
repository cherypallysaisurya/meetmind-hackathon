"""End-of-turn detection: when did a speaker finish?

The speech-to-text adapter closes a speech segment after the silence window (TURN_SILENCE_MS) and
sends its final text. That final is a turn. This module keeps the recent turns for the detectors,
knows who is speaking right now, and measures how late each turn was known: the audio clock when the
final arrived, minus the moment the last word ended. That is the first stage of the latency budget,
target 400 to 700 ms.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..ports import ME, THEM, Transcript

ECHO_SIMILARITY = 0.75   # a me turn this close to a them turn nearby in time is the speakers, not the user
ECHO_WINDOW_S = 3.0


@dataclass
class Turn:
    channel: str
    text: str
    start_s: float
    end_s: float
    delay_s: float    # audio seconds between the last word and the moment the turn was known
    echo: bool = False   # a me turn that repeats what them just said: the mic heard the speakers


class EndOfTurnDetector:
    def __init__(self, keep_seconds: float = 300.0):
        self.keep_seconds = keep_seconds
        self.turns: list[Turn] = []
        self.speaking: dict[str, bool] = {}

    def on_transcript(self, transcript: Transcript, audio_now_s: float) -> Turn | None:
        """Feed every transcript. Returns a Turn when one just ended, otherwise None."""
        if transcript.is_partial:
            self.speaking[transcript.channel] = True
            return None
        self.speaking[transcript.channel] = False
        delay = round(max(0.0, audio_now_s - transcript.end_s), 2)
        turn = Turn(transcript.channel, transcript.text, transcript.start_s, transcript.end_s, delay)
        if turn.channel == ME:
            turn.echo = self._matches_nearby(turn, THEM)
        else:
            # The mic's echo of a them turn can be transcribed first; mark it now that the them text is known.
            for me_turn in self.turns:
                if me_turn.channel == ME and not me_turn.echo and self._same_words(me_turn, turn):
                    me_turn.echo = True
        self.turns.append(turn)
        self.turns = [t for t in self.turns if t.end_s >= audio_now_s - self.keep_seconds]
        return turn

    def is_speaking(self, channel: str) -> bool:
        return self.speaking.get(channel, False)

    def last_turn(self, channel: str, ended_before_s: float | None = None) -> Turn | None:
        """The channel's latest turn, skipping me turns that were only the speakers echoing them.

        With ended_before_s, only turns that ended before that moment count: a me turn overlapping the
        them utterance under consideration is the mic hearing the speakers, not the user speaking first."""
        for turn in reversed(self.turns):
            if turn.channel != channel or turn.echo:
                continue
            if ended_before_s is not None and turn.end_s > ended_before_s:
                continue
            return turn
        return None

    def _matches_nearby(self, turn: Turn, channel: str) -> bool:
        return any(other.channel == channel and self._same_words(other, turn) for other in self.turns)

    @staticmethod
    def _same_words(a: Turn, b: Turn) -> bool:
        close_in_time = abs(a.end_s - b.end_s) <= ECHO_WINDOW_S
        return close_in_time and SequenceMatcher(None, a.text.lower(), b.text.lower()).ratio() >= ECHO_SIMILARITY

    def recent(self, seconds: float, now_s: float) -> list[Turn]:
        """Turns that ended within the last `seconds` of audio, oldest first."""
        return [turn for turn in self.turns if turn.end_s >= now_s - seconds]
