"""R3 -- MINIMAL standalone repro of D8-fuzz-1:
`await send(EV, wait=True)` resolves with `current_state_ids == []`,
`last_transition_ok=True`, `last_error=None`, `status="running"`.

Shrunk from this build's own f2 `B2-illegal-configuration` capture by
r2_torn_shrink.py (1230 -> 284 bytes).  The window is transient now (it heals
within ~500 ms, unlike the round-7 defect which never healed) -- but the
caller's own "this step is complete" signal is the exact instant the
configuration is empty and every health field reports success.

Ablation: `async def` service vs `plain def` service; async engine vs sync.
"""
import asyncio, copy, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    SnapshotCorruptError,
)

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 38,
    "after": {"17": {"target": "#m.a.c"}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a.a"},
            "states": {
                "a": {
                    "initial": "a",
                    "invoke": {"id": "inv", "src": "svc"},
                    "states": {"a": {"type": "final"}},
                },
                "c": {},
            },
        }
    },
}


async def async_svc(i, c, e):
    return {"ok": 1}


def plain_svc(i, c, e):
    return {"ok": 1}


def mk(svc):
    return create_machine(
        copy.deepcopy(CFG), logic=MachineLogic(services={"svc": svc})
    )


def snap(it):
    try:
        it.get_persisted_snapshot()
        return "PRODUCED"
    except (SnapshotMidStepError, SnapshotCorruptError) as e:
        return f"REFUSED:{type(e).__name__}"
    except Exception as e:
        return f"UNTYPED:{type(e).__name__}"


async def trial(svc):
    it = Interpreter(mk(svc))
    await asyncio.wait_for(it.start(), 10)
    for ev in ("GO", "GO", "PING", "NOPE"):
        try:
            await asyncio.wait_for(it.send(ev, wait=True), 8)
        except asyncio.TimeoutError:
            await it.stop()
            return ("SEND_TIMEOUT",)
        except Exception:
            continue
        if not list(it.current_state_ids):
            row = (
                "EMPTY",
                f"ok={it.last_transition_ok}",
                f"err={type(it.last_error).__name__ if it.last_error else None}",
                f"status={it.status}",
                f"snapshot={snap(it)}",
            )
            await asyncio.sleep(0.5)
            row += (f"+500ms ids={sorted(it.current_state_ids)}",)
            await it.stop()
            return row
    await it.stop()
    return ("ok",)


def run_sync(svc):
    it = SyncInterpreter(mk(svc))
    it.start()
    out = [sorted(it.current_state_ids)]
    for ev in ("GO", "GO", "PING", "NOPE"):
        try:
            it.send(ev)
        except Exception as e:
            out.append(f"raise:{type(e).__name__}")
        out.append(sorted(it.current_state_ids))
    it.stop()
    return out


async def main(n=15):
    print("== sync engine, plain def svc ==")
    print("  ", run_sync(plain_svc))
    for name, svc in (("async def", async_svc), ("plain def", plain_svc)):
        hits = 0
        sample = None
        for _ in range(n):
            r = await trial(svc)
            if r[0] == "EMPTY":
                hits += 1
                sample = sample or r
        print(f"== async engine, {name:<9} svc: EMPTY config {hits}/{n} ==")
        if sample:
            for x in sample:
                print("    ", x)


asyncio.run(main())
