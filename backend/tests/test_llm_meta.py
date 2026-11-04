"""The Meta adapter's handling of the Model API's replies, on recorded shapes (no network)."""

import json

import httpx
import pytest

from app.adapters.meta.llm_meta import MetaLLM
from app.ports import Message

STREAM = "\n\n".join([
    'data: {"choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "The user asks for a fruit."}}]}',
    'data: {"choices": [{"index": 0, "delta": {"content": "ban"}}]}',
    'data: {"choices": [{"index": 0, "delta": {"reasoning_content": "Still thinking."}}]}',
    'data: {"choices": [{"index": 0, "delta": {"content": "ana"}, "finish_reason": "stop"}]}',
    'data: {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}',
    "data: [DONE]",
]) + "\n\n"


def adapter(handler) -> MetaLLM:
    return MetaLLM("https://api.meta.ai/v1", "test-key", transport=httpx.MockTransport(handler))


async def test_the_stream_yields_the_answer_and_skips_the_reasoning():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=STREAM, headers={"content-type": "text/event-stream"})

    pieces = [p async for p in adapter(handler).stream("muse-spark-1.3", [Message("user", "Say banana.")])]
    assert pieces == ["ban", "ana"]
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["stream"] is True and seen["body"]["reasoning_effort"] == "minimal"
    assert seen["body"]["messages"] == [{"role": "user", "content": "Say banana."}]


async def test_complete_json_asks_for_the_schema_and_parses_the_reply():
    seen = {}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": '{"ok": true}',
                                                                               "reasoning_content": "Easy."}}]})

    assert await adapter(handler).complete_json("muse-spark-1.3", [Message("user", "ok?")], schema) == {"ok": True}
    assert seen["body"]["response_format"] == {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
    assert seen["body"]["temperature"] == 0


async def test_an_api_error_names_the_status_and_the_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "No payment method on file."}})

    with pytest.raises(RuntimeError, match="402.*No payment method"):
        await adapter(handler).complete_json("muse-spark-1.3", [Message("user", "ok?")], {"type": "object"})
    with pytest.raises(RuntimeError, match="402"):
        [p async for p in adapter(handler).stream("muse-spark-1.3", [Message("user", "hi")])]
