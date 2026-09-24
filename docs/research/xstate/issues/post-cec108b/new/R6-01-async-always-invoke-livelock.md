---
r6: R6-01
title: "Bug: `await Interpreter.send(EV, wait=True)` never resolves and the event loop burns a core when an `always` descends into a child with a completed `invoke` (#144's chain-budget fix landed on `SyncInterpreter` only)"
labels: [bug, severity/blocker, area/interpreter, area/events]
severity: Blocker
engines: async only (SyncInterpreter is correct)
repro_script: repro/R6-01_async_always_invoke_livelock.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

On the async `Interpreter`, an event that re-enters a compound state whose `always`
transition descends into a child carrying an `invoke` **livelocks the run loop** once
that invoke has completed. `await send(EV, wait=True)` never resolves, the machine
reports `status="running"` with `error is None`, and one core is pegged indefinitely.

`SyncInterpreter` returns in **0.08 s** on the identical configuration with
`RunawayChainError` and `last_transition_ok=False`. This is #144's fix — *"a chain
ends only when nothing self-generated remains queued"* — which shipped in
`sync_interpreter.py` and was never ported to `interpreter.py`.

## Environment

- Library: `xstate-statemachine` @ `cec108b` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python 3.13.7, Windows 11
- Engines: async `Interpreter` fails; `SyncInterpreter` is the control and is correct
- No plugins, no custom clock, default `maxIterations`

## Minimal reproduction

Complete standalone script — also at `repro/R6-01_async_always_invoke_livelock.py`.
Exit code **1** means the livelock was observed (the 5 s watchdog fired).

```python
# -*- coding: utf-8 -*-
"""R6-01 -- async Interpreter livelock: `always` descending into a child that
carries a COMPLETED `invoke`.

`await send("GO", wait=True)` never resolves; status stays "running", .error is
None, and one core is pegged. SyncInterpreter on the identical machine trips
RunawayChainError and returns.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the livelock was observed (watchdog fired).
"""
import asyncio
import copy
import logging
import threading
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

WATCHDOG = 5.0

CFG = {
    "id": "m",
    "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a", "guard": "g"},
            "states": {"a": {"invoke": {"id": "i", "src": "svc"}}},
        },
    },
}


def svc(interp, ctx, evt):
    return {"ok": 1}


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={},
            guards={"g": lambda c, e: True},
            services={"svc": svc},
        ),
    )


async def async_probe():
    it = Interpreter(build(False), strict=False)
    await asyncio.wait_for(it.start(), timeout=WATCHDOG)
    await asyncio.sleep(0.05)         # let the first invoke complete
    task = asyncio.ensure_future(it.send("GO", wait=True))
    done, _ = await asyncio.wait({task}, timeout=WATCHDOG)
    if done:
        print("async : send resolved -> %r" % (task.result(),))
        hung = False
    else:
        print("async : HANG -- no receipt after %.1fs  status=%s  error=%r"
              % (WATCHDOG, it.status, it.error))
        task.cancel()
        hung = True
    await it.stop()
    return hung


def sync_probe():
    it = SyncInterpreter(build(True), strict=False)
    box = {}

    def run():
        try:
            it.start()
            box["r"] = it.send("GO", wait=True)
        except BaseException as exc:      # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=run, daemon=True)
    t0 = time.monotonic()
    th.start()
    th.join(WATCHDOG)
    if th.is_alive():
        print("sync  : HANG after %.1fs" % WATCHDOG)
        return True
    dt = time.monotonic() - t0
    r = box.get("r")
    print("sync  : returned in %.2fs  ok=%s  err=%s"
          % (dt, getattr(it, "last_transition_ok", None),
             type(r.error).__name__ if r is not None and r.error else
             type(box.get("exc")).__name__ if box.get("exc") else None))
    return False


def main():
    sync_hung = sync_probe()
    async_hung = asyncio.run(async_probe())
    print()
    if async_hung and not sync_hung:
        print("REPRODUCED: async livelocks where sync terminates.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed (verbatim)

```
sync  : returned in 0.08s  ok=False  err=RunawayChainError
async : HANG -- no receipt after 5.0s  status=running  error=None

REPRODUCED: async livelocks where sync terminates.
```

Process exit code `1`. Instrumented during the pending `send`: ~23 000
`_process_event` calls in a 3-second window, alternating `done.invoke.i` and the
`always`, `qsize` pinned at 1, RSS flat, one core saturated. It is a **livelock**, not a
queue explosion — the *receipt* at `interpreter.py:1560` is simply never constructed.

Ablations (async): remove the `always` → resolves in 0.00 s; remove the `invoke` →
resolves in 0.04 s; do not let the invoke settle → resolves in 0.16 s. Both the `always`
**and** a *completed* `invoke` are necessary. `maxIterations=1` and `maxIterations=1000`
both hang, as do internal and external triggering events.

## Expected

The macrostep terminates and `send(..., wait=True)` resolves with a receipt, or the
runaway guard trips observably (`receipt.error=RunawayChainError`,
`last_transition_ok=False`, `on_event_dropped(reason="chain_budget")`) exactly as
`SyncInterpreter` does here.

- **SCXML** — [Algorithm for SCXML Interpretation, `mainEventLoop`](https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation):
  *"A macrostep is a series of one or more microsteps ending in a configuration where the
  internal event queue is empty and no transitions are enabled by NULL."* SCXML also
  requires the `<invoke>` handler to run **after** the macrostep completes — *"only after
  checking for eventless transitions and transitions driven by pending internal events …
  invocations are triggered only when the state machine has reached a stable
  configuration"* — so an invoke that keeps re-arming inside an unsettled `always` chain
  is not a legal macrostep.
- **XState v5** — [Eventless (`always`) transitions → "Avoid infinite loops"](https://stately.ai/docs/eventless-transitions):
  *"XState will help guard against most infinite loop scenarios."* v5 bounds the
  microstep loop with **no exemption for engine completions**; this library cites that
  same guard at `interpreter.py:1678` (*"XState added the same guard in v5.31.0"*).

## Root cause

1. **`interpreter.py:1427`** —
   `if self._raise_depth > limit and not is_system_event(event):`
   Every second lap of this cycle is an engine completion (`done.invoke.i`), so the chain
   budget is **never charged**, not merely exceeded. The in-source comment claims *"The
   sync engine spares these by construction; mirror that here"*, but
   `sync_interpreter.py:792` spares a completion only at the moment of the trip
   (`spare = is_completion and not tripped`). See the companion report R6-02.
2. **`interpreter.py::_run_event_loop`** — the async macrostep-termination condition never
   concludes a self-generated `always` chain once the invoke has completed.
   `sync_interpreter.py:768-829` carries #144's rule; `interpreter.py` does not.

## Impact

An `await send(...)` on an **order-management path** that never returns, plus a silently
pegged core, while every health signal reads clean (`status="running"`, `error is None`,
`on_event_dropped` empty). A supervisor cannot distinguish it from a slow exchange
call, so it will not fail over; meanwhile the order-state machine is wedged mid-flight
with an unacknowledged `PLACE`/`CANCEL` and the operator has no signal to act on.
There is no configuration that bounds it — `maxIterations` is inert by construction
because of the exemption.

## The `always` is not load-bearing — this is #144 on the other engine

The **literal #144 configuration** (nested invokes whose `onDone` targets their common
compound ancestor, *no `always` anywhere*) also hangs on async, while sync trips
`RunawayChainError`:

```
literal #144 config:  sync -> RunawayChainError, returns
                      async -> ~34 000 invocations in 2 s, status="running", no trip
```

We have not reopened #144: its acceptance criteria as written are met and its pin
(`tests/test_round5_findings.py::TestInvokeCycleTerminates`) is correctly scoped to the
sync engine. But the two are one root cause and we would expect one change to close both.

## Refutations we attempted, and why each failed

- **Documented?** No — the opposite. `docs/_guide/json-config.md:110` and
  `docs/_guide/troubleshooting.md:49` promise an observable trip via
  `receipt.error` / `last_error` / `on_event_dropped`, and that `RunawayChainError` is
  *"never raised"* — i.e. always reported.
- **API misuse?** No. No mandatory configuration is missing; no `maxIterations` value
  bounds it.
- **Sync-only concern?** No — sync is the **control**, and the async engine is the one
  our deployment requires.
- **Superseded?** No note in `CHANGELOG.md [Unreleased]` addresses it.

## Proposed fix

Port #144's termination rule from `sync_interpreter.py:768-829` into
`interpreter.py::_run_event_loop`, so a macrostep concludes only when nothing
self-generated remains queued, and make the async chain-budget test at
`interpreter.py:1427` charge completions (see R6-02).

**Please also consider an `Interpreter`/`SyncInterpreter` parity test class** — a handful
of pathological configurations asserting both engines reach the same terminal
disposition. Three of the four candidate Blockers we found this round are "fixed on the
engine the issue was filed against", and all three would have been caught by such a class
before review.

## Acceptance criteria

1. `tests/test_round6_findings.py::TestAlwaysIntoCompletedInvoke::test_async_send_resolves`
   — **ASYNC-engine pin.** Builds the `CFG` above on `Interpreter`, `await
   asyncio.wait_for(it.send("GO", wait=True), timeout=5)` resolves; asserts no
   `asyncio.TimeoutError`.
2. `…::test_async_trip_is_observable` — if the resolution is a budget trip rather than a
   clean settle, `receipt.error` is `RunawayChainError`, `last_transition_ok is False`,
   and `on_event_dropped` fired with `reason="chain_budget"`.
3. `…::test_sync_parity` — `SyncInterpreter` on the identical machine reaches the same
   terminal disposition as `Interpreter` (guards against "fixed by breaking sync").
4. `…::test_literal_144_config_async` — **ASYNC-engine pin** of the nested-invoke
   `onDone`-to-ancestor shape from #144: `await asyncio.wait_for(it.start(), 5)` and a
   subsequent `send` both complete.
5. `…::test_max_iterations_is_not_required` — the above hold at default `maxIterations`,
   at `maxIterations=1`, and at `maxIterations=1000`.
6. A CPU-sanity assertion: fewer than 1 000 `_process_event` calls over the whole test.

## Related

- **#144** (closed) — *nested invokes whose `onDone` targets their common compound
  ancestor livelock `SyncInterpreter.start()`*. Same root cause, sync side; its fix was
  not ported to `interpreter.py`. Its pin is correctly sync-scoped, so we did **not**
  reopen it.
- **#120** (closed) — *'engine completions are never discarded' (#94) is implemented on
  the sync engine only*. This is the same async/sync asymmetry, deepened: the async
  exemption is not merely a doc gap, it removes the bound entirely.
- **#94** (closed) — established that a completion is spared **only at the moment of the
  trip**; `interpreter.py:1427` spares unconditionally.
- **#103** (closed) — the sync analogue for a cross-region `always` re-entering an
  invoking state.
- **R6-02** (this batch) — the `interpreter.py:1427` exemption in isolation.
- **R6-03** (this batch) — the same exemption reached via `rollback` + `onDone`.
- Our adoption audit (#26).

## Verification

Verified 2026-09-20 against `cec108b` (`.venv-main`, Python 3.13.7, Windows 11).

- **Repro run fresh:** `repro/R6-01_async_always_invoke_livelock.py` executed in a clean
  process; **exit code 1** (watchdog fired — the livelock is the observed result). Output
  quoted verbatim in *Observed*. Sync control returned in 0.09 s with
  `RunawayChainError` / `last_transition_ok=False`; async produced no receipt after 5.0 s
  with `status=running`, `error=None`.
- **Embedded script checked byte-identical** to the file under `repro/`.
- **Source lines confirmed open:** `interpreter.py:1427` is exactly
  `if self._raise_depth > limit and not is_system_event(event):`;
  `interpreter.py:1421-1426` carries the "#120 … mirror that here" comment;
  `interpreter.py:1560` is the receipt construction; `interpreter.py:1678` carries the
  *"XState added the same guard in v5.31.0"* comment;
  `sync_interpreter.py:768-829` carries the #144/#94 rule with
  `spare = is_completion and not tripped` at `:792`.
- **Doc citations confirmed:** `docs/_guide/json-config.md:110` and
  `docs/_guide/troubleshooting.md:49` read as quoted.
- **Citation URLs fetched:** W3C SCXML Appendix D (macrostep/`mainEventLoop` definition and
  the `<invoke>`-after-stable-configuration rule) and the XState v5 *Eventless (always)
  transitions* page ("Avoid infinite loops") both confirm the quoted text.
- **Duplicate check:** `gh issue list -R basiltt/xstate-statemachine --state all --limit 200`
  for `livelock`, `chain budget`, `always`, `system event`, `parity`. Nearest prior art is
  **#144**, **#120**, **#103**, **#94** — all CLOSED, all retained in *Related*; none is a
  duplicate (#144's pin, `tests/test_round5_findings.py::TestInvokeCycleTerminates`, is
  correctly sync-scoped and still passes). No open issue covers this.
- **Labels** drawn only from the repository's label set; `area/async` and
  `area/engine-parity` do not exist and were replaced with `area/interpreter` /
  `area/events`.
- **No project-name leak.**
