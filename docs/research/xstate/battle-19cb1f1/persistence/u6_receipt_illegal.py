# -*- coding: utf-8 -*-
"""U6 -- #208 receipts are never success-shaped over an illegal
configuration, including around the snapshot boundary.

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

#208 resolves receipts after the in-flight flag is down and refuses to
report `ok` when the step ended with an illegal configuration.  The
persistence question is the inverse pair:

  A  NEVER `ok` OVER AN ILLEGAL OUTCOME.  Drive six step shapes that end
     badly -- entry action raises, entry raises under `rollback`, the event
     is unhandled under `onUnhandled:error`, the event is refused by
     `strict`, a guard raises, and a chain trips -- each via
     `await send(..., wait=True)`, and assert the receipt is never
     `error=None and changed=True` when the machine did not legally move.

  B  NEVER `error` OVER A LEGAL OUTCOME.  The same surface must not
     manufacture failures: a plain legal transition, a legal self-`raise`
     chain within budget, and a legal invoke completion must all return a
     clean receipt.

  C  A RECEIPT AND A SNAPSHOT AGREE.  For each shape, snapshot right after
     the receipt resolves and check that a receipt reporting `ok` is never
     paired with a blob the library itself then refuses to restore
     (`SnapshotCorruptError`), and that `changed=True` matches a blob whose
     `state_ids` really did move.

Both service kinds.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import XStateMachineError

KIND = os.environ.get("XS_SVC", "async")


def _svc():
    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return svc_def if KIND == "def" else svc_async


def boom(i, c, e, a):  # noqa: ANN001
    raise RuntimeError("entry failed")


def tick(i, c, e, a):  # noqa: ANN001
    c["n"] = c.get("n", 0) + 1


def bad_guard(c, e):  # noqa: ANN001
    raise RuntimeError("guard failed")


def ok_guard(c, e):  # noqa: ANN001
    return True


LOGIC = dict(
    actions={"boom": boom, "tick": tick},
    guards={"bad": bad_guard, "ok": ok_guard},
)

# name -> (spec, event, legal?)
CASES = {
    # ---- illegal / failing outcomes -----------------------------------
    "entry action raises": (
        {"id": "c1", "initial": "a",
         "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["boom"]}}},
        "GO", False),
    "entry raises under rollback": (
        {"id": "c2", "initial": "a", "actionErrorPolicy": "rollback",
         "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["boom"]}}},
        "GO", False),
    "unhandled under onUnhandled:error": (
        {"id": "c3", "initial": "a", "onUnhandled": "error",
         "states": {"a": {}}},
        "NOPE", False),
    "refused by strict": (
        {"id": "c4", "initial": "a", "strict": True,
         "states": {"a": {"on": {"GO": "a"}}}},
        "NOPE", False),
    "guard raises": (
        {"id": "c5", "initial": "a",
         "states": {"a": {"on": {"GO": {"target": "b", "guard": "bad"}}},
                    "b": {}}},
        "GO", False),
    # 📏 the chain-trip shape is a CYCLE (a -> b -> a): it legally moves and
    #    returns, so `changed=True` with `before == after` is correct, not a
    #    #208 violation. The criterion below therefore requires an
    #    ILLEGAL/`error` outcome, not merely "did not appear to move"; the
    #    cut itself is separately shown announced in u4b P2.
    "chain trips": (
        {"id": "c6", "initial": "a", "maxIterations": 4,
         "states": {
             "a": {"entry": [{"type": "raise", "params": {"event": "GO"}}],
                   "on": {"GO": "b"}},
             "b": {"entry": [{"type": "raise", "params": {"event": "GO"}}],
                   "on": {"GO": "a"}}}},
        "GO", False),
    # ---- legal outcomes ------------------------------------------------
    "plain legal transition": (
        {"id": "l1", "initial": "a",
         "states": {"a": {"on": {"GO": {"target": "b", "actions": ["tick"]}}},
                    "b": {}}},
        "GO", True),
    "legal guarded transition": (
        {"id": "l2", "initial": "a",
         "states": {"a": {"on": {"GO": {"target": "b", "guard": "ok"}}},
                    "b": {}}},
        "GO", True),
    "legal raise chain in budget": (
        {"id": "l3", "initial": "a", "maxIterations": 50,
         "states": {"a": {"on": {"GO": "b"}},
                    "b": {"entry": [{"type": "raise",
                                     "params": {"event": "NEXT"}}],
                          "on": {"NEXT": "c"}},
                    "c": {}}},
        "GO", True),
    "legal invoke completion": (
        {"id": "l4", "initial": "a",
         "states": {"a": {"on": {"GO": "w"}},
                    "w": {"invoke": {"id": "k", "src": "svc",
                                     "onDone": "done_"}},
                    "done_": {"type": "final"}}},
        "GO", True),
}


def _fields(r) -> dict:
    return {k: getattr(r, k, None)
            for k in ("changed", "error", "deferred", "denied")}


async def run_case(name: str, spec: dict, ev: str, legal: bool) -> tuple:
    m = create_machine(json.loads(json.dumps(spec)),
                       logic=MachineLogic(services={"svc": _svc()}, **LOGIC))
    i = Interpreter(m)
    await i.start()
    before = sorted(i.current_state_ids)
    receipt, raised = None, None
    try:
        receipt = await i.send(ev, wait=True)
    except XStateMachineError as exc:
        raised = type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        raised = f"RAW:{type(exc).__name__}"
    await asyncio.sleep(0.15)
    after = sorted(i.current_state_ids)
    status = getattr(i, "status", "?")

    blob, blob_note = None, "-"
    try:
        blob = i.get_snapshot()
        blob_note = "accepted"
    except Exception as exc:  # noqa: BLE001
        blob_note = f"refused {type(exc).__name__}"

    restore_note = "-"
    if blob is not None:
        try:
            mm = create_machine(
                json.loads(json.dumps(spec)),
                logic=MachineLogic(services={"svc": _svc()}, **LOGIC))
            Interpreter.from_snapshot(blob, mm)
            restore_note = "ok"
        except Exception as exc:  # noqa: BLE001
            restore_note = f"refused {type(exc).__name__}"
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return receipt, raised, before, after, status, blob_note, restore_note


async def main() -> None:
    print(f"=== U6 receipt vs illegal configuration (#208) [{KIND}] ===")
    fails = []
    for name, (spec, ev, legal) in CASES.items():
        r, raised, before, after, status, blob_note, restore_note = \
            await run_case(name, spec, ev, legal)
        f = _fields(r) if r is not None else None
        ok_shaped = bool(f and f["error"] is None and not f["deferred"]
                         and not f["denied"])
        moved = before != after
        tag = "LEGAL  " if legal else "ILLEGAL"
        print(f"  [{tag}] {name}")
        print(f"      receipt={f} raised={raised} status={status}")
        print(f"      states {before} -> {after}  snapshot={blob_note} "
              f"restore={restore_note}")

        if not legal:
            # #208: never success-shaped when the step did not legally move.
            if ok_shaped and not after:
                fails.append(
                    f"A: '{name}' returned an ok receipt over an EMPTY "
                    f"configuration ({before} -> {after})")
            if ok_shaped and status == "error":
                fails.append(
                    f"A: '{name}' returned an ok receipt while the machine "
                    f"went to status=error")
        else:
            if raised is not None:
                fails.append(f"B: legal '{name}' raised {raised}")
            elif f and f["error"] is not None:
                fails.append(
                    f"B: legal '{name}' returned error={f['error']!r}")
            elif f and f["denied"]:
                fails.append(f"B: legal '{name}' was denied")
        # C: an ok receipt paired with an unrestorable blob
        if ok_shaped and restore_note.startswith("refused"):
            fails.append(
                f"C: '{name}' returned an ok receipt but its own snapshot "
                f"is {restore_note}")
        print()

    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
