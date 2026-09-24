"""Final-verdict fresh-process re-reproduction: surviving Blockers + Highs.

Run with the pinned venv:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  _ref/xstate-statemachine/.venv-main/Scripts/python fv1_blockers_highs.py

No library source is modified. Public API only.
"""
import asyncio
import json
import threading
import logging
import time


def _snap(interp):
    raw = interp.get_persisted_snapshot()
    return json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

OUT = {}


# ---------- R4-04 (Blocker): SyncInterpreter.start() never terminates
def r4_04(max_iter, budget_s):
    cfg = {
        "id": "m",
        "type": "parallel",
        "maxIterations": max_iter,
        "states": {
            "A": {
                "initial": "a1",
                "states": {
                    "a1": {
                        "invoke": {"id": "sv", "src": "sv", "onDone": {"target": "a1"}}
                    },
                    "a2": {},
                },
            },
            "B": {"initial": "b1", "states": {"b1": {"always": {"target": "#m.A.a1"}}}},
        },
    }

    def sv(i, c, e):
        return 1

    res = {}

    def run():
        try:
            st = time.time()
            SyncInterpreter(
                create_machine(cfg, logic=MachineLogic(services={"sv": sv}))
            ).start()
            res["elapsed_s"] = round(time.time() - st, 3)
        except Exception as ex:  # noqa: BLE001
            res["err"] = repr(ex)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(budget_s)
    return {"max_iterations": max_iter, "finished": not t.is_alive(), **res}



if __name__ == "__main__":
    res = {
        "sweep": [r4_04(k, 8) for k in (18, 24, 28)],
        "default_1000": r4_04(1000, 20),
    }
    print(json.dumps(res, indent=1, default=str))
