---
r6: R6-02
title: "Bug: the async chain budget exempts every system event (`interpreter.py:1427`), so an invoke cycle runs unbounded and silent on `Interpreter` while `SyncInterpreter` raises `RunawayChainError`"
labels: [bug, severity/high, area/interpreter, area/sync-interpreter, area/events]
severity: High
engines: async only (SyncInterpreter is correct)
repro_script: repro/R6-02_system_event_budget_exemption.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

`interpreter.py:1427` reads:

```python
if self._raise_depth > limit and not is_system_event(event):
```

with the comment *"The sync engine spares these by construction; mirror that here. It
still counts toward the depth (below) so a rollback->re-arm cycle stays bounded."*
**Both halves of that premise are false on this commit.** `sync_interpreter.py:786-829`
(#94) spares a completion only **at the moment of the trip** —
`spare = is_completion and not tripped` — and drops it thereafter. The async engine's
exemption is **unconditional**, so any cycle whose laps are engine completions is never
charged at all.

## Environment

- Library: `xstate-statemachine` @ `cec108b` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python 3.13.7, Windows 11
- Engines: async `Interpreter` fails; `SyncInterpreter` is the control and is correct
- Machine sets an explicit `maxIterations: 500`

## Minimal reproduction

Complete standalone script — also at `repro/R6-02_system_event_budget_exemption.py`.
Exit code **1** means the parity break was observed.

```python
# -*- coding: utf-8 -*-
"""R6-02 -- the async chain budget exempts EVERY system event
(`interpreter.py:1427`), so an invoke cycle runs unbounded and silent on
`Interpreter` while `SyncInterpreter` trips `RunawayChainError`.

Shape: two states, each with an `invoke` whose `onDone` targets the other.
Every lap is a `done.invoke.*` -- an engine completion -- so the async
exemption means the budget is never charged AT ALL.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the parity break was observed.
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

BUDGET_S = 8.0

CFG = {
    "id": "cyc",
    "initial": "idle",
    "maxIterations": 500,
    "states": {
        "idle": {"on": {"GO": "ver"}},
        "ver": {"invoke": {"id": "ver", "src": "svc",
                           "onDone": {"target": "#cyc.arm"}}},
        "arm": {"invoke": {"id": "arm", "src": "svc",
                           "onDone": {"target": "#cyc.ver"}}},
    },
}

laps = []


class Spy:
    """Minimal plugin: record every event the engine drops."""

    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((getattr(event, "type", event), reason))

    def __getattr__(self, _name):          # all other hooks are no-ops
        return lambda *a, **k: None


async def svc_async(interp, ctx, evt):
    laps.append(time.monotonic())
    return {"ok": 1}


def svc_sync(interp, ctx, evt):
    laps.append(time.monotonic())
    return {"ok": 1}


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={}, guards={},
            services={"svc": svc_sync if sync else svc_async},
        ),
    )


async def async_probe():
    laps.clear()
    spy = Spy()
    it = Interpreter(build(False), strict=False)
    it.use(spy)
    await asyncio.wait_for(it.start(), timeout=BUDGET_S)
    t0 = time.monotonic()
    await it.send("GO")
    while time.monotonic() - t0 < BUDGET_S and it.status == "running":
        await asyncio.sleep(0.25)
    dt = time.monotonic() - t0
    n = len(laps)
    print("async : %d laps in %.2fs (%.0f/s)" % (n, dt, n / dt))
    print("        status=%s  error=%r  last_transition_ok=%s  dropped=%r"
          % (it.status, it.error,
             getattr(it, "last_transition_ok", None), spy.dropped))
    signal = bool(spy.dropped) or it.error is not None
    await it.stop()
    return n, signal


def sync_probe():
    laps.clear()
    spy = Spy()
    it = SyncInterpreter(build(True), strict=False)
    it.use(spy)
    it.start()
    t0 = time.monotonic()
    r = it.send("GO", wait=True)
    dt = time.monotonic() - t0
    n = len(laps)
    err = type(r.error).__name__ if r is not None and r.error else None
    print("sync  : %d laps in %.2fs -> Receipt.error=%s" % (n, dt, err))
    print("        dropped=%r  last_transition_ok=%s"
          % (spy.dropped, getattr(it, "last_transition_ok", None)))
    it.stop()
    return n, bool(spy.dropped) or err is not None


def main():
    s_laps, s_signal = sync_probe()
    a_laps, a_signal = asyncio.run(async_probe())
    print()
    if s_signal and not a_signal:
        print("REPRODUCED: sync charges the budget and signals; async never "
              "charges it (%d async laps vs %d sync)." % (a_laps, s_laps))
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed (verbatim)

```
sync  : 502 laps in 0.02s -> Receipt.error=RunawayChainError
        dropped=[('done.invoke.arm', 'chain_budget')]  last_transition_ok=False
async : 82682 laps in 8.00s (10331/s)
        status=running  error=None  last_transition_ok=True  dropped=[]

REPRODUCED: sync charges the budget and signals; async never charges it (82682 async laps vs 502 sync).
```

Process exit code `1`. Same machine, same configuration, opposite outcomes. The async
side shows **no signal of any kind**: `status="running"`, `error is None`,
`last_transition_ok is True`, `on_event_dropped` never fires. Raising `maxIterations` is
**inert** — the exemption is unconditional, so the budget is never consulted.

## Expected

The async engine should charge engine completions to the chain budget once the chain has
tripped, exactly as `sync_interpreter.py:792` does, producing
`receipt.error=RunawayChainError`, `last_transition_ok=False` and
`on_event_dropped(reason="chain_budget")`.

- **SCXML** — [Algorithm for SCXML Interpretation](https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation)
  puts `done.invoke.*` on the **internal** event queue (*"internal event … raised
  automatically by the platform"*), and the macrostep completes only *"when the internal
  event queue is empty"*. A completion is therefore self-generated work in exactly the
  sense the budget exists to bound; nothing in the spec distinguishes it as exempt.
- **XState v5** — [Eventless transitions → "Avoid infinite loops"](https://stately.ai/docs/eventless-transitions):
  *"XState will help guard against most infinite loop scenarios."* v5 offers no mechanism
  for exempting `done.invoke.*` from a runaway guard.

## Root cause

- **`interpreter.py:1427`** — `not is_system_event(event)` makes the exemption
  unconditional. Because the guard short-circuits on the *whole* branch, the
  `on_event_dropped` / `RunawayChainError` reporting block below it never runs either, so
  the cycle is not merely unbounded but **unobservable**.
- **`sync_interpreter.py:786-829`** — the correct behaviour: *"A completion is spared ONLY
  at the moment of the trip"*, `spare = is_completion and not tripped`.

## Impact

Unbounded CPU, unbounded service invocations and unbounded silent side effects. In
**order management** the cycle shape is real and ordinary: a `verify` state invoking a
position read whose `onDone` targets an `arm` state invoking a stop-loss attach whose
`onDone` targets `verify` again — a guard that never flips (the exchange keeps reporting
no stop-loss) turns that into ~10 000 exchange calls per second, indefinitely, with the
machine reporting perfect health. That is a rate-limit ban at best and a wall of
duplicate order submissions at worst, and no wrapper can detect it because there is
nothing to look at.

## Why High and not Blocker

We originally scored this a Blocker and downgraded it on our own refutation pass, because
**the machine is not bricked**:

- after the cycle the escape hatch still works — an external event gives
  `changed=True, denied=False` and the machine leaves the cycle;
- the event loop is **not** starved;
- the configuration stays legal (exactly one leaf per region throughout);
- nothing is corrupted or lost.

Serious, but **externally recoverable**. We still consider it must-fix before we would
run money through it.

## Refutations attempted

- **API misuse?** No — no mandatory configuration is missing, `maxIterations` is set
  explicitly, and raising it is inert because the exemption is unconditional.
- **Sync-only?** No — sync is the correct side.
- **Duplicate of #144?** No. #144 was the sync nested-invoke `onDone` livelock, fixed via
  the "chain ends only when nothing self-generated remains" rule; it left the async
  exemption untouched.
- **Duplicate of #120?** No — #120 was filed and closed as a **documentation** issue
  about the #94 claim. This is the behavioural consequence: not a doc gap but a missing
  bound. See Related.

## One documentation sentence does support the async behaviour — and it is the one that is wrong

`docs/_guide/getting-started.md:462` states *"…engine completions are never"* cut by the
budget. The async engine matches that sentence exactly. But the sentence is falsified by
the sync engine's own behaviour on this commit, and contradicted by three other documents:

- `docs/_guide/core-concepts.md:639` — *"**Identical semantics on both engines.**"*
- `docs/api/index.md:1786` — names *"a cross-region `always` keeps re-arming an invoke"*
  as a cause of `RunawayChainError`, which is precisely this shape.
- `docs/_guide/json-config.md:110` — a trip *"is **observable** (0.8.1)"* via
  `receipt.error`, `last_transition_ok`, `last_error` and
  `on_event_dropped(reason="chain_budget")`.

So whichever way the team resolves it, **the docs currently disagree with each other** and
one of them must change along with the code.

## Proposed fix

Mirror #94 on the async engine: spare a completion only at the moment of the trip, then
charge it —

```python
spare = is_system_event(event) and not self._chain_tripped
if self._raise_depth > limit and not spare:
    ...
```

At minimum, fire `on_event_dropped` / set `RunawayChainError` on the exempted path so the
cycle is observable, and correct `docs/_guide/getting-started.md:462`.

Fixing this one line also closes the two companion reports we filed (R6-01, the
`always`-into-completed-`invoke` hang, and R6-03, the `rollback` + `onDone` re-invocation
spin) — they are the same root cause seen from different angles.

## Acceptance criteria

1. `tests/test_round6_findings.py::TestCompletionChargedToBudget::test_async_cycle_trips`
   — **ASYNC-engine pin.** The two-invoke `CFG` above on `Interpreter`; within 2 s the
   machine stops cycling and `interp.last_transition_ok is False`.
2. `…::test_async_trip_is_observable` — `on_event_dropped` fired at least once with
   `reason="chain_budget"`, and `last_error` / `receipt.error` is `RunawayChainError`.
3. `…::test_sync_parity` — `SyncInterpreter` on the identical machine produces the same
   `Receipt.error` and the same `on_event_dropped` reason.
4. `…::test_completion_spared_at_trip_not_after` — pins #94's rule on the async engine:
   the *tripping* completion is processed (the machine does not park in the invoking
   state), subsequent ones are dropped.
5. `…::test_max_iterations_is_respected` — lap count scales with `maxIterations`
   (e.g. 50 vs 500), proving the budget is actually consulted.
6. `docs/_guide/getting-started.md:462` updated to match the implemented semantics.

## Related

- **#120** (closed) — *'engine completions are never discarded' (#94) is implemented on
  the sync engine only.* Closest prior art, closed as a **docs** issue; this report
  deepens it to a behavioural bound that is missing entirely. Not a duplicate, but the
  two should be resolved together.
- **#94** (closed) — established `spare = is_completion and not tripped` on the sync
  engine; that rule is what `interpreter.py:1427` claims to mirror and does not.
- **#144** (closed) — the sync nested-invoke `onDone` livelock; same family, other engine.
- **#77** (closed), **#88**, **#90**, **#105** — chain-budget scoping history.
- **#137** (closed) — `is_system_event` is undocumented/unexported, which is part of why
  this exemption is hard to reason about from outside.
- **R6-01** and **R6-03** (this batch) — the two Blockers this one line produces.
- Our adoption audit (#26).

## Verification

Verified 2026-09-20 against `cec108b` (`.venv-main`, Python 3.13.7, Windows 11).

- **Repro run fresh:** `repro/R6-02_system_event_budget_exemption.py`; **exit code 1**.
  Output quoted verbatim in *Observed*: sync trips at 502 laps in 0.02 s with
  `RunawayChainError` and `on_event_dropped(('done.invoke.arm','chain_budget'))`; async
  ran 82 682 laps in 8.00 s with `status=running`, `error=None`,
  `last_transition_ok=True`, `dropped=[]`.
- **Embedded script checked byte-identical** to the file under `repro/`.
- **Source lines confirmed open:** `interpreter.py:1427`; the comment block at
  `interpreter.py:1421-1426`; the `on_event_dropped` / `last_transition_ok=False`
  reporting at `interpreter.py:1436-1440` (unreachable on the exempted path);
  `sync_interpreter.py:786` (*"A completion is spared ONLY at the moment of the trip"*)
  and `:792` (`spare = is_completion and not tripped`).
- **Doc citations confirmed:** `docs/_guide/getting-started.md:462`,
  `docs/_guide/core-concepts.md:639`, `docs/api/index.md:1786`,
  `docs/_guide/json-config.md:110` all read as quoted.
- **Citation URLs fetched:** W3C SCXML Appendix D (internal-event queue, macrostep
  termination) and XState v5 *Eventless transitions* both confirm the quoted text.
- **Duplicate check:** searches for `chain budget`, `system event`, `parity`, `livelock`.
  **#120** is the closest prior art and is CLOSED as a *documentation* issue about exactly
  this claim; it is retained in *Related* and explicitly distinguished (this report is the
  behavioural consequence, not the doc gap) rather than dropped. **#94**, **#144**,
  **#77**, **#88**, **#90**, **#105**, **#137** also retained. No open duplicate.
- **Labels** drawn only from the repository's label set; `area/async` and
  `area/engine-parity` do not exist and were replaced with `area/interpreter` /
  `area/sync-interpreter` / `area/events`.
- **No project-name leak.**
