---
r8: R8-03
title: "Bug: `start(children_timeout=)` is a no-op against a plain-`def` child entry action and suppresses its own WARNING; the bound is aggregate, not per child"
labels: [bug, severity/high, area/interpreter, actors]
severity: High
engines: async `Interpreter`
service_kinds: plain `def` entry actions (the `async def` control is correct)
repro_script: repro/R8-03_children_timeout_def_noop.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

`start(children_timeout=)` (#181) does not bound a **plain-`def`** child entry action, and
it **suppresses its own WARNING** while failing. Separately, the bound is **aggregate**
rather than per child, so N slow children take N × their own delay regardless of the value
passed.

## Environment

* Commit `6db65d8` (unreleased 0.8.1; `__version__` reports `0.8.0`)
* Python 3.13.7, Windows 11
* Async `Interpreter`; plain `def` child entry actions (the `async def` control is correct)

## Observed (fresh run, `6db65d8`)

`repro/R8-03_children_timeout_def_noop.py` → **exit 1** (`result: FAIL`), verbatim rows:

| entry kind | children | child entry | `children_timeout` | `start_seconds` | bounded | overrun | WARNING |
|---|---|---|---|---|---|---|---|
| `async def` | 1 | 3.0 s | 0.2 | **0.2** | yes | ×1.0 | **yes** |
| `async def` | 5 | 3.0 s | 0.2 | **0.2** | yes | ×1.0 | **yes** |
| `def` | 1 | 3.0 s | 0.2 | **3.0** | **no** | **×15.0** | **none** |
| `def` | 5 | 3.0 s | 0.2 | **15.0** | **no** | **×75.0** | **none** |

Two independent defects are visible in those four rows:

* the bound is a **no-op** against a plain-`def` entry action — 3.0 s against a 0.2 s
  timeout, and the `async def` control on the identical chart returns in 0.2 s;
* the overrun scales **linearly in child count** (1 child → 3.0 s, 5 children → 15.0 s),
  so the bound is aggregate over serial bring-ups, not per child;
* the WARNING that is supposed to announce a timeout is **suppressed together with it** —
  `warning_logged: false` on both failing rows, `true` on both `async def` rows. The
  failure is completely silent.

## Expected

The library's own contract, at `docs/api/index.md:701`:

> `await .start(*, children_timeout=DEFAULT_CHILDREN_TIMEOUT)` … **[0.8.1]** That wait is
> bounded by `children_timeout` seconds (default `DEFAULT_CHILDREN_TIMEOUT` = 2.0;
> `None` = unbounded) **because a child's bring-up runs its entry actions — user code
> (#181)**. On timeout a WARNING is logged and `start()` returns with the machine running
> and the child still starting.

Three promises, all broken on the `def` arm: the wait is not bounded, no WARNING is
logged, and `start()` does not return. Nothing in that sentence restricts the guarantee to
coroutine entry actions — and it cannot, because "user code" is precisely what the
parameter exists to defend against. SCXML §6.4 likewise requires the invoking session to
reach a stable configuration and then continue processing; a bring-up that monopolises the
processor indefinitely has no licence in the specification. XState v5 has no
`children_timeout` analogue, so it cannot sanction the behaviour either.

### Minimal reproduction — complete, standalone

Byte-identical to `repro/R8-03_children_timeout_def_noop.py`. Exits **1** while the
defect is present, **0** once fixed; every `start()` is wrapped in an
`asyncio.wait_for` watchdog so a hang is an observed result, not a stall.

```python
"""R6b - MINIMAL: `start(children_timeout=)` (#181) does not bound start()
when the child's slow entry action is a plain `def`.

#181: "a slow child's `async def` entry action no longer holds `await
start()` for its whole duration." The fix is an `asyncio.wait_for` around
the bring-ups (`_await_actor_bringups(timeout=)`), which can only pre-empt
at an `await`. A plain `def` entry action runs ON THE LOOP THREAD inside
`child.start()`, so the timeout cannot fire until the action returns --
and with N children the delay is N x duration, serialized.

ONE child, 3 s entry, children_timeout=0.2. Both spellings.
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
import logging
class Cap(logging.Handler):
    def __init__(self): super().__init__(level=logging.WARNING); self.msgs=[]
    def emit(self,r): self.msgs.append(r.getMessage())
KID={"id":"kid","initial":"k","context":{},"states":{"k":{"entry":["slow"]}}}
PAR={"id":"r6b","initial":"up","context":{},"states":{
 "up":{"invoke":{"src":"kid","id":"kid"},"on":{"P":{"target":"off"}}},"off":{}}}
D=3.0
async def one(kind,timeout,n):
    if kind=="def":
        def slow(i,c,e,a): time.sleep(D)
    else:
        async def slow(i,c,e,a): await asyncio.sleep(D)
    kid=create_machine(KID,logic=MachineLogic(actions={"slow":slow}))
    par=dict(PAR); par["states"]=dict(PAR["states"])
    par["states"]["up"]=dict(PAR["states"]["up"])
    par["states"]["up"]["invoke"]=[{"src":"kid","id":f"kid{j}"} for j in range(n)]
    m=create_machine(par,logic=MachineLogic(actions={"slow":slow},services={"kid":kid}))
    cap=Cap(); lg=logging.getLogger("xstate_statemachine"); lg.addHandler(cap)
    i=Interpreter(m); t0=time.perf_counter()
    await asyncio.wait_for(i.start(children_timeout=timeout), 300)
    s=round(time.perf_counter()-t0,2)
    await asyncio.wait_for(i.stop(),60); lg.removeHandler(cap)
    return {"entry_kind":kind,"children":n,"child_entry_seconds":D,
            "children_timeout":timeout,"start_seconds":s,
            "bounded":s < timeout+1.0,
            "overrun_factor":round(s/timeout,1),
            "warning_logged":any("#181" in m or "still starting" in m for m in cap.msgs)}
async def main():
    rows=[await one(k,0.2,n) for k in ("async def","def") for n in (1,5)]
    bad=[r for r in rows if not r["bounded"]]
    emit("r6b_children_timeout_def_noop",{"rows":rows,"unbounded":bad,
      "source":"interpreter.py:601 _await_actor_bringups(timeout=) -- wait_for cannot preempt a `def` entry action running on the loop thread",
      "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
```

## Root cause (source read at `6db65d8`)

`interpreter.py:601` → `_await_actor_bringups:2753` uses `asyncio.wait(timeout=)`, which
cannot pre-empt a non-yielding `def` entry action running on the loop thread inside
`child.start()` (`:2973`). Bring-ups are serial, which produces the exact N × D scaling
above. The WARNING sits on the same timeout path, so it is suppressed together with the
bound — the failure is completely silent.

## Why this is correct usage, not misuse

`docs/api/index.md:701` justifies the parameter precisely by "a child's bring-up runs its
entry actions — user code (#181)", with no restriction to coroutine actions. The
`service_executor` / `service_pool_size` off-loading (#149/#173) applies to plain
**services** (`run_in_executor` at `interpreter.py:2813`); there is no executor or
`to_thread` path for **actions**, so a plain-`def` action is a first-class supported
spelling with nowhere else to run. XState v5 has no `children_timeout` analogue, so it
cannot license the behaviour either.

## The guarding test cannot fail

`tests/test_round7_findings.py:557` parametrises over `KINDS` but gives the `def` arm
`time.sleep(0.05)` against the `async` arm's `asyncio.sleep(3.0)` — the `def` branch never
exceeds the bound, so the parametrisation is decorative.
`test_bringup_timeout_is_observable` is async-only. Giving the `def` arm work that can
actually exceed the timeout makes it fail immediately.

## Proposed fix

Run child bring-up off the loop thread (or require coroutine entry actions on
`invoke`-bearing states and say so), apply the bound **per child** rather than to the
aggregate `asyncio.wait`, and move the WARNING off the timeout path so a suppressed bound
is still a logged bound.

## Impact

An advertised safety bound silently fails for one of two supported spellings, with no
diagnostic, blocking the event loop linearly in child count. For us this is the
bring-up path of every supervised machine group.

**Order management.** `start()` is where a trading process brings up its per-venue and
per-instrument child machines. A bound that silently does not hold means process start-up
is unbounded in the one place an operator most needs a deadline, and linear in child count
on the loop thread — so the more venues you supervise, the longer the whole process is
unresponsive, with no log line to say why.

## Acceptance criteria

Named tests, parametrised over `("def", "async def")` entry-action spellings and giving
**both** arms work that genuinely exceeds the bound:

1. `test_children_timeout_bounds_start[def|async def]` — with `children_timeout=0.2` and a
   child entry action that takes 3.0 s, `start()` returns in < 1.2 s on **both**
   spellings. (This is the assertion `tests/test_round7_findings.py:557` cannot make
   today, because its `def` arm sleeps 0.05 s against the `async` arm's 3.0 s.)
2. `test_children_timeout_warning_is_logged[def|async def]` — a timeout emits the
   documented WARNING on both spellings. Parametrise
   `test_bringup_timeout_is_observable`, which is async-only today.
3. `test_children_timeout_is_per_child_not_aggregate[def|async def]` — with N ∈ {1, 5, 20}
   children each taking 3.0 s and `children_timeout=0.2`, `start_seconds` is flat in N.
   The current ×15 → ×75 scaling fails this immediately.
4. `test_children_timeout_none_is_unbounded[def|async def]` — the documented `None`
   escape hatch still waits, on both spellings, so the fix does not silently bound an
   opted-out caller.

Both engines where the construct exists; `SyncInterpreter.start()` has no
`children_timeout` parameter, so the sync arm asserts that absence explicitly rather than
being skipped silently.

## Related

* **#181** — *Bug: `await start()` hangs unboundedly on a slow invoked child*, which
  introduced `children_timeout`. This issue is the **regression surface of #181**: the fix
  is `asyncio.wait(timeout=)` at `interpreter.py:2753`, which can only pre-empt at an
  `await`, so it lands on the coroutine arm only. #181 is **narrower than claimed** — its
  title and the API docs promise a bound on "user code", and it delivers one for
  `async def` entry actions alone.
* **#149 / #173** — `run_in_executor` / `service_pool_size` for plain **services**. There
  is deliberately no equivalent path for **actions**, which is why a plain-`def` entry
  action has nowhere but the loop thread to run.
* **#171** — the bring-up wait #181 later bounded.
* **#179** — the same "fixed on the axis the test was written against" pattern, on the
  service-kind axis.

## Verification

* Date: 2026-09-21 · Python 3.13.7 · commit `6db65d8`
* `repro/R8-03_children_timeout_def_noop.py` → **exit 1** (`result: FAIL`), 2 of 4 rows
  unbounded; `def` arm 3.00 s and 15.0 s against a 0.2 s bound, `async def` arm 0.2 s on
  both. Every `start()` is wrapped in an `asyncio.wait_for(..., 300)` watchdog.
* Script is standalone (no shared helper import) and byte-identical to the block above.
* Source confirmed open at `6db65d8`: `interpreter.py:601` (`_await_actor_bringups(
  timeout=children_timeout)`) and `interpreter.py:2753` (`await asyncio.wait(pending,
  timeout=...)`).
* Duplicate check: `gh issue list --state all --limit 240 --search "children_timeout"` →
  #181 only, CLOSED. No open duplicate.
