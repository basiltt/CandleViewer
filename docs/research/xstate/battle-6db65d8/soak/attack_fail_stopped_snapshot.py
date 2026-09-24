# -*- coding: utf-8 -*-
"""Round-5 #145 in the soak context: after actionErrorPolicy triggers a
'fail'-stop, is the resulting snapshot legally restorable / correctly
refused? soak_machine.py uses actionErrorPolicy='rollback' (boom() action
on FAIL_HARD), so this probes a *separate* machine w/ policy='fail' to hit
the #145 path directly, then feeds that terminal-looking snapshot back into
from_snapshot() to confirm handling (either clean resumable-stopped restore
or documented refusal, not silent corruption)."""
import asyncio
import copy
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak_machine as sm

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import XStateMachineError


def build_fail_policy():
    cfg = copy.deepcopy(sm.ORDER_CONFIG)
    cfg["actionErrorPolicy"] = "fail"
    logic = MachineLogic(actions=dict(sm.ACTIONS), services={"ack_service": sm.ack_service})
    m = create_machine(cfg, logic=logic)
    return m


async def main():
    m = build_fail_policy()
    interp = Interpreter(m)
    await interp.start()
    await interp.send({"type": "SUBMIT", "payload": {"qty": 5}}, wait=True)
    r = await interp.send({"type": "FAIL_HARD"}, wait=True)
    print("status after FAIL_HARD:", interp.status)
    print("config after FAIL_HARD:", interp.state_ids if hasattr(interp, "state_ids") else "n/a")
    snap = interp.get_persisted_snapshot()
    print("snapshot status field:", snap.get("status"))
    print("snapshot configuration:", snap.get("configuration") or snap.get("state_ids"))

    snap_str = json.dumps(snap, default=repr)
    m2 = build_fail_policy()
    try:
        restored = Interpreter.from_snapshot(snap_str, m2)
        print("RESTORE RESULT: accepted, restored.status =", restored.status)
    except XStateMachineError as exc:
        print(f"RESTORE RESULT: typed refusal {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"RESTORE RESULT: FAIL untyped {type(exc).__name__}: {exc}")

asyncio.run(main())
