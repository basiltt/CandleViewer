"""Wires `ReadOnlyGate` transitions onto the `system` WS topic (E09-T04 AC3).

QA defect #1578 (blocker 1): `ReadOnlyGate.subscribe()` existed but had no
production caller, so a tripped gate never produced the "blocking banner...
on the `system` WS topic" the acceptance criteria and `23-ws-protocol.md`
§6 `system` require. This module is the one production subscriber: the
composition root (`candleviewer.app`) constructs it and calls
`read_only_gate.subscribe(publisher.on_change)` once, so every trip/clear —
from the boot check, the hourly re-check, or a manual test trip — publishes
a `system` topic event any connected client sees (every authenticated
connection is auto-subscribed to `system`, `23-ws-protocol.md` §6).

The payload matches the `system.schema.json` `notice`/`health` shape (§13-15
of the protocol doc): `kind="notice"`, `severity="critical"` while tripped,
the machine-readable `reason_code` and human `message`, so CMP-092
`DegradedModeBanner` can render icon+text (never colour alone, per
`05-accessibility-standard.md`) without any UI-side guessing.

This module owns no asyncio state of its own: `Bus.publish()` is a
coroutine, but `ReadOnlyGate` notifies listeners synchronously (outside its
lock) from whatever thread/task called `trip()`/`clear()` — which, for this
guard, is always the event loop (the scheduler's `_run_forever` task or the
lifespan's boot check), so scheduling `publish()` via
`asyncio.ensure_future` from the synchronous callback is safe here and never
blocks the gate's own state transition on a full `system` subscriber queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.observability.context import spawn

# nosemgrep: cv-obs-no-direct-getlogger -- legacy stdlib logger; migrate to cv.obs logger (#1716)
logger = logging.getLogger(__name__)

SYSTEM_TOPIC_DOMAIN = "system"


class SystemTopicPublisher:
    """Publishes `ReadOnlyGate` trip/clear transitions onto `{env}.system`.

    `env` is the deployment `Environment` value (`demo`/`live`/`testnet`,
    per `Topic`'s `{env}.{domain}...` contract) — the same value every other
    production publisher uses, so a `system` subscriber for this environment
    sees the banner alongside every other system notice.
    """

    def __init__(self, *, bus: Bus, env: str) -> None:
        self._bus = bus
        self._topic = Topic(env=env, domain=SYSTEM_TOPIC_DOMAIN)
        self._pending: set[asyncio.Task[None]] = set()

    def on_change(
        self, is_read_only: bool, reason_code: str | None, reason_text: str | None
    ) -> None:
        """`ReadOnlyGate` listener callback (see `ReadOnlyGate.subscribe`)."""
        default_message = (
            "Read-only mode: mesh binding is unsafe." if is_read_only else "Mesh binding is safe."
        )
        payload: dict[str, object] = {
            "kind": "notice",
            "severity": "critical" if is_read_only else "info",
            "message": reason_text or default_message,
            "reason_code": reason_code or "net.binding_safe",
            "read_only": is_read_only,
        }
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. a synchronous unit test driving the
            # gate directly outside asyncio) — nothing to schedule; the gate
            # state itself is still correct and is what OMS/the health
            # payload consult, so this is not fail-open for order placement.
            logger.debug(
                "net.system_topic: no running event loop; skipping system-topic publish "
                "for reason_code=%s",
                reason_code,
            )
            return
        # Kept referenced on `self._pending` (discarded on completion) so it
        # cannot be garbage-collected mid-flight — a bare `create_task()`
        # result with no reference is only a weak guarantee in CPython.
        task = spawn(self._publish(payload), name="system-topic-publish")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _publish(self, payload: dict[str, object]) -> None:
        try:
            await self._bus.publish(self._topic, payload)
        except Exception:
            # Publishing the banner must never be able to raise back into
            # the gate's trip()/clear() caller (mirrors ReadOnlyGate._notify
            # already isolating a misbehaving listener) — the gate's own
            # state is authoritative regardless of whether the banner made
            # it onto the bus this time.
            logger.exception(
                "net.system_topic: failed to publish read-only gate transition to %s",
                self._topic.key,
            )


def register_system_topic_subscriber(
    *, bus: Bus, env: str, read_only_gate: ReadOnlyGateLike
) -> SystemTopicPublisher:
    """Construct a `SystemTopicPublisher` and subscribe it to `read_only_gate`.

    Returned so the composition root can hold a reference (not strictly
    required — `ReadOnlyGate` holds the callback — but keeps the object
    inspectable in tests and avoids relying on GC timing for a bound method).
    """
    publisher = SystemTopicPublisher(bus=bus, env=env)
    read_only_gate.subscribe(publisher.on_change)
    return publisher


class ReadOnlyGateLike(Protocol):
    def subscribe(self, listener: Callable[[bool, str | None, str | None], None]) -> None: ...
