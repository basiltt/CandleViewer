---
r8: R8-04
title: "Bug: on an `always` -> invoke -> `onDone` re-entry, events are delivered but silently do not apply (`_settle_tripped=True`, `last_error=None`); plus a `def`/`async def` `RunawayChainError` detectability gap"
labels: [bug, severity/medium, area/interpreter, events]
severity: Medium
engines: async `Interpreter`
service_kinds: both (detectability differs)
repro_script: repro/R8-04_always_ondone_reentry_settle_tripped.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

On an `always` → invoking child → `onDone` re-entry cycle, external events are **delivered
but silently do not apply**: `_settle_tripped` is `True` (`settle_iters=52`) while
`last_error is None`, `drops={}` and `status="running"`. Separately, the same shape shows a
genuine parity gap against #179: the runaway trips `RunawayChainError` on the `def` lane
(27 of 400 polled samples) but **never** on `async def` (0 of 400).

## What we withdrew before filing

We originally rated this High on a "permanent starvation, no fairness bound in
`_next_event`" theory. Both load-bearing claims failed our own refutation and we are
reporting the narrower thing that survived:

* **The starvation is not permanent.** With a 12 s settle, `on_event_received` fires
  300/300, both queues drain to 0, and the machine returns to stable `m.a`. Our earlier
  STUCK verdict came from a 10 s observation window.
* **The trigger is a chart the library documents as invalid.** The repro's unguarded
  `always -> b2` targets a state inside its own source region and so self-re-enables; with
  one event and zero external traffic it fires ~50×/s and trips `RunawayChainError` on both
  service kinds. `docs/api/index.md:1788` names this exact shape as a `RunawayChainError`
  cause, and `FEATURE_GAP_ANALYSIS.md:212` cites XState v5.31.0 `maxIterations` detection.
  Correct usage — a guarded `always`, the decision-state form in `faq.md:278` — gives
  300/300 EXT applied on **both** spellings, as does a legitimate
  invoke → `onDone` → re-enter cycle without the `always`. The invoke cycle is not the
  cause.

## Environment

* Commit `6db65d8` (unreleased 0.8.1; `__version__` reports `0.8.0`)
* Python 3.13.7, Windows 11
* Async `Interpreter`, both service spellings; a `SyncInterpreter` control row is included

## Observed (fresh run, `6db65d8`)

`repro/R8-04_always_ondone_reentry_settle_tripped.py` → **exit 1**
(`VERDICT: REPRODUCED`). 500 external `send("EXT", priority=True)` under an
`always` -> invoke -> `onDone` re-entry, `maxIterations=50`:

```
  SYNC engine, plain def:  EXT sent=500 APPLIED=500 (100.0%)
                           status=running last_error=None drops={}

  plain def   defect       EXT sent=500 received=379 APPLIED=353 (70.6%)
                           status=running last_error=None
                           drops={'drop:chain_budget': 173}
                           queues at end: inbox=496 priority=1 internal=0
  async def   defect       EXT sent=500 received=56  APPLIED=1   (0.2%)
                           status=running last_error=None  drops={}
                           queues at end: inbox=499 priority=444 internal=0

ablation A: drop the `always` (invoke onDone -> a is the only cycle)
  plain def   no-always    EXT sent=500 received=500 APPLIED=500 (100.0%)
  async def   no-always    EXT sent=500 received=500 APPLIED=500 (100.0%)
                           both: last_error=None drops={} queues drained

ablation B: drop the `invoke` (the `always` alone)
  plain def   no-invoke    EXT sent=500 received=500 APPLIED=1 (0.2%)
                           last_error=RunawayChainError
  async def   no-invoke    EXT sent=500 received=500 APPLIED=1 (0.2%)
                           last_error=RunawayChainError

VERDICT: REPRODUCED      exit code: 1
```

Reading the four cells together:

* **The `always` is necessary and the invoke is not the cause.** Ablation A (invoke cycle,
  no `always`) applies **500/500 on both spellings** and drains both queues.
* **Ablation B pins the trigger** on the unguarded `always`, which the library documents
  as an invalid chart — and which *does* report `RunawayChainError`, on both spellings.
* **The defect cell is the one that is silent.** With the `always` *and* the invoke, the
  machine sheds or starves external priority traffic while `status="running"` and
  `last_error is None` — on the `async def` arm, 499 of 500 external events never apply
  and **no drop hook fires at all**; on the `def` arm, 173 external events are shed as
  `chain_budget` with `last_error` still `None`.
* **The sync engine is clean** on the identical chart: 500/500 applied.

The `async def` arm's silence is the sharper half: ablation B shows the runaway *is*
detectable on this chart, and adding the invoke back makes the very same runaway
undetectable.

### Minimal reproduction — complete, standalone

Byte-identical to `repro/R8-04_always_ondone_reentry_settle_tripped.py`, including
both necessity ablations. Exits **1** while the defect is present, **0** once fixed.

```python
"""R18 -- D8-fuzz-3 MINIMAL: an `always` that re-enters the invoking child on
every completion spins without ever tripping the chain budget, and STARVES
external priority traffic. `async def` service only.

r17's instrumentation on the `always_into_invoke` shape:

    svc=asyncdef: status=running last_error=None
      always-transition fires    = 3042
      EXT received               =   60 of 500 sent
      EXT actions run            =    1
      queues at end: inbox=499  priority=440  (both backed up)
    svc=plaindef: same chart
      EXT received               =  500 of 500
      EXT actions run            =  486

So on the coroutine lane the machine consumes its own transient chain in
preference to 440 queued EXTERNAL priority events, reports
`last_error=None`, fires no `on_event_dropped`, and stays `"running"`. The
#180 promise ("external traffic of any volume is never throttled") and the
#179 promise ("both service kinds trip at the same lap count") both fail here
-- not by dropping, but by never getting to them.

This script is the standalone repro + the ablations that pin the cause.
"""
import asyncio, logging, warnings, collections, time
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()
RESULTS = []


class Spy(PluginBase):
    def on_event_received(self, interp, event):
        C[f"recv:{getattr(event,'type',event)}"] += 1

    def on_event_dropped(self, interp, event, reason=None, **kw):
        C[f"drop:{reason}"] += 1


CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 50,
    "context": {"ext": 0},
    "on": {"EXT": {"actions": ["extbump"]}},  # root handler: always matches
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "always": {"target": "b2"},
            "initial": "b2",
            "states": {
                "b2": {
                    "invoke": {"id": "s", "src": "svc", "onDone": {"target": "#m.a"}}
                }
            },
        },
    },
}


async def a_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


def logic(async_svc):
    return MachineLogic(
        services={"svc": a_svc if async_svc else p_svc},
        actions={"extbump": extbump},
    )


async def trial(async_svc, n=500, label=""):
    C.clear()
    it = Interpreter(create_machine(dict(CFG), logic=logic(async_svc)))
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    t0 = time.time()
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    await asyncio.sleep(1.0)
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    kind = "async def" if async_svc else "plain def"
    print(
        f"  {kind:<9} {label:<14} EXT sent={n} received={C['recv:EXT']} "
        f"APPLIED={applied} ({100*applied/n:.1f}%)\n"
        f"                            status={it.status} last_error={err} "
        f"drops={{k:v for k,v in C.items() if k.startswith('drop')}} = "
        f"{ {k: v for k, v in C.items() if k.startswith('drop')} }\n"
        f"                            queues at end: inbox={it._event_queue.qsize()} "
        f"priority={len(it._priority_queue)} internal={len(it._internal_queue)}"
    )
    await it.stop()
    return {"kind": kind, "label": label, "sent": n, "applied": applied,
            "status": it.status, "last_error": err,
            "drops": {k: v for k, v in C.items() if k.startswith("drop")}}


def sync_trial(n=500):
    C.clear()
    it = SyncInterpreter(create_machine(dict(CFG), logic=logic(False)))
    it.use(Spy())
    it.start()
    for _ in range(n):
        try:
            it.send("GO")
            it.send("EXT", priority=True)
        except Exception:
            pass
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    print(
        f"  SYNC engine, plain def:  EXT sent={n} APPLIED={applied} "
        f"({100*applied/n:.1f}%) status={it.status} last_error={err} "
        f"drops={ {k: v for k, v in C.items() if k.startswith('drop')} }"
    )
    it.stop()


async def main():
    print(
        "An external send(priority=True) must be applied whatever the machine "
        "is doing (#180).\n"
    )
    sync_trial()
    for a in (False, True):
        RESULTS.append(await trial(a, label="defect"))
    # --- ablation: remove the `always`, keep the invoke cycle
    print("\nablation A: drop the `always` (invoke onDone -> a is the only cycle)")
    global CFG
    keep = dict(CFG)
    CFG = {
        **keep,
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "initial": "b2",
                "states": {
                    "b2": {
                        "invoke": {
                            "id": "s",
                            "src": "svc",
                            "onDone": {"target": "#m.a"},
                        }
                    }
                },
            },
        },
    }
    for a in (False, True):
        await trial(a, label="no-always")
    # --- ablation: keep the `always`, drop the invoke
    print("\nablation B: drop the `invoke` (the `always` alone)")
    CFG = {
        **keep,
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"always": {"target": "b2"}, "initial": "b2", "states": {"b2": {}}},
        },
    }
    for a in (False, True):
        await trial(a, label="no-invoke")

    # --- verdict: on the defect shape external priority traffic must all apply
    bad = [r for r in RESULTS
           if r["applied"] < r["sent"] and r["last_error"] is None]
    print("\nVERDICT:", "REPRODUCED" if bad else "clean")
    for r in bad:
        print("  LOSS:", r)
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
```

## Root cause (source read at `6db65d8`)

`_next_event()` (`:1573-1583`) drains the priority lane and the transient/`always` chain
ahead of the inbox with no fairness bound; the chain-end reset at `:1725-1735` clears
`_raise_depth` every lap, because by the time the test runs each completion-driven `always`
re-entry "raised nothing, armed nothing, owes nothing". The async-lane half of the parity
gap has the same origin.

## What we are actually asking for

Two small things, neither urgent:

1. **Make the tripped settle observable.** `_settle_tripped=True` with `last_error=None`,
   `drops={}` and `status="running"` is indistinguishable from healthy, on a machine that is
   demonstrably not processing its inbox. A hook, an error, or a status is enough.
2. **Close the `def` / `async def` detectability parity gap**, or say in the docs that
   `RunawayChainError` detection for this shape is service-kind dependent.

Medium, not High: the trigger is a chart the library documents as invalid and detects on 3
of 4 engine × service-kind combinations, correct usage is clean on all 4, and nothing is
permanently stuck or lost. The residue is a detectability gap on an already-broken chart.

## Expected

The library's own contract, `docs/api/index.md:1788` on `RunawayChainError`:

> A self-generated event chain exceeded `maxIterations` and was cut (#77, #103). The
> machine stays `running`; the trip is reported here. … **a cross-region `always` keeps
> re-arming an invoke** … Surfaces as `receipt.error` / `last_error`.

That sentence names this exact chart, and promises the trip is *reported* on
`last_error`. On the `async def` arm it is not: `last_error is None`, `drops == {}`,
`status == "running"`, while 499 of 500 external events never apply. Ablation B proves the
promise is keepable — the same chart without the invoke does set `last_error`.

XState v5 makes the same commitment informally — *"XState will help guard against most
infinite loop scenarios"* — and its inspection API reports **every** microstep
(`@xstate.microstep`), so a spinning `always` is observable by construction rather than
inferred from a counter. SCXML §D notes a non-terminating macrostep "is currently
allowed", so the specification does not forbid the spin; it is the **unobservability**
that is the defect here, not the spin.

## Impact

**General.** A machine in this state is indistinguishable from a healthy one by every
signal the library exposes: `status`, `last_error`, `on_event_dropped`. A supervisor,
health check or readiness probe built on those three — which is what the documentation
directs users to build on — reports green while the machine processes 0.2 % of its inbox.
The secondary `def` / `async def` parity gap means a chart that a team validates on one
service spelling can be undetectable after a routine `def` → `async def` refactor that has
no statechart meaning.

**Order management.** The starved traffic here is specifically `priority=True` — the
kill-switch and risk-check lane. A risk halt that never applies, on a machine whose health
endpoint is green, is the failure mode an operator cannot act on because nothing tells
them to.

## Acceptance criteria

Named tests, parametrised over `("def", "async def")` services **and** both engines
(`Interpreter`, `SyncInterpreter`):

1. `test_settle_trip_is_observable[def|async def]` — when `_settle_tripped` becomes
   `True` (`interpreter.py:1933`), at least one of `last_error`, `status`, or an
   `on_event_dropped` / dedicated hook changes. Assert on the public surface only; a
   tripped settle must never present as healthy.
2. `test_runaway_detection_parity_across_service_kinds[def|async def]` — on the
   `always` -> invoke -> `onDone` chart, `RunawayChainError` is observed on **both**
   spellings, or on neither. The current 173-drops-vs-zero-drops split fails this.
3. `test_external_priority_applies_under_transient_chain[def|async def]` — external
   `send(priority=True)` traffic reaches ≥ 99 % application under a spinning transient
   chain, matching the `SyncInterpreter` control's 500/500 (#180's promise that external
   traffic is never throttled). Shares its fix surface with R8-01.
4. `test_always_ablations_are_clean[def|async def]` — both ablations keep their current
   behaviour: the invoke-only cycle applies 500/500, the `always`-only chart reports
   `RunawayChainError`. Guards against a fix that makes the defect cell observable by
   making the clean cells lossy.

## Related

* **#180** — external `send(priority=True)` must never be throttled or charged. The `def`
  arm's 173 `chain_budget` drops of external `EXT` events are #180's symptom under a
  different trigger; **R8-01 is the same root cause** and the two should be fixed
  together.
* **#179** — service-kind parity for completions. The `def` / `async def` detectability
  split here shows #179 is **narrower than claimed**: completions are now charged on both
  lanes, but whether the resulting trip is *reported* still depends on the spelling.
* **#168** — the async chain budget exempting system events, which made invoke cycles
  unbounded and silent. This is the same silence surviving on a narrower chart.
* **#112** — settling-budget trip leaving an orphaned leaf reported as healthy: the same
  "tripped but green" shape, on the configuration rather than the inbox.
* **#103 / #166 / #167** — prior `always`-into-invoke runaways, all closed.

## Verification

* Date: 2026-09-21 · Python 3.13.7 · commit `6db65d8`
* `repro/R8-04_always_ondone_reentry_settle_tripped.py` → **exit 1**
  (`VERDICT: REPRODUCED`), both service kinds plus a `SyncInterpreter` control and both
  necessity ablations in one script.
* Source confirmed open at `6db65d8`: `interpreter.py:1922-1936` sets `_settle_tripped`
  and assigns `_last_action_error` only on the settle path; `interpreter.py:1573-1583`
  drains the priority lane and transient chain ahead of the inbox with no fairness bound;
  `interpreter.py:1729-1736` clears `_raise_depth` on the "raised nothing, armed nothing,
  owes nothing" check every lap.
* Duplicate check: `gh issue list --state all --limit 240` over *always onDone* /
  *settle* — #103, #112, #144, #151, #166, #167, #168 all CLOSED; no open duplicate.
