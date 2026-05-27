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

    # Auth and project access
    auth_enabled: bool = False
    auth_bootstrap_admin_username: str = "admin"
    auth_bootstrap_admin_password: str = ""
    auth_bootstrap_admin_display_name: str = "Administrator"
    auth_bootstrap_project_key: str = "default"
    auth_bootstrap_project_name: str = "Default Project"

    # Secret store
    secret_store_master_key: str = ""
    secret_store_key_id: str = "local"

    # Delivery execution
    workspace_root: str = ""
    execution_worktree_root: str = ""
    execution_command_timeout_seconds: int = 120
    execution_codex_enabled: bool = False
    execution_codex_command_template: str = ""
    execution_codex_preflight_command: str = ""
    execution_codex_preflight_timeout_seconds: int = 30
    execution_codex_timeout_seconds: int = 1800
    execution_auto_repair_max_attempts: int = 1
    execution_max_concurrency: int = 1
    merge_request_default_target_branch: str = "main"

    # AI API (reserved)
    anthropic_api_key: str = ""
    ai_workflow_provider: str = "local"
    dify_api_base_url: str = ""
    dify_api_key: str = ""
    dify_spec_workflow_id: str = ""
    dify_impact_workflow_id: str = ""

    # CORS
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
    ]

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/app.log"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
