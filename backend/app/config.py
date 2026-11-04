"""All settings in one place.

Values come from environment variables or the .env file at the repo root (.env.example lists them all).
The adapter switches pick one adapter per interface. Model names live here and nowhere else.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Relative paths in settings (model files) are resolved against the repo root, whatever the working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Adapter switches: "local" for Phases 0 to 3, "aws" from Phase 4.
    stt_provider: str = "local"
    llm_provider: str = "local"
    embeddings_provider: str = "local"
    store_provider: str = "local"
    auth_provider: str = "local"
    vector_store_provider: str = "local"
    document_parser_provider: str = "local"

    # The service listens on localhost only.
    backend_host: str = "127.0.0.1"
    backend_port: int = 8080

    # Store
    dynamodb_endpoint: str = "http://localhost:8000"   # empty means real DynamoDB (Phase 4)
    aws_region: str = "us-east-1"
    table_prefix: str = "meetmind_"

    # Transcripts and cards expire after this many days. Audio is never stored at all.
    retention_days: int = 30

    # Test meetings that replay mode may play (the eval set, also the demo fallback).
    replay_dir: str = "eval/audio"

    # Documents: the vector store file and how text is cut into chunks before embedding.
    vector_db_path: str = "data/vectors.db"
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 150
    max_document_mb: int = 20

    # Audio is never written to disk unless this is on.
    debug_save_audio: bool = False

    # Ollama and the model slots
    meta_api_url: str = "https://api.meta.ai/v1"   # LLM_PROVIDER=meta, the Meta AI hackathon (decision 0008)
    meta_api_key: str = ""
    meta_reasoning_effort: str = "minimal"   # Muse Spark always reasons; minimal is the shortest pass
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_keep_alive: str = "30m"
    llm_classifier_model: str = "qwen3.5:4b-q4_K_M"
    llm_answer_model: str = "qwen3.5:9b-q4_K_M"
    llm_doubt_model: str = "qwen3.5:9b-q4_K_M"
    embeddings_model: str = "nomic-embed-text"

    # Speech-to-text
    stt_model: str = "mlx-community/whisper-small-mlx"
    stt_language: str = "en"
    vad_model_path: str = "models/stt/silero_vad.onnx"
    stt_partial_every_ms: int = 1000

    # Silence that ends a turn. Applied by the VAD inside the STT adapter, measured by the end-of-turn detector.
    turn_silence_ms: int = 600

    # Detector A windows, in seconds: how long an Attention press stays armed, and how long after the user
    # spoke a "you" or topic question still counts as aimed at them.
    attention_window_s: int = 15
    after_you_spoke_window_s: int = 10

    # Detector B keeps an alert only when the classifier is at least this sure.
    classifier_min_confidence: float = 0.5

    # Answer agent: how many document chunks to pull for a question, and the least similarity (0 to 1) that counts.
    retrieval_top_k: int = 4
    cache_hit_score: float = 0.75       # a prepared card is shown when a question matches it this closely (step P.4)
    retrieval_min_score: float = 0.45   # 0.60 kept general questions clean but cost weak document matches; see progress 2026-10-26

    # Claim checker: how much of the user's documents it reads whole, in characters (0 switches it off). The local
    # model's 32K-token context holds 40,000 characters with room for the rest; Muse Spark holds millions (decision 0009).
    claim_context_chars: int = 40000

    # Notes agent: how often the running notes are rewritten, in seconds of meeting audio.
    notes_every_s: int = 180

    def path(self, setting: str) -> Path:
        """A settings path as an absolute Path, relative ones taken from the repo root."""
        value = Path(getattr(self, setting))
        return value if value.is_absolute() else REPO_ROOT / value


settings = Settings()
