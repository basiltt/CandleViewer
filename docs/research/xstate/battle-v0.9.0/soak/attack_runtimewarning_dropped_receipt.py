# -*- coding: utf-8 -*-
"""NEW round-13 attack: RuntimeWarning on dropped wait=True receipt (#232).

Standalone. A `def` action cannot await; if it calls
`i.send(..., wait=True)` and drops the receipt (never awaits it, never
hands it to ensure_future/add_done_callback/.result()), the object must
emit a RuntimeWarning when finalised -- like CPython does for a
never-awaited coroutine.

Also checks: does the warning surface if the whole thing runs inside
`asyncio.run(...)` under `-W error`? (brief says: "RuntimeWarning under
-W error inside asyncio (where does it surface?)"). We run this file
itself as the -W error worker via subprocess to catch it without killing
the main harness.
"""
from __future__ import annotations

import asyncio
import gc
import sys
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {
        "a": {
            "on": {
                "DROP": {"actions": ["drop_receipt"]},
                "USE": {"actions": ["use_receipt"]},
                "B": {"target": "b"},
            }
        },
        "b": {},
    },
}


def drop_receipt(i, ctx, ev, ad):
    i.send("B", wait=True)  # receipt discarded, never awaited


def use_receipt(i, ctx, ev, ad):
    r = i.send("B", wait=True)
    asyncio.ensure_future(r)  # counts as "use" per changelog


async def main_capture():
    logic = MachineLogic(actions={"drop_receipt": drop_receipt, "use_receipt": use_receipt})
    m = create_machine(CONFIG, logic=logic)
    i = Interpreter(m)
    await i.start()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i.send("DROP")
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        gc.collect()
    dropped_warns = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    print("DROP case: RuntimeWarning count =", len(dropped_warns))
    if dropped_warns:
        print("  message:", str(dropped_warns[0].message)[:150])

    # reset machine to 'a' by making a fresh interpreter for the USE case
    i2 = Interpreter(create_machine(CONFIG, logic=logic))
    await i2.start()
    with warnings.catch_warnings(record=True) as caught2:
        warnings.simplefilter("always")
        i2.send("USE")
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        gc.collect()
    use_warns = [w for w in caught2 if issubclass(w.category, RuntimeWarning)]
    print("USE case: RuntimeWarning count =", use_warns.__len__(), "(expect 0)")

    await i.stop()
    await i2.stop()
    ok = len(dropped_warns) >= 1 and len(use_warns) == 0
    print("RUNTIME_WARNING_OK:", ok)


if __name__ == "__main__":
    if "--werror-child" in sys.argv:
        # Run under -W error to see whether it surfaces as an *exception*
        # instead of a warning when the interpreter is strict.
        warnings.simplefilter("error", RuntimeWarning)
        logic = MachineLogic(actions={"drop_receipt": drop_receipt, "use_receipt": use_receipt})
        m = create_machine(CONFIG, logic=logic)

        async def run():
            i = Interpreter(m)
            await i.start()
            i.send("DROP")
            for _ in range(20):
                await asyncio.sleep(0.02)
                gc.collect()
            await i.stop()

        try:
            asyncio.run(run())
            print("WERROR_CHILD: no exception raised (warning did not surface as error here)")
        except RuntimeWarning as e:
            print("WERROR_CHILD: RuntimeWarning raised as exception:", str(e)[:150])
        except Exception as e:  # pragma: no cover - diagnostic only
            print("WERROR_CHILD: other exception:", type(e).__name__, str(e)[:150])
    else:
        asyncio.run(main_capture())
        # Now spawn a child under -W error to see where the warning surfaces.
        import subprocess

        r = subprocess.run(
            [sys.executable, "-W", "error", __file__, "--werror-child"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        print("---- -W error child stdout ----")
        print(r.stdout.strip())
        if r.stderr.strip():
            print("---- -W error child stderr (tail) ----")
            print("\n".join(r.stderr.strip().splitlines()[-15:]))
