"""Contract every VectorStore adapter must pass."""

from uuid import uuid4

from app.ports import VectorStore


class VectorStoreContract:
    def make_adapter(self) -> VectorStore:
        raise NotImplementedError("the adapter test must build its adapter here")

    async def test_nearest_first_then_collection_deleted(self):
        store = self.make_adapter()
        collection = f"contract-{uuid4().hex}"
        await store.add(
            collection,
            ids=["x", "y", "z"],
            vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            metadata=[{"name": "x"}, {"name": "y"}, {"name": "z"}],
        )
        matches = await store.search(collection, [0.9, 0.1, 0.0], limit=2)
        assert [m.id for m in matches] == ["x", "y"]
        assert matches[0].score >= matches[1].score
        assert matches[0].metadata == {"name": "x"}

        await store.add(collection, ids=["x"], vectors=[[0.0, 0.0, 1.0]], metadata=[{"name": "x moved"}])
        matches = await store.search(collection, [0.0, 0.0, 1.0], limit=3)
        assert matches[0].id in ("x", "z") and len(matches) == 3, "adding an existing id must replace it, not duplicate it"

        await store.delete(collection, ["x", "never-existed"])
        assert {m.id for m in await store.search(collection, [0.0, 0.0, 1.0], limit=3)} == {"y", "z"}

        await store.delete_collection(collection)
        assert await store.search(collection, [1.0, 0.0, 0.0], limit=3) == []
