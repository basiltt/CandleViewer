"""N6 -- shrunk repros for the two findings N5 produced.

D1  RECEIPT OVER AN EMPTY CONFIGURATION -- **VERIFIES CLEAN** (#208).
    Retained as the positive control. An earlier draft of this script
    scored it as a defect using a `getattr(r, "ok", ...)` oracle; `Receipt`
    has no `.ok` field, so the fallback read `True` on every receipt. The
    real field is `.error`, and the library fills it correctly. Recorded
    so the correction is auditable rather than silently dropped.

    The shape below is still worth keeping: a chart whose INITIAL state has
    a failing entry action under `actionErrorPolicy: "rollback"`.
    #208: "the receipt path now also refuses to report `ok` when the step
    ended with an illegal configuration". A chart whose INITIAL state has a
    failing entry action under `actionErrorPolicy: "rollback"` has nothing
    to roll back to: the rollback unwinds the initial descent and leaves
    `current_state_ids == []`. `await send(..., wait=True)` still resolves
    SUCCESS-SHAPED over that configuration. 42/704 cells in N5; shrunk here
    to two states and one action, both service/action kinds, both engines.

    Distinct from D9-fuzz-4 (R9-08): that one was an async-only transient
    that healed in ~500 ms. This configuration is empty PERMANENTLY and is
    reached on BOTH engines.

D2  DEF-LANE LAP PARITY, engine-work-only charts. #209 pins "all three
    lanes agree at limits 1-25". On an `always` + zero-delay `raise` cycle
    (no timers, no delayed sends -- pure engine work, exactly what the
    budget is supposed to charge), the sync engine runs FEWER laps than the
    async engine, and the gap GROWS with maxIterations. Swept 1-25 here.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

# ---------------------------------------------------------------------- D1

D1_CFG = {
    "id": "d1",
    "initial": "a",
    "actionErrorPolicy": "rollback",
    "context": {},
    "states": {
        "a": {"entry": ["boom"], "on": {"GO": "b"}},
        "b": {},
    },
}


def boom_def(i, c, e, a=None):
    raise RuntimeError("initial entry fails; rollback has no floor")


async def boom_async(i, c, e, a=None):
    raise RuntimeError("initial entry fails; rollback has no floor")


def receipt_ok(r):
    """Success-shaped: a real Receipt whose `error` is None. `Receipt` has
    no `.ok`; `.error` is the field #208 talks about."""
    from xstate_statemachine.events import Receipt

    if isinstance(r, BaseException) or not isinstance(r, Receipt):
        return False
    return r.error is None


async def d1_async(kind):
    m = create_machine(
        D1_CFG,
        logic=MachineLogic(
            actions={"boom": boom_def if kind == "def" else boom_async}
        ),
    )
    it = Interpreter(m)
    await it.start()
    ids_at_start = list(it.current_state_ids)
    try:
        r = await it.send("GO", wait=True)
    except Exception as exc:  # noqa: BLE001
        r = exc
    ids = list(it.current_state_ids)
    out = {
        "ids_after_start": ids_at_start,
        "ids_at_receipt": ids,
        "receipt": repr(r)[:90],
        "receipt_ok": receipt_ok(r),
        "last_transition_ok": it.last_transition_ok,
        "last_error": type(it.last_error).__name__ if it.last_error else None,
        "status": it.status,
    }
    await asyncio.sleep(0.6)
    out["ids_after_600ms"] = list(it.current_state_ids)
    try:
        it.get_snapshot()
        out["snapshot"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        out["snapshot"] = f"REFUSED:{type(exc).__name__}"
    await it.stop()
    return out


def d1_sync(kind):
    if kind != "def":
        return {"skip": "async action on SyncInterpreter"}
    m = create_machine(D1_CFG, logic=MachineLogic(actions={"boom": boom_def}))
    it = SyncInterpreter(m)
    it.start()
    ids_at_start = list(it.current_state_ids)
    try:
        r = it.send("GO")
    except Exception as exc:  # noqa: BLE001
        r = exc
    out = {
        "ids_after_start": ids_at_start,
        "ids_at_receipt": list(it.current_state_ids),
        "receipt": repr(r)[:90],
        "receipt_ok": receipt_ok(r),
        "last_transition_ok": it.last_transition_ok,
        "status": it.status,
    }
    try:
        it.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------- D2


def d2_cfg(mi):
    """`always` + zero-delay `raise` cycle. No timers, no delayed sends:
    every step is engine work the chain budget is meant to charge."""
    return {
        "id": "d2",
        "initial": "a",
        "maxIterations": mi,
        "actionErrorPolicy": "rollback",
        "context": {"laps": 0},
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}],
                "on": {"GO": "b"},
                "exit": ["tick"],
            },
            "b": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}],
                "on": {"GO": "c"},
                "exit": ["tick"],
            },
            "c": {"always": {"target": "a"}, "on": {"GO": "a"},
                  "exit": ["tick"]},
        },
    }


def tick(i, c, e, a=None):
    c["laps"] = c.get("laps", 0) + 1


async def d2_async(mi):
    m = create_machine(d2_cfg(mi), logic=MachineLogic(actions={"tick": tick}))
    it = Interpreter(m)
    await it.start()
    try:
        await it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    prev, stable = -1, 0
    for _ in range(200):
        await asyncio.sleep(0.01)
        if it.last_error is not None:
            break
        cur = it.context.get("laps", 0)
        if cur == prev:
            stable += 1
            if stable > 8:
                break
        else:
            prev, stable = cur, 0
    laps = it.context.get("laps", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    await it.stop()
    return laps, err


def d2_sync(mi):
    m = create_machine(d2_cfg(mi), logic=MachineLogic(actions={"tick": tick}))
    it = SyncInterpreter(m)
    it.start()
    try:
        it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    laps = it.context.get("laps", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        it.stop()
    except Exception:  # noqa: BLE001
        pass
    return laps, err


async def main():
    bad = 0
    print("D1 -- receipt shape over a PERMANENTLY empty configuration")
    print("     (initial entry fails under actionErrorPolicy: rollback)")
    for kind in ("def", "async def"):
        a = await d1_async(kind)
        print(f"   async engine / {kind:<9} {a}")
        if a["receipt_ok"] and not a["ids_at_receipt"]:  # expect: never
            bad += 1
            print("      => DEFECT: ok receipt over []")
    s = d1_sync("def")
    print(f"   sync engine  / def       {s}")
    if s.get("receipt_ok") and not s.get("ids_at_receipt", ["x"]):
        bad += 1
        print("      => DEFECT: ok receipt over []")
    print()

    print("D2 -- lap parity, engine-work-only cycle (always + raise0)")
    print("     #209 pins agreement at limits 1-25")
    mism = 0
    for mi in range(1, 26):
        la, ea = await d2_async(mi)
        ls, es = d2_sync(mi)
        tag = "SAME" if abs(la - ls) <= 1 else "DIFFER"
        if tag == "DIFFER":
            mism += 1
        print(
            f"   mi={mi:<3} sync={ls:<4}({es}) async={la:<4}({ea})  {tag}"
        )
    print()
    print(f"   parity mismatches over limits 1-25 = {mism}/25")
    bad += mism
    print()
    print(f"DEFECT CELLS = {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
