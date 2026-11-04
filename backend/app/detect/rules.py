"""Detector A: cheap rules on every partial transcript of the them channel.

Decides in microseconds whether what is being said is probably a question for the user. Strong
signals fire on their own: the user's name or an alias, or the Attention button. Weak signals need
company: a question cue, "you" right after the user spoke, a word from the user's topics. Detector B
(Step 1.8) confirms or retracts what fires here. When unsure, this detector stays quiet.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

QUESTION_WORDS = {"what", "why", "how", "when", "which", "who", "where", "can", "could", "do", "does",
                  "did", "would", "will", "is", "are", "should", "any", "anyone", "have", "has"}
QUESTION_PHRASES = ("what do you think", "your thoughts", "your take", "can you", "could you", "do you",
                    "did you", "would you", "any thoughts", "what about", "how about", "right?")
YOU_WORDS = {"you", "your", "yours", "you're", "you've"}
# "..., right?" and "... . Right." (speech-to-text often ends a tag question with a period). "Right, so ..." at the
# start of a sentence is an acknowledgement, not a question, so the tag must close a sentence.
TAG_QUESTION = re.compile(r"(?:,\s*|\.\s+)(?:right|correct|isn't it|is that right)[.?!]?(?=\s|$)", re.IGNORECASE)
HANDOFF_PHRASES = ("take that one", "take this one", "take that question", "take this question", "want to take that",
                   "want to take this", "answer that one", "answer this one", "answer that question", "want to answer",
                   "like to answer", "is for you", "'s for you", "over to you", "that's yours", "one's yours",
                   "speak to that", "field that one")
# "Any questions?", "Thoughts?", "Does anyone have questions?": the room opens up, which is when a question to ask
# helps (spec: doubts only on an open floor). "If there are no more questions, let's wrap up" closes it instead.
OPEN_FLOOR = re.compile(
    r"\bany (?:other |more |final |last )?(?:questions|thoughts|comments)\b|"
    r"(?:^|[.?!]\s+)(?:so,? |ok(?:ay)?,? |alright,? |great,? )?(?:questions|thoughts|comments)(?:\s*\?|\s+(?:on|about)\b)|"
    r"\banything else\s*[?,]|"
    r"\bany(?:one|body) (?:have |got )?(?:any )?(?:questions|thoughts|comments)\b|"
    r"\bopen (?:it|things) up\b|\bopen the floor\b|\bfloor is open\b|\btime for (?:some )?questions\b|"
    r"\bq ?(?:&|and) ?a\b|\bquestions for (?:me|us)\b",
    re.IGNORECASE,
)

# "What do you make of this chart?": the question points at what is being shared, so the card needs the screen.
SCREEN_REFERENCE = re.compile(
    r"\b(?:on (?:the|my|your|this) screen|(?:this|that|these|those) (?:charts?|slides?|graphs?|plots?|diagrams?|tables?|"
    r"dashboards?|numbers?|figures?|pages?|screens?|code|curves?|metrics?|images?|pictures?)|i'm sharing|i am sharing|"
    r"you can see here|can you see this|look at this|shown here|up here on)\b",
    re.IGNORECASE,
)

NAME_SCORE = 0.6
ATTENTION_SCORE = 0.6
QUESTION_SCORE = 0.3
AFTER_YOU_SPOKE_SCORE = 0.3      # a question with "you" or a topic word, right after the user's turn
FOLLOWS_YOUR_TURN_SCORE = 0.2    # any other question right after the user's turn
TOPIC_SCORE = 0.2
FIRE_AT = 0.6                    # the alert shows at once
WEAK_AT = 0.5                    # not shown; Detector B reads the final text first and decides

# "siraia" and "sereya" (what speech-to-text made of Surya) score 0.73 against the aliases; real words
# that happen to look alike, such as "surely" (0.73) or "syria" (0.8), are refused by the dictionary check.
NAME_SIMILARITY = 0.7
DICTIONARY = Path("/usr/share/dict/words")


@dataclass
class Candidate:
    score: float
    reasons: list[str]

    @property
    def fires(self) -> bool:
        return self.score >= FIRE_AT

    @property
    def weak(self) -> bool:
        return WEAK_AT <= self.score < FIRE_AT


@cache
def english_words() -> frozenset[str]:
    """The system dictionary, lowercased. Empty where there is none, which only disables the refusal."""
    if not DICTIONARY.exists():
        return frozenset()
    return frozenset(word.strip().lower() for word in DICTIONARY.read_text().split("\n") if word.strip())


def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def matched_name(text: str, aliases: list[str]) -> str | None:
    """The word that matches one of the aliases, exactly or closely.

    Close matches only for names of 4+ letters, and never for a word that is in the English dictionary:
    a misheard name is a non-word like "siraia", while "surely" is just a word."""
    names = [alias.lower() for alias in aliases]
    for word in words(text):
        if word in names:
            return word
        if word in english_words() or len(word) < 3:
            continue
        for name in names:
            if len(name) >= 4 and SequenceMatcher(None, word, name).ratio() >= NAME_SIMILARITY:
                return word
    return None


def says_name(text: str, aliases: list[str]) -> bool:
    return matched_name(text, aliases) is not None


def with_real_name(text: str, aliases: list[str], display_name: str) -> str:
    """Speech-to-text wrote "Saria": put the user's real name back so the card and the classifier see it."""
    word = matched_name(text, aliases)
    if word is None or word == display_name.lower():
        return text
    return re.sub(rf"\b{re.escape(word)}\b", display_name, text, count=1, flags=re.IGNORECASE)


def is_handoff(text: str) -> bool:
    """'Surya, do you want to take that one?' passes the user a question somebody else asked a moment ago."""
    lowered = text.lower().replace("\u2019", "'")
    return any(phrase in lowered for phrase in HANDOFF_PHRASES)


def looks_like_question(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered.endswith("?") or any(phrase in lowered for phrase in QUESTION_PHRASES) or TAG_QUESTION.search(lowered):
        return True
    # A question word among the first three words: "Surya, what batch size ..."
    return any(word in QUESTION_WORDS for word in words(lowered)[:3])


def is_open_floor(text: str) -> bool:
    return bool(OPEN_FLOOR.search(text.strip()))


def refers_to_screen(text: str) -> bool:
    return bool(SCREEN_REFERENCE.search(text.replace("\u2019", "'")))


def mentions_you(text: str) -> bool:
    return bool(YOU_WORDS & set(words(text)))


def mentions_topic(text: str, topics: list[str]) -> bool:
    """A word of the text matches a word of a topic: "pipeline" matches the topic "data pipelines"."""
    topic_words = {w for topic in topics for w in words(topic) if len(w) >= 4}
    for word in words(text):
        for topic_word in topic_words:
            if word == topic_word or (len(word) >= 5 and len(topic_word) >= 5 and word[:5] == topic_word[:5]):
                return True
    return False


class RulesDetector:
    def __init__(self, aliases: list[str], topics: list[str], attention_window_s: float, after_you_spoke_window_s: float):
        self.aliases = aliases
        self.topics = topics
        self.attention_window_s = attention_window_s
        self.after_you_spoke_window_s = after_you_spoke_window_s
        self.one_on_one = False   # a meeting of two: every question from the other side is for the user

    def evaluate(self, text: str, now_s: float, you_spoke_at_s: float | None, attention_at_s: float | None,
                 started_s: float | None = None) -> Candidate:
        """All times are on the audio clock: now, when the user last finished speaking, when Attention was pressed,
        and when this sentence started (a long sentence must not fall out of the after-you-spoke window)."""
        score, reasons = 0.0, []
        if says_name(text, self.aliases):
            score += NAME_SCORE
            reasons.append("your name")
        if attention_at_s is not None and 0 <= now_s - attention_at_s <= self.attention_window_s:
            score += ATTENTION_SCORE
            reasons.append("attention")
        if looks_like_question(text):
            score += QUESTION_SCORE
            reasons.append("question")
        began_s = started_s if started_s is not None else now_s
        recently_spoke = you_spoke_at_s is not None and 0 <= began_s - you_spoke_at_s <= self.after_you_spoke_window_s
        question = looks_like_question(text)
        if recently_spoke and (mentions_you(text) or mentions_topic(text, self.topics)):
            score += AFTER_YOU_SPOKE_SCORE
            reasons.append("after you spoke")
        elif recently_spoke and question:
            score += FOLLOWS_YOUR_TURN_SCORE
            reasons.append("follows your turn")
        if mentions_topic(text, self.topics):
            score += TOPIC_SCORE
            reasons.append("your topic")
        if self.one_on_one and question:
            score = max(score, FIRE_AT)
            reasons.append("one-on-one")
        return Candidate(round(score, 2), reasons)
