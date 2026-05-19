"""Application configuration management"""

from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "AI PJM Backend"
    app_version: str = "0.1.0"
    debug: bool = True
    environment: str = "development"

    # Server
    host: str = "0.0.0.0"
    port: int = 8010

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/ai_pjm_dev.db"
    database_echo: bool = False

    # Delivery execution
    workspace_root: str = ""
    execution_command_timeout_seconds: int = 120

    # AI API (reserved)
    anthropic_api_key: str = ""
    ai_workflow_provider: str = "mock"
    dify_api_base_url: str = ""
    dify_api_key: str = ""
    dify_spec_workflow_id: str = ""
    dify_impact_workflow_id: str = ""

    # CORS
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176"]

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/app.log"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
