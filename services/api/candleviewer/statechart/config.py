"""candleviewer.statechart.config — E50-T59.

Static configuration for `factory.py`: the per-lane inbox bound, service
pool size, the shared start-timeout, and the (currently empty, populated by
future tickets) `CV_EVENT_SCHEMAS` map.

This module is deliberately data-only (29-statechart-adoption-plan.md §1.1)
so it can be imported anywhere — including `registry.py`, `tools/
lint_statecharts.py` and tests — without tripping CV-LINT-IMPORT (it never
imports `xstate_statemachine`).
"""

from __future__ import annotations

from typing import Any, Final, Literal

#: The three lanes every catalogue machine is assigned to
#: (29-statechart-adoption-plan.md §1.2, CV-C13). Order-path charts run on
#: a dedicated loop and never share one with the platform lane.
Lane = Literal["order", "control", "platform"]

LANES: Final[tuple[Lane, ...]] = ("order", "control", "platform")

#: `max_queue_size` per lane (`Interpreter(..., overflow_policy="refuse")`,
#: CV-C36). The order lane is deliberately the smallest bound: a full order
#: inbox must refuse fast (503 + page) rather than let latency-sensitive
#: commands queue behind a backlog. Control and platform lanes carry more
#: slack because their events are lower-frequency and idempotent-safe to
#: retry.
CV_INBOX_BOUND: Final[dict[Lane, int]] = {
    "order": 64,
    "control": 128,
    "platform": 256,
}

#: `service_pool_size` per lane (29-statechart-adoption-plan.md §1.2,
#: MUSTNOT-08: <=200 concurrent invoked children per process across every
#: lane combined — 32 + 8 + 16 = 56, well inside that ceiling per machine
#: instance).
CV_SERVICE_POOL: Final[dict[Lane, int]] = {
    "order": 32,
    "control": 8,
    "platform": 16,
}

#: `await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)` (CV-C56). A
#: timeout here is a hard startup failure, never a retry — this is the only
#: detector the wrapper has for the CV-C51 unsatisfiable-cycle hang.
CV_START_TIMEOUT: Final[float] = 5.0

#: `maxIterations` default sized against the descent plateau
#: (`limit + 3`, CV-C62); individual chart JSON may declare its own value
#: when the descent plateau requires it, but every chart must set the key
#: explicitly (`registry`/`schema.py` requires the field to be present).
CV_DEFAULT_MAX_ITERATIONS: Final[int] = 500

#: Snapshot envelope version floor (E50-T02, 28-statechart-catalogue.md
#: "Envelope version floor is 3 (v3 carries chain_trips)"). Every call to
#: `Interpreter.from_snapshot(..., minimum_version=SNAPSHOT_V)` and every
#: `seal(..., version=SNAPSHOT_V)` in `persistence.py` (E50-T10/T49) must
#: use this constant rather than a literal `3`, so a future envelope-floor
#: bump is a one-line change with every call site following automatically.
#: The upstream library's own `SNAPSHOT_VERSION` (currently 3 in 0.9.1) is
#: a *ceiling* on what this constant may be set to — `restore()` refuses a
#: newer-than-library version outright — but this project pins its own
#: floor independently so a future library bump does not silently lower
#: our accepted minimum.
SNAPSHOT_V: Final[int] = 3

#: Event-name -> JSON-Schema map passed to `Interpreter(event_schemas=...)`
#: (CV-C-strict unknown-event refusal). Populated per machine as B1-B20
#: land (E50-T02..T?? bindings tickets); empty here is valid — an empty
#: map plus `strict=True` still refuses every event, which is the correct,
#: safe default until a machine registers its own schemas via
#: `register_event_schemas()`.
CV_EVENT_SCHEMAS: dict[str, dict[str, Any]] = {}


def register_event_schemas(schemas: dict[str, dict[str, Any]]) -> None:
    """Merge *schemas* into the module-level `CV_EVENT_SCHEMAS` map.

    Called once per machine binding module at import time (`bindings/
    b01_order.py`, etc.) so the factory's `event_schemas=CV_EVENT_SCHEMAS`
    kwarg reflects every machine that has been imported so far. Raises on a
    colliding event name registered with a different schema, since that
    would silently change which chart's validation wins.
    """
    for name, schema in schemas.items():
        existing = CV_EVENT_SCHEMAS.get(name)
        if existing is not None and existing != schema:
            raise ValueError(
                f"event schema collision for '{name}': already registered with a different schema"
            )
        CV_EVENT_SCHEMAS[name] = schema
