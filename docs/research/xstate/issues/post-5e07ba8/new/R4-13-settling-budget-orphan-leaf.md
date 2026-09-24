---
r4: R4-13
title: "Bug: settling-budget trip leaves an orphaned active leaf reported as healthy, and mutates on restore"
labels: [bug, severity/medium, area/interpreter, area/sync-interpreter]
severity: Medium
repro_script: repro/R4-13_settling_budget_orphan_leaf.py
commit: 5e07ba8
python: 3.13.7
verified: true
---
## Summary

When the transient ("always") settling loop hits its `maxIterations`
budget mid-microstep, the interpreter can be left with an active leaf
state node whose ancestor chain is **not** active — a structurally
corrupt configuration — while `status` stays `"running"`,
`last_transition_ok` stays `True`, and `last_error` stays `None`. Worse,
persisting and restoring this configuration does not preserve it: the
restore path (which always re-activates the full ancestor chain of every
restored leaf) silently repairs the torn configuration into a different
shape, so `save() -> restore() -> save()` produces two different
snapshots for the same logical machine state. Filed as High in the
original register row; downgraded to Medium because the live machine,
while structurally torn, is not fully inert (it still processes new
external events), unlike R4-01's empty-configuration case.

## Environment

- Commit: `5e07ba8` (xstate_statemachine 0.8.1 unreleased; `__version__` reports 0.8.0)
- Python: 3.13.7, Windows 11
- Editable install of the library under a project-local venv (`.venv-main`)

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-13: A runaway-chain trip during transient ("always") settling leaves an
active leaf whose ancestors are INACTIVE. The machine reports "running"
with no error, and a save->restore->save round-trip silently rewrites the
persisted configuration to a different (ancestor-repaired) shape.

Standalone, derived from battle-5e07ba8/fuzz/repros.py::d10.

Root cause: sync_interpreter.py's settling-budget break (~lines 812-824)
has no `last_error` / `last_transition_ok` reporting, unlike the
event-chain budget break a few hundred lines above it (~lines 700-733).

Exits 1 (defect present) while:
  - the live machine has an orphaned active leaf (ancestors not active), and
  - the machine reports last_transition_ok True / last_error None, and
  - a snapshot taken before a restore differs from one taken after.
Exits 0 once the settling-budget trip is reported and/or repairs the
active-node set consistently.
"""
from __future__ import annotations

import json

from xstate_statemachine import SyncInterpreter, create_machine

CFG = {
    "id": "m",
    "initial": "b",
    "maxIterations": 1,
    "always": {"target": "#m.b", "guard": "g_true"},
    "states": {
        "b": {
            "type": "parallel",
            "states": {
                "a": {
                    "initial": "a",
                    "always": {"target": "#m", "guard": "g_true"},
                    "states": {"a": {}},
                },
                "b": {
                    "initial": "a",
                    "invoke": {
                        "id": "v",
                        "src": "svc_ok",
                        "onDone": "#m.b",
                        "onError": "#m.b",
                    },
                    "states": {"a": {}},
                },
            },
        }
    },
}

LOGIC_KW = dict(
    guards={"g_true": lambda c, e: True},
    services={"svc_ok": lambda i, c, e: {"ok": 1}},
)


def main() -> int:
    from xstate_statemachine import MachineLogic

    machine = create_machine(CFG, logic=MachineLogic(**LOGIC_KW))
    i = SyncInterpreter(machine)
    i.start()

    active = {n.id for n in i._active_state_nodes}
    orphans = sorted(
        n.id
        for n in i._active_state_nodes
        if n.parent is not None and n.parent not in i._active_state_nodes
    )

    s1 = i.get_persisted_snapshot()
    r = SyncInterpreter.from_snapshot(json.dumps(s1, default=str), machine)
    s2 = r.get_persisted_snapshot()

    print(f"OBSERVED: live active={sorted(active)}")
    print(f"OBSERVED: orphaned leaves (ancestors inactive)={orphans}")
    print(
        f"OBSERVED: status={i.status} last_transition_ok={i.last_transition_ok} "
        f"last_error={i.last_error!r}"
    )
    print(f"OBSERVED: save1 configuration={s1['configuration']}")
    print(f"OBSERVED: save2 (post-restore) configuration={s2['configuration']}")
    print(
        "EXPECTED: no orphan active node; a settling-budget trip surfaces via "
        "last_error/last_transition_ok; save->restore->save is stable "
        "(save1 == save2)"
    )

    defect = bool(orphans) and i.last_transition_ok and i.last_error is None
    configs_differ = s1["configuration"] != s2["configuration"]
    print(f"\nVERDICT: orphan_unreported={defect} configs_differ={configs_differ}")
    return 1 if (defect or configs_differ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
ERROR:xstate_statemachine.sync_interpreter:🔁 Exceeded 1 microsteps while settling transient transitions in 'm'. Aborting to avoid an infinite loop; check for mutually-targeting 'always' transitions.
... (repeated for each internal retry)
OBSERVED: live active=['m', 'm.b.b.a']
OBSERVED: orphaned leaves (ancestors inactive)=['m.b.b.a']
OBSERVED: status=running last_transition_ok=True last_error=None
OBSERVED: save1 configuration=['m', 'm.b.b.a']
OBSERVED: save2 (post-restore) configuration=['m', 'm.b', 'm.b.b', 'm.b.b.a']
EXPECTED: no orphan active node; a settling-budget trip surfaces via last_error/last_transition_ok; save->restore->save is stable (save1 == save2)

VERDICT: orphan_unreported=True configs_differ=True
```
(exit code 1 — defect present)

## Expected behaviour

The library already implements exactly this reporting contract for the
sibling budget: the event-chain (`RunawayChainError`) budget break in
`sync_interpreter.py` (~lines 700-733) sets `last_transition_ok = False`
and `self._last_action_error = RunawayChainError(...)`, and fires
`on_event_dropped` for every discarded event, making the trip observable.
The settling-budget break for transient ("always") loops should offer the
same guarantee: any time the interpreter's own budget forces early
termination mid-microstep, `last_transition_ok`/`last_error` must reflect
that the step did not complete cleanly, and the active-node set must
remain a valid configuration (one leaf with a fully active ancestor
chain per region) — the same invariant `get_persisted_snapshot()` and
`from_snapshot()` both assume elsewhere in the code (the restore path's
"ancestors must be active too" comment in `base_interpreter.py`).

## Root cause analysis

- `sync_interpreter.py` transient-settling loop (~lines 800-824): the
  `while True` loop bounded by `max_iterations` (`getattr(self.machine,
  "max_iterations", 1000)`) simply `break`s when the limit is exceeded,
  after only a `logger.error(...)` call — no `last_transition_ok`,
  `last_error`, or plugin hook is set, unlike the chain-budget break at
  ~lines 700-733 which does all three.
- Because the break happens mid-microstep, whatever partial
  exit/enter work has already run can leave `_active_state_nodes`
  containing a leaf (`m.b.b.a`) without its full ancestor chain
  (`m.b`, `m.b.b`) also present — a torn configuration structurally
  identical in kind to R4-01's mid-macrostep window, but reached via a
  different code path (the settling budget, not the exit/enter
  interlock).
- `base_interpreter.py`'s restore path always walks `node.parent` and
  adds every ancestor to `_active_state_nodes` (the "Ancestors must be
  active too" comment), so restoring a torn configuration silently
  "repairs" it into a different, larger configuration — hence
  `save1 != save2`.

## Impact

For general users, any machine whose `always` transitions can enter a
degenerate mutually-retriggering shape (easy to construct accidentally
with parallel regions and shared targets) silently corrupts its own
active-state invariant with zero observability — no exception, no
`last_error`, `status` stays `"running"`. In the adopting project's order
path, this defeats snapshot-equality-based audit reconciliation: the same
logical machine state serializes to two different persisted
configurations depending on whether it was ever round-tripped through a
restore, which breaks any reconciliation/dedup logic that compares
snapshot blobs or their `configuration` field for equality.

## Proposed fix

Give the settling-budget break in `sync_interpreter.py` the same
reporting the chain-budget break already has: set
`self.last_transition_ok = False` and `self._last_action_error =
RunawayChainError(self.id, limit, ...)` (or a dedicated
`SettlingBudgetExceededError`) before breaking, and fire
`on_event_dropped`/an equivalent plugin hook so the trip is observable
the same way. Additionally, either (a) repair the active-node set at the
break point so it is always a valid configuration (matching what
`from_snapshot` already does on restore), or (b) refuse to hand back a
torn configuration from `get_persisted_snapshot()`/`current_state_ids`
while the interpreter is in this tripped state. Whichever repair strategy
is chosen should be applied identically live and on restore so
`save() -> restore() -> save()` is idempotent.

## Acceptance criteria

- [ ] After a settling-budget trip, `last_transition_ok is False` and
      `last_error` is a typed error (mirroring the chain-budget path).
- [ ] `_active_state_nodes` never contains a leaf without its full active
      ancestor chain, even mid-trip.
- [ ] `tests/test_sync_interpreter_budgets.py::test_settling_budget_trip_reports_error`
- [ ] `tests/test_sync_interpreter_budgets.py::test_settling_budget_trip_save_restore_save_is_stable`
- [ ] `repro/R4-13_settling_budget_orphan_leaf.py` exits 0

## Related

- Register source id: `D-fuzz-9` (`d10` in `battle-5e07ba8/fuzz/repros.py`)
- Shares the "torn/orphan active configuration" defect family with R4-01
  (mid-macrostep window) and the validation gap in R4-02 (restore path
  does not reject or flag a torn configuration on the way in)

## Verification

- Date: 2026-09-19; Python 3.13.7; commit `5e07ba8`.
- Re-ran `repro/R4-13_settling_budget_orphan_leaf.py` in a fresh process
  (60s cap): output matched the Observed block verbatim (live active
  `['m', 'm.b.b.a']`, orphan `['m.b.b.a']`, `last_transition_ok=True`,
  `last_error=None`, `save1 != save2`); exit code `1`.
- Confirmed the settling-budget `break` in
  `src/xstate_statemachine/sync_interpreter.py`'s transient-settling loop
  logs an error and breaks with no `last_transition_ok`/`last_error`
  assignment, unlike the sibling chain-budget break earlier in the same
  file which does set both — matching the draft's root-cause narrative.
  Confirmed the restore path in `base_interpreter.py` always walks
  `node.parent` to add every ancestor (the "Ancestors must be active too"
  comment), which is why `save1 != save2`.
- No external XState/SCXML claim to check (this is about the library's
  own internal budget-reporting symmetry, not spec conformance).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 120 --search "settling"`: only #43 (unrelated actor-task perf)
  matched; no duplicate found for the settling-budget orphan-leaf/unstable
  round-trip defect.
- No project name/label leakage found in the file.
