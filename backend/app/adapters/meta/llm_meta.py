"""LLM adapter on Meta's Model API (Muse Spark), for the Meta AI hackathon (decision 0008).

Chat Completions at https://api.meta.ai/v1/chat/completions, OpenAI-compatible, bearer key. Muse Spark always
reasons before it answers and the reasoning cannot be switched off; "minimal" is the shortest pass, which a live
meeting needs. The reasoning streams in delta.reasoning_content and is skipped: only delta.content reaches the card.
Strict JSON uses response_format json_schema, as the classifier and the predictor expect. A picture goes with a
message as an image_url part holding a base64 data URL.
"""

import base64
import json
from typing import AsyncIterator

import httpx

from ...ports import LLM, Message


class MetaLLM(LLM):
    def __init__(self, base_url: str, api_key: str, reasoning_effort: str = "minimal", transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=httpx.Timeout(120.0, connect=10.0),
            headers={"Authorization": f"Bearer {api_key}"}, transport=transport,
        )
        self.reasoning_effort = reasoning_effort

    def _body(self, model: str, messages: list[Message], **extra) -> dict:
        return {
            "model": model,
            "messages": [self._message(m) for m in messages],
            "reasoning_effort": self.reasoning_effort,
            **extra,
        }

    @staticmethod
    def _message(message: Message) -> dict:
        if not message.images:
            return {"role": message.role, "content": message.content}
        pictures = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}}
                    for image in message.images]
        return {"role": message.role, "content": [{"type": "text", "text": message.content}, *pictures]}

    @staticmethod
    def _check(response: httpx.Response, body: bytes) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"Meta Model API {response.status_code}: {body.decode(errors='replace')[:300]}")

    async def stream(self, model: str, messages: list[Message]) -> AsyncIterator[str]:
        async with self.client.stream("POST", "/chat/completions", json=self._body(model, messages, stream=True)) as response:
            if response.status_code >= 400:
                self._check(response, await response.aread())
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                for choice in json.loads(data).get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece

    async def complete_json(self, model: str, messages: list[Message], schema: dict) -> dict:
        body = self._body(model, messages, temperature=0,
                          response_format={"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}})
        response = await self.client.post("/chat/completions", json=body)
        self._check(response, response.content)
        return json.loads(response.json()["choices"][0]["message"]["content"])
