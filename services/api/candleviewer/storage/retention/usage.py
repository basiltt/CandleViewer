"""Internal `StorageUsage` payload (shape = OpenAPI `StorageUsage`; endpoint is E16/E42)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def build_storage_usage(
    *,
    total: int,
    used: int,
    daily_growth: int,
    tiers: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    free = total - used
    projected = (at + timedelta(days=free / daily_growth)).isoformat() if daily_growth > 0 else None
    return {
        "disk_total_bytes": total,
        "disk_used_bytes": used,
        "disk_free_bytes": free,
        "projected_full_at": projected,
        "daily_growth_bytes": daily_growth,
        "tiers": tiers,
        "symbols": symbols,
        "generated_at": at.isoformat(),
    }
