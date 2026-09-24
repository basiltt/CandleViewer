"""VERIFY #222 on de2da4e (STANDALONE; stdlib + xstate_statemachine only).

Claim: a chain-budget/settle-budget trip is STICKY via `chain_trips`
(monotonic counter) and `last_chain_error` (latch), unlike the per-step
`last_error` which the next clean event erases. `clear_chain_error()`
clears the latch (count keeps counting). Verified across >=10 benign
events, on both engines, both action spellings.

Exit 0 = all cells pass.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, RunawayChainError, SyncInterpreter, create_machine

MAXIT = 6
CFG = {
    "id": "trip",
    "initial": "spin",
    "maxIterations": MAXIT,
    "states": {
        "spin": {
            "entry": [
                {"type": "raise", "params": {"event": "LAP"}},
                "bump",
            ],
            "on": {
                "LAP": {"target": "spin", "reenter": True},
                "BENIGN": {"target": "spin", "reenter": False},
            },
        }
    },
}


def _mk(logic):
    return create_machine(CFG, logic=logic)


async def cell_async(kind):
    if kind == "async":
        async def bump(i, c, e, a):
            pass
    else:
        def bump(i, c, e, a):
            pass

    logic = MachineLogic(actions={"bump": bump})
    i = Interpreter(_mk(logic))
    await i.start()
    await asyncio.sleep(0.2)

    at = (i.chain_trips, type(i.last_chain_error).__name__, type(i.last_error).__name__)
    for _ in range(10):
        await i.send("BENIGN", wait=True)
    after = (i.chain_trips, type(i.last_chain_error).__name__, type(i.last_error).__name__)
    i.clear_chain_error()
    cleared = (i.chain_trips, i.last_chain_error)
    await i.stop()

    ok = (
        at == (1, "RunawayChainError", "RunawayChainError")
        and after == (1, "RunawayChainError", "NoneType")
        and cleared == (1, None)
    )
    return ok, at, after, cleared


def cell_sync():
    logic = MachineLogic(actions={"bump": lambda i, c, e, a: None})
    s = SyncInterpreter(_mk(logic))
    s.start()
    at = (s.chain_trips, type(s.last_chain_error).__name__, type(s.last_error).__name__)
    for _ in range(10):
        s.send("BENIGN")
    after = (s.chain_trips, type(s.last_chain_error).__name__, type(s.last_error).__name__)
    s.clear_chain_error()
    cleared = (s.chain_trips, s.last_chain_error)
    s.stop()

    ok = (
        at == (1, "RunawayChainError", "RunawayChainError")
        and after == (1, "RunawayChainError", "NoneType")
        and cleared == (1, None)
    )
    return ok, at, after, cleared


def main():
    fail = False

    ok, at, after, cleared = cell_sync()
    print(f"[sync sticky trip] at={at} after={after} cleared={cleared} {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    for kind in ("def", "async"):
        ok, at, after, cleared = asyncio.run(cell_async(kind))
        print(f"[async sticky trip kind={kind}] at={at} after={after} cleared={cleared} {'OK' if ok else 'FAIL'}")
        fail = fail or not ok

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
