"""Follow-up to n6: `invoke.src: null` is the ONE non-string src that builds
clean.  What does the machine then do -- and is a missing service reported?"""
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {"id": "f", "initial": "run", "context": {},
       "states": {"run": {"invoke": {"id": "job", "src": None,
                                     "onDone": {"target": "done"},
                                     "onError": {"target": "oops"}}},
                  "done": {}, "oops": {}}}

async def main():
    out = {}
    for strict_cfg in (False, True):
        try:
            m = create_machine(json.loads(json.dumps(CFG)),
                               logic=MachineLogic(),
                               strict_config=strict_cfg)
        except Exception as ex:                # noqa: BLE001
            out[f"strict_config={strict_cfg}"] = f"build: {type(ex).__name__}: {ex}"
            continue
        i = Interpreter(m)
        try:
            await i.start()
            await asyncio.sleep(0.3)
            blob = i.get_persisted_snapshot()
            b = json.loads(blob) if isinstance(blob, str) else blob
            out[f"strict_config={strict_cfg}"] = {
                "state": sorted(i.current_state_ids),
                "status": i.status,
                "last_error": repr(i.last_error),
                "pending_invocations": [str(x) for x in
                                        (i.pending_invocations() or [])],
                "snapshot_invocations": b.get("invocations"),
            }
            await i.stop()
        except Exception as ex:                # noqa: BLE001
            out[f"strict_config={strict_cfg}"] = f"run: {type(ex).__name__}: {ex}"
    print(json.dumps(out, indent=1, default=str))

asyncio.run(main())
