"""Builds the adapter each setting asks for. App logic calls these and never names an engine."""

from ..config import settings
from ..ports import LLM, Auth, DocumentParser, Embeddings, SpeechToText, Store, VectorStore

NOT_YET = "only 'local' exists until the AWS adapters arrive in Phase 4"


def make_speech_to_text() -> SpeechToText:
    if settings.stt_provider == "local":
        from .local.stt_mlx_whisper import MlxWhisperSpeechToText
        return MlxWhisperSpeechToText(
            model=settings.stt_model,
            language=settings.stt_language,
            vad_model_path=settings.path("vad_model_path"),
            silence_ms=settings.turn_silence_ms,
            partial_every_ms=settings.stt_partial_every_ms,
        )
    raise ValueError(f"STT_PROVIDER={settings.stt_provider!r}: {NOT_YET}")


def make_store() -> Store:
    if settings.store_provider == "local":
        from .local.store_dynamodb import DynamoDbStore
        return DynamoDbStore(settings.dynamodb_endpoint, settings.aws_region, settings.table_prefix)
    raise ValueError(f"STORE_PROVIDER={settings.store_provider!r}: {NOT_YET}")


def make_auth() -> Auth:
    if settings.auth_provider == "local":
        from .local.auth_local import LocalAuth
        return LocalAuth()
    raise ValueError(f"AUTH_PROVIDER={settings.auth_provider!r}: {NOT_YET}")


def make_llm() -> LLM:
    if settings.llm_provider == "local":
        from .local.llm_ollama import OllamaLLM
        return OllamaLLM(settings.ollama_url, settings.ollama_keep_alive)
    if settings.llm_provider == "meta":   # the Meta AI hackathon, decision 0008
        if not settings.meta_api_key:
            raise ValueError("LLM_PROVIDER=meta needs META_API_KEY in .env (create one at dev.meta.ai, API keys)")
        from .meta.llm_meta import MetaLLM
        return MetaLLM(settings.meta_api_url, settings.meta_api_key, settings.meta_reasoning_effort)
    raise ValueError(f"LLM_PROVIDER={settings.llm_provider!r}: use local or meta")


def make_embeddings() -> Embeddings:
    if settings.embeddings_provider == "local":
        from .local.embeddings_ollama import OllamaEmbeddings
        return OllamaEmbeddings(settings.ollama_url, settings.embeddings_model, settings.ollama_keep_alive)
    raise ValueError(f"EMBEDDINGS_PROVIDER={settings.embeddings_provider!r}: {NOT_YET}")


def make_vector_store() -> VectorStore:
    if settings.vector_store_provider == "local":
        from .local.vector_store_sqlite import SqliteVecStore
        return SqliteVecStore(settings.path("vector_db_path"))
    raise ValueError(f"VECTOR_STORE_PROVIDER={settings.vector_store_provider!r}: {NOT_YET}")


def make_document_parser() -> DocumentParser:
    if settings.document_parser_provider == "local":
        from .local.document_parser_local import LocalDocumentParser
        return LocalDocumentParser(settings.chunk_chars, settings.chunk_overlap_chars)
    raise ValueError(f"DOCUMENT_PARSER_PROVIDER={settings.document_parser_provider!r}: {NOT_YET}")
