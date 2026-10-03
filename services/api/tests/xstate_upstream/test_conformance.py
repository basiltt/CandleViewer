"""Library-generic conformance tests for `xstate-statemachine` (E50-C01).

Deliberately imports NOTHING from `candleviewer` so the file can be dropped into
the upstream repository unchanged (see docs/plan/spikes/E50-C01.md). Covers the
patterns used by `tests/xstate_contract/`: both service spellings, snapshot
round-trip, version-floor and drift refusal, guard-denied events never bricking
the machine, and `strict_config` rejection of unknown keys.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    MachineLogic,
    MachineNode,
    SnapshotDriftError,
    SnapshotVersionError,
    create_machine,
)

CHART: dict[str, Any] = {
    "id": "conf",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy", "guard": "allowed"}}},
        "busy": {"invoke": {"src": "work", "onDone": {"target": "done", "actions": ["bump"]}}},
        "done": {"on": {"RESET": "idle"}},
    },
}


async def _bump(_i: Any, ctx: dict[str, Any], _e: Any, _a: Any) -> None:
    ctx["n"] += 1


def _async_work(_i: Any, _e: Any, _c: Any) -> Awaitable[int]:
    async def _run() -> int:
        return 1

    return _run()


async def _native_async_work(_i: Any, _e: Any, _c: Any) -> int:
    return 1


SPELLINGS: dict[str, Callable[..., Any]] = {
    "def_returning_coroutine": _async_work,
    "async_def": _native_async_work,
}


def _machine(
    work: Callable[..., Any], *, allow: bool = True, chart: dict[str, Any] | None = None
) -> MachineNode[Any]:
    logic: MachineLogic[Any] = MachineLogic(
        actions={"bump": _bump},
        guards={"allowed": lambda _c, _e: allow},
        services={"work": work},
    )
    return create_machine(chart or CHART, context_type=dict, logic=logic, strict_config=True)


def _blob(interp: Interpreter[Any]) -> str:
    """The persisted snapshot as the JSON string `from_snapshot` expects."""
    raw: Any = interp.get_persisted_snapshot()
    return raw if isinstance(raw, str) else json.dumps(raw)


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
async def test_service_spelling_reaches_done(spelling: str) -> None:
    interp = Interpreter(_machine(SPELLINGS[spelling]))
    await interp.start()
    await interp.send("GO")
    await _settle()
    assert interp.current_state_ids == {"conf.done"}
    assert interp.context == {"n": 1}
    await interp.stop()


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
async def test_snapshot_round_trip_is_identical(spelling: str) -> None:
    machine = _machine(SPELLINGS[spelling])
    interp = Interpreter(machine)
    await interp.start()
    await interp.send("GO")
    await _settle()
    blob = _blob(interp)
    await interp.stop()

    restored: Interpreter[Any] = Interpreter.from_snapshot(blob, machine, minimum_version=3)
    await restored.start()
    assert restored.current_state_ids == {"conf.done"}
    assert restored.context == {"n": 1}
    await restored.stop()


async def test_restore_below_minimum_version_is_refused() -> None:
    machine = _machine(_native_async_work)
    interp = Interpreter(machine)
    await interp.start()
    blob = _blob(interp)
    await interp.stop()
    with pytest.raises(SnapshotVersionError):
        Interpreter.from_snapshot(blob, machine, minimum_version=99)


async def test_restore_against_changed_machine_is_refused() -> None:
    machine = _machine(_native_async_work)
    interp = Interpreter(machine)
    await interp.start()
    blob = _blob(interp)
    await interp.stop()
    changed = json.loads(json.dumps(CHART))
    changed["states"]["done"]["on"]["EXTRA"] = "idle"
    with pytest.raises(SnapshotDriftError):
        Interpreter.from_snapshot(
            blob, _machine(_native_async_work, chart=changed), minimum_version=3
        )


async def test_guard_denied_event_does_not_brick_machine() -> None:
    interp = Interpreter(_machine(_native_async_work, allow=False))
    await interp.start()
    await interp.send("GO")
    await _settle()
    assert interp.current_state_ids == {"conf.idle"}
    await interp.send("GO")  # still accepts events afterwards
    assert interp.current_state_ids == {"conf.idle"}
    await interp.stop()


def test_strict_config_rejects_unknown_key() -> None:
    bad = json.loads(json.dumps(CHART))
    bad["states"]["idle"]["bogusKey"] = True
    with pytest.raises(InvalidConfigError):
        _machine(_native_async_work, chart=bad)
