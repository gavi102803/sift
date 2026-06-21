import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5432/sift"
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""
    model_explain: str = "sift-explain"
    model_curate: str = "sift-curate"
    model_fast: str = "sift-fast"


def load_settings() -> Settings:
    return Settings(
        env=os.getenv("SIFT_ENV", Settings.env),
        log_level=os.getenv("SIFT_LOG_LEVEL", Settings.log_level),
        database_url=os.getenv("SIFT_DATABASE_URL", Settings.database_url),
        litellm_base_url=os.getenv("SIFT_LITELLM_BASE_URL", Settings.litellm_base_url),
        litellm_api_key=os.getenv("SIFT_LITELLM_API_KEY", Settings.litellm_api_key),
        model_explain=os.getenv("SIFT_MODEL_EXPLAIN", Settings.model_explain),
        model_curate=os.getenv("SIFT_MODEL_CURATE", Settings.model_curate),
        model_fast=os.getenv("SIFT_MODEL_FAST", Settings.model_fast),
    )
