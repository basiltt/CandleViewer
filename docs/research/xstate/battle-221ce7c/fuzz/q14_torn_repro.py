"""Q14 -- D7-fuzz-2 MINIMAL repro (shrunk by q13_torn_shrink.py).
`await send(GO, wait=True)` RESOLVES while the machine's configuration is
EMPTY: current_state_ids == [], every compound torn. No `on` handler is even
needed -- an UNHANDLED event is enough. Sync engine keeps a legal config on the
identical chart."""
import asyncio, copy, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.exceptions import SnapshotMidStepError, SnapshotCorruptError

CFG = {
    "id": "m", "initial": "a",
    "states": {"a": {
        "initial": "a",
        "always": {"target": "#m.a.a.a"},
        "states": {"a": {
            "initial": "a",
            "invoke": {"id": "inv", "src": "svc"},
            "states": {"a": {"type": "final"}}}}}},
}
def plain_svc(i, c, e): return {"ok": 1}
async def async_svc(i, c, e): return {"ok": 1}
KIND = "async"
def L():
    return MachineLogic(services={"svc": async_svc if KIND == "async" else plain_svc})

def sync_run():
    it = SyncInterpreter(create_machine(copy.deepcopy(CFG),
        logic=MachineLogic(services={"svc": plain_svc}))); it.start()
    out = [sorted(it.current_state_ids)]
    for ev in ("GO", "GO"):
        try: it.send(ev)
        except Exception as e: out.append(f"raise:{type(e).__name__}")
        out.append(sorted(it.current_state_ids))
    it.stop(); return out

async def async_run():
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=L()))
    await asyncio.wait_for(it.start(), 10)
    out = [("start", sorted(it.current_state_ids))]
    for ev in ("GO", "GO"):
        try: await asyncio.wait_for(it.send(ev, wait=True), 10)
        except asyncio.TimeoutError: out.append((ev, "SEND_TIMEOUT")); break
        ids = sorted(it.current_state_ids)
        out.append((ev, ids, f"ok={it.last_transition_ok}",
                    f"err={type(it.last_error).__name__ if it.last_error else None}",
                    f"status={it.status}"))
        if not ids:
            try: it.get_persisted_snapshot(); snap = "PRODUCED"
            except (SnapshotMidStepError, SnapshotCorruptError) as e: snap = f"REFUSED:{type(e).__name__}"
            out.append(("  snapshot-at-torn", snap))
            await asyncio.sleep(0.5)
            out.append(("  +500ms heal?", sorted(it.current_state_ids), f"status={it.status}"))
    await it.stop(); return out

async def main():
    global KIND
    print("sync (plain svc):", sync_run())
    for kind in ("plain", "async"):
        KIND = kind
        hits = 0; first = None
        for k in range(10):
            r = await async_run()
            if any(isinstance(x, tuple) and len(x) > 1 and x[1] == [] for x in r):
                hits += 1
            first = first or r
        print(f"\n== async engine, `{kind} def` service: EMPTY config {hits}/10 ==")
        for line in first:
            print("   ", line)
asyncio.run(main())
