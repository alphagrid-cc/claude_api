"""Konfiguration aus Environment / .env (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PermissionMode = str  # "default" | "acceptEdits" | "plan" | "bypassPermissions"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Gateway-Auth: Bearer, den externe Clients senden muessen.
    gateway_token: str = Field(default="", description="Bearer-Token fuer die eigene API")

    # Abo-Auth: wird per Environment an die Claude-Code-Binary durchgereicht.
    claude_code_oauth_token: str | None = None
    # Nur zur Erkennung: wenn gesetzt, warnen (Vorrang -> Token-Abrechnung).
    anthropic_api_key: str | None = None

    # Optionaler Pfad zu einer bestimmten `claude`-Binary. Leer = gebuendelte
    # SDK-Binary. Nuetzlich, um auf eine org-verwaltete CLI zu zeigen.
    claude_cli_path: str | None = None

    host: str = "0.0.0.0"
    port: int = 8000

    workspaces_dir: Path = Path("./workspaces")

    default_permission_mode: PermissionMode = "acceptEdits"
    default_model: str | None = None
    # low | medium | high | xhigh | max; leer = Default des Modells.
    default_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None

    session_ttl_seconds: int = 3600
    max_sessions: int = 20
    rate_limit_per_minute: int = 60

    def resolved_workspaces_dir(self) -> Path:
        p = self.workspaces_dir.expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
