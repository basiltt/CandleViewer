# -*- coding: utf-8 -*-
"""N10 -- this round's semantics fixes, in their PERSISTENCE bearing.

The brief lists #116 (completion ordering), #109 (`done.invoke` output),
#108 (root target rejected at build) and #130 (escalate reaches the
parent's onError). Those are the semantics track's business; what belongs
here is whether each one SURVIVES A SNAPSHOT -- i.e. whether a restore can
undo the fix or observe a state the fix says is impossible.

  A. #109 -- `done.invoke` carries the child's declared `output`, not its
     private context. Checked live, then checked on a `DoneEvent` that is
     persisted and restored (the payload must still be the output, and must
     not acquire the private context on the way back).
  B. #108 -- a transition targeting the machine ROOT is rejected at build.
     Persistence angle: a snapshot whose `configuration` names only the root
     (the shape #108 makes unreachable) must not restore into a live
     machine.
  C. #130 -- `escalate` from an invoked child reaches the parent's onError.
     Persistence angle: the resulting `ErrorEvent`, if pending at snapshot
     time, must round-trip as an ErrorEvent with its `src`.
  D. #116 -- an inline (non-coroutine) sync service completes at the same
     point on both engines. Persistence angle: the in-step completion must
     not be visible as a pending event in a snapshot taken at quiescence
     (it would be replayed twice).
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
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import (
    ErrorEvent,
    DoneEvent,
    persist_event,
    restore_event,
)

import order_machine


async def test_a() -> None:
    print("=== A. #109 done.invoke output, live and across a snapshot ===")
    child = {
        "id": "kid",
        "initial": "w",
        "context": {"secret": "PRIVATE", "result": 0},
        "output": {"result": 42},
        "states": {"w": {"on": {"FIN": "d"}}, "d": {"type": "final"}},
    }
    parent = {
        "id": "par",
        "initial": "run",
        "context": {"got": None},
        "states": {
            "run": {
                "invoke": {"src": "kidm", "id": "k",
                           "onDone": {"target": "ok", "actions": ["grab"]}},
                "on": {"PUSH": {"actions": ["push"]}},
            },
            "ok": {"type": "final"},
        },
    }

    seen = {}

    def grab(i, ctx, e, ad):  # noqa: ANN001
        ctx["got"] = json.loads(json.dumps(getattr(e, "data", None),
                                           default=str))
        seen["src"] = getattr(e, "src", None)

    async def push(i, ctx, e, ad):  # noqa: ANN001
        ch = i.get_child("k") if hasattr(i, "get_child") else None
        if ch is not None:
            await ch.send("FIN")

    cm = create_machine(child, logic=MachineLogic())
    pm = create_machine(parent, logic=MachineLogic(
        actions={"grab": grab, "push": push}, services={"kidm": cm}))
    i = Interpreter(pm, clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.05)
    try:
        await i.send("PUSH"); await asyncio.sleep(0.08)
    except Exception as exc:  # noqa: BLE001
        print(f"   (push path: {type(exc).__name__}: {exc})")
    got = i.context["got"]
    print(f"   live done.invoke data = {got}  src={seen.get('src')}")
    leaked = isinstance(got, dict) and "secret" in got
    print(f"   private context leaked = {leaked}  <- must be False")
    if i.status == "running":
        await i.stop()

    de = DoneEvent(type="done.invoke.k", data={"result": 42}, src="k")
    back = restore_event(persist_event(de))
    print(f"   persisted+restored: {type(back).__name__} data={back.data} "
          f"src={back.src}")
    ok = (not leaked and isinstance(back, DoneEvent)
          and back.data == {"result": 42} and back.src == "k")
    print(f"   VERDICT = {ok}")


async def test_b() -> None:
    print("\n=== B. #108 root-only configuration cannot be restored ===")
    from xstate_statemachine.exceptions import (
        InvalidConfigError,
        XStateMachineError,
    )
    # build-time half
    bad = {"id": "r", "initial": "a",
           "states": {"a": {"on": {"GO": {"target": "r"}}}}}
    try:
        create_machine(bad, logic=MachineLogic())
        build_refused = False
        print("   build-time: root target ACCEPTED  <- #108 says it must not be")
    except XStateMachineError as exc:
        build_refused = True
        print(f"   build-time: {type(exc).__name__}: {str(exc)[:110]}")

    # persistence half: a blob naming only the root
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.02)
    blob = i.get_snapshot()
    await i.stop()
    d = json.loads(blob)
    d["state_ids"] = ["order"]
    d["configuration"] = ["order"]
    try:
        j = Interpreter.from_snapshot(json.dumps(d), order_machine.build(),
                                      clock=SimulatedClock())
        await j.start(); await asyncio.sleep(0.03)
        r = await j.send("SUBMIT", wait=True, qty=1)
        print(f"   restore: ACCEPTED status={j.status} "
              f"states={sorted(j.current_state_ids)} "
              f"SUBMIT changed={r.changed}")
        restore_refused = False
        if j.status == "running":
            await j.stop()
    except Exception as exc:  # noqa: BLE001
        restore_refused = True
        print(f"   restore: {type(exc).__name__}: {str(exc)[:110]}")
    print(f"   VERDICT build={build_refused} restore_refused={restore_refused}")


def test_c() -> None:
    print("\n=== C. #130 escalate ErrorEvent round-trips with src ===")
    ee = ErrorEvent(type="error.platform.k",
                    error=RuntimeError("child blew up"), src="k")
    rec = persist_event(ee)
    back = restore_event(rec)
    print(f"   record   = {json.dumps(rec)[:150]}")
    print(f"   restored = {type(back).__name__} src={back.src} "
          f"error={back.error!r}")
    ok = isinstance(back, ErrorEvent) and back.src == "k" and back.error is not None
    print(f"   VERDICT = {ok}")


async def test_d() -> None:
    print("\n=== D. #116 inline sync service: no double-replay via snapshot ===")
    cfg = {
        "id": "inl",
        "initial": "go",
        "context": {"n": 0},
        "states": {
            "go": {"invoke": {"src": "svc", "id": "s",
                              "onDone": {"target": "done_",
                                         "actions": ["count"]}}},
            "done_": {"type": "final"},
        },
    }

    def count(i, ctx, e, ad): ctx["n"] += 1      # noqa: ANN001,E704
    def svc(i, ctx, e):  # noqa: ANN001
        return {"v": 1}

    def build():
        return create_machine(cfg, logic=MachineLogic(
            actions={"count": count}, services={"svc": svc}))

    i = Interpreter(build(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.06)
    print(f"   async: states={sorted(i.current_state_ids)} n={i.context['n']}")
    blob = i.get_snapshot()
    d = json.loads(blob)
    print(f"   snapshot pending={[r['type'] for r in d['pending_events']]}"
          f"  <- must not hold the in-step completion")
    if i.status == "running":
        await i.stop()

    s = SyncInterpreter(build())
    s.start()
    print(f"   sync : states={sorted(s.current_state_ids)} n={s.context['n']}")
    sblob = s.get_snapshot()
    sd = json.loads(sblob)
    print(f"   sync snapshot pending={[r['type'] for r in sd['pending_events']]}")
    if s.status == "running":
        s.stop()

    j = Interpreter.from_snapshot(blob, build(), clock=SimulatedClock())
    await j.start(); await asyncio.sleep(0.05)
    print(f"   restored: states={sorted(j.current_state_ids)} n={j.context['n']}"
          f"  <- n must stay {i.context['n']}, not double")
    ok = (i.context["n"] == s.context["n"] == 1
          and not d["pending_events"] and j.context["n"] == 1)
    print(f"   engine parity + no double-count = {ok}")
    if j.status == "running":
        await j.stop()


async def main() -> None:
    await test_a(); await test_b(); test_c(); await test_d()


if __name__ == "__main__":
    asyncio.run(main())
