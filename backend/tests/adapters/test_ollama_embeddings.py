import pytest

from app.adapters.factory import make_embeddings
from tests.adapters.test_ollama_llm import ollama_is_up
from tests.contract.embeddings_contract import EmbeddingsContract


@pytest.mark.skipif(not ollama_is_up(), reason="Ollama is not running: brew services start ollama")
class TestOllamaEmbeddings(EmbeddingsContract):
    def make_adapter(self):
        return make_embeddings()
