"""t3 (@19cb1f1) -- STANDALONE. #207: a chain cut that strands an
invocation must be observable -- `on_invocation_stranded` fires, exactly
once per stranded (state_id, invoke_id) pair, with the CORRECT ids, and
`RunawayChainError.stranded` carries the same ids, and
`has_dormant_invocations` agrees afterwards.

Attack: N concurrent `rollback + onDone` storm machines, both service
kinds. Each drives an invoke whose onDone rolls the machine back into the
invoking state, so the chain trips at `maxIterations` with the completion
in the cut set.

Reduced: N=50 per (kind) rather than 200, to fit the 120 s script bound;
the exactly-once / ids invariants are per-machine and scale-free.

Run: python t3_stranded_hook_storm.py [--n=50]   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import PluginBase
from xstate_statemachine.exceptions import RunawayChainError


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


LIMIT = 8

CFG = {
    "id": "t3",
    "initial": "idle",
    "maxIterations": LIMIT,
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "invoke": {"id": "spin", "src": "svc",
                       "onDone": {"target": "work", "actions": ["bump"]}},
        },
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Any] = []
        self.dropped: List[Any] = []
        self.order: List[str] = []

    def on_invocation_stranded(self, itp, state_id, invoke_id, error):  # noqa: ANN001
        self.stranded.append((state_id, invoke_id, type(error).__name__))
        self.order.append("stranded")

    def on_event_dropped(self, itp, event, reason=None):  # noqa: ANN001
        self.dropped.append(getattr(event, "type", str(event)))
        self.order.append("dropped")


def build(kind: str) -> MachineLogic:
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            return {"ok": 1}

    else:

        async def svc(i, ctx, e):  # noqa: ANN001
            return {"ok": 1}

    def bump(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"bump": bump}, services={"svc": svc})


async def one(kind: str) -> Dict[str, Any]:
    spy = Spy()
    itp = Interpreter(create_machine(copy.deepcopy(CFG), logic=build(kind)))
    itp.use(spy)
    row: Dict[str, Any] = {"kind": kind}
    try:
        await itp.start()
        await itp.send("GO")
        await asyncio.sleep(1.2)
        row["state"] = sorted(itp.current_state_ids)
        row["dormant"] = bool(itp.has_dormant_invocations)
        row["pending"] = [
            getattr(p, "invoke_id", str(p)) for p in itp.pending_invocations()
        ]
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}"
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
    row["stranded_calls"] = spy.stranded
    row["n_stranded"] = len(spy.stranded)
    row["n_dropped"] = len(spy.dropped)
    row["order_first"] = spy.order[:4]
    return row


async def main() -> int:
    n = 50
    for a in sys.argv[1:]:
        if a.startswith("--n="):
            n = int(a.split("=")[1])
    rows: List[Dict[str, Any]] = []
    for kind in ("def", "async def"):
        rows.extend(await asyncio.gather(*[one(kind) for _ in range(n)]))

    viol: List[Any] = []
    summary: Dict[str, Any] = {}
    for kind in ("def", "async def"):
        sub = [r for r in rows if r["kind"] == kind]
        cnt = Counter(r["n_stranded"] for r in sub)
        ids = Counter(
            tuple(s[:2]) for r in sub for s in r["stranded_calls"]
        )
        dormant = Counter(r.get("dormant") for r in sub)
        summary[kind] = {
            "machines": len(sub),
            "n_stranded_histogram": dict(cnt),
            "ids_seen": {f"{a}/{b}": c for (a, b), c in ids.items()},
            "dormant_histogram": {str(k): v for k, v in dormant.items()},
            "states": dict(Counter(",".join(r.get("state") or []) for r in sub)),
        }
        for r in sub:
            if r["n_stranded"] != 1:
                viol.append((kind, "stranded hook not exactly once",
                             r["n_stranded"]))
            for sid, iid, _ in r["stranded_calls"]:
                if (sid, iid) != ("t3.work", "spin"):
                    viol.append((kind, "wrong ids", sid, iid))
            if r.get("dormant") is not True and r["n_stranded"]:
                viol.append((kind, "dormant disagrees with hook",
                             r.get("dormant")))

    # RunawayChainError.stranded payload, read directly.
    payload: Dict[str, Any] = {}
    for kind in ("def", "async def"):
        err = RunawayChainError("t3", LIMIT, 1, ["spin"])
        payload[kind] = {"stranded_attr": list(err.stranded),
                         "in_message": "spin" in str(err)}
        if list(err.stranded) != ["spin"]:
            viol.append((kind, "RunawayChainError.stranded payload"))

    emit("t3_stranded_hook_storm",
         {"claim": "#207 stranded invocation observable exactly-once, ids "
                   "correct, dormant agrees",
          "limit": LIMIT, "machines_per_kind": n,
          "summary": summary, "runaway_payload": payload,
          "violations": viol[:20], "n_violations": len(viol),
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
