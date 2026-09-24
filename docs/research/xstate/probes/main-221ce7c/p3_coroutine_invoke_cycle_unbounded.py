"""L-3 probe: #166/#167/#168 bound the invoke cycle only for PLAIN-def
services. A COROUTINE service's `done.invoke` is delivered with
`await self.send(done_event)` from a task -- so it lands in the INBOX, not
the priority lane. In the run loop that means:

  * `_deliver_priority` never runs -> `_raise_depth` is never incremented,
    so the chain budget never accumulates; and
  * `from_inbox` is True, so `if not is_system_event(event) or from_inbox`
    RESETS `_settle_iterations` / `_settle_tripped` to 0 on every lap.

Both bounds are therefore defeated on the coroutine path. Same machine
shape as the #168 `ver -> arm -> ver` invoke ping-pong; only the service's
`def` vs `async def` differs. The sync engine bounds both.
"""

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

# ver --(always)--> arm --(invoke completes)--> ver --(always)--> arm ...
CONFIG = {
    "id": "p3",
    "initial": "ver",
    "context": {"laps": 0},
    "maxIterations": 50,
    "states": {
        "ver": {"always": {"target": "arm"}},
        "arm": {
            "invoke": {
                "src": "svc",
                "id": "svc",
                "onDone": {"target": "ver", "actions": ["lap"]},
            }
        },
    },
}


def lap(interp, ctx, ev, action_def):  # noqa: ANN001
    ctx["laps"] += 1


def svc_plain(interp, ctx, ev):  # noqa: ANN001
    return 1


async def svc_coro(interp, ctx, ev):  # noqa: ANN001
    return 1


async def run(kind: str, service) -> None:  # noqa: ANN001
    m = create_machine(
        CONFIG, logic=MachineLogic(actions={"lap": lap}, services={"svc": service})
    )
    interp = Interpreter(m)
    await interp.start()
    # Watchdog: the whole point is whether this terminates.
    for _ in range(300):  # ~15 s ceiling
        await asyncio.sleep(0.05)
        if interp.context["laps"] > 5000:
            break
        if interp._chain_tripped or interp._settle_tripped:
            break
    laps = interp.context["laps"]
    print(
        f"[{kind}] laps={laps} raise_depth={interp._raise_depth} "
        f"chain_tripped={interp._chain_tripped} "
        f"settle_tripped={interp._settle_tripped} "
        f"last_error={type(interp.last_error).__name__}"
    )
    print(
        f"[{kind}] VERDICT:",
        "BOUNDED" if (interp._chain_tripped or interp._settle_tripped)
        else f"UNBOUNDED (limit was 50, ran {laps} laps)",
    )
    try:
        await asyncio.wait_for(interp.stop(), timeout=3)
    except Exception:  # noqa: BLE001
        print(f"[{kind}] stop() timed out")


async def main() -> None:
    await run("plain-def", svc_plain)
    await run("coroutine", svc_coro)


asyncio.run(main())
