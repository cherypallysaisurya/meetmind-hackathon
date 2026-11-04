"""Checks on the port definitions themselves. Adapter behavior is covered by the contract tests."""

import pytest

from app.ports import LLM, Auth, DocumentParser, Embeddings, SpeechToText, Store, VectorStore
from tests.contract.auth_contract import AuthContract
from tests.contract.document_parser_contract import DocumentParserContract
from tests.contract.embeddings_contract import EmbeddingsContract
from tests.contract.llm_contract import LLMContract
from tests.contract.speech_to_text_contract import SpeechToTextContract
from tests.contract.store_contract import StoreContract
from tests.contract.vector_store_contract import VectorStoreContract

PORTS_AND_CONTRACTS = [
    (SpeechToText, SpeechToTextContract),
    (LLM, LLMContract),
    (Embeddings, EmbeddingsContract),
    (Store, StoreContract),
    (Auth, AuthContract),
    (DocumentParser, DocumentParserContract),
    (VectorStore, VectorStoreContract),
]


@pytest.mark.parametrize("port,_", PORTS_AND_CONTRACTS, ids=lambda p: getattr(p, "__name__", ""))
def test_port_cannot_be_used_without_an_adapter(port, _):
    with pytest.raises(TypeError):
        port()


@pytest.mark.parametrize("port,contract", PORTS_AND_CONTRACTS, ids=lambda p: getattr(p, "__name__", ""))
def test_port_has_a_contract_with_tests(port, contract):
    test_methods = [name for name in dir(contract) if name.startswith("test_")]
    assert test_methods, f"{contract.__name__} has no tests"
    assert hasattr(contract, "make_adapter")
