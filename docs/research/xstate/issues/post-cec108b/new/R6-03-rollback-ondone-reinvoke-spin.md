---
r6: R6-03
title: "Bug: `actionErrorPolicy: \"rollback\"` + `invoke.onDone` re-arms the invoke for ever — ~10 000 service invocations/sec, unbounded, with `status=\"running\"` and `error is None` (async only)"
labels: [bug, severity/blocker, area/interpreter, area/sync-interpreter]
severity: Blocker
engines: async only (SyncInterpreter is correct)
repro_script: repro/R6-03_rollback_ondone_reinvoke_spin.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

Under the default `actionErrorPolicy: "rollback"`, a raising entry action on a state
reached from an `invoke.onDone` rolls the machine **back into the invoking state**, which
re-arms the invoke, which completes, which fires `onDone`, which raises again — for ever.
One user-visible event produces **~20 000 service invocations in 2.0 seconds** with
`status="running"` and `.error is None`.

`SyncInterpreter` is correct on the identical machine: **2 invocations**, then quiescent.

## Environment

- Library: `xstate-statemachine` @ `cec108b` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python 3.13.7, Windows 11
- Engines: async `Interpreter` fails; `SyncInterpreter` is the control and is correct
- `actionErrorPolicy: "rollback"` — the documented 1.0 default policy

## Minimal reproduction

Complete standalone script — also at `repro/R6-03_rollback_ondone_reinvoke_spin.py`.
Exit code **1** means the unbounded re-arm was observed.

```python
# -*- coding: utf-8 -*-
"""R6-03 -- `actionErrorPolicy: "rollback"` + `invoke.onDone` re-arms the invoke
for ever.

Shape (minimised):
    starting --invoke svc--> onDone --> recording
    recording.entry = [boom]          (raises)
    rollback undoes the entry, returning to `starting`
    re-entering `starting` re-arms the invoke, the service runs again, ...

Nothing bounds this: not maxIterations, not the chain budget, not the settle
budget -- because every lap is a *separate* macrostep driven by a genuine
engine completion (`done.invoke.svc`), which `interpreter.py:1427` exempts
from the chain budget unconditionally.

SyncInterpreter on the identical machine is quiescent after 2 invocations.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the unbounded async re-arm was observed.
"""
import asyncio
import copy
import logging
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {"id": "s", "src": "svc",
                       "onDone": {"target": "#spin.recording"}},
        },
        "recording": {"entry": ["boom"]},
    },
}

calls = []


async def svc_async(interp, ctx, evt):
    calls.append(time.monotonic())
    return {"ok": True}


def svc_sync(interp, ctx, evt):
    calls.append(time.monotonic())
    return {"ok": True}


def boom(interp, ctx, evt, ad):
    raise RuntimeError("entry action failed")


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={"boom": boom},
            services={"svc": svc_sync if sync else svc_async},
        ),
    )


async def async_probe():
    calls.clear()
    it = Interpreter(build(False))
    await it.start()
    t0 = time.monotonic()
    for _ in range(4):
        await asyncio.sleep(0.5)
        print("async : t=%.1fs  service invocations=%-6d  state=%s  status=%s"
              % (time.monotonic() - t0, len(calls),
                 sorted(it.current_state_ids), it.status))
    n = len(calls)
    print("        status=%s  .error=%r  last_transition_ok=%s"
          % (it.status, it.error, getattr(it, "last_transition_ok", None)))
    await it.stop()
    return n


def sync_probe():
    calls.clear()
    it = SyncInterpreter(build(True))
    it.start()
    time.sleep(0.5)
    n = len(calls)
    print("sync  : %d service invocations, state=%s status=%s"
          % (n, sorted(it.current_state_ids), it.status))
    it.stop()
    return n


def main():
    s_n = sync_probe()
    a_n = asyncio.run(async_probe())
    print()
    if a_n > 100 * max(s_n, 1):
        print("REPRODUCED: async %d invocations in 2.0s for ONE user-visible "
              "event; sync %d then quiescent." % (a_n, s_n))
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed (verbatim)

```
sync  : 2 service invocations, state=['spin.starting'] status=running
async : t=0.5s  service invocations=4901    state=['spin.starting']  status=running
async : t=1.0s  service invocations=9779    state=['spin.starting']  status=running
async : t=1.5s  service invocations=14834   state=['spin.starting']  status=running
async : t=2.0s  service invocations=19903   state=['spin.starting']  status=running
        status=running  .error=None  last_transition_ok=False

REPRODUCED: async 19903 invocations in 2.0s for ONE user-visible event; sync 2 then quiescent.
```

Process exit code `1`. The rate is linear and does not decay; we let it run for 60 s
without a trip. An **explicit `maxIterations=5`** does not change it — each lap is a
separate macrostep driven by a genuine `done.invoke.s`, so nothing is ever charged to
the chain budget. `interp.error` stays `None` and `on_event_dropped` never fires; the
only signal is `last_transition_ok=False`, which is indistinguishable from a single
recovered failure.

## Expected

The `rollback` → re-arm → `done.invoke` cycle is charged to the chain budget and
terminates with `RunawayChainError` reported on `receipt.error` / `last_error`, with
`on_event_dropped(reason="chain_budget")` — exactly as `SyncInterpreter` behaves.

- **SCXML** — [Algorithm for SCXML Interpretation](https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation):
  *"invocations are triggered only when the state machine has reached a stable
  configuration, i.e., one that it will be staying in while it waits"*, and a macrostep
  ends *"where the internal event queue is empty"*. A configuration that is re-entered by
  a rollback is by construction not stable, so re-arming the `<invoke>` on every lap is
  not spec-conformant.
- **XState v5** — [Eventless transitions → "Avoid infinite loops"](https://stately.ai/docs/eventless-transitions):
  *"XState will help guard against most infinite loop scenarios."* v5 has no
  `actionErrorPolicy`/rollback concept at all, so there is no upstream precedent that
  endorses an unbounded re-arm.

## Root cause

`interpreter.py:1427` — `if self._raise_depth > limit and not is_system_event(event):`.
Every lap of this cycle is delivered as `done.invoke.s`, an engine completion, so the
exemption is unconditional and the budget is never charged. The in-source comment at
`interpreter.py:1421-1426` explicitly claims the opposite: *"It still counts toward the
depth (below) so a rollback->re-arm cycle stays bounded."* It does not — the `and not
is_system_event(event)` short-circuits the whole branch, including the depth accounting
and the `on_event_dropped` reporting at `interpreter.py:1436-1440`.

`sync_interpreter.py:786-829` has the correct rule (`spare = is_completion and not
tripped`), which is why the sync control stops at 2 invocations.

## Impact

`actionErrorPolicy: "rollback"` is the documented default, so this is reachable with no
unusual configuration, and the triggering shape — a state with an `invoke` whose `onDone`
target has entry actions that can raise — is extremely ordinary.

For **order management** the service being re-invoked ~10 000 times a second is an order
placement or a stop-loss attach. A single transient bug in a fill-recording entry action
turns one `PLACE` into a flood of duplicate submissions against the exchange, bounded only
by how fast an operator notices — and the machine reports `running` with `.error is None`
throughout, so no health check fires. It is mandatory in our own configuration standard,
and the shape is carried by four of five machines in one of our contract groups; we have
had to invert a constraint we wrote a round ago and **forbid** `"rollback"` on order-path
states carrying an `invoke`, in favour of `"fail"` (which #145 made safe).

## Mitigations we found (weighed, and insufficient)

Being fair to the failure mode: **the event loop is not starved.** Heartbeat gaps stay
≤ 0.7 ms, and `send("ABORT")` is accepted at 0.000 s latency and halts the spin. The
individual failures *are* observable via `on_transition_failed` and `last_transition_ok`.

What is missing is a **bound** and a **terminal state**. The damage is done by the time
anybody sends `ABORT`, and `last_transition_ok=False` on its own cannot distinguish "one
action failed and recovered" from "20 000 failures per second".

## Refutations attempted

- **Documented?** No. `docs/_guide/reliability.md` defines `rollback` as *configuration
  and context restored, machine still running*; it does not warn that restoring the
  configuration **re-arms an `invoke`**, which is the entire mechanism here.
- **Bounded by design?** No — `CHANGELOG` for #94 and the comment at
  `interpreter.py:1421-1426` both assert *"a rollback → re-arm → done cycle stays
  bounded"*. That claim is false on the async engine on this commit.
- **API misuse?** No — default policy, ordinary shape, explicit `maxIterations` is inert.
- **Sync-only?** No — sync is the correct side.
- **Duplicate of #103, #144 or #94?** No — those are sync-engine or
  self-generated-chain fixes, and we verified they do not apply to this path.

## Proposed fix

Charge each `rollback` → re-arm → `done.invoke` lap to the chain budget so the cycle
terminates with `RunawayChainError`, as the sync engine does — i.e. fix
`interpreter.py:1427` per R6-02.

If the design view is that a rollback cycle genuinely should not be charged, then at
minimum **fire `on_event_dropped` and set `RunawayChainError` on the exempted path** so
the spin is *observable*. Silence is the unacceptable part: an unbounded loop that reports
`running` / `error=None` cannot be wrapped, because there is nothing for a wrapper to look
at. Separately, `docs/_guide/reliability.md` should state that a rollback into an invoking
state re-arms that invoke.

## Acceptance criteria

1. `tests/test_round6_findings.py::TestRollbackReinvokeBounded::test_async_cycle_terminates`
   — **ASYNC-engine pin.** The `CFG` above on `Interpreter`; after 2 s of wall time the
   service call count is `< 100` (today it is ~20 000).
2. `…::test_async_trip_is_observable` — `interp.last_error` (or the `send` receipt's
   `.error`) is `RunawayChainError`, and `on_event_dropped` fired with
   `reason="chain_budget"`.
3. `…::test_sync_parity` — `SyncInterpreter` on the identical machine records the same
   bounded call count and the same reported error.
4. `…::test_max_iterations_scales` — the bound tracks `maxIterations` (e.g. 5 vs 500),
   proving the budget is consulted on this path.
5. `…::test_fail_policy_unaffected` — the same machine under
   `actionErrorPolicy: "fail"` still behaves per #145 (no regression).
6. `docs/_guide/reliability.md` documents that `rollback` into an invoking state re-arms
   the invoke.

## Related

- **#94** (closed) — its `CHANGELOG` entry claims *"a rollback → re-arm → done cycle
  remains bounded"*; that claim holds on sync and is false on async here.
- **#120** (closed) — *'engine completions are never discarded' (#94) is implemented on
  the sync engine only*. Same asymmetry; this is its behavioural consequence for the
  rollback path.
- **#144** (closed) — the sync nested-invoke `onDone` livelock. Same family, other engine;
  not a duplicate, its pin is sync-scoped.
- **#145** (closed) — `actionErrorPolicy: "fail"`; the policy we have had to switch to,
  so its guarantees are load-bearing for us now.
- **#27** (closed) — an action that raises still commits the transition; the origin of
  `actionErrorPolicy`.
- **#103** (closed) — the sync cross-region `always` re-entering an invoking state.
- **R6-01** and **R6-02** (this batch) — the same `interpreter.py:1427` exemption from two
  other directions; one change should close all three.
- Our adoption audit (#26).

## Verification

Verified 2026-09-20 against `cec108b` (`.venv-main`, Python 3.13.7, Windows 11).

- **Repro run fresh:** `repro/R6-03_rollback_ondone_reinvoke_spin.py`; **exit code 1**.
  Output quoted verbatim in *Observed*: sync 2 invocations then quiescent; async 19 903
  invocations in 2.0 s with `status=running`, `.error=None`. Re-run three times; the async
  count ranged 19 900–20 900 and the sync control was 2 every time.
- **Embedded script checked byte-identical** to the file under `repro/`.
- **Source lines confirmed open:** `interpreter.py:1427` (the exemption);
  `interpreter.py:1421-1426` — the comment asserting *"It still counts toward the depth
  (below) so a rollback->re-arm cycle stays bounded"*, which the `and not
  is_system_event(event)` short-circuit falsifies; `interpreter.py:1436-1440` (the
  unreachable reporting block); `sync_interpreter.py:786-829` (the correct rule).
- **Doc citation confirmed:** `docs/_guide/reliability.md` exists and defines `rollback`
  without mentioning invoke re-arming.
- **Citation URLs fetched:** W3C SCXML Appendix D — the `<invoke>` "stable configuration"
  rule in §6.1 and the run-to-completion macrostep definition — and XState v5 *Eventless
  transitions*; both confirm the quoted text, and v5 confirmed to have no
  `actionErrorPolicy` analogue.
- **Duplicate check:** searches for `rollback`, `chain budget`, `always`, `parity`.
  **#27**, **#94**, **#103**, **#120**, **#144**, **#145** are the relevant CLOSED issues
  and are all retained in *Related*; none duplicates this path (verified that #103/#144
  are sync-engine fixes and #94's bounded-rollback claim holds only on sync). No open
  duplicate.
- **Labels** drawn only from the repository's label set; `area/async` and
  `area/error-policy` do not exist and were replaced with `area/interpreter` /
  `area/sync-interpreter`.
- **No project-name leak.**
