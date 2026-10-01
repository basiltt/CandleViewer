"""Scheduler registration behind a flag, off by default in dev (E07-T05)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class _RetentionSettings(Protocol):
    retention_enabled: bool
    retention_cron: str
    export_cron: str
    compact_cron: str


@dataclass(frozen=True, slots=True)
class RetentionSchedule:
    enabled: bool
    retention_cron: str
    export_cron: str
    compact_cron: str

    @classmethod
    def from_settings(cls, settings: _RetentionSettings) -> RetentionSchedule:
        return cls(
            enabled=settings.retention_enabled,
            retention_cron=settings.retention_cron,
            export_cron=settings.export_cron,
            compact_cron=settings.compact_cron,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RetentionSchedule:
        """Build from an explicit mapping (never reads os.environ)."""
        return cls(
            enabled=env.get("CV_RETENTION_ENABLED", "false").lower() == "true",
            retention_cron=env.get("CV_RETENTION_CRON", "0 3 * * *"),
            export_cron=env.get("CV_EXPORT_CRON", "15 2 * * *"),
            compact_cron=env.get("CV_COMPACT_CRON", "0 3 * * 0"),
        )

    def jobs(self) -> dict[str, str]:
        """Cron per job name; empty when the feature flag is off."""
        if not self.enabled:
            return {}
        return {
            "export": self.export_cron,
            "retention": self.retention_cron,
            "compact": self.compact_cron,
        }
