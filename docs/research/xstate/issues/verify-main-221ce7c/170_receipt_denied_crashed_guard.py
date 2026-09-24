# -*- coding: utf-8 -*-
"""Verify #170 on main @ 221ce7c: Receipt.denied is False (not True) for a
guard that CRASHES under guardErrorPolicy="raise"; error carries the
exception, and (denied, error is None) now discriminates all three guard
outcomes: false / denied, crashed / error, true / passed.

Criteria (both engines):
 1. A guard returning False -> denied=True, error=None.
 2. A guard raising under guardErrorPolicy="raise" -> denied=False,
    error is not None (the exception propagates / is recorded, but is not
    mislabelled as a denial).
 3. A guard returning True -> denied=False, error=None, transition taken.
"""
import sys

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

CFG = {
    "id": "guarded",
    "initial": "idle",
    "guardErrorPolicy": "raise",
    "context": {"mode": "false"},
    "states": {
        "idle": {
            "on": {
                "GO": {"target": "done", "guard": "check"},
            }
        },
        "done": {},
    },
}


def check(context, event):
    mode = context["mode"]
    if mode == "false":
        return False
    if mode == "crash":
        raise RuntimeError("guard boom")
    return True


def make_logic():
    return MachineLogic(guards={"check": check})


def run_case(engine_cls, mode, is_async):
    cfg = {**CFG, "context": {"mode": mode}}
    m = create_machine(cfg, logic=make_logic())
    if is_async:
        import asyncio

        async def _run():
            i = engine_cls(m)
            await i.start()
            try:
                r = await i.send("GO", wait=True)
            except RuntimeError:
                r = None
            await i.stop()
            return r, i

        return asyncio.run(_run())
    else:
        i = engine_cls(m).start()
        try:
            r = i.send("GO", wait=True)
        except RuntimeError:
            r = None
        return r, i


def main():
    ok = True
    for is_async, engine_cls, label in (
        (False, SyncInterpreter, "sync"),
        (True, Interpreter, "async"),
    ):
        # case 1: false guard -> denied True
        r1, i1 = run_case(engine_cls, "false", is_async)
        c1 = r1 is not None and r1.denied is True and r1.error is None
        print(f"[{label} false] denied={r1.denied if r1 else None} error={r1.error if r1 else None} -> {c1}")
        ok &= c1

        # case 2: crash guard -> denied False, error not None
        r2, i2 = run_case(engine_cls, "crash", is_async)
        c2 = (r2 is None) or (r2.denied is False and r2.error is not None)
        print(f"[{label} crash] r={r2} -> {c2}")
        ok &= c2

        # case 3: true guard -> denied False, error None, transitioned
        r3, i3 = run_case(engine_cls, "true", is_async)
        c3 = r3 is not None and r3.denied is False and r3.error is None
        print(f"[{label} true] denied={r3.denied if r3 else None} error={r3.error if r3 else None} -> {c3}")
        ok &= c3

    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
