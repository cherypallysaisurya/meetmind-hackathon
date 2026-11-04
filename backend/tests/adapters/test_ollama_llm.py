"""The Ollama LLM adapter against the LLM contract, on the classifier model (Ollama must be running)."""

import socket
from urllib.parse import urlparse

import pytest

from app.adapters.local.llm_ollama import OllamaLLM
from app.config import settings
from tests.contract.llm_contract import LLMContract


def ollama_is_up() -> bool:
    url = urlparse(settings.ollama_url)
    try:
        socket.create_connection((url.hostname, url.port), timeout=0.5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not ollama_is_up(), reason="Ollama is not running: brew services start ollama")
class TestOllamaLLM(LLMContract):
    model = settings.llm_classifier_model if settings.llm_provider == "local" else "qwen3.5:4b-q4_K_M"

    def make_adapter(self):
        return OllamaLLM(settings.ollama_url, settings.ollama_keep_alive)   # Ollama itself, whatever LLM_PROVIDER says
