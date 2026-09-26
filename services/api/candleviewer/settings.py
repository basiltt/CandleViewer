"""Placeholder settings module.

Loads configuration from environment variables only (never from a checked-in
file), per `CONSTITUTION.md` C-12.9 and `.claude/rules/50-security.md`. This
is a minimal stub for E02-T02's canary test; the real settings surface
(secrets, per-environment host tables) is built out starting in E02-T05 /
E02-T08.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Root application settings, populated from the environment only."""

    model_config = SettingsConfigDict(
        env_prefix="CV_",
        extra="forbid",
        frozen=True,
    )

    environment: str = "dev"


def get_settings() -> Settings:
    """Return a fresh `Settings` instance built from the current environment."""
    return Settings()
