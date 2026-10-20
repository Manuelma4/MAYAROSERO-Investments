from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(v: str | None) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime settings, read from environment variables (12-factor style)."""

    config_path: Path = field(default_factory=lambda: Path(os.environ.get("TRADEBOT_CONFIG", "config/config.yaml")))
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("TRADEBOT_DB", "data/tradebot.db")))
    static_dir: Path | None = field(default_factory=lambda: Path(p) if (p := os.environ.get("TRADEBOT_STATIC", "web/dist")) else None)
    api_token: str | None = field(default_factory=lambda: os.environ.get("TRADEBOT_API_TOKEN") or None)
    autostart_live: bool = field(default_factory=lambda: _bool(os.environ.get("TRADEBOT_AUTOSTART")))
    cors_origins: list[str] = field(default_factory=lambda: [
        o for o in os.environ.get("TRADEBOT_CORS", "http://localhost:5173").split(",") if o])
    precompute: bool = field(default_factory=lambda: _bool(os.environ.get("TRADEBOT_PRECOMPUTE", "1")))
    precompute_seconds: int = field(default_factory=lambda: int(os.environ.get("TRADEBOT_PRECOMPUTE_SECONDS", "1800")))
    cache_seconds: int = field(default_factory=lambda: int(os.environ.get("TRADEBOT_CACHE_SECONDS", "60")))

    def load_config(self) -> dict:
        import yaml

        path = self.config_path
        if not path.exists():
            path = Path("config/config.example.yaml")
        return yaml.safe_load(path.read_text()) if path.exists() else {}
