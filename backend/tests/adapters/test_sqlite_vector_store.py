import pytest

from app.adapters.local.vector_store_sqlite import SqliteVecStore
from tests.contract.vector_store_contract import VectorStoreContract


class TestSqliteVecStore(VectorStoreContract):
    @pytest.fixture(autouse=True)
    def fresh_file(self, tmp_path):
        self.path = tmp_path / "vectors.db"

    def make_adapter(self):
        return SqliteVecStore(self.path)


async def test_the_store_survives_reopening_and_refuses_other_sizes(tmp_path):
    path = tmp_path / "vectors.db"
    first = SqliteVecStore(path)
    await first.add("c", ["a"], [[1.0, 0.0, 0.0]], [{"n": 1}])
    reopened = SqliteVecStore(path)
    assert reopened.dimensions == 3
    assert (await reopened.search("c", [1.0, 0.0, 0.0], 1))[0].id == "a"
    with pytest.raises(ValueError):
        await reopened.add("c", ["b"], [[1.0, 0.0]], [{}])
