---
r4: R4-12
title: "Bug: a transition targeting the machine root empties the configuration on both engines, leaving status='running'"
labels: [bug, severity/high, area/validation, area/interpreter]
severity: High
repro_script: repro/R4-12_always_root_target_empties_configuration.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

A transition whose target resolves to the machine root — `"always": "#m"` on a
machine with `"id": "m"` — builds without complaint and, when taken, leaves the
interpreter with an **empty configuration** while `status` stays `"running"`.
Both engines agree, so the sync/async parity check that catches so much else
here catches nothing. The result is a silently inert machine: it accepts every
event forever, transitions on none of them, runs no actions, and reports
itself healthy. The same happens for an ordinary `on` transition targeting the
root, so this is not specific to `always`. `validation.py`'s existing
dead-`always`-loop check fires only when the target *is* the source, so a
one-character config typo (`"#m"` instead of `"#m.b"`) produces a dead machine
that passes build-time validation.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-12: a transition targeting the machine ROOT empties the configuration.

`{"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}` builds without
complaint, and starting it leaves the interpreter with NO active states while
`status` is still "running". The same happens for an ordinary `on` transition
targeting the root. The machine accepts events forever and does nothing --
a silent inert machine from a one-character config typo.

`validation.py::_is_dead_always_loop` only rejects `target is t.source`, so a
root-targeting `always` passes build-time validation.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

ALWAYS_CFG = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}
EVENT_CFG = {
    "id": "m2",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m2"}}, "b": {}},
}


async def main() -> int:
    failures = []

    # --- async engine, `always` -> root -------------------------------------
    i = Interpreter(create_machine(ALWAYS_CFG, logic=MachineLogic()))
    await i.start()
    ids = sorted(i.current_state_ids)
    snap = i.get_persisted_snapshot()
    d = snap if isinstance(snap, dict) else json.loads(snap)
    print("OBSERVED: async always->#m  state_ids=%r status=%r" % (ids, i.status))
    print("OBSERVED:   snapshot state_ids=%r configuration=%r"
          % (d.get("state_ids"), d.get("configuration")))
    if not ids:
        failures.append("async always->root emptied the configuration")
    await i.stop()

    # --- sync engine, `always` -> root -------------------------------------
    s = SyncInterpreter(create_machine(ALWAYS_CFG, logic=MachineLogic()))
    s.start()
    sids = sorted(s.current_state_ids)
    print("OBSERVED: sync  always->#m  state_ids=%r status=%r" % (sids, s.status))
    if not sids:
        failures.append("sync always->root emptied the configuration")

    # --- sync engine, ordinary `on` -> root --------------------------------
    s2 = SyncInterpreter(create_machine(EVENT_CFG, logic=MachineLogic()))
    s2.start()
    before = sorted(s2.current_state_ids)
    s2.send("GO")
    after = sorted(s2.current_state_ids)
    print("OBSERVED: sync  on GO -> #m2  %r -> %r status=%r"
          % (before, after, s2.status))
    if before and not after:
        failures.append("sync on->root emptied the configuration")

    print("EXPECTED: a transition whose target is the machine root is "
          "rejected at build time (InvalidConfigError), or re-enters the root "
          "and lands on the initial state -- never an empty configuration "
          "with status='running'.")
    print("RESULT:", "PASS" if not failures else "FAIL: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: async always->#m  state_ids=[] status='running'
OBSERVED:   snapshot state_ids=[] configuration=['m']
OBSERVED: sync  always->#m  state_ids=[] status='running'
OBSERVED: sync  on GO -> #m2  ['m2.a'] -> [] status='running'
EXPECTED: a transition whose target is the machine root is rejected at build time (InvalidConfigError), or re-enters the root and lands on the initial state -- never an empty configuration with status='running'.
RESULT: FAIL: async always->root emptied the configuration; sync always->root emptied the configuration; sync on->root emptied the configuration
```

Note the snapshot disagrees with itself: `state_ids=[]` but
`configuration=['m']`. A machine persisted in this state cannot be meaningfully
restored either.

## Expected behaviour

XState v5 requires every transition target to resolve to a state node that can
be entered; entering a compound node enters its `initial` child, so the
configuration is never empty while an actor is `running`
(https://stately.ai/docs/transitions, https://stately.ai/docs/states — "a state
machine is always in exactly one state per region"). The W3C SCXML
recommendation says the same in §3.1.3 and in the `enterStates` procedure of
Appendix D: entering a compound state adds its initial descendants to the
configuration, and the configuration of a running interpreter always contains
exactly one atomic state per active parallel region. An empty configuration is
not a reachable state of a conformant interpreter.

Two acceptable outcomes, in preference order:

1. **Reject at build time.** `create_machine()` raises `InvalidConfigError` for
   a transition whose target is the machine root (or, more generally, a proper
   ancestor of its source for `always` — see below). This matches how the
   library already treats other statically-provable dead configurations.
2. **Re-enter correctly at run time.** The root is entered and its `initial`
   child chain is entered, landing on `m.a` — which for `always: "#m"` then
   makes the eventless loop non-progressing and so *also* a build-time error
   under the existing `_is_dead_always_loop` rationale.

What must not happen is the current third outcome: an empty configuration with
`status="running"`.

## Root cause analysis

Two layers both fail to catch it.

**Validation.** `src/xstate_statemachine/validation.py:132-150`:

```python
def _is_dead_always_loop(label, t, target) -> bool:
    """True when an ``always`` transition can never make progress (#29)."""
    return (
        label == "always"
        and target is t.source          # <-- line 147
        and not t.reenter
        and not t.actions
    )
```

The check is identity against the *source itself*. A root-targeting `always`
has `target is machine`, not `target is t.source`, so `_collect_findings`
(`validation.py:176`) never appends a dead-loop finding and the machine builds
clean. The docstring's own reasoning — "an eventless transition that targets
its own owning state without `reenter` never exits/re-enters […] so the machine
parks forever while reporting `running`" — applies verbatim to *any* ancestor
target, root included; only the predicate is too narrow.

**Transition execution.** The exit/entry set computation treats the root as the
transition's target: the exit set covers every active node up to and including
the source's ancestors, and the entry set for a root target adds nothing
(the root is not itself an enterable leaf and its `initial` chain is not
re-descended). The configuration is emptied and never refilled. The engines
share this code path via `base_interpreter`, which is why sync and async agree
and no parity escape exists. The snapshot's `configuration=['m']` vs
`state_ids=[]` disagreement is the same split visible from the outside: the
root is recorded as "active" while no leaf is.

## Impact

**General users.** A single-character typo in a hand-written or generated
machine JSON — `"#m"` where `"#m.b"` was meant, easy to hit when the machine id
and a state id are similar — yields a machine that starts successfully, reports
`status="running"`, accepts every `send()` without error, and does nothing at
all. There is no exception, no warning, no log line, and no parity mismatch to
trip an engine-comparison test. Because it is build-time reachable on a
single-region machine, a library's own validation pass is the natural place to
catch it and does not. Any monitoring based on `status` reads the machine as
healthy forever.

**Concrete order-management scenario.** An order machine is generated from a
template where the root id and the top-level `working` region id are both
derived from the instrument. A root-targeting `always` slips into the
`pending → working` path. Every order created from that template starts,
reports running, and silently drops every subsequent `SUBMIT`, `FILL`,
`CANCEL` and `EXPIRE`. Orders are never submitted, or — worse, if the typo is
downstream — orders are live at the venue while the machine that is supposed to
manage and cancel them is inert. The service's dashboards show N healthy
running order machines. The defect is only discovered by reconciliation against
the venue.

## Proposed fix

**Design — two parts.**

1. *Build-time (primary).* Broaden the validator in
   `src/xstate_statemachine/validation.py` alongside `_is_dead_always_loop`
   (≈ line 132), where the other `always` validations already live:

   ```python
   def _is_ancestor(candidate, node) -> bool:
       p = node.parent
       while p is not None:
           if p is candidate:
               return True
           p = p.parent
       return False

   def _is_root_or_ancestor_always(label, t, target) -> bool:
       return label == "always" and (
           target is t.source or _is_ancestor(target, t.source)
       )
   ```

   Report it through the existing `dead_loops` channel in `_collect_findings`
   with a message naming the offending node and target, and suggesting
   `"reenter": true` or an explicit descendant target. Reject **any**
   transition (not only `always`) whose target is the machine root: a root
   target is never expressible as a meaningful XState target and is always a
   typo.

2. *Run-time (defence in depth).* In the transition-execution path in
   `base_interpreter.py`, when the computed entry set would leave the
   configuration empty while `status == "running"`, either descend the target's
   `initial` chain (the SCXML `enterStates` behaviour) or raise
   `ImpossibleTransitionError`. Silently producing an empty configuration
   should not be reachable.

**Compatibility.** Part 1 turns a currently-"valid" config into a build error.
Any machine it rejects is already dead, so no working machine can break; still,
it is a behaviour change worth a CHANGELOG entry, and it should be gated the
same way the existing dead-loop findings are (same `validation` pass, same
error type) so users who already tolerate those get consistent treatment.
Part 2 is purely additive.

**Alternatives considered.**
1. *Run-time fix only.* Leaves a config typo to be discovered at run time
   rather than at `create_machine()`, which is strictly worse for a service
   that loads machine JSON at startup. Wanted as defence in depth, not as the
   fix.
2. *Warn instead of raise.* Consistent with nothing else in `validation.py`, and
   a warning in a service log is precisely the signal this class of bug already
   evades.
3. *Make a root target mean "restart the machine".* Tempting, but it has no
   XState v5 or SCXML counterpart and would silently give a typo a dramatic
   meaning. Reject.

## Acceptance criteria

- [ ] `create_machine()` raises `InvalidConfigError` for a transition whose
      target resolves to the machine root, and for an `always` whose target is
      any proper ancestor of its source.
- [ ] `repro/R4-12_always_root_target_empties_configuration.py` exits `0`.
- [ ] `tests/test_validation_always.py::test_always_targeting_machine_root_rejected`
- [ ] `tests/test_validation_always.py::test_always_targeting_proper_ancestor_rejected`
- [ ] `tests/test_validation_always.py::test_event_transition_targeting_machine_root_rejected`
- [ ] `tests/test_validation_always.py::test_always_targeting_ancestor_with_reenter_and_actions_still_allowed`
      — the existing `reenter` / actions exemptions are not regressed.
- [ ] `tests/test_interpreter_configuration.py::test_configuration_never_empty_while_running`
      — both engines; a transition that would empty the configuration raises
      instead.
- [ ] The validator's error message names the offending state id and target and
      suggests the fix.

## Related

- Register row `R4-12` (filed High, **CONFIRMED** at filed severity). Source id
  `D-fuzz-2`; unmerged 1:1.
- Evidence: `battle-5e07ba8/fuzz/repros.py d2`, `battle-5e07ba8/fuzz.md` /
  `.triage.md`; final-verification runs `probes/main-5e07ba8-final/v2_root_target.py`
  and `fv1_blockers_highs.py` (`always → "#m"` starts `[] / 'running'` with
  snapshot `state_ids=[] configuration=['m']`; the ordinary `on: {"GO": "#m2"}`
  variant goes `['m2.a'] → []` with `status='running'`).
- **`R4-01`** — the same silent-inert-machine outcome reached by a different,
  parity-escaping path; this issue is the simpler, single-region,
  *build-time-reachable* version and both engines agree, so there is no parity
  signal to catch it.
- Prior issue: **#29** (the `always` dead-loop validator whose predicate is too
  narrow).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-18
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- `repro/R4-12_always_root_target_empties_configuration.py` re-run in a fresh
  process: exit code `1`, output matches the Observed section verbatim (async
  and sync `always: "#m"` both empty the configuration with `status`
  `'running'`, snapshot disagreement `state_ids=[]` vs `configuration=['m']`,
  and the ordinary `on: {"GO": "#m2"}` case goes `['m2.a'] -> []`).
- Root cause confirmed by direct inspection of
  `src/xstate_statemachine/validation.py`: `_is_dead_always_loop` (line 132)
  tests `target is t.source` only (line ~147 in the cited region), so a
  root-targeting `always` (`target is machine`, not `target is t.source`)
  is never flagged; `_collect_findings` (line 153) calls it as the sole
  dead-loop check. This matches the issue's narrative exactly.
- XState/SCXML claim checked via `https://stately.ai/docs/transitions` and
  `https://stately.ai/docs/final-states` (fetched): entering a compound state
  always resolves to an atomic descendant per active region, consistent with
  the issue's claim that a running actor's configuration is never empty; the
  W3C SCXML `enterStates` procedure (§3.1.3, Appendix D) is well-established
  and not contradicted by anything found.
- No self-containedness issues; no project name/label leak found.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --search "always root target"` surfaces issue **#29** (the too-narrow
  `always` self-target dead-loop validator this issue extends — cited as
  "Prior issue," not a duplicate) and unrelated issues (#30, #59, #77, #36,
  #35, #57, #27, #32, #49, #37, #46). No duplicate found.
