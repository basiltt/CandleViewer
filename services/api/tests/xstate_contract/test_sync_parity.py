"""Informational sync-engine parity (29-statechart-adoption-plan.md §1.7).

Runs every `on` arm of every committed chart on `SyncInterpreter` with
synchronous stub bindings and compares the target reached with the async
gate (`test_contract_transitions.py`). It NEVER gates and never ships
(MUSTNOT-06): marked `sync_parity`, deselected from the blocking run, and
executed by the separate non-blocking CI job `xstate-sync-parity`.
`SyncInterpreter` is imported here only — the one place CV-LINT-IMPORT
allows it.
"""

from __future__ import annotations

from typing import Any

import pytest
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    AuditTap,
    TransitionCase,
    binding_module,
    derive,
    node_at,
    resolve_target,
    transition_cases,
)

pytestmark = pytest.mark.sync_parity

_REG = Registry()
#: Sources that `invoke` are excluded: the sync engine completes a plain
#: service inline on entry, so the machine has already left the state before
#: the event arrives — an engine difference, not a chart divergence.
CASES = [
    c
    for k in _REG.keys()
    for c in transition_cases(k, _REG.get(k))
    if c.kind == "on" and not node_at(_REG.get(k), c.source).get("invoke")
]


def _sync_logic(case: TransitionCase) -> MachineLogic[Any]:
    __import__(binding_module(case.machine))
    maps = load_binding_maps(case.machine)

    def _noop(*_a: object, **_k: object) -> None:
        return None

    def _guard(name: str) -> Any:
        return lambda *_a, **_k: case.guards.get(name, False)

    return MachineLogic(
        actions=dict.fromkeys(maps.actions, _noop),
        guards={g: _guard(g) for g in maps.guards},
        services=dict.fromkeys(maps.services, _noop),
    )


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_sync_engine_parity(case: TransitionCase) -> None:
    chart = derive(_REG.get(case.machine), case.source)
    machine = create_machine(chart, context_type=dict, logic=_sync_logic(case))
    interp: SyncInterpreter[Any] = SyncInterpreter(machine)
    audit = AuditTap()
    interp.use(audit)
    interp.start()
    try:
        mark = len(audit.transitions)
        interp.send(case.event)
        if case.target is not None:
            want = resolve_target(case.machine, case.source, case.target)
            seen = set().union(*(ids for _e, ids in audit.transitions[mark:]))
            assert want in seen, f"{case.id}: {want} never entered on the sync engine"
    finally:
        interp.stop()
