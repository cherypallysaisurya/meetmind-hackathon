"""Contract every LLM adapter must pass. The subclass sets `model` to a model name from config."""

from app.ports import LLM, Message

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "is_question": {"type": "boolean"},
        "topic": {"type": "string", "enum": ["fruit", "weather", "other"]},
    },
    "required": ["is_question", "topic"],
}


class LLMContract:
    model = ""

    def make_adapter(self) -> LLM:
        raise NotImplementedError("the adapter test must build its adapter here")

    async def test_stream_yields_pieces_that_follow_the_instruction(self):
        llm = self.make_adapter()
        prompt = [Message("user", "Reply with exactly the word banana and nothing else.")]
        pieces = [piece async for piece in llm.stream(self.model, prompt)]
        assert pieces, "the stream yielded nothing"
        assert "banana" in "".join(pieces).lower()

    async def test_complete_json_follows_the_schema(self):
        llm = self.make_adapter()
        prompt = [Message("user", "Someone said: 'do you like apples?'. Is that a question, and what is its topic?")]
        result = await llm.complete_json(self.model, prompt, CLASSIFIER_SCHEMA)
        assert result["is_question"] is True
        assert result["topic"] in ("fruit", "weather", "other")
