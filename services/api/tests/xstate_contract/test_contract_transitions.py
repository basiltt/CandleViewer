"""Every declared arm of every committed chart, on both service spellings
(29-statechart-adoption-plan.md §1.7, E50-T31).

Cases are generated from `machines/*.machine.json`; nothing is hand-listed,
so a new arm is covered the moment it is committed.
"""

from __future__ import annotations

import pytest

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    SPELLINGS,
    Charts,
    Spelling,
    TransitionCase,
    all_events,
    denied_cases,
    instrument,
    park,
    resolve_target,
    service_for,
    settle,
    tap,
    transition_cases,
    unhandled_probe,
)

_REG = Registry()
CASES = [c for key in _REG.keys() for c in transition_cases(key, _REG.get(key))]


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_arm_fires_and_reaches_target(
    case: TransitionCase, spelling: Spelling, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    chart = _REG.get(case.machine)
    instrument(
        case.machine, monkeypatch, spelling, guards=case.guards, service_mode=service_for(case)
    )
    res = await park(case.machine, chart, case.source, charts)
    interp, audit = res.interpreter, tap(res)
    try:
        mark = len(audit.transitions) if case.kind == "on" else 0
        if case.kind == "on":
            await interp.send(case.event, wait=True)
        await settle()
        assert interp.error is None, case.id
        assert audit.unhandled == [], case.id
        if case.target is not None:
            want = resolve_target(case.machine, case.source, case.target)
            seen = set().union(*(ids for _ev, ids in audit.transitions[mark:]))
            assert want in seen, f"{case.id}: {want} never entered"
        else:
            assert interp.deferred_count == 0, case.id
    finally:
        await interp.stop()


DENIED = [c for key in _REG.keys() for c in denied_cases(key, _REG.get(key))]


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize("case", DENIED, ids=[c.id for c in DENIED])
async def test_guard_denied_event_is_audited_and_never_bricks(
    case: TransitionCase, spelling: Spelling, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument(case.machine, monkeypatch, spelling, guards=case.guards)
    res = await park(case.machine, _REG.get(case.machine), case.source, charts)
    interp, audit = res.interpreter, tap(res)
    try:
        before = set(interp.current_state_ids)
        await interp.send(case.event, wait=True)
        await settle()
        assert set(case.guards) & set(audit.denied), f"{case.id}: denial not observed"
        if case.target is None:
            assert set(interp.current_state_ids) == before, case.id
        assert interp.error is None and interp.is_running, case.id
    finally:
        await interp.stop()


@pytest.mark.parametrize("machine", _REG.keys())
async def test_unhandled_event_is_audited_and_never_bricks(
    machine: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event the chart declares but the resting state does not handle is
    reported through `on_unhandled_event` and deferred, never an error."""
    chart = _REG.get(machine)
    rest, event = unhandled_probe(chart)
    instrument(machine, monkeypatch, "async_def")
    res = await park(machine, chart, rest, charts)
    interp, audit = res.interpreter, tap(res)
    try:
        if event is None:  # total chart: prove it at runtime instead
            assert all(interp.can(e) for e in all_events(chart)), machine
            return
        await interp.send(event, wait=True)
        await settle()
        assert audit.unhandled == [event]
        assert interp.error is None and interp.is_running
    finally:
        await interp.stop()
