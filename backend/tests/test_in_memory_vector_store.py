from tests.contract.vector_store_contract import VectorStoreContract
from tests.fakes import InMemoryVectorStore


class TestInMemoryVectorStore(VectorStoreContract):
    def make_adapter(self):
        return InMemoryVectorStore()
