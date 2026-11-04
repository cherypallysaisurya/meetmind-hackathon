"""The Meta Model API adapter against the LLM contract, on the real API (needs META_API_KEY in .env)."""

import pytest

from app.adapters.meta.llm_meta import MetaLLM
from app.config import settings
from tests.contract.llm_contract import LLMContract


@pytest.mark.skipif(not settings.meta_api_key, reason="META_API_KEY is not set in .env")
class TestMetaLLM(LLMContract):
    model = "muse-spark-1.3"

    def make_adapter(self):
        return MetaLLM(settings.meta_api_url, settings.meta_api_key, settings.meta_reasoning_effort)
