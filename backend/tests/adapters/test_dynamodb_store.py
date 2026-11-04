"""The DynamoDB Store adapter against the Store contract, on DynamoDB Local (docker compose up -d)."""

import socket
from urllib.parse import urlparse

import pytest

from app.adapters.factory import make_store
from app.config import settings
from tests.contract.store_contract import StoreContract


def dynamodb_local_is_up() -> bool:
    url = urlparse(settings.dynamodb_endpoint)
    try:
        socket.create_connection((url.hostname, url.port), timeout=0.5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not dynamodb_local_is_up(), reason="DynamoDB Local is not running: docker compose up -d")
class TestDynamoDbStore(StoreContract):
    def make_adapter(self):
        return make_store()
