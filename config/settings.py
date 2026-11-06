"""System Configuration and Environment Management."""

from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class AppSettings(BaseSettings):
    """Central Application Settings with Pydantic v2 validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Project metadata
    PROJECT_NAME: str = "MultiAgent-Software-Engineering"
    VERSION: str = "1.0.0"

    # LLM Settings
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key (optional)")
    DEFAULT_MODEL: str = "gemini-3.8-flash"
    TEMPERATURE: float = 0.2

    # GitHub Integration
    GITHUB_TOKEN: str = Field(default="", description="GitHub Personal Access Token for PR publishing")
    GITHUB_API_BASE_URL: str = Field(default="https://api.github.com", description="GitHub REST API Base URL")

    @field_validator("DEFAULT_MODEL", mode="before")
    @classmethod
    def normalize_model(cls, v: str) -> str:
        if v in ("gemini-2.0-flash", ""):
            return "gemini-3.8-flash"
        return v

    @field_validator("EXECUTION_MODE", mode="before")
    @classmethod
    def normalize_execution_mode(cls, v: str) -> str:
        if v in ("deterministic_simulation", "simulation", "mock"):
            return "deterministic_simulation"
        return "live"

    # Execution Mode: 'live' uses online API calls; 'deterministic_simulation' uses structured reproducible mocks
    EXECUTION_MODE: Literal["live", "deterministic_simulation"] = "live"

    # Paths (Resolved to absolute paths)
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    SANDBOX_ROOT: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "sandbox_workspace"
    )
    BLACKBOARD_PERSIST_PATH: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
        / "sandbox_workspace"
        / "blackboard_state.json"
    )
    EXPERIMENTS_DB_PATH: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
        / "sandbox_workspace"
        / "experiments.db"
    )

    # Human-In-The-Loop gatekeeper
    REQUIRE_HUMAN_APPROVAL: bool = True
    AUTO_APPROVE_IN_TESTS: bool = False

    # Security & Guardrails
    MAX_TOOL_TIMEOUT_SECONDS: int = 30
    ENABLE_PROMPT_INJECTION_CHECK: bool = True
    ENABLE_AST_SECURITY_SCAN: bool = True
    RESTRICT_FILE_OPERATIONS_TO_SANDBOX: bool = True

    # Observability
    LOG_LEVEL: str = "INFO"
    ENABLE_PROVENANCE_LOGGING: bool = True

    def ensure_directories(self) -> None:
        """Ensure necessary runtime directories exist."""
        self.SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        (self.SANDBOX_ROOT / "runs").mkdir(parents=True, exist_ok=True)
        (self.SANDBOX_ROOT / "sample_repo").mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = AppSettings()
settings.ensure_directories()

# Propagate securely to process environment for Google ADK and CrewAI SDKs without logging
if settings.GEMINI_API_KEY:
    import os
    os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
if settings.GITHUB_TOKEN:
    import os
    os.environ["GITHUB_TOKEN"] = settings.GITHUB_TOKEN

