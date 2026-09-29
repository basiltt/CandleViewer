"""bus module (M5).

In-process pub/sub, bounded queues, backpressure policies
(`docs/plan/20-architecture.md` §3 bus contract, §4.2 backpressure matrix).

Public interface: `Bus`, `Topic`, `TopicPattern`, `QueuePolicy`,
`StreamInvalidated`, and the errors below. Internal implementation modules
(`bus.py`, `metrics.py`) are not otherwise re-exported.

Allowed dependencies (CONSTITUTION.md C-3.1): M1.
"""

from __future__ import annotations

from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.errors import (
    BusError,
    BusNotStartedError,
    BusShuttingDownError,
    InvalidTopicError,
)
from candleviewer.bus.models import QueuePolicy, StreamInvalidated, Topic, TopicPattern

__all__ = [
    "Bus",
    "BusError",
    "BusNotStartedError",
    "BusShuttingDownError",
    "InvalidTopicError",
    "QueuePolicy",
    "StreamInvalidated",
    "Subscription",
    "Topic",
    "TopicPattern",
]
