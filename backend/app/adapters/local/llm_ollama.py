"""LLM adapter on Ollama: streaming chat and schema-bound JSON over its HTTP API on localhost.

Models that can "think" are told not to, so replies start at once. keep_alive keeps the weights
loaded between calls (a cold load costs seconds, see Step 0.2). Stopping the iteration of stream()
closes the HTTP response, which makes Ollama stop generating.
"""

import base64
import json
from typing import AsyncIterator

import httpx

from ...ports import LLM, Message


class OllamaLLM(LLM):
    def __init__(self, url: str, keep_alive: str):
        self.client = httpx.AsyncClient(base_url=url.rstrip("/"), timeout=httpx.Timeout(120.0, connect=5.0))
        self.keep_alive = keep_alive
        self.can_think: dict[str, bool] = {}

    async def _body(self, model: str, messages: list[Message], **extra) -> dict:
        if model not in self.can_think:
            shown = await self.client.post("/api/show", json={"model": model})
            shown.raise_for_status()
            self.can_think[model] = "thinking" in shown.json().get("capabilities", [])
        body = {
            "model": model,
            "messages": [self._message(m) for m in messages],
            "keep_alive": self.keep_alive,
            **extra,
        }
        if self.can_think[model]:
            body["think"] = False
        return body

    @staticmethod
    def _message(message: Message) -> dict:
        body = {"role": message.role, "content": message.content}
        if message.images:
            body["images"] = [base64.b64encode(image).decode() for image in message.images]
        return body

    async def stream(self, model: str, messages: list[Message]) -> AsyncIterator[str]:
        body = await self._body(model, messages, stream=True)
        async with self.client.stream("POST", "/api/chat", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    return

    async def complete_json(self, model: str, messages: list[Message], schema: dict) -> dict:
        body = await self._body(model, messages, stream=False, format=schema, options={"temperature": 0})
        response = await self.client.post("/api/chat", json=body)
        response.raise_for_status()
        return json.loads(response.json()["message"]["content"])
