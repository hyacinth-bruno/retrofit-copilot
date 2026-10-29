"""Application settings, read from environment variables or a .env file."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Also export .env into the process environment, so libraries that read os.environ
# directly (LangSmith, Langfuse, the Anthropic SDK) see the same keys.
# Variables that are already set win, so tests and CI can override them.
load_dotenv(REPO_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # LLM
    anthropic_api_key: str | None = None
    primary_model: str = "claude-sonnet-5-5"
    fallback_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2

    # Guardrails and budgets
    max_upload_mb: int = 10
    max_pdf_pages: int = 10
    max_run_cost_usd: float = 0.50
    max_agent_iterations: int = 6
    review_confidence_threshold: float = 0.7

    # Retrieval
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "retrofit_knowledge"
    embedding_backend: str = "fastembed"  # "fastembed" or "hash" (offline, for tests and CI)
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.02

    # Paths
    data_dir: Path = REPO_ROOT / "data"
    telemetry_db: Path = REPO_ROOT / "data" / "telemetry.db"
    eval_report_dir: Path = REPO_ROOT / "backend" / "evals" / "reports"

    # Optional external tracing
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    cors_origins: str = "http://localhost:3000"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
