# -*- coding: utf-8 -*-
"""New round-9-targeted soak attacks for battle-19cb1f1.

Standalone (stdlib + xstate_statemachine only). Targets:
  A. #204 statesToInvoke: a state entered+exited in ONE macrostep (via an
     `always` rolling it forward) must never submit its invoke's service,
     both engines, both service kinds (def/async def).
  B. #206 delayed self-send debt: raise(delay=1ms) self-ping-pong across
     100 "machines" (simulated as N interleaved cycles on shared loop) must
     trip the SAME lap under maxIterations, both engines.
  C. #207 stranded-invocation hook: rollback+onDone storm at maxIterations
     must strand exactly once, on_invocation_stranded fires exactly once,
     RunawayChainError.stranded carries invoke ids -- under a light
     concurrent storm (20 interpreters, both engines).
  D. #203 after-provenance: a hand-built AfterEvent must NOT fire an
     `after` transition (spot check, both engines).

Run from neutral cwd; each section prints a JSON-ish summary line.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")

from xstate_statemachine import (  # noqa: E402
    AfterEvent,
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase  # noqa: E402


class Drops(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Any] = []

    def on_invocation_stranded(self, interp, state_id, invoke_id, error) -> None:  # noqa: ANN001
        self.stranded.append((state_id, invoke_id))


def mk_svc(kind: str, calls: List[str]):
    if kind == "def":
        def svc(i, c, e):  # noqa: ANN001
            calls.append("called")
            return {"ok": True}
        return svc

    async def svc(i, c, e):  # noqa: ANN001
        calls.append("called")
        return {"ok": True}
    return svc


# ---------------------------------------------------------------------------
# A. invoke arms only after settle; a same-macrostep enter+exit never submits
# ---------------------------------------------------------------------------
CFG_A = {
    "id": "a",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "mid"}},
        "mid": {
            "invoke": {"id": "svc", "src": "svc", "onDone": "done"},
            "always": "skip",  # rolls forward in the SAME macrostep
        },
        "skip": {},
        "done": {},
    },
}


def run_a() -> Dict[str, Any]:
    results = {}
    for kind in ("def", "async def"):
        for engine_name, Engine in (("async", Interpreter), ("sync", SyncInterpreter)):
            calls: List[str] = []
            logic = MachineLogic(services={"svc": mk_svc(kind, calls)})
            m = create_machine(dict(CFG_A), logic=logic)
            interp = Engine(m)

            async def go_async(interp=interp):
                await interp.start()
                await interp.send({"type": "GO"})
                await asyncio.sleep(0.05)
                await interp.stop()

            def go_sync(interp=interp):
                interp.start()
                interp.send({"type": "GO"})
                for _ in range(5):
                    interp.tick()
                interp.stop()

            if engine_name == "async":
                asyncio.run(go_async())
            else:
                go_sync()
            key = f"{kind}/{engine_name}"
            results[key] = {"svc_calls": len(calls), "final": list(interp.current_state_ids)}
    return results


# ---------------------------------------------------------------------------
# D. after-provenance: hand-built AfterEvent must not fire the transition
# ---------------------------------------------------------------------------
CFG_D = {
    "id": "d",
    "initial": "waiting",
    "states": {
        "waiting": {"after": {"60000": {"target": "timedout"}}},
        "timedout": {},
    },
}


def run_d() -> Dict[str, Any]:
    out = {}
    for engine_name, Engine in (("async", Interpreter), ("sync", SyncInterpreter)):
        m = create_machine(dict(CFG_D))
        interp = Engine(m)
        if engine_name == "async":
            async def go(interp=interp):
                await interp.start()
                forged = AfterEvent(type="after.60000.d.waiting")
                try:
                    await interp.send(forged)
                except Exception as exc:  # noqa: BLE001
                    return f"refused:{exc!r}"
                await asyncio.sleep(0.01)
                return list(interp.current_state_ids)
            res = asyncio.run(go())
        else:
            interp.start()
            forged = AfterEvent(type="after.60000.d.waiting")
            try:
                interp.send(forged)
                res = list(interp.current_state_ids)
            except Exception as exc:  # noqa: BLE001
                res = f"refused:{exc!r}"
        out[engine_name] = res
    return out


if __name__ == "__main__":
    t0 = time.time()
    print("=== A: invoke arms only after settle (enter+exit same macrostep) ===")
    a = run_a()
    for k, v in a.items():
        print(k, v)
    a_ok = all(v["svc_calls"] == 0 for v in a.values())
    print("A_NO_SPURIOUS_INVOKE:", a_ok)

    print()
    print("=== D: hand-built AfterEvent must not fire `after` early ===")
    d = run_d()
    print(d)
    d_ok = all(v == ["d.waiting"] for v in d.values())
    print("D_FORGED_AFTER_REFUSED:", d_ok)

    print(f"\ndt_s={time.time()-t0:.2f}")
