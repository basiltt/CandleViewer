"""G2 -- NEW ATTACK: #201 lap parity, stated exactly.

The round-8 pin says "all three lanes now agree at every limit tested".
r20 (prior round's script) shows agreement at maxIterations 20/1000/None but
DISAGREEMENT at 1 and 5 on both `nested_invoke` and `rollback_ondone`.
This script is the standalone minimal form, run over a limit sweep
1..25 on BOTH service kinds, both engines.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, copy, logging, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

LAPS = []
_orig_a = bi.BaseInterpreter._process_event


async def _patched(self, e):
    LAPS.append(getattr(e, "type", "?"))
    return await _orig_a(self, e)


bi.BaseInterpreter._process_event = _patched


def nested_invoke(mi):
    c = {
        "id": "m0",
        "initial": "a",
        "states": {
            "a": {
                "initial": "a",
                "invoke": {
                    "id": "i1",
                    "src": "svc",
                    "onDone": {"target": "#m0.a.b"},
                },
                "states": {
                    "a": {},
                    "b": {
                        "invoke": {
                            "id": "i2",
                            "src": "svc",
                            "onDone": {"target": "#m0.a.a"},
                        }
                    },
                },
            }
        },
    }
    if mi is not None:
        c["maxIterations"] = mi
    return c


def rollback_ondone(mi):
    c = {
        "id": "m0",
        "initial": "a",
        "actionErrorPolicy": "rollback",
        "states": {
            "a": {
                "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}
            },
            "b": {"always": {"target": "a"}},
        },
    }
    if mi is not None:
        c["maxIterations"] = mi
    return c


def dsvc(i, c, e):
    return {"v": 1}


async def asvc(i, c, e):
    return {"v": 1}


def run_sync(cfg, svc):
    LAPS.clear()
    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(services={"svc": svc}))
    it = SyncInterpreter(m)
    try:
        it.start()
    except Exception as exc:
        return len(LAPS), type(exc).__name__
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        it.stop()
    except Exception:
        pass
    return len(LAPS), err


async def run_async(cfg, svc):
    LAPS.clear()
    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(services={"svc": svc}))
    it = Interpreter(m)
    try:
        await it.start()
    except Exception as exc:
        return len(LAPS), type(exc).__name__
    for _ in range(60):
        await asyncio.sleep(0.01)
        if it.last_error is not None:
            break
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        await it.stop()
    except Exception:
        pass
    return len(LAPS), err


async def main():
    print("G2 -- #201 lap parity sweep, both service kinds, both engines")
    bad = 0
    for shape, build in (("nested_invoke", nested_invoke), ("rollback_ondone", rollback_ondone)):
        for kind, svc in (("def", dsvc), ("async def", asvc)):
            rows = []
            for mi in list(range(1, 11)) + [15, 20, 25]:
                cfg = build(mi)
                sl, se = run_sync(cfg, svc)
                al, ae = await run_async(cfg, svc)
                same = sl == al
                if not same:
                    bad += 1
                rows.append((mi, sl, al, se, ae, same))
            print(f"\n  {shape} / {kind}")
            for mi, sl, al, se, ae, same in rows:
                flag = "SAME " if same else "DIFFER"
                print(
                    f"    mi={mi:<3d} sync_laps={sl:<5d} async_laps={al:<5d} "
                    f"{flag} sync_err={se} async_err={ae}"
                )
    print(f"\n  TOTAL lap-parity mismatches = {bad}")


asyncio.run(main())
