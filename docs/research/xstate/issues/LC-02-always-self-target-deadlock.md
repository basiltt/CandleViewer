---
lc: LC-02
title: "Bug: an `always` transition with a self-target deadlocks silently, with no config-time diagnostic"
labels: [bug, severity/blocker, area/interpreter, candleviewer]
severity: Blocker
blocks_adoption: true
repro_script: repro/LC-02_always-self-target-deadlock.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`base_interpreter.py:1769` classifies any transition whose resolved target equals its source as an internal self-transition unless `reenter: True` is set. On the `entry`/`exit` axis that matches XState v5 (see Expected behaviour — the "external by default" claim is v4 terminology and does not apply). The defect is what happens when this correct-but-subtle rule meets an `always` transition: the fallback `{"target": "loop"}` executes its (usually empty) action list, does not re-enter `loop`, therefore never re-runs `loop`'s `entry`, therefore never changes the context the guard reads — and the machine parks in `loop` forever with no error, no warning, and `status == "running"`.

XState v5 documents this precise footgun and says it guards against it ("If `target` is declared, the value should differ from the current state node"). This library provides no such guard at config time and no liveness signal at runtime, so the failure is a **silent deadlock**. Separately, the XState v4 `internal` key is parsed and silently discarded. The identical logic routed through a distinct intermediate state converges correctly, and `reenter: True` also converges — which proves the engine can drive the loop; only the undiagnosed self-target form parks.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (local clone, `pip install -e`)
- Python: 3.13.7 (CPython, venv)
- OS: Windows 11
- Install: editable install from source clone

## Minimal reproduction

```python
"""LC-02 repro: an `always` (eventless) transition whose fallback targets its OWN
state never re-runs `entry`, so the guard is never re-evaluated and the machine
parks forever in the loop state with no error and `status == "running"`.

Note on scope: XState v5 AGREES that an explicit self-target does not re-run
`entry`/`exit` (https://stately.ai/docs/transitions#re-entering) -- so the
entry/exit semantics here are correct and `reenter: True` is the documented
opt-in, which works (control case below). The defect is the absence of any
DIAGNOSTIC: XState documents that it "will help guard against most infinite loop
scenarios" and that "if `target` is declared, the value should differ from the
current state node" (https://stately.ai/docs/eventless-transitions
#avoid-infinite-loops). This library accepts the non-progressing config at
build time and then deadlocks silently. It also silently discards the XState v4
`internal` key, which is what a migrating user would reach for.

Exits 1 when the defect is present.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

SELF_LOOP = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [{"target": "done", "guard": "enough"}, {"target": "loop"}],
        },
        "done": {},
    },
}

# Identical logic, but the loop goes through a DISTINCT intermediate state.
VIA_B = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "A"}},
        "A": {
            "entry": ["inc"],
            "always": [{"target": "done", "guard": "enough"}, {"target": "B"}],
        },
        "B": {"always": {"target": "A"}},
        "done": {},
    },
}

# Control: the XState v5 opt-in. This converges today, proving the engine can
# drive the loop and that no semantic change is needed -- only a diagnostic.
REENTER = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [
                {"target": "done", "guard": "enough"},
                {"target": "loop", "reenter": True},
            ],
        },
        "done": {},
    },
}

# Control: the XState v4 spelling a migrating user reaches for. Silently dropped
# (models.py:397 reads `reenter` but never `internal`), so it parks like SELF_LOOP.
INTERNAL_FALSE = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "loop"}},
        "loop": {
            "entry": ["inc"],
            "always": [
                {"target": "done", "guard": "enough"},
                {"target": "loop", "internal": False},
            ],
        },
        "done": {},
    },
}


def make_logic():
    def inc(i, c, e, a):
        c["n"] += 1

    return MachineLogic(actions={"inc": inc}, guards={"enough": lambda c, e: c["n"] >= 5})


async def run(cfg):
    interp = Interpreter(create_machine(cfg, logic=make_logic()))
    await interp.start()
    await interp.send("GO")
    await asyncio.sleep(0.2)
    out = (sorted(interp.current_state_ids), interp.context["n"], interp.status)
    await interp.stop()
    return out


async def main() -> int:
    self_state, self_n, self_status = await run(SELF_LOOP)
    via_state, via_n, _ = await run(VIA_B)
    re_state, re_n, _ = await run(REENTER)
    int_state, int_n, _ = await run(INTERNAL_FALSE)

    print(f"OBSERVED self-target loop  : state={self_state} n={self_n} status={self_status}")
    print(f"OBSERVED via-B loop        : state={via_state} n={via_n}")
    print(f"OBSERVED reenter:True loop : state={re_state} n={re_n}")
    print(f"OBSERVED internal:False    : state={int_state} n={int_n}")
    print("EXPECTED: NOT that the self-target loop converges -- XState v5 agrees an")
    print("EXPECTED: explicit self-target does not re-run `entry` (docs/transitions")
    print("EXPECTED: #re-entering). `reenter: True` is the v5 opt-in and works here.")
    print("EXPECTED: The defect is the ABSENCE OF A DIAGNOSTIC: create_machine()")
    print("EXPECTED: should reject an `always` self-target that can never progress")
    print("EXPECTED: (XState: 'If target is declared, the value should differ from")
    print("EXPECTED: the current state node'), and `internal: False` must not be")
    print("EXPECTED: silently dropped. Today both are accepted and the machine")
    print("EXPECTED: parks forever while still reporting status == 'running'.")

    # The defect: the non-progressing config builds without error, then parks
    # silently -- while the documented opt-in (`reenter: True`) proves the engine
    # can drive the loop, and `internal: False` is silently discarded.
    parks_silently = self_state == ["m.loop"] and self_n < 5 and self_status == "running"
    engine_can_loop = via_state == ["m.done"] and re_state == ["m.done"]
    internal_dropped = int_state == ["m.loop"] and int_n < 5

    bad = parks_silently and engine_can_loop and internal_dropped
    print("RESULT: DEFECT REPRODUCED" if bad else "RESULT: not reproduced")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED self-target loop  : state=['m.loop'] n=1 status=running
OBSERVED via-B loop        : state=['m.done'] n=5
OBSERVED reenter:True loop : state=['m.done'] n=5
OBSERVED internal:False    : state=['m.loop'] n=1
EXPECTED: NOT that the self-target loop converges -- XState v5 agrees an
EXPECTED: explicit self-target does not re-run `entry` (docs/transitions
EXPECTED: #re-entering). `reenter: True` is the v5 opt-in and works here.
EXPECTED: The defect is the ABSENCE OF A DIAGNOSTIC: create_machine()
EXPECTED: should reject an `always` self-target that can never progress
EXPECTED: (XState: 'If target is declared, the value should differ from
EXPECTED: the current state node'), and `internal: False` must not be
EXPECTED: silently dropped. Today both are accepted and the machine
EXPECTED: parks forever while still reporting status == 'running'.
RESULT: DEFECT REPRODUCED
```

Exit code `1`. Adding `reenter: True` to the fallback transition makes the same machine converge to `['m.done']` with `n == 5`, confirming the engine can drive the loop and that only the undiagnosed form parks.

## Expected behaviour

**Correction to an earlier reading of this issue.** XState v5 does **not** make an explicit self-target external by default. From https://stately.ai/docs/transitions#re-entering: *"By default, when a state machine transitions from some state to the same state … it will not re-enter the state; that is, it will not execute the `exit` and `entry` actions of the parent state."* The page's own table is explicit:

| Transition | Child states | Entry/exit actions | Invocations |
|---|---|---|---|
| **Targetless** (no `target`) | Preserved | Not re-executed | Kept running |
| **Targeted** (`target: 'sameState'`) | Re-resolved to initial | **Not re-executed** | Kept running |
| **Re-entering** (`target` + `reenter: true`) | Re-resolved to initial | Re-executed | Restarted |

So on the `entry`-re-execution axis this library **already matches XState v5**, and `reenter: True` is the correct XState-v5 spelling for the re-entering case — which works here today (verified: the repro's machine with `reenter: True` reaches `m.done` with `n == 5`). The "self-transitions are external by default" wording is **XState v4** terminology; the v5 docs carry an explicit callout that v4's "external" is v5's "re-entering". **The semantic-change request in the original draft is therefore withdrawn.**

What remains, and is the actual defect:

**1. A silent, undetectable deadlock.** XState v5 documents this exact footgun and states it defends against it — https://stately.ai/docs/eventless-transitions#avoid-infinite-loops: *"Since unguarded 'always' transitions always run, you should be careful not to create an infinite loop. XState will help guard against most infinite loop scenarios… If `target` is declared, the value should differ from the current state node."* This library offers no such guard: `create_machine()` accepts `always: [{"target": "loop"}]` on `loop` without complaint, and at runtime the machine simply goes quiet — no exception, no warning, `status == "running"`. The chained-event limiter at `interpreter.py:429-440` does not fire, because no event is being raised. A user following the XState docs writes a construction those docs call out as invalid and gets no diagnostic from either layer.

**2. `internal` is silently dropped.** `{"target": "loop", "internal": False}` — the XState v4 spelling a migrating user will reach for, and the one that *would* express the intended external semantics — is parsed and discarded with no validation error. Verified: it behaves identically to the plain self-target (parks at `n == 1`).

So the expectation is **not** "change the semantics" but: **a self-targeting `always` transition must be rejected or warned about at `create_machine()` time**, and unknown transition keys such as `internal` must not vanish silently.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:1769-1782`, in `_execute_transition`:

```python
        # 3. A self-transition without `reenter: True` is an "internal" transition.
        # It executes actions but does not exit or re-enter the source state.
        if target_state == transition.source and not transition.reenter:
            logger.debug("🎬 Executing internal self-transition for event '%s'.", ...)
            await self._execute_actions(transition.actions, event)
            for plug in self._plugins:
                plug.on_transition(self, self._active_state_nodes,
                                   self._active_state_nodes, transition)
            return
```

Two observations about this condition:

1. **`internal` is never read.** `models.py:397` is `self.reenter = config.get("reenter", False)`; there is no `config.get("internal", ...)` anywhere in the file. A user writing the XState-v4-idiomatic `{"target": "loop", "internal": False}` gets it silently ignored, with no validation error to tell them the key was dropped. Verified: that config parks at `n == 1`, identical to the plain self-target.
2. **The condition itself is not the bug.** `target_state == transition.source and not transition.reenter` produces the same entry/exit behaviour XState v5 documents. `reenter: True` correctly bypasses it — verified, the repro's machine reaches `m.done` with `n == 5` when `reenter: True` is added to the fallback. The problem is that nothing tells the user which of the two they wrote.

For an `always` transition the consequence is a hard silent deadlock. The eventless-transition loop terminates when a macrostep produces no state change — and this transition, by construction, never produces one. The chained-event guard at `interpreter.py:429-440` ("Exceeded %d chained self-raised events") does not fire either, because no event is being raised; the machine simply goes quiet while continuing to report `status == "running"`.

`LC-04` (an event-driven self-transition with an explicit target does not re-enter) shares this code path, but per the Expected behaviour section above that is **correct XState v5 behaviour**, not a defect; LC-04 should be re-scoped to a documentation request rather than grouped here as a bug.

## Impact

**General users:** the self-target `always` loop is the canonical way to express "keep doing X until the guard says stop" — batching, retry-with-backoff counters, work-queue draining, iterative state refinement. Every one of those written the XState way deadlocks here, and deadlocks *quietly*: no exception, no warning, `is_running` still `True`, health checks green. Debugging requires reading interpreter internals. Separately, LC-04 means every explicit self-transition in existing user code has subtly wrong entry/exit semantics compared with the XState docs those users are reading.

**CandleViewer trading OMS:** iceberg slicing (B5) is exactly this shape — `slicing` state with `entry: [emit_next_slice]` and `always: [{target: "complete", guard: "all_slices_sent"}, {target: "slicing"}]`. Under this bug exactly **one** slice is emitted and the machine parks in `slicing` with a partially-executed parent order: the remaining quantity is never sent, the order never completes, and nothing raises. The same shape breaks rule counting (B9) and retry loops (B3) — a retry loop that parks means an order stuck in `retrying` while the market moves. Because `status` stays `"running"`, no liveness probe catches it; only an out-of-band order-age reconciliation does.

## Proposed fix

No semantic change is requested — the entry/exit behaviour already matches XState v5. The ask is **diagnostics**.

**1. Reject the non-progressing construction at `create_machine()` time (primary).** An `always` transition whose target resolves to its own owning state can never make progress, because `entry` will not re-run and nothing else in the microstep mutates context. That is statically detectable. `create_machine()` should walk each state's `always` list and, for any entry whose target resolves to the owning state and that lacks `reenter: True`, raise a validation error naming the state:

```
always self-target on 'm.loop' can never make progress: the transition does not
re-enter the state, so 'entry' will not re-run. Add "reenter": True, route via an
intermediate state, or give the transition actions that mutate context.
```

This mirrors XState's documented rule ("If `target` is declared, the value should differ from the current state node") and its claim to "guard against most infinite loop scenarios". Validation belongs with the existing config checks invoked from `factory.py::create_machine`.

If raising is judged too breaking for a patch release, ship it as a `logger.warning` + `DeprecationWarning` in 0.8 and promote it to an error in 1.0 — but note that anyone hitting this warning has a machine that is already dead, so a hard error is the kinder option.

**2. Do not silently drop unknown transition keys.** `{"target": "loop", "internal": False}` currently vanishes. Either support `internal` as an accepted alias (`internal: False` ⇒ behave as `reenter: True`, preserving the v4 spelling for migrating users) or reject unknown transition keys with a clear `ValueError`. Silently discarding a key that changes intended semantics is the worst of the three options.

**3. Documentation.** Add a short "self-transitions" section stating plainly that an explicit self-target does **not** re-run `entry`/`exit` (matching XState v5), that `reenter: True` is how to opt in, and that `always` + self-target is invalid. This also resolves LC-04, which is a documentation gap rather than a bug.

## Acceptance criteria

- [ ] `create_machine()` raises (or, in 0.8, warns loudly) for an `always` transition whose target resolves to its own owning state without `reenter: True`, and the message names the offending state.
- [ ] The diagnostic does **not** fire for `always` self-targets that carry `reenter: True`, nor for those whose actions mutate context, nor for `always` transitions targeting a different state.
- [ ] `{"target": "loop", "internal": False}` either behaves as `reenter: True` or raises a clear `ValueError` — it is no longer silently discarded.
- [ ] Existing entry/exit semantics are **unchanged**: an explicit self-target still does not re-run `entry`/`exit` (this matches XState v5), and `reenter: True` still does.
- [ ] `SyncInterpreter` performs the same config-time validation (validation lives in `create_machine`, so this should follow automatically — assert it).
- [ ] Docs gain a self-transitions section covering targetless vs targeted vs `reenter: True`, mirroring the XState v5 table.
- [ ] Tests added:
  - `tests/test_self_transitions.py::test_always_self_target_is_rejected_at_build_time`
  - `tests/test_self_transitions.py::test_always_self_target_with_reenter_is_allowed_and_converges`
  - `tests/test_self_transitions.py::test_always_targeting_other_state_is_not_flagged`
  - `tests/test_self_transitions.py::test_internal_key_is_not_silently_dropped`
  - `tests/test_self_transitions.py::test_explicit_self_target_does_not_reenter`
  - `tests/test_self_transitions.py::test_targetless_transition_stays_internal`
  - `tests/test_self_transitions.py::test_sync_interpreter_self_transition_parity`
- [ ] `repro/LC-02_always-self-target-deadlock.py` exits `0` — under the fix `create_machine(SELF_LOOP, ...)` raises, so the repro must be updated to assert the validation error rather than the converged state.

## Related

- **LC-04** — explicit self-transition does not re-enter. Per the Expected behaviour section this is **correct XState v5 behaviour**; re-scope LC-04 from a bug to a documentation request and close it with item 3 above. It is no longer grouped into this issue as a defect.
- **LC-03** — same "silent no-op instead of an error" design family.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (`main`), editable install.
- Python: 3.13.7 (CPython), Windows 11.
- Repro run in a fresh process: output matches the **Observed behaviour** block verbatim; **exit code `1`**.
- Root cause re-checked against source: `base_interpreter.py:1767-1782` confirmed verbatim as quoted; `models.py:397` confirmed (`reenter` present, `internal` absent anywhere in the file).
- Additional runtime checks performed for this verification: adding `reenter: True` to the fallback makes the repro's machine converge to `['m.done']` with `n == 5`; adding `internal: False` behaves identically to the plain self-target (parks at `n == 1`), confirming the key is silently dropped.
- **Major correction.** The draft's Expected section quoted stately.ai as saying "Self-transitions are external by default." That sentence does not appear on https://stately.ai/docs/transitions, and the page's actual "Re-entering" section plus its three-row table state the opposite for v5: a targeted self-transition does **not** re-execute entry/exit. "External by default" is XState v4 terminology, which the v5 page explicitly flags as renamed to "re-entering". The semantic-change proposal (`self_transition_semantics="xstate"`, external-by-default) has therefore been **withdrawn**, and the issue re-scoped to the surviving, verified defects: the absent config-time diagnostic for a non-progressing `always` self-target (which XState v5 does document guarding against, per `/docs/eventless-transitions#avoid-infinite-loops`) and the silently dropped `internal` key. Summary, Root cause, Proposed fix, Acceptance criteria and Related were rewritten to match.
- Not a duplicate: the upstream tracker (`basiltt/xstate-statemachine`) has one issue, #17 (closed, camelCase→snake_case auto-discovery), unrelated.
