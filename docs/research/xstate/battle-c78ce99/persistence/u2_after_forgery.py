# -*- coding: utf-8 -*-
"""U2 -- #203 `after` provenance across the PERSISTENCE boundary.

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

#203 made `after` selection match only an ENGINE-MINTED `AfterEvent`
(`_EngineAfter`), so a hand-built event or a forged snapshot record can no
longer fire a 60-second timer instantly.  The persisted surface has the same
shape as the `done` surface #195 left open: `persist_event` writes
``"engine": true`` for an engine-minted `after`, and `restore_event` trusts
that plaintext boolean (`events.py:414`).

Six vectors, each run END-TO-END on a machine whose only `after` is 60 s, so
any transition to `fired` within the test window is instant-fire:

  A  honest round-trip of a GENUINE fired timer   (must still fire)
  B  hand-written record, no `engine` key          (must NOT fire)
  C  hand-written record with `"engine": true`     (the forgery)
  D  `events._EngineAfter` imported by private name
  E  `type(genuine)(...)`
  F  `pickle` round-trip of a genuine AfterEvent

Under `strict: True` + `onUnhandled: "error"`, so a refused event is visible
as a raised/errored machine rather than a silent drop.
"""
from __future__ import annotations

import asyncio
import json
import os
import pickle

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import events as ev_mod
from xstate_statemachine.events import AfterEvent, persist_event, restore_event
from xstate_statemachine.exceptions import XStateMachineError

KIND = os.environ.get("XS_SVC", "async")

SPEC = {
    "id": "sec",
    "initial": "waiting",
    "strict": True,
    "onUnhandled": "error",
    "context": {"fired": 0},
    "states": {
        # 60 000 ms: nothing legitimate can fire this inside the test.
        "waiting": {"after": {"60000": {"target": "fired",
                                        "actions": ["mark"]}}},
        "fired": {"type": "final"},
    },
}

# A machine with a SHORT timer, used only to capture a genuine engine event.
SPEC_FAST = json.loads(json.dumps(SPEC))
SPEC_FAST["states"] = {
    "waiting": {"after": {"10": {"target": "fired", "actions": ["mark"]}}},
    "fired": {"type": "final"},
}


def _logic():
    def mark(i, c, e, a):  # noqa: ANN001
        c["fired"] = c.get("fired", 0) + 1

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return MachineLogic(
        actions={"mark": mark},
        services={"svc": svc_def if KIND == "def" else svc_async},
    )


def build(spec=SPEC):
    return create_machine(json.loads(json.dumps(spec)), logic=_logic())


async def capture_genuine() -> AfterEvent:
    """Grab a real engine-minted AfterEvent out of a live interpreter."""
    grabbed = []
    i = Interpreter(build(SPEC_FAST))

    orig = i._put_priority if hasattr(i, "_put_priority") else None

    # The fired timer lands in the priority lane; read it before it drains.
    await i.start()
    for _ in range(400):
        if i._priority_queue:  # noqa: SLF001
            grabbed = [e for e, _ in i._priority_queue]  # noqa: SLF001
            break
        await asyncio.sleep(0.001)
    await asyncio.sleep(0.05)
    await i.stop()
    del orig
    for e in grabbed:
        if isinstance(e, AfterEvent):
            return e
    return None


async def drive(event) -> str:
    """Send *event* into a fresh 60-second machine; report what happened."""
    i = Interpreter(build())
    await i.start()
    raised = None
    try:
        await i.send(event)
        await asyncio.sleep(0.05)
    except XStateMachineError as exc:
        raised = type(exc).__name__
    leaves = sorted(s.id for s in i.current_state_ids_nodes) \
        if hasattr(i, "current_state_ids_nodes") else sorted(i.current_state_ids)
    fired = i.context.get("fired", 0)
    status = getattr(i, "status", "?")
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return f"leaves={leaves} fired={fired} raised={raised} status={status}"


async def restore_and_drive(record: dict) -> str:
    """Restore *record* through the public restore path, then drive it."""
    e = restore_event(record)
    sysflag = ev_mod.is_system_event(e)
    out = await drive(e)
    return f"{type(e).__name__:<14} system={str(sysflag):<5} {out}"


async def main() -> None:
    print(f"=== U2 after-provenance across persistence [{KIND}] ===")
    genuine = await capture_genuine()
    print(f"captured genuine: {genuine!r} "
          f"system={ev_mod.is_system_event(genuine) if genuine else None}")
    rec_honest = persist_event(genuine) if genuine else None
    print(f"persisted record: {rec_honest}")
    print()

    TYPE = "after.60000.sec.waiting"
    results = {}

    if rec_honest is not None:
        r = dict(rec_honest)
        r["type"] = TYPE  # retarget the honest record at the 60 s timer
        results["A genuine record, retargeted"] = await restore_and_drive(r)

    results["B hand record, no engine key"] = await restore_and_drive(
        {"kind": "after", "type": TYPE,
         "scheduled_for": 0.0, "fired_at": 0.0})

    results['C hand record, "engine": true'] = await restore_and_drive(
        {"kind": "after", "type": TYPE, "engine": True,
         "scheduled_for": 0.0, "fired_at": 0.0})

    # D: private name imported directly
    mk = getattr(ev_mod, "engine_after", None) or getattr(
        ev_mod, "_EngineAfter", None)
    if mk is not None:
        e = mk(TYPE, 0.0, 0.0) if not isinstance(mk, type) else mk(
            type=TYPE, scheduled_for=0.0, fired_at=0.0)
        results["D events._EngineAfter(...)"] = (
            f"{type(e).__name__:<14} system={ev_mod.is_system_event(e)!s:<5} "
            f"{await drive(e)}")

    # E: type(genuine)(...)
    if genuine is not None:
        e = type(genuine)(type=TYPE, scheduled_for=0.0, fired_at=0.0)
        results["E type(genuine)(...)"] = (
            f"{type(e).__name__:<14} system={ev_mod.is_system_event(e)!s:<5} "
            f"{await drive(e)}")

        # F: pickle round-trip of a genuine event, retargeted
        p = pickle.loads(pickle.dumps(genuine))
        p = p._replace(type=TYPE) if hasattr(p, "_replace") else p
        results["F pickle(genuine), retargeted"] = (
            f"{type(p).__name__:<14} system={ev_mod.is_system_event(p)!s:<5} "
            f"{await drive(p)}")

    # G: public class by hand
    e = AfterEvent(type=TYPE)
    results["G public AfterEvent(...)"] = (
        f"{type(e).__name__:<14} system={ev_mod.is_system_event(e)!s:<5} "
        f"{await drive(e)}")

    breaches = []
    for k, v in results.items():
        drove = "fired=1" in v and "'sec.fired'" in v
        flag = "  <-- DROVE the 60s after" if drove else ""
        print(f"  {k:<32} {v}{flag}")
        if drove and not k.startswith("A"):
            breaches.append(k)
    print()
    print("BREACHES:", breaches or "none")
    print("VERDICT:", "FAIL" if breaches else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
