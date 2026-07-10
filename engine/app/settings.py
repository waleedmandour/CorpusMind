"""
CorpusMind engine configuration.

All settings are environment-driven so the same code runs:
  - as a Tauri sidecar (localhost, single user)
  - as a self-hosted lab service (configurable host/port)
  - in CI / tests (overrides via env)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORPUSMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Process / network ---
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # --- Storage ---
    data_dir: Path = Field(default=Path.home() / ".corpusmind", description="Root for projects, indices, caches.")
    db_url: str = ""  # empty → defaults to sqlite under data_dir

    # --- Model providers (§11.4) ---
    # All off until first use; the desktop shell spawns Ollama on demand.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_default_model: str = "llama3.2:3b"
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_default_model: str = "local-model"
    cloud_provider: Literal["anthropic", "openai", "none"] = "none"
    cloud_api_key: str = ""
    cloud_default_model: str = ""
    cloud_base_url: str = ""  # override for proxies / Azure / Bedrock-compatible gateways

    # --- Smart Troubleshooting (Gemini) ---
    # Optional. When set, the /api/v1/troubleshoot/interpret endpoint uses
    # Google's Gemini API to interpret backend errors and suggest fixes.
    # The key is stored in the engine environment (never exposed to the
    # browser). Get a free key at https://aistudio.google.com/apikey.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # --- Reproducibility ---
    enable_methods_export: bool = True

    # --- Privacy / safety ---
    # If True, any request that would route to CloudProvider returns 403.
    # Belt-and-suspenders alongside the UI's cloud indicator (§7.5).
    cloud_disabled_hard: bool = False

    # --- CORS (for PWA running in browser pointed at a non-localhost engine) ---
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "tauri://localhost",
            "https://localhost",
        ]
    )

    @property
    def sqlite_url(self) -> str:
        if self.db_url:
            return self.db_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{self.data_dir / 'corpusmind.db'}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
