---
r8: R8-01
title: "Bug: the priority lane charges by provenance and sheds by position — a `send(priority=True)` issued from an action livelocks unbounded and silently; an external one is destroyed as `chain_budget`"
labels: [bug, severity/blocker, area/interpreter]
severity: Blocker
engines: async `Interpreter`
service_kinds: both `def` and `async def`
repro_script: repro/R8-01_priority_self_send_livelock.py, repro/R8-01_external_priority_shed.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

#180 taught the **charge** site of the priority lane to decide by *who issued* an event.
The **shed** site was never taught the same rule, and still decides by *where the event
sits in the queue*. Both sites operate on a single FIFO (`_priority_queue`) that carries
engine completions and public `send(..., priority=True)` events together, so the ledger is
now wrong in both directions:

* a priority event **issued from the machine's own action** is never charged, so
  `maxIterations` is inert on that lane and the machine livelocks — unbounded, and with
  every health signal green;
* a genuinely **external** priority event sitting at the head of the FIFO when an unrelated
  self-generated chain trips is **destroyed** with `reason="chain_budget"`, while `send()`
  reports success and `last_error` reads `None`.

This is the regression surface of #180 itself. Please do not cut 0.8.1 until it lands.

## Environment

* Commit `6db65d8` (unreleased 0.8.1; `__version__` reports `0.8.0`)
* Python 3.13.7, Windows 11
* Async `Interpreter` only (`SyncInterpreter` has no priority lane)
* Both service spellings, `def` and `async def`

## Reproduction (both halves, both service spellings, `6db65d8`)

### (a) Self-issued priority send → unbounded, unobservable livelock

`repro/R8-01_priority_self_send_livelock.py` → `result: FAIL`.

```
4 cells run as isolated child processes, maxIterations=25:

  self_send=plain  def        -> bounded: laps=27, trip_observable=true,
                                 RunawayChainError, drops={'chain_budget': 1}
  self_send=plain  async def  -> bounded: laps=27, trip_observable=true,
                                 RunawayChainError, drops={'chain_budget': 1}
  self_send=prio   def        -> LIVELOCK, trip_observable=false
  self_send=prio   async def  -> LIVELOCK, trip_observable=false

  detail (both prio cells): "child process exceeded a 20s WALL watchdog:
  the spin starves the event loop, so even asyncio.wait_for() inside the
  process never fires"

  result: FAIL      exit code: 1
```

The `self_send="plain"` rows **are** the `priority=False` control: the identical
machine, identical `maxIterations`, differing only in the `priority=` kwarg — it trips
at lap 27 against a limit of 25 and fires a `chain_budget` drop.

A **process-level** watchdog is required to observe the defect at all: the spin starves
the loop so hard that an in-process `asyncio.wait_for` never fires and `stop()` never
returns.

### (b) External priority send → silently destroyed at an already-tripped chain

`repro/R8-01_external_priority_shed.py` → verdict line `REPRODUCED`. 2 000 external `EXT`
sends during a self-generated invoke cycle, `maxIterations=50`:

```
{'kind': 'plain', 'external_sent': 2000, 'send_accepted_no_raise': 2000,
 'external_applied': 1990, 'external_LOST': 10,
 'chain_budget_drops_by_type': {'EXT': 10, 'done.invoke.pp.a': 1},
 'last_error': None,
 'VERDICT': 'REPRODUCED: external sends shed as chain_budget'}
{'kind': 'async', 'external_sent': 2000, 'send_accepted_no_raise': 2000,
 'external_applied': 2000, 'external_LOST': 0,
 'chain_budget_drops_by_type': {'done.invoke.pp.b': 1},
 'last_error': 'RunawayChainError', 'VERDICT': 'clean'}
exit code: 1
```

The loss count is load-dependent (8–10 across runs); the `EXT` entry in
`chain_budget_drops_by_type` — an *external* event type shed with `reason="chain_budget"`
— is the invariant. Control with `priority=False` under identical load: **0 lost**, on
both service kinds.

### Minimal reproduction (a) — complete, standalone

Byte-identical to `repro/R8-01_priority_self_send_livelock.py`. Exits **1** while the
defect is present, **0** once fixed. Half (b) is
`repro/R8-01_external_priority_shed.py`, whose full output is quoted above.

```python
"""R8b - MINIMAL: a `send(priority=True)` issued FROM AN ENTRY ACTION is an
UNBOUNDED self-feeding loop. `maxIterations` never trips, `stop()` never
returns, and no hook fires: the machine spins for ever, silently.

#180: "External `send(priority=True)` is never charged ... Accounting is
by *who issued it*: only engine completions and self-raised events count."
The implementation decides "external" by the `engine_completion` kwarg on
`_deliver_priority` (interpreter.py:2342-2375), which is False for EVERY
`send(priority=True)` -- including one issued by the machine's own action,
which is self-generated work by the very definition #180 states. The
non-priority path DOES route an action's own send to the internal queue
and charge it (`_issued_from_own_action()`, interpreter.py:898-908);
`priority=True` bypasses that branch entirely.

Contrast rows in this probe:
  priority_self_send      -> unbounded, stop() hangs         (the defect)
  plain_self_send         -> bounded by maxIterations, trips (the control)

Both service kinds; the async engine only (SyncInterpreter has no
priority lane). Watchdog 8 s -- a timeout IS the observed result.
"""
import asyncio, json, os, sys, time
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 SyncInterpreter, create_machine)

KINDS = ("def", "async def")


def emit(name, data):
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    print(txt)


def make_service(kind, delay=0.0, value=None):
    val = {"v": 1} if value is None else value
    if kind == "def":
        def svc(i, ctx, e):
            if delay:
                time.sleep(delay)
            return val
        return svc

    async def asvc(i, ctx, e):
        if delay:
            await asyncio.sleep(delay)
        return val
    return asvc
from xstate_statemachine.exceptions import RunawayChainError
LAPS={"n":0}
class Drop(PluginBase):
    def __init__(self): self.reasons={}
    def on_event_dropped(self,i,e,reason=None,**kw):
        self.reasons[str(reason)]=self.reasons.get(str(reason),0)+1
def prio(i,ctx,e,ad):
    LAPS["n"]+=1
    try:
        r=i.send("P",priority=True)
        if asyncio.iscoroutine(r): r.close()
    except Exception: pass
def plain(i,ctx,e,ad):
    LAPS["n"]+=1
    try:
        r=i.send("P")
        if asyncio.iscoroutine(r): r.close()
    except Exception: pass
def cfg(action):
    return {"id":"r8b","initial":"a","context":{"n":0},"maxIterations":25,
     "states":{"a":{"entry":[action],"on":{"P":{"target":"b"}}},
               "b":{"entry":[action],"on":{"P":{"target":"a"}}}}}
def mk(action,kind):
    return create_machine(cfg(action),logic=MachineLogic(
        actions={"prio":prio,"plain":plain},services={"s":make_service(kind)}))
async def one(action,kind,wd=8.0):
    LAPS["n"]=0; d=Drop()
    i=Interpreter(mk(action,kind)).use(d)
    row={"self_send":action,"service_kind":kind,"maxIterations":25,"watchdog_s":wd}
    t0=time.perf_counter()
    try:
        await asyncio.wait_for(i.start(),wd)
        row["start"]="ok"
    except asyncio.TimeoutError:
        row.update({"start":"TIMEOUT","start_seconds":round(time.perf_counter()-t0,2),
                    "laps_at_watchdog":LAPS["n"],"trip_observable":False,
                    "drops":d.reasons,"outcome":"LIVELOCK"})
        return row
    await asyncio.sleep(0.3)
    row["laps"]=LAPS["n"]
    row["trip_observable"]=isinstance(i.last_error,RunawayChainError) or bool(d.reasons)
    row["last_error"]=repr(i.last_error)[:60]; row["drops"]=d.reasons
    t1=time.perf_counter()
    try:
        await asyncio.wait_for(i.stop(),wd); row["stop"]="ok"
    except asyncio.TimeoutError:
        row["stop"]="HUNG"; row["outcome"]="LIVELOCK"
    row["stop_seconds"]=round(time.perf_counter()-t1,2)
    row.setdefault("outcome","bounded")
    return row
async def child(action,kind):
    row=await one(action,kind)
    print("ROW:"+__import__("json").dumps(row,default=str))
async def main():
    import sys,os,json,subprocess
    if len(sys.argv)>2 and sys.argv[1]=="--cell":
        await child(sys.argv[2],sys.argv[3]); return 0
    rows=[]
    for a in ("plain","prio"):
        for k in ("def","async def"):
            env={**os.environ,"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"}
            try:
                p=subprocess.run([sys.executable,os.path.abspath(__file__),"--cell",a,k],
                                 capture_output=True,text=True,timeout=20,env=env)
                line=[l for l in p.stdout.splitlines() if l.startswith("ROW:")]
                if line: rows.append(json.loads(line[0][4:]))
                else: rows.append({"self_send":a,"service_kind":k,
                     "outcome":"LIVELOCK","detail":"child produced no row",
                     "trip_observable":False})
            except subprocess.TimeoutExpired:
                rows.append({"self_send":a,"service_kind":k,"outcome":"LIVELOCK",
                  "detail":"child process exceeded a 20s WALL watchdog: the spin "
                           "starves the event loop, so even asyncio.wait_for() "
                           "inside the process never fires",
                  "trip_observable":False})
    bad=[r for r in rows if r.get("outcome")=="LIVELOCK" or not r.get("trip_observable",True)]
    emit("r8b_priority_self_send_livelock",{"rows":rows,"livelocks":bad,
      "source":"interpreter.py:2342-2375 `_deliver_priority(engine_completion=False)` for every send(priority=True), vs :898-908 `_issued_from_own_action()` on the non-priority path",
      "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
```

## Root cause (source read at `6db65d8`)

`_deliver_priority` (`interpreter.py:2342-2389`) charges only on `engine_completion`:

```python
if engine_completion:
    if self._chain_owed:
        self._chain_owed -= 1
    self._raise_depth += 1
self._priority_queue.append(event)
```

`engine_completion` is `False` for **every** public `send(priority=True)`, whatever the
issuer — so a self-issued priority send is never charged. The shed test in the run loop
(`:1598`) is a property of the chain applied to whatever `_next_event()` pulled off that
same FIFO:

```python
over = self._raise_depth > limit
```

with no provenance test — so an external event is freely dropped.

The **non**-priority `send()` path already gets this right at `:898-908` via
`_issued_from_own_action()` (#90): a self-issued send is routed to the internal queue and
charged, an external one is not. `priority=True` never reaches that branch.

## Why the usual refutations do not apply

* **Not documented.** `docs/api/index.md:1788` promises the opposite — "a caller's `send()`
  on either lane (`priority=True` included) never is [charged]". `docs/_guide/interpreters.md:514-524`
  presents `priority=True` as ordinary application usage.
* **Not API misuse.** The identical construct on the plain lane is explicitly supported,
  charged, and behaves correctly in our control.
* **No XState v5 cover.** v5 has neither a priority lane nor a chain budget, so it cannot
  sanction either half.
* **Not a duplicate.** `tests/test_round7_findings.py:413-520` exercises only *externally
  issued* priority sends into an *untripped* chain — never one issued from an action, and
  never an external one arriving at an already-tripped chain. That is exactly the blind
  spot.

## Proposed fix

Carry provenance on the **event**, not inferred at either site: tag the queued item at
enqueue time as engine-completion / self-raised / external; charge the first two; and make
the shed test refuse to drop anything tagged external. Equivalently, route
`send(priority=True)` through `_issued_from_own_action()` the way the inbox lane already
does, and give external priority sends a FIFO the chain-budget axe cannot reach.

## Expected

The library's own contract, `docs/api/index.md:1788`:

> **Self-generated** is decided by *provenance*, not timing (#179, #180): every engine
> completion … is charged when it continues a chain; **a caller's `send()` on either lane
> (`priority=True` included) never is.**

Both halves violate the sentence, in opposite directions. A `send(priority=True)` issued
from the machine's own action is **not a caller's send** — it is self-generated work by
the definition the same paragraph states, so it must be charged, and today it is not
(half a). An event on the public priority lane that a *caller* issued must **never** be
charged — so it must never be shed with `reason="chain_budget"`, and today it is
(half b).

SCXML §3.13/§D is the underlying rule the docstring restates: the external event queue is
drained by `mainEventLoop()` once the macrostep completes, and internal (self-raised)
events are what a macrostep is made of. An implementation that classifies a queue entry by
its *position* rather than by which queue semantically owns it cannot honour that split.
XState v5 has neither a priority lane nor a chain budget, so it sanctions neither half.

## Acceptance criteria

A single matrix test, parametrised over **three** axes — the third is the one that got
through this time:

* **issuer provenance** ∈ {external caller, issued from an action, engine completion}
* **chain state at delivery** ∈ {untripped, already tripped}
* **service kind** ∈ {`def`, `async def`}
* and both engines where the construct exists (`SyncInterpreter` has no priority lane, so
  the sync arm asserts that absence explicitly rather than being skipped).

Named tests:

1. `test_priority_self_send_is_charged[def|async def]` — a `send(priority=True)` issued
   from an entry action trips `maxIterations` at the same lap count as the identical
   `priority=False` control (27 against a limit of 25 today), raising
   `RunawayChainError` and firing one `chain_budget` drop. Must run under a
   **process-level** watchdog: an in-process `asyncio.wait_for` cannot fire while the
   regression is present.
2. `test_external_priority_never_shed_when_chain_tripped[def|async def]` — 2 000 external
   `send(priority=True)` events delivered while a self-generated chain is already tripped
   are all applied; `chain_budget_drops_by_type` contains **no external event type**.
3. `test_priority_lane_charge_matrix[issuer × chain_state × kind]` — the full grid above,
   asserting charged ⟺ issuer ∈ {action, engine completion} and shed ⟹ issuer ≠ external,
   independent of queue position.
4. `test_priority_send_failure_is_observable[def|async def]` — whenever a priority event
   is not applied, at least one of `last_error`, `on_event_dropped`, or the `send()`
   return value says so. Today all three report success.

`tests/test_round7_findings.py:413-520` is the existing guard: it exercises only
*externally issued* priority sends into an *untripped* chain — one cell of the grid, and
not either failing one. Rounds 6, 7 and 8 have each been "fixed on the axis the test was
written against" — engine, then service kind, now issuer provenance. The matrix ends the
pattern.

## Impact

For an order-management system, `send(priority=True)` *is* the kill-switch, cancel and
risk-check lane. Half (a) is an unbounded livelock that starves the event loop hosting
every other machine and any co-resident server, with `status="running"` and
`last_error is None` throughout — undetectable in-process, because the detector would run
on the starved thread. Half (b) silently destroys a kill-switch press with a success-shaped
send. Either alone is disqualifying.

## Related

* **#180** — *Bug: an EXTERNAL `send(..., priority=True)` is charged to the chain budget*.
  This is the **regression surface of #180**: #180 fixed the charge site to decide by
  provenance, and the shed site at `interpreter.py:1598` was left deciding by position.
  Half (b) is #180's own symptom reappearing whenever the chain is already tripped.
* **#90** — the non-priority lane's `_issued_from_own_action()` routing, which half (a)
  bypasses.
* **#105** — the inbox-lane ancestor of half (b).
* **#179** — service-kind parity on the same lane; the `def`/`async` asymmetry in half (b)
  rides on it.

## Verification

* Date: 2026-09-21 · Python 3.13.7 · commit `6db65d8`
* `repro/R8-01_priority_self_send_livelock.py` → **exit 1** (`result: FAIL`); prio cells
  LIVELOCK for `def` **and** `async def`; plain-lane control bounded at 27 laps on both.
* `repro/R8-01_external_priority_shed.py` → **exit 1** (`VERDICT: REPRODUCED`);
  `def` lane loses 10/2000 external `EXT` sends as `chain_budget`, `async def` lane 0.
* Both scripts are standalone (no shared helper import) and byte-identical to the blocks
  referenced above.
* Duplicate check: `gh issue list --state all --limit 240` over *priority* /
  *chain_budget* — all related issues (#180, #105, #179, #168, #167) are CLOSED; no open
  duplicate.
