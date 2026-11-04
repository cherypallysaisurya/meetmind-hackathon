"""The notes agent keeps the meeting's memory: short running notes rewritten every minute or so from
the final turns, shown to the user and fed to the answer agent so cards know what was decided and said."""

import re

from ..ports import LLM, Message, Profile
from ..turns.end_of_turn import Turn

MAX_NOTES = 12

INSTRUCTIONS = (
    "You keep short running notes of a live meeting for one participant, the user. You get the notes so far "
    "and the new part of the transcript. Rewrite the notes: keep what still matters, add what is new, merge "
    "repeats, drop greetings and chit-chat. Record decisions, numbers, names, deadlines, open questions and who "
    "asked what. Never add anything that was not said. Output only the notes: at most 12 lines, each starting "
    "with '- ', each at most 15 words."
)


def parse_notes(text: str) -> list[str]:
    notes = []
    for line in text.split("\n"):
        line = line.strip()
        if line[:1] in "-•*":
            line = line[1:].strip()
        if line and not line.lower().startswith("notes"):
            notes.append(line)
    return notes[:MAX_NOTES]


class NotesAgent:
    def __init__(self, llm: LLM, model: str):
        self.llm = llm
        self.model = model

    def prompt(self, profile: Profile, notes: list[str], new_turns: list[Turn]) -> list[Message]:
        so_far = "\n".join(f"- {n}" for n in notes) or "(none yet)"
        transcript = "\n".join(f"{t.channel}: {t.text}" for t in new_turns if not t.echo) or "(nothing new)"
        context = (
            f"The user is {profile.display_name}, {profile.role or 'role not given'}. In the transcript, me is the user and them is everyone else.\n\n"
            f"NOTES SO FAR:\n{so_far}\n\nNEW TRANSCRIPT:\n{transcript}"
        )
        return [Message("system", INSTRUCTIONS), Message("user", context)]

    async def update(self, profile: Profile, notes: list[str], new_turns: list[Turn]) -> list[str]:
        text = "".join([piece async for piece in self.llm.stream(self.model, self.prompt(profile, notes, new_turns))])
        return parse_notes(text) or notes
