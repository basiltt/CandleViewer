# re_mint() accepts type/src overrides and can forge a completion for another live invoke

**NOT POSTED. Draft.** Severity (ours): **Medium**. Version: 0.9.1 (tag `v0.9.1` = `45bb7f3`).

## Summary

`events.re_mint(ev, **fields)` (added for #248) correctly refuses plain or demoted events. However, it forwards **every** override, including `type` and `src`, to the engine-private `_EngineDone` / `_EngineError` / `_EngineAfter` constructors. A genuine `done.invoke.<A>` event can therefore be re-minted as `done.invoke.<B>` with `src=<B>`. The router's live-invocation check trusts `is_system_event` plus the `src` match, so it accepts the forged event, and B's `onDone` fires **while B's service is still running**.

This contradicts the `re_mint` docstring, which says provenance "can only be carried forward from an event the engine produced, never created", and that the purpose is patching a payload field such as `data`. The fuzz track also saw a retyped `AfterEvent` make the sync engine fire a 99999 ms `after` timer immediately.

Reaching this needs in-process code (a plugin or listener) that already holds a genuine engine event. External input cannot reach it, which is why we rate it Medium and not High.

## Standalone repro (stdlib + xstate_statemachine only; run from any directory)

```python
import asyncio, os
from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.events import re_mint
KIND = os.environ.get("K", "async")          # K=async or K=def
cap = {}
async def aq(i, c, e): return 1
def dq(i, c, e): return 1
async def av(i, c, e): await asyncio.sleep(30); return 2   # victim: still running
async def adone(i, c, e, a=None): cap["ev"] = e
def ddone(i, c, e, a=None): cap["ev"] = e
cfg = {"id": "m", "type": "parallel", "states": {
  "a":   {"initial": "r", "states": {"r": {"invoke": {"src": "quick",
          "onDone": {"target": "d", "actions": "cap"}}}, "d": {}}},
  "pay": {"initial": "w", "states": {"w": {"invoke": {"src": "victim",
          "onDone": "settled"}}, "settled": {}}}}}
lg = MachineLogic(services={"quick": aq if KIND == "async" else dq, "victim": av},
                  actions={"cap": adone if KIND == "async" else ddone})
async def main():
    it = await Interpreter(create_machine(cfg, logic=lg)).start()
    for _ in range(50):
        if "ev" in cap: break
        await asyncio.sleep(0.05)
    ev = cap["ev"]                                    # genuine done.invoke.m.a.r
    src = ev.src.replace("m.a.r", "m.pay.w") if ev.src else "m.pay.w"
    forged = re_mint(ev, type="done.invoke.m.pay.w", src=src)
    await it.send(forged)
    for _ in range(40):
        if "pay.settled" in str(it.current_state_ids): break
        await asyncio.sleep(0.05)
    print(KIND, sorted(it.current_state_ids)); await it.stop()
    raise SystemExit(1 if any("settled" in s for s in it.current_state_ids) else 0)
asyncio.run(main())
```

**Observed (both `K=async` and `K=def`):** `['m.a.d', 'm.pay.settled']`, exit 1. The victim invoke completed without its service returning.
**Expected:** `re_mint` raises `TypeError` for `type`/`src`, and `pay` stays in `w`.

## Suggested fix

Reject any override other than payload fields: `data`, `error`, and for timers `fired_at`/`scheduled_for`. Or reject `type` and `src` explicitly. Add a regression test for the retarget case with both `DoneEvent` and `AfterEvent`, on both engines.
