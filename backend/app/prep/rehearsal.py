"""Rehearsal before a meeting (decision 0009): the app asks a predicted question out loud, the user answers, and
their answer comes back as a card in their own words, checked against their documents.

The recording arrives as the same 16 kHz stereo frames a live meeting sends (the user on the left channel) and goes
through the same SpeechToText port, in memory; audio is never written anywhere. The check is the claim checker's:
the user's answer is a claim about their own work.
"""

import asyncio
from dataclasses import dataclass

from ..agents.claims import NOT_FOUND, ClaimCheck, ClaimChecker
from ..audio.frames import FRAME_BYTES
from ..ports import LLM, ME, Message, Profile, SpeechToText

MAX_POINTS = 3

SCHEMA = {
    "type": "object",
    "properties": {"line": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["line", "points"],
}

INSTRUCTIONS = (
    "The user rehearsed out loud the answer to a question they expect in a meeting. Turn their answer into a cue card "
    "in their own words. line: one sentence they can say, at most 25 words, keeping their wording and only dropping "
    "filler words and false starts. points: 2 or 3 short points, at most 15 words each, taken from what they said. "
    "Add nothing they did not say, and do not correct them."
)


@dataclass
class Rehearsed:
    heard: str              # what the user said, as transcribed
    line: str               # their answer as one sentence to say
    points: list[str]
    check: ClaimCheck       # what their documents say about it


async def transcribe(stt: SpeechToText, audio: bytes) -> str:
    """The user's words in a recording of frames, through the same SpeechToText port as a live meeting."""
    heard: list[str] = []

    async def collect() -> None:
        async for transcript in stt.transcripts():
            if transcript.channel == ME and not transcript.is_partial:
                heard.append(transcript.text)

    await stt.start()
    reader = asyncio.create_task(collect())
    for start in range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES):
        await stt.feed(audio[start:start + FRAME_BYTES])
    await stt.stop()
    await reader
    return " ".join(heard).strip()


class Rehearsal:
    def __init__(self, llm: LLM, model: str, checker: ClaimChecker | None):
        self.llm = llm
        self.model = model
        self.checker = checker

    async def in_own_words(self, profile: Profile, question: str, answer: str) -> tuple[str, list[str]]:
        context = f"The user is {profile.display_name}, {profile.role or 'role not given'}.\n\nQUESTION: \"{question}\"\n\nTHEIR ANSWER: \"{answer}\""
        reply = await self.llm.complete_json(self.model, [Message("system", INSTRUCTIONS), Message("user", context)], SCHEMA)
        points = [str(p).strip() for p in reply.get("points", []) if str(p).strip()][:MAX_POINTS]
        return str(reply.get("line", "")).strip() or answer, points

    async def check(self, user_id: str, answer: str) -> ClaimCheck:
        return await self.checker.check(user_id, answer) if self.checker else NOT_FOUND

    async def review(self, user_id: str, profile: Profile, question: str, answer: str) -> Rehearsed:
        """The card from the user's words and the check of those words against their documents, side by side."""
        (line, points), check = await asyncio.gather(self.in_own_words(profile, question, answer), self.check(user_id, answer))
        return Rehearsed(answer, line, points, check)
