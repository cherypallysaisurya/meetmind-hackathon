"""Embeddings adapter on Ollama's /api/embed. One request per batch of texts."""

import httpx

from ...ports import Embeddings

BATCH = 32


class OllamaEmbeddings(Embeddings):
    def __init__(self, url: str, model: str, keep_alive: str):
        self.client = httpx.AsyncClient(base_url=url.rstrip("/"), timeout=httpx.Timeout(120.0, connect=5.0))
        self.model = model
        self.keep_alive = keep_alive

    async def embed(self, texts):
        vectors = []
        for start in range(0, len(texts), BATCH):
            response = await self.client.post("/api/embed", json={"model": self.model, "input": texts[start:start + BATCH], "keep_alive": self.keep_alive})
            response.raise_for_status()
            vectors += response.json()["embeddings"]
        return vectors
