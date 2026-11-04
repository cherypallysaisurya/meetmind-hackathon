"""The claim checker: do the user's own documents back a claim about their work, or contradict it?

Used when someone asks the user to agree with a statement about their work ("you're just querying the database
directly, right?") and when the user rehearses an answer before a meeting. In the first real call the nearest
pieces of the documents never reached the answer to that question (the deciding piece ranked 32nd of 66), so the
checker reads the documents whole, up to context_chars: Muse Spark reads a million tokens, the local 9B model 32
thousand. The pieces go in a fixed order, so the model's prompt cache keeps them between checks: on the local
model the first read takes about 35 s, each check after it 3 to 6 s. A verdict counts only when its quote really
is in the documents, word for word (decision 0009).
"""

import re
from dataclasses import dataclass

from ..ports import LLM, Embeddings, Message, VectorStore
from ..prep.documents import collection_for

MAX_PIECES = 4096       # sqlite-vec returns at most this many neighbours, far more than a document set has
MIN_QUOTE_WORDS = 4     # a quote of two or three words matches almost anything

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supports", "contradicts", "not_found"]},
        "quote": {"type": "string"},
        "line": {"type": "string"},
    },
    "required": ["verdict", "quote", "line"],
}

INSTRUCTIONS = (
    "You check a claim about the user's own work against the user's documents, the SOURCES. The claim may have "
    "several parts ('you are not doing A, you are doing B'); check each part. "
    "verdict 'contradicts': a source plainly says something that makes a part of the claim false. "
    "verdict 'supports': sources plainly say every part is true. "
    "verdict 'not_found': no source plainly settles it; when in doubt, not_found. "
    "quote: for supports or contradicts, the one sentence from a source that settles it, copied word for word. "
    "line: one sentence the user can say out loud in their own voice ('I', 'we'), at most 20 words: for contradicts, "
    "what is true instead; for supports, the confirmation. Empty quote and line for not_found."
)


@dataclass
class ClaimCheck:
    verdict: str            # supports, contradicts or not_found
    line: str = ""          # what the user can say: the correction or the confirmation
    quote: str = ""         # the words in the document that settle it
    document: str = ""
    location: str = ""
    text: str = ""          # the whole piece the quote is in


NOT_FOUND = ClaimCheck("not_found")


def plain(text: str) -> str:
    """Lower case letters and digits only, so a quote matches whatever its punctuation or line breaks."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()



class ClaimChecker:
    def __init__(self, llm: LLM, embeddings: Embeddings, vectors: VectorStore, model: str, context_chars: int):
        self.llm = llm
        self.embeddings = embeddings
        self.vectors = vectors
        self.model = model
        self.context_chars = context_chars

    async def pieces(self, user_id: str, claim: str) -> list[dict]:
        """The user's document pieces, nearest to the claim first until context_chars is full, then put back in
        document order so that, when everything fits, the prompt starts the same way for every claim."""
        vector = (await self.embeddings.embed([claim]))[0]
        chosen, size = [], 0
        for match in await self.vectors.search(collection_for(user_id), vector, MAX_PIECES):
            size += len(match.metadata["text"])
            if size > self.context_chars:
                break
            chosen.append(match.metadata)
        return sorted(chosen, key=lambda piece: (piece["document"], piece["index"]))

    def prompt(self, pieces: list[dict], claim: str) -> list[Message]:
        documents = "\n".join(f"{p['document']}, {p['location']}: \"{p['text']}\"" for p in pieces)
        return [Message("system", INSTRUCTIONS), Message("user", f"SOURCES:\n{documents}\n\nCLAIM: \"{claim}\"")]

    async def prime(self, user_id: str) -> None:
        """Read the documents once when a meeting starts, so the first real check pays only for its claim."""
        pieces = await self.pieces(user_id, "my work")
        if pieces:
            await self.llm.complete_json(self.model, self.prompt(pieces, ""), SCHEMA)

    async def check(self, user_id: str, claim: str) -> ClaimCheck:
        pieces = await self.pieces(user_id, claim)
        if not pieces:
            return NOT_FOUND
        reply = await self.llm.complete_json(self.model, self.prompt(pieces, claim), SCHEMA)
        verdict, quote, line = reply.get("verdict"), str(reply.get("quote", "")).strip(), str(reply.get("line", "")).strip()
        if verdict not in ("supports", "contradicts") or not line or len(plain(quote).split()) < MIN_QUOTE_WORDS:
            return NOT_FOUND
        # The model sometimes leaves words out with "...", even across two sections: every part must be in a document.
        parts = [plain(part) for part in re.split(r"\.\.\.|\u2026", quote) if plain(part)]
        homes = [next((piece for piece in pieces if part in plain(piece["text"])), None) for part in parts]
        if not parts or None in homes:
            return NOT_FOUND   # words in no document: the model misremembered them, so the user decides
        home = homes[max(range(len(parts)), key=lambda i: len(parts[i]))]   # the source of the longest part
        return ClaimCheck(verdict, line, quote, home["document"], home["location"], home["text"])
