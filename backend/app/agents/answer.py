"""The grounded answer agent: a cue card for a question just asked to the user.

Retrieve the most relevant chunks of the user's documents, then ask the answer model for plain lines:
the cue (one sentence to say out loud), dash points with [S1] style markers for the source each fact
came from, and a final confidence line. The card is built from the stream as it arrives, so the cue
line can be shown as soon as its newline comes in. Facts about the user's work may only come from the
sources and the profile; when they are not there, the card says "Not in your docs".
"""

import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from ..detect.rules import TAG_QUESTION, mentions_you
from ..ports import LLM, Embeddings, Match, Message, Profile, VectorStore
from ..turns.end_of_turn import Turn
from .claims import ClaimChecker

MAX_CUE_WORDS = 20
MAX_POINTS = 4   # the prompt asks for 2 to 4; a longer list cannot be read mid-sentence

INSTRUCTIONS = (
    "You sit next to the user in a live meeting. Someone just asked them a question. Write a cue card the "
    "user can read in two seconds and answer from.\n"
    "Format, plain text, nothing else:\n"
    "Line 1: 'CONFIDENCE: high', 'CONFIDENCE: medium' or 'CONFIDENCE: low'. Decide this first. High: the SOURCES answer "
    "a fact question directly. Medium: a reasoning question or a general knowledge question, answered from what you know "
    "and what the sources or the meeting say about the current setup. Low: only when the card rests on guesses, or a "
    "fact about the user's work is missing everywhere.\n"
    "Line 2: the cue, one natural sentence the user can say out loud, in the user's own voice ('I', 'we'), "
    "at most 20 words, no preamble.\n"
    "Then 2 to 4 lines starting with '- ': short cue points (a fact, a number, a name), at most 15 words each. "
    "Each point states something the user can say; never a point about where the facts come from. "
    "Every point that states something from the SOURCES must end with the marker of that source, like [S1]; "
    "a point may carry two markers. A point without a marker is read as general knowledge.\n"
    "SOURCES are the nearest pieces of the user's documents and may be unrelated. If a source answers the question, "
    "the answer comes from it, with its marker, and never contradicts it. Ignore sources that do not answer it.\n"
    "Rules. Three kinds of question. A general question is about technology or practice in general, not about the "
    "user's own work or results (for example 'Lambda or Fargate for an API?', 'how does RAG reduce hallucinations?'): "
    "when no source answers it, answer from your own knowledge as a senior engineer would, with a clear position in "
    "the cue and concrete points, marked with no source and at medium confidence; do not say 'Not in your docs'. The PROFILE is for speaking as the user and "
    "for questions about their own work; a general question gets a general answer, not one about their project. "
    "Never state what the user has or has not tried, used or built unless the SOURCES, PROFILE or transcript say so. "
    "A fact question asks what was done, measured or decided: a number, a date, "
    "a result. Such facts about the user's own work may come only from the SOURCES, the PROFILE and the transcript. "
    "Never invent them. A question that states something about the user's work and asks them to agree ('you're just "
    "doing X, right?') is a fact question: agree only if the SOURCES or the PROFILE say so, correct it if they say "
    "otherwise, and never agree because the speaker said it. If a fact question is about the user's work and nothing "
    "there has it, the cue says so plainly, "
    "starting with 'Not in your docs', and the points give what the user can still say. A reasoning question asks "
    "what would happen, whether something is worth it, why, or how two options compare: answer it. Take the current "
    "setup from the SOURCES (marked) and reason with what you know (unmarked). The cue is the position the user can "
    "state, for example what would change and what to test first. Never answer a reasoning question with "
    "'Not in your docs'. General knowledge questions may be answered from what you know, marked with no source. "
    "Use the recent transcript to understand what the question refers to; something another participant said in the "
    "meeting may be used as a point, without a marker. If the user already answered the question themselves (a 'me' "
    "line in the transcript), the cue repeats what they said; never contradict the user's own words, and never turn "
    "another participant's claim about the user's work into a fact. "
    "Names: write the user's name exactly as the PROFILE spells it."
)

SOURCE_MARKER = re.compile(r"\s*\[S(\d+)\]")
OTHER_TAG = re.compile(r"\s*\[[^\]]{1,40}\]")   # the model sometimes writes its own tags like [MEETING NOTES SO FAR]
LIST_NUMBER = re.compile(r"^\d+[.)]\s+")   # "1. " or "2) " in front of a point
# Only in the prompt when a picture goes with it, so the cached start of every other prompt stays the same.
SCREEN_NOTE = (
    "SCREEN: the attached picture is the user's screen when the question was asked; the question points at something "
    "on it (a chart, a slide, numbers). Answer about what it shows, with the numbers and labels you can read on it. "
    "The narrow MeetMind panel with cue cards is the user's own tool: ignore it.\n\n"
)
MAX_PREVIOUS_CARDS = 1
MAX_NOTES_IN_PROMPT = 8


@dataclass
class Source:
    number: int
    document: str
    location: str
    text: str
    score: float


@dataclass
class Point:
    text: str
    sources: list[int] = field(default_factory=list)   # source numbers this point cites


NOT_IN_DOCS = "not in your docs"


@dataclass
class Card:
    line: str | None = None
    points: list[Point] = field(default_factory=list)
    partial: str = ""                     # the line still being written
    confidence: str | None = None
    grounded: bool = True                 # at least one point cites one of the user's documents
    asks_to_agree: bool = False           # "you're doing X, right?": never a line to read out, see asks_to_agree()
    claim: str | None = None              # "supports" or "contradicts" once the claim checker found the deciding words
    screen: bool = False                  # the model saw a picture of the user's screen with the question

    @property
    def low_confidence(self) -> bool:
        return self.confidence == "low" or (self.asks_to_agree and not self.claim)

    @property
    def not_in_docs(self) -> bool:
        return bool(self.line) and self.line.lower().startswith(NOT_IN_DOCS)

    def snapshot(self) -> dict:
        """What the client may show. At low confidence the cue line is withheld: key points only, never a
        confident-sounding sentence. Until the confidence is known, the line is withheld too."""
        show_line = self.confidence is not None and not self.low_confidence
        return {
            "line": self.line if show_line else None,
            "points": [{"text": p.text, "sources": p.sources} for p in self.points],
            "partial": self.partial,
            "confidence": self.confidence,
            "tags": {"low_confidence": self.low_confidence, "not_in_docs": self.not_in_docs, "ungrounded": not self.grounded,
                     "asks_to_agree": self.asks_to_agree, "claim": self.claim, "screen": self.screen},
        }


def split_markers(text: str) -> tuple[str, list[int]]:
    numbers = [int(n) for n in SOURCE_MARKER.findall(text)]
    cleaned = OTHER_TAG.sub("", SOURCE_MARKER.sub("", text)).strip()
    return cleaned, sorted(set(numbers))


def has_words(text: str) -> bool:
    return re.search(r"[A-Za-z]", text) is not None


class CardBuilder:
    """Feeds the model's stream into a Card, one complete line at a time."""

    def __init__(self):
        self.card = Card()
        self.buffer = ""

    def feed(self, piece: str) -> bool:
        """Returns True when the card changed in a way worth sending."""
        self.buffer += piece
        changed = False
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            changed = self._take_line(line) or changed
        partial = self.buffer.strip().lstrip("-").strip()
        confidence_coming = "CONFIDENCE".startswith(partial.upper()[:10]) or partial.upper().startswith("CONFIDENCE")
        if self.card.line is not None and not confidence_coming and partial != self.card.partial:
            self.card.partial = partial
            changed = True
        return changed

    def finish(self) -> Card:
        if self.buffer.strip():
            self._take_line(self.buffer)
        self.buffer = ""
        self.card.partial = ""
        self._split_crowded_cue()
        return self.card

    def _split_crowded_cue(self) -> None:
        """The model sometimes writes the whole card as one line. Keep the first sentence as the cue, the rest become points."""
        if self.card.points or not self.card.line:
            return
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", self.card.line) if s.strip()]
        if len(sentences) >= 2:
            self.card.line = sentences[0]
            self.card.points = [Point(s) for s in sentences[1:5] if has_words(s)]

    def _take_line(self, raw: str) -> bool:
        line = raw.strip()
        if not line:
            return False
        if line.upper().startswith("CONFIDENCE"):
            level = line.split(":", 1)[-1].strip().lower()
            self.card.confidence = level if level in ("high", "medium", "low") else "low"
            return True
        text, sources = split_markers(line.lstrip("-\u2022*").strip())
        if not text:
            return False
        if self.card.line is None:
            self.card.line = text.strip('"\u201c\u201d\'')   # the model sometimes quotes the cue
        else:
            text = LIST_NUMBER.sub("", text)
            if not has_words(text) or len(self.card.points) >= MAX_POINTS:
                return False   # a stray list number like "2" is not a point; a fifth point is dropped
            self.card.points.append(Point(text, sources))
        self.card.partial = ""
        return True


OnUpdate = Callable[[dict], Awaitable[None]]


def asks_to_agree(question: str) -> bool:
    """'You're just querying the database directly, right?': the speaker states something about the user's work
    and asks them to agree. In the first real meeting and five tries after it, the 9B model answered this kind of
    question wrongly every time, agreeing or disagreeing at random and once citing a source that said neither. The
    user knows what they did; the card gives points under a warning and never a line to read out, unless the claim
    checker finds the words in the user's documents that settle it."""
    return bool(TAG_QUESTION.search(question.lower())) and mentions_you(question)


DISTINCTIVE = re.compile(r"\d+(?:\.\d+)?|[a-z]{6,}")


def attribute_unmarked_points(card: Card, sources: list[Source]) -> None:
    """The model sometimes forgets its markers. A point that shares a number or a long word with exactly the
    text of a source is attributed to it, so the card still shows where the fact came from."""
    tokens = {s.number: set(DISTINCTIVE.findall(s.text.lower())) for s in sources}
    for point in card.points:
        if point.sources or not sources:
            continue
        words = set(DISTINCTIVE.findall(point.text.lower()))
        best = max(sources, key=lambda s: len(words & tokens[s.number]), default=None)
        shared = words & tokens[best.number] if best else set()
        # A shared number is strong evidence; otherwise two distinctive words are needed, one is coincidence.
        if any(ch.isdigit() for w in shared for ch in w) or len(shared) >= 2:
            point.sources = [best.number]


class AnswerAgent:
    def __init__(self, llm: LLM, embeddings: Embeddings, vectors: VectorStore, model: str, top_k: int, min_score: float,
                 checker: ClaimChecker | None = None):
        self.llm = llm
        self.embeddings = embeddings
        self.vectors = vectors
        self.model = model
        self.top_k = top_k
        self.min_score = min_score
        self.checker = checker   # settles "you're doing X, right?" from the documents; None when it is switched off

    async def retrieve(self, user_id: str, question: str) -> list[Source]:
        vector = (await self.embeddings.embed([question]))[0]
        matches: list[Match] = await self.vectors.search(f"docs:{user_id}", vector, self.top_k)
        return [
            Source(number, m.metadata["document"], m.metadata["location"], m.metadata["text"], m.score)
            for number, m in enumerate((m for m in matches if m.score >= self.min_score), start=1)
        ]

    @staticmethod
    def profile_block(profile: Profile) -> str:
        """The stable start of every prompt. Identical across questions, so the model's cache keeps it."""
        return (
            f"PROFILE: {profile.display_name}, {profile.role or 'role not given'}. Topics: {', '.join(profile.topics) or 'not given'}. "
            f"About: {profile.bio or 'not given'}. Current projects: {profile.current_projects or 'not given'}\n\n"
        )

    def prompt(self, profile: Profile, question: str, sources: list[Source], recent: list[Turn],
               notes: list[str] = (), previous_cards: list[dict] = (), screen: bytes | None = None) -> list[Message]:
        source_lines = "\n".join(f"[S{s.number}] {s.document}, {s.location}: \"{s.text}\"" for s in sources) or "(no relevant documents)"
        transcript = "\n".join(f"{t.channel}: {t.text}" for t in recent if not t.echo) or "(nothing yet)"
        notes_block = "\n".join(f"- {n}" for n in list(notes)[-MAX_NOTES_IN_PROMPT:]) or "(none yet)"
        cards_block = "\n".join(
            f"Q: {c['question']}\nA: {c['line']}" + "".join(f"\n- {p}" for p in c["points"]) for c in list(previous_cards)[-MAX_PREVIOUS_CARDS:]
        ) or "(none yet)"
        context = (
            self.profile_block(profile)
            + f"SOURCES (nearest pieces of the user's documents, may be unrelated):\n{source_lines}\n\n"
            + f"MEETING NOTES SO FAR:\n{notes_block}\n\n"
            + f"PREVIOUS CARDS IN THIS MEETING (a follow-up question builds on these):\n{cards_block}\n\n"
            + f"RECENT TRANSCRIPT (me is the user, them is everyone else):\n{transcript}\n\n"
            + (SCREEN_NOTE if screen else "")
            + f"QUESTION TO THE USER: \"{question}\""
        )
        return [Message("system", INSTRUCTIONS), Message("user", context, [screen] if screen else [])]

    async def prime(self, profile: Profile) -> None:
        """Read the stable prefix once so the first real question only pays for its own tokens."""
        async for _ in self.llm.stream(self.model, [Message("system", INSTRUCTIONS), Message("user", self.profile_block(profile))]):
            break

    async def answer(self, user_id: str, profile: Profile, question: str, recent: list[Turn], on_update: OnUpdate,
                     notes: list[str] = (), previous_cards: list[dict] = (), use_documents: bool = True,
                     screen: bytes | None = None) -> tuple[Card, list[Source]]:
        """Retrieve, then stream the card. on_update gets a snapshot whenever the card changes. With use_documents
        off (a talk where the user's documents do not apply), the card is the model's own answer. A claim about the
        user's work is checked against the whole documents once the card is on screen; a verdict replaces the card."""
        sources = await self.retrieve(user_id, question) if use_documents else []
        builder = CardBuilder()
        builder.card.asks_to_agree = asks_to_agree(question)
        builder.card.screen = screen is not None
        async for piece in self.llm.stream(self.model, self.prompt(profile, question, sources, recent, notes, previous_cards, screen)):
            if builder.feed(piece):
                await on_update(builder.card.snapshot())
        card = builder.finish()
        known = {s.number for s in sources}
        for point in card.points:
            point.sources = [n for n in point.sources if n in known]   # a marker for a source that was never given
        attribute_unmarked_points(card, sources)
        card.grounded = bool(sources) and any(point.sources for point in card.points)
        if not card.grounded and card.confidence == "high":
            card.confidence = "medium"   # nothing from the user's documents backs this; never call it certain
        if card.asks_to_agree:
            card.confidence = "low"
        if card.confidence is None:
            card.confidence = "low"
        if card.asks_to_agree and use_documents and self.checker:
            await on_update(card.snapshot())   # "Your call" stays on screen while the documents are read
            sources = await self.settle_claim(card, user_id, question, sources)
        return card, sources

    async def settle_claim(self, card: Card, user_id: str, question: str, sources: list[Source]) -> list[Source]:
        """The card says what the documents say: the correction or the confirmation, and the deciding words with their source."""
        assert self.checker
        check = await self.checker.check(user_id, question)
        if check.verdict == "not_found":
            return sources
        source = Source(len(sources) + 1, check.document, check.location, check.text, 1.0)
        card.claim, card.line, card.confidence, card.grounded = check.verdict, check.line, "high", True
        card.points = [Point(check.quote, [source.number])]
        return [*sources, source]
