"""Environment-backed application configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_name: str = "Requirements API"
    app_env: str = "development"
    log_level: str = "INFO"
    llm_model: str = "llama3.1:8b"
    api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"


def get_settings() -> Settings:
    """Load settings from environment variables."""
    return Settings(
        app_name=os.getenv("APP_NAME", "Requirements API"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        llm_model=os.getenv("LLM_MODEL", "llama3.1:8b"),
        api_key=os.getenv("OLLAMA_API_KEY") or os.getenv("OPENAI_API_KEY"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
