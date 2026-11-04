"""Contract every Embeddings adapter must pass."""

import math

from app.ports import Embeddings


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


class EmbeddingsContract:
    def make_adapter(self) -> Embeddings:
        raise NotImplementedError("the adapter test must build its adapter here")

    async def test_one_vector_per_text_all_the_same_length(self):
        vectors = await self.make_adapter().embed(["a short note", "another short note", "a third one"])
        assert len(vectors) == 3
        assert len(vectors[0]) > 0
        assert len({len(v) for v in vectors}) == 1

    async def test_similar_texts_are_closer_than_unrelated_ones(self):
        base, similar, unrelated = await self.make_adapter().embed([
            "What batch size did you use for the training run?",
            "Which batch size was used when you trained the model?",
            "The quarterly tax filing deadline moved to Friday.",
        ])
        assert cosine(base, similar) > cosine(base, unrelated)
