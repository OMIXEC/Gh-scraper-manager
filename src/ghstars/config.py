"""Configuration management via environment variables and settings file."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # GitHub
    github_token: Optional[str] = None
    github_username: Optional[str] = None

    # LLM Provider
    llm_provider: str = "openai"  # openai | anthropic | deepseek
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    deepseek_api_key: Optional[str] = None
    deepseek_model: str = "deepseek-v4-flash"

    # LLM enrichment settings
    enrich_batch_size: int = 10
    enrich_concurrency: int = 3

    # Data storage
    data_dir: Path = Path("data")
    db_path: Optional[Path] = None

    # Export
    default_export_dir: Path = Path("exports")

    # Embedding model for hybrid search
    embedding_model: str = "all-MiniLM-L6-v2"
    hf_token: Optional[str] = None

    @property
    def database_path(self) -> Path:
        if self.db_path:
            return self.db_path
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "stars.db"

    @property
    def llm_api_key(self) -> str:
        if self.llm_provider == "anthropic":
            key = self.anthropic_api_key
        elif self.llm_provider == "deepseek":
            key = self.deepseek_api_key
        else:
            key = self.openai_api_key
        if not key:
            raise ValueError(f"No API key found for LLM provider '{self.llm_provider}'")
        return key

    @property
    def llm_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        elif self.llm_provider == "deepseek":
            return self.deepseek_model
        return self.openai_model


settings = Settings()
