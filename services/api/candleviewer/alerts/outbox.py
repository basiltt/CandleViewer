"""Outbox topic constants and `dedup_key` rules for the alerts module (E40-T01).

`ux_outbox_dedup (topic, dedup_key)` makes the transactional outbox
exactly-once from the producer side (docs/plan/21-database-schema.md 3.10.4).
"""

from __future__ import annotations

TOPIC_ALERT_DELIVER = "alert.deliver"
TOPIC_WEBHOOK_POST = "webhook.post"
ALERT_OUTBOX_TOPICS: frozenset[str] = frozenset({TOPIC_ALERT_DELIVER, TOPIC_WEBHOOK_POST})


def alert_deliver_dedup_key(delivery_id: int) -> str:
    """One outbox row per delivery row, so replay is naturally idempotent."""
    return f"{delivery_id}"


def webhook_post_dedup_key(alert_id: str, fired_at_ms: int, attempt_group: int) -> str:
    """`{alert_id}:{fired_at_ms}:{attempt_group}`."""
    return f"{alert_id}:{fired_at_ms}:{attempt_group}"
