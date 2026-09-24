"""P1 (#218): timer-handle release on fire / cancel / exit / stop.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

BEATS = 200

ARM = {"type": "raise", "params": {"event": "BEAT", "delay": 1}}
CFG = {
    "id": "hb",
    "initial": "up",
    "context": {"n": 0},
    "states": {
        "up": {"entry": [ARM, "beat"], "on": {"BEAT": "down"}},
        "down": {"entry": [ARM, "beat"], "on": {"BEAT": "up"}},
    },
}


def _beat(i, c, e, a):
    c["n"] += 1


def _handles(i):
    return sum(len(v) for v in i._timer_handles.values())


async def _async_case():
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"beat": _beat}))
    ).start()
    peak = 0
    for _ in range(600):
        await asyncio.sleep(0.005)
        peak = max(peak, _handles(i))
        if i.context["n"] >= BEATS:
            break
    await asyncio.sleep(0.05)
    end = _handles(i)
    n = i.context["n"]
    await i.stop()
    return peak, end, n, _handles(i)


def _sync_case():
    s = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"beat": _beat}))
    ).start()
    peak = 0
    for _ in range(BEATS + 50):
        s.tick()
        peak = max(peak, _handles(s))
        if s.context["n"] >= BEATS:
            break
    s.tick()
    end = _handles(s)
    n = s.context["n"]
    s.stop()
    return peak, end, n, _handles(s)


def _cancel_case():
    """Arm with an id, cancel it, and re-use the id: no orphan handles."""
    cfg = {
        "id": "c",
        "initial": "a",
        "states": {
            "a": {
                "entry": [],
                "on": {"CANCEL": {"target": "b", "actions": []}},
            },
            "b": {},
        },
    }

    ARM_X = {"type": "raise", "params": {"event": "LATE", "delay": 10000, "id": "x"}}
    cfg["states"]["a"]["entry"] = [ARM_X, ARM_X, ARM_X]
    cfg["states"]["a"]["on"]["CANCEL"]["actions"] = [
        {"type": "cancel", "params": {"sendId": "x"}}
    ]

    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    armed = _handles(s)
    s.send("CANCEL")
    after = _handles(s)
    s.stop()
    return armed, after, _handles(s)


def main():
    a = asyncio.run(_async_case())
    print(f"async  peak={a[0]} after_settle={a[1]} beats={a[2]} after_stop={a[3]}")
    s = _sync_case()
    print(f"sync   peak={s[0]} after_settle={s[1]} beats={s[2]} after_stop={s[3]}")
    try:
        c = _cancel_case()
        print(f"cancel armed={c[0]} after_cancel={c[1]} after_stop={c[2]}")
    except Exception as exc:  # noqa: BLE001
        print(f"cancel RAISED {type(exc).__name__}: {exc}")
    ok = a[0] <= 2 and a[1] <= 1 and s[0] <= 2 and s[1] <= 1
    print("VERDICT:", "BOUNDED" if ok else "LEAK")


if __name__ == "__main__":
    sys.exit(main())
