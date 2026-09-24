"""P15 (STANDALONE): which forged engine events does `strict` actually
refuse? #195 routes user-built engine NamedTuples through
`is_known_event(user_sent=True)`, which refuses names starting with
ENGINE_EVENT_SHAPES. But the refusal only helps under `strict=True`; with
strict off (the default) the forged event is merely "unhandled" -- and for
`done.state.*` / `after.*` it is not unhandled at all, it TRANSITIONS
(see P1/P2).

Table: engine name x strict on/off x engine, reporting refused / handled.
Exit 1 if any forged event is HANDLED (i.e. drove a transition).
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
    DoneEvent, AfterEvent, ErrorEvent, UnknownEventError,
)

CFG = {
    "id": "m",
    "initial": "work",
    "states": {
        "work": {
            "type": "parallel",
            "onDone": {"target": "fin"},
            "after": {"60000": {"target": "fin"}},
            "states": {
                "a": {"initial": "r", "states": {"r": {"on": {"FA": "d"}}, "d": {"type": "final"}}},
                "b": {"initial": "r", "states": {"r": {"on": {"FB": "d"}}, "d": {"type": "final"}}},
            },
        },
        "fin": {},
    },
}

CASES = {
    "DoneEvent(done.state.m.work)": lambda: DoneEvent("done.state.m.work", {}, "m.work"),
    "AfterEvent(after.60000.m.work)": lambda: AfterEvent("after.60000.m.work", None, None),
    "DoneEvent(done.invoke.NOPE)": lambda: DoneEvent("done.invoke.NOPE", {}, "NOPE"),
    "ErrorEvent(error.platform.NOPE)": lambda: ErrorEvent("error.platform.NOPE", RuntimeError("x"), "NOPE"),
}


def build(strict):
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic()), strict


def outcome(ids):
    return "TRANSITIONED" if "m.fin" in ids else "no effect"


async def run_async(mk, strict):
    m, _ = build(strict)
    i = Interpreter(m, strict=strict)
    await i.start()
    res = "no effect"
    try:
        await i.send(mk())
        await asyncio.sleep(0.05)
        res = outcome(set(i.current_state_ids))
    except UnknownEventError:
        res = "refused(strict)"
    finally:
        await i.stop()
    return res


def run_sync(mk, strict):
    m, _ = build(strict)
    i = SyncInterpreter(m, strict=strict)
    i.start()
    try:
        i.send(mk())
        return outcome(set(i.current_state_ids))
    except UnknownEventError:
        return "refused(strict)"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}"
    finally:
        i.stop()


async def main():
    rows = []
    for name, mk in CASES.items():
        for strict in (False, True):
            rows.append((name, strict, await run_async(mk, strict), run_sync(mk, strict)))
    return rows


bad = 0
print(f"{'forged event':<34} {'strict':<7} {'async':<16} sync")
for name, strict, a, s in asyncio.run(asyncio.wait_for(main(), 30.0)):
    print(f"{name:<34} {str(strict):<7} {a:<16} {s}")
    if "TRANSITIONED" in (a, s):
        bad = 1
print("VERDICT:", "A FORGED EVENT DROVE A TRANSITION (bug)" if bad else "all refused/inert (ok)")
sys.exit(bad)
