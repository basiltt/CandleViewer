"""tests/xstate_contract/test_b10_b20_kill_fallthrough.py — E50-S02 golden traces.

Catalogue *Corrected 2026-10-01* arms (C-04 / C-07b class):

* root `KILL` from every invoking state lands in the chart's existing
  terminal/halted state and writes exactly one `audit_kill` record;
* a guard-denied event takes the ordered unguarded auditing arm —
  the machine stays in the same state, is not errored, and audits once.

Construction goes through `cv.statechart.factory.build()` only. To park the
machine inside an invoking state, a derived copy of the committed chart is
written to `tmp_path` with `initial` pointed at that state (arms untouched)
and the chart's services are replaced by a never-completing coroutine.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from xstate_statemachine import SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.config import Lane
from candleviewer.statechart.registry import Registry

# chart key -> (binding module, KILL terminal/halted leaf id)
KILL_CHARTS: dict[str, tuple[str, str]] = {
    "alert": ("b10_alert", "alert.disabled"),
    "recording": ("b11_recording", "recording.error"),
    "replay": ("b12_replay", "replay.error"),
    "ws_conn": ("b13_ws_conn", "ws_conn.closed"),
    "kill_switch": ("b18_kill_switch", "kill_switch.engaged_incomplete"),
    "reconciliation": ("b19_reconciliation", "reconciliation.stale_lockout"),
}

BINDING: dict[str, str] = {
    **{k: v[0] for k, v in KILL_CHARTS.items()},
    "paper_account": "b15_paper_account",
    "live_gate": "b17_live_gate",
}

# (chart, state path, denied event, audit action) — fall-through arms (2026-10-01).
FALLTHROUGH_ARMS: tuple[tuple[str, str, str, str], ...] = (
    ("paper_account", "active", "MARK_UPDATE", "note_mark_no_change"),
    ("paper_account", "margin_call", "MARK_UPDATE", "note_mark_no_change"),
    ("live_gate", "enabled", "DISABLE_REQUESTED", "audit_disable_denied"),
    ("kill_switch", "engaged", "RELEASE", "audit_release_denied"),
    ("kill_switch", "engaged_incomplete", "RELEASE", "audit_release_denied"),
)

_CONTROL = {"kill_switch", "live_gate"}


def _lane(key: str) -> Lane:
    return "control" if key in _CONTROL else "platform"


def _walk(node: dict[str, Any], prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for name, child in (node.get("states") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        out.append((path, child))
        out.extend(_walk(child, path))
    return out


def _invoking_states() -> list[tuple[str, str]]:
    reg = Registry()
    return [
        (key, path)
        for key in KILL_CHARTS
        for path, node in _walk(reg.get(key))
        if node.get("invoke")
    ]


def _derive(key: str, path: str, tmp_path: Path) -> Registry:
    """Copy the committed chart with `initial` re-pointed at *path* only."""
    chart = copy.deepcopy(Registry().get(key))
    node: dict[str, Any] = chart
    for part in path.split("."):
        node["initial"] = part
        node = node["states"][part]
    (tmp_path / f"{key}.machine.json").write_text(json.dumps(chart), encoding="utf-8")
    return Registry(machines_dir=tmp_path)


def _instrument(key: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    module = importlib.import_module(f"candleviewer.statechart.bindings.{BINDING[key]}")
    calls = {"audit_kill": 0, "note_mark_no_change": 0, "audit_disable_denied": 0}
    calls["audit_release_denied"] = 0

    def _recorder(name: str) -> Any:
        async def _record(*_a: object, **_k: object) -> None:
            calls[name] += 1

        return _record

    async def _hang(*_a: object, **_k: object) -> None:
        await asyncio.Event().wait()

    for name in calls:
        if name in module.ACTIONS:
            monkeypatch.setitem(module.ACTIONS, name, _recorder(name))
    for svc in list(module.SERVICES):
        monkeypatch.setitem(module.SERVICES, svc, _hang)
    return calls


@pytest.mark.parametrize(("key", "path"), _invoking_states())
async def test_kill_from_invoking_state_lands_terminal_and_audits(
    key: str, path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _instrument(key, monkeypatch)
    registry = _derive(key, path, tmp_path)
    result = await build(key, clock=SimulatedClock(), lane=_lane(key), registry=registry)
    interp = result.interpreter
    try:
        assert f"{key}.{path}" in interp.current_state_ids
        await interp.send("KILL", wait=True)
        assert KILL_CHARTS[key][1] in interp.current_state_ids
        assert calls["audit_kill"] == 1
        assert interp.error is None
    finally:
        await interp.stop()


@pytest.mark.parametrize(("key", "path", "event", "audit"), FALLTHROUGH_ARMS)
async def test_guard_denied_event_takes_audit_arm(
    key: str, path: str, event: str, audit: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _instrument(key, monkeypatch)
    registry = _derive(key, path, tmp_path)
    result = await build(key, clock=SimulatedClock(), lane=_lane(key), registry=registry)
    interp = result.interpreter
    try:
        before = set(interp.current_state_ids)
        assert f"{key}.{path}" in before
        await interp.send(event, wait=True)  # stub guards deny (catalogue A6)
        assert set(interp.current_state_ids) == before
        assert calls[audit] == 1
        assert interp.deferred_count == 0
        assert interp.error is None
    finally:
        await interp.stop()
