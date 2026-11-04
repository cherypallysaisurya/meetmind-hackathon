"""The test stand-in must itself honor the Store contract, or the session tests prove nothing."""

from tests.contract.store_contract import StoreContract
from tests.fakes import InMemoryStore


class TestInMemoryStore(StoreContract):
    def make_adapter(self):
        return InMemoryStore()
