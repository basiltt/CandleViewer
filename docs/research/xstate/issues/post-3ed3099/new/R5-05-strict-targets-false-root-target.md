---
r5: R5-05
title: "Semantics: `strict_targets=False` reopens the #108 root-target hole verbatim — the configuration empties while `last_transition_ok=True` on both engines"
labels: [bug, severity/high, area/validation, area/interpreter, area/sync-interpreter]
severity: High
repro_script: repro/R5-05_strict_targets_false_root_target.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`#108` added a build-time rejection for a transition targeting the machine
root, because entering the root "enters nothing below it; the configuration
ends up EMPTY while `status` stays 'running' — a silently inert machine on
both engines" (its own comment). That rejection is emitted from the
*unresolvable-targets* branch of `validation.py`, which `strict_targets=False`
skips wholesale. With the flag set, the pre-#108 behaviour returns byte for
byte: one event empties the configuration, `status` stays `running`,
`last_transition_ok` stays `True`, `last_error` stays `None`, and the empty
configuration snapshots and restores cleanly. A root target is different *in
kind* from the unresolvable target the flag documents — it resolves fine, to a
node that cannot be a leaf — so the escape hatch should never have covered it.

## Environment

- Commit: `3ed3099` (`main`, "Merge pull request #139 from fix/0.8.1-round4"),
  unreleased 0.8.1 (`__version__` still reports `0.8.0`; keyed on the commit)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 5.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R5-05: `strict_targets=False` reopens the #108 root-target hole verbatim.

#108 rejects a transition targeting the machine root at build time. The
documented escape hatch `strict_targets=False` is for *unresolvable* targets
("these transitions will be silent no-ops at runtime"), but it skips the root
check wholesale. A root target RESOLVES -- to a node that cannot be a leaf --
so taking it empties the configuration while `status` stays "running",
`last_transition_ok` stays True and `last_error` stays None, on BOTH engines.
The empty configuration then snapshots and restores cleanly.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}, "b": {}}}


def mk():
    return create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(), strict_targets=False
    )


def sync_case() -> bool:
    it = SyncInterpreter(mk()).start()
    print("  sync before GO:", sorted(it.current_state_ids))
    it.send("GO")
    ids = sorted(it.current_state_ids)
    status, ok = it.status, it.last_transition_ok
    print(f"  sync after  GO: states={ids} status={it.status} "
          f"last_transition_ok={it.last_transition_ok} "
          f"last_error={type(it.last_error).__name__ if it.last_error else None}")
    snap = it.get_persisted_snapshot()
    print(f"  sync snapshot : configuration={snap.get('configuration')} "
          f"state_ids={snap.get('state_ids')} status={snap.get('status')}")
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(snap), mk())
        print(f"  sync restored : states={sorted(r.current_state_ids)} status={r.status}")
        restored_inert = not r.current_state_ids
    except XStateMachineError as exc:
        print(f"  sync restored : refused with typed {type(exc).__name__}")
        restored_inert = False
    it.send("GO")
    print(f"  sync further send accepted; states={sorted(it.current_state_ids)}")
    it.stop()
    # Defect present when the configuration emptied while reporting healthy.
    return not ids and status == "running" and ok and restored_inert


async def async_case() -> bool:
    i = Interpreter(mk())
    await i.start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0.05)
    ids = sorted(i.current_state_ids)
    print(f"  async after GO: states={ids} status={i.status} "
          f"last_transition_ok={i.last_transition_ok} "
          f"last_error={type(i.last_error).__name__ if i.last_error else None}")
    bad = not ids and i.status == "running" and i.last_transition_ok
    await i.stop()
    return bad


def main() -> int:
    bad_sync = sync_case()
    bad_async = asyncio.run(asyncio.wait_for(async_case(), 30))
    print()
    print("OBSERVED: with strict_targets=False a root target empties the "
          f"configuration silently (sync_defect={bad_sync}, async_defect={bad_async}).")
    print("EXPECTED: the #108 root-target rejection is unconditional (it is a "
          "configuration-legality rule, not a target-resolution one); failing "
          "that, taking it must set last_transition_ok=False with a typed "
          "last_error and must never leave zero active leaves while 'running'.")
    print("RESULT:", "FAIL" if (bad_sync or bad_async) else "PASS")
    return 1 if (bad_sync or bad_async) else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
  sync before GO: ['m.a']
  sync after  GO: states=[] status=running last_transition_ok=True last_error=None
  sync snapshot : configuration=['m'] state_ids=[] status=running
  sync restored : states=[] status=running
  sync further send accepted; states=[]
  async after GO: states=[] status=running last_transition_ok=True last_error=None

OBSERVED: with strict_targets=False a root target empties the configuration silently (sync_defect=True, async_defect=True).
EXPECTED: the #108 root-target rejection is unconditional (it is a configuration-legality rule, not a target-resolution one); failing that, taking it must set last_transition_ok=False with a typed last_error and must never leave zero active leaves while 'running'.
RESULT: FAIL
```

Exit code `1`. Every documented health signal reads clean: `status` is
`"running"`, `last_transition_ok` is `True`, `last_error` is `None`. Further
`send()` calls are accepted and do nothing. The snapshot writes
`configuration=['m'] state_ids=[] status='running'` and restores into the same
inert machine — so the corruption is *durable*.

## Expected behaviour

**Per SCXML §3.13 and XState v5 configuration legality.** SCXML's definition
of a legal configuration requires that it contain exactly one atomic
(leaf) descendant for every active compound state, and that the root
`<scxml>` element is always active with exactly one active child. A
configuration consisting of the root alone is not legal in any engine. XState
v5 has no representation for it either: `machine.transition()` always yields a
state value that bottoms out in atomic states
(https://stately.ai/docs/states — "a state machine is always in exactly one of
its finite states"; for compound states, entering a state enters its initial
child).

**Per the library's own contract**, quoted from `validation.py:177-187`:

> 🛑 #108: entering the ROOT enters nothing below it; the configuration ends
> up EMPTY while `status` stays "running" -- a silently inert machine on both
> engines. XState/SCXML: entering a compound state enters its initial child,
> so "target the root" has no meaning.

and from the `strict_targets=False` warning text itself
(`validation.py:290-297`):

> (strict_targets=False: these transitions will be silent no-ops at runtime.
> This escape hatch is removed in 1.0.)

The flag's documented semantics are *silent no-op*. A root target is not a
no-op: it takes the transition, exits the source, and enters nothing. So even
on the flag's own terms the behaviour is wrong — the correct degraded
behaviour under `strict_targets=False` would be to leave the machine in `m.a`.

## Root cause analysis

`src/xstate_statemachine/validation.py:170-190` builds one list, `unresolved`,
from two structurally different conditions inside the same loop:

```python
t.resolved_target = target
if target is None:
    unresolved.append(
        f"  {node.id}: {label} -> target {t.target_str!r} does not resolve..."
    )
elif target is machine:
    # 🛑 #108: entering the ROOT enters nothing below it; ...
    unresolved.append(
        f"  {node.id}: {label} -> target {t.target_str!r} is the "
        f"machine root; entering it empties the configuration. ..."
    )
```

and then, at `validation.py:287-297`, disposes of the *combined* list under a
single flag:

```python
if unresolved:
    message = (...)
    if strict_targets:
        raise InvalidConfigError(message)
    warnings.warn(message + "\n  (strict_targets=False: ...)", DeprecationWarning, ...)
```

So `#108`'s check was implemented by appending to the list the escape hatch
was already designed to bypass. This is a regression *of intent* introduced by
the #108 fix itself: the flag predates it, and folding a
configuration-legality rule into a target-resolution list silently made the
new rule optional.

The runtime consequence follows from `t.resolved_target` having been set to
the root node: the transition is perfectly well-formed as far as the engines
are concerned, so it also evades `#31`'s runtime `StateNotFoundError` surface
(which fires only for `resolved_target is None`). Entering the root adds the
root to `_active_state_nodes` and descends no further, leaving
`current_state_ids` (which reports leaves) empty. Nothing downstream asserts
that a `running` interpreter has at least one leaf — the same missing
invariant as R5-01/R5-02 — so `last_transition_ok` is set `True` by the normal
success path and the snapshot writer happily emits `configuration=['m'],
state_ids=[]`.

## Impact

**General users.** `strict_targets=False` is the documented migration path for
anyone adopting the library with a large pre-existing machine catalogue that
does not yet pass the new validation — precisely the population that has not
audited its targets. For them, `#108` is not fixed. The failure mode is the
worst available: total, silent and durable. The machine accepts events
forever, changes nothing, reports `running` / `last_transition_ok=True`, and
persists its own corruption so a restart does not clear it.

**Concrete order-management scenario.** A catalogue is migrated with
`strict_targets=False` to get the service up while a handful of unrelated
legacy targets are fixed. One order machine contains
`{"on": {"RESET": "#order"}}` — a hand-written "go back to the top" target
that looks right and was never exercised because `RESET` is a rare
operator-initiated path. An operator resets one stuck order during an
incident. That order's machine is now inert: it will never again respond to
`FILL`, `CANCEL` or `EXPIRE`, its position is never reconciled, and the health
check reading `status`/`last_transition_ok` reports it as a healthy running
order. The snapshot written immediately afterwards makes the loss permanent
across restarts, and because `current_state_ids` is empty rather than wrong,
any downstream consumer keyed on state tags simply sees the order vanish from
every bucket.

## Proposed fix

**Design.** Separate configuration-legality from target-resolution, and give
the runtime a backstop.

1. **Split the list in `validation.py`.** Collect root targets into a distinct
   `illegal_targets` list, and raise `InvalidConfigError` for it
   *unconditionally* — `strict_targets` governs only `unresolved`:

   ```python
   if illegal_targets:
       raise InvalidConfigError(
           f"Machine '{machine.id}' has transitions whose target cannot be a "
           f"configuration:\n" + "\n".join(illegal_targets)
       )
   if unresolved:
       ...  # existing strict_targets branch, unchanged
   ```

   This is correct because `strict_targets` is documented as an escape hatch
   for targets that *do not resolve*; a root target resolves, and no flag
   value makes an empty configuration meaningful.

2. **If an unconditional raise is judged too breaking for 0.8.1**, the minimum
   acceptable degraded behaviour is to make the flag do what it says: mark
   the transition `resolved_target = None` alongside the warning, so it
   becomes the promised silent no-op and the machine stays in `m.a`. Even
   then, step 3 is still needed.

3. **Runtime backstop (shared with R5-01/R5-02).** The engines should refuse
   to *commit* a microstep whose resulting configuration has zero active
   leaves while `status == "running"`. That belongs in the one place both
   engines already funnel through when applying a macrostep result: set
   `last_transition_ok = False`, set `last_error` to a typed
   `InvalidConfigurationError`, fire the error hook, and leave the prior
   configuration in place (the `_repair_configuration` machinery from `#112`
   already demonstrates exactly this shape and is known to work). This also
   closes the `#31` gap for any other route to an empty configuration.

4. **Write side.** `get_persisted_snapshot()` must not emit
   `status="running"` with zero leaves; `check_shape`'s read-side rule already
   rejects an *empty* `configuration`, and it should be tightened to reject a
   configuration with no leaf (see R5-02).

**Compatibility.** Step 1 turns a warning into a build error for machines
that both set `strict_targets=False` *and* contain a root target — a machine
that is already broken at runtime. The escape hatch is documented as removed
in 1.0, so narrowing it in 0.8.1 is within the stated trajectory. Step 3 is
additive and changes behaviour only for configurations that are already
illegal.

**Alternatives considered.** Documenting the interaction ("`strict_targets=False`
also disables the root-target check") was rejected: the flag's users are by
definition the ones who have not audited their targets, and the failure is
silent and durable, so a doc note cannot be the primary mitigation.

## Acceptance criteria

- [ ] `repro/R5-05_strict_targets_false_root_target.py` exits `0`.
- [ ] `tests/test_validation_targets.py::test_root_target_rejected_regardless_of_strict_targets`
      — parametrised over `strict_targets` in `(True, False)`: both raise
      `InvalidConfigError`; the `False` case additionally asserts the message
      names the root, so the #108 diagnostic is preserved.
- [ ] `tests/test_validation_targets.py::test_strict_targets_false_still_warns_for_unresolvable`
      — the genuine escape-hatch case is unaffected: a target that does not
      resolve still only warns, and the machine builds.
- [ ] `tests/test_interpreter_invariants.py::test_running_interpreter_never_has_zero_leaves`
      — parametrised over both engines: after any accepted event, either
      `current_state_ids` is non-empty or `last_transition_ok is False` with a
      typed `last_error`.
- [ ] `tests/test_persistence_shape.py::test_snapshot_never_written_running_with_no_leaf`
      — `get_persisted_snapshot()` on an interpreter with no active leaf
      raises rather than emitting `configuration=['m'], state_ids=[]`.

## Related

- Round 4: **#108** (the root-target rejection this bypasses — the fix whose
  intent regressed), **#31** (runtime `StateNotFoundError`, which a root
  target evades because it *resolves*), **#112** (`_repair_configuration`,
  the working precedent for the runtime backstop in step 3).
- **R5-01** / **R5-02** — the same missing invariant (a `running` machine must
  have at least one active leaf per region) on the snapshot write and read
  sides respectively. R5-05 is the third route to the same illegal state; all
  three are closed by one shared configuration-legality predicate.
- Register source id: `D5-fuzz-3` (unmerged 1:1 for this row).
- Evidence: `battle-3ed3099/fuzz/n8_strict_targets_root.py`.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Ran `repro/R5-05_strict_targets_false_root_target.py` in a fresh process:
  exit code `1`, output pasted verbatim above. Both engines reproduce.
- Root cause confirmed by reading `src/xstate_statemachine/validation.py`
  at lines `170-190` (the shared `unresolved` list) and `287-297` (the single
  `strict_targets` disposition).

## Verification (independent re-run)

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `3ed3099`
- Fresh-process re-run of `repro/R5-05_strict_targets_false_root_target.py`:
  exit code `1`, output byte-identical to the pasted transcript above; both
  the sync and async engines reproduce.
- Root-cause line citations re-checked against source: the combined
  `unresolved` list (the root-target branch and the unresolvable-target
  branch appended to the same list) and the single `strict_targets`
  disposition (`if strict_targets: raise ... else: warnings.warn(...)`) both
  confirmed in `validation.py` as described.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "strict_targets root"` and `--search "108"` return
  only round-4 `#108` (the parent this reopens/deepens, already cited under
  Related), `#30`, `#31`, `#34`, `#134`, `#26` — none a duplicate of this
  `strict_targets=False` escape-hatch finding.
