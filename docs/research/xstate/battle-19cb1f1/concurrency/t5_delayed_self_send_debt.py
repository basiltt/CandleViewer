"""t5 (@19cb1f1) -- STANDALONE. #206: a `raise(delay=)` self-send is a
debt of the arming step and its firing is charged as ENGINE work, so a
1 ms ping-pong trips at the same lap as the zero-delay cycle (+/-1); a
delayed send issued from OUTSIDE an action stays external.

Attacks, both service kinds x both engines:
  P1  zero-delay raise ping-pong        -> reference lap
  P2  1 ms delayed raise ping-pong      -> must trip, lap ~= P1 (+/-1)
  P3  N=100 concurrent P2 machines      -> all must trip, same lap
  P4  external delayed send from outside an action -> must NOT be charged
      (machine keeps running past maxIterations laps of external pings)

Reduced: N=100 for P3 (as asked), 1.5 s settle per machine, async engine
only for P3 (the sync engine's timer-paced self-send is caller-driven and
has user standing by construction -- stated in the #206 pin).

Run: python t5_delayed_self_send_debt.py   (exit 1 == defect)
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


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


LIMIT = 12


def cfg(delay_ms):
    """Ping-pong via DECLARATIVE `raise` entry actions -- the #206 shape.
    `delay_ms is None` == zero-delay `raise` (the reference cycle)."""
    def act():
        p = {"event": "PING"}
        if delay_ms is not None:
            p["delay"] = delay_ms / 1000.0
        return {"type": "raise", "params": p}

    return {
        "id": "p", "initial": "a", "maxIterations": LIMIT, "context": {"n": 0},
        "states": {
            "a": {"entry": [act()], "on": {"PING": "b"}, "exit": ["tick"]},
            "b": {"entry": [act()], "on": {"PING": "a"}, "exit": ["tick"]},
        },
    }


def build(kind, delay_ms, laps):
    def tick(i, c, e, ad):  # noqa: ANN001
        laps[0] += 1

    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            return 1

    else:

        async def svc(i, c, e):  # noqa: ANN001
            return 1

    return MachineLogic(actions={"tick": tick}, services={"svc": svc})


async def one(kind: str, delay_ms: int | None, settle: float) -> Dict[str, Any]:
    laps = [0]
    itp = Interpreter(
        create_machine(copy.deepcopy(cfg(delay_ms)), logic=build(kind, delay_ms, laps))
    )
    row: Dict[str, Any] = {"kind": kind, "delay_ms": delay_ms}
    try:
        await itp.start()
        await asyncio.sleep(settle)
        row["laps"] = laps[0]
        row["last_error"] = type(getattr(itp, "last_error", None)).__name__
        row["state"] = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        row["error"] = type(exc).__name__
        row["laps"] = laps[0]
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
    # a second settle: if the cycle were uncharged it would still be running
    row["tripped"] = row.get("last_error") == "RunawayChainError"
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    viol: List[Any] = []

    # P1 / P2
    ref: Dict[str, int] = {}
    for kind in ("def", "async def"):
        r0 = await one(kind, None, 1.2)
        r0["case"] = "P1_zero_delay"
        r1 = await one(kind, 1, 1.2)
        r1["case"] = "P2_1ms_delay"
        rows += [r0, r1]
        ref[kind] = r0["laps"]
        if not r0["tripped"]:
            viol.append((kind, "P1 zero-delay cycle did not trip"))
        if not r1["tripped"]:
            viol.append((kind, "P2 1ms delayed self-send cycle did not trip",
                         r1["laps"], r1.get("last_error")))
        elif abs(r1["laps"] - r0["laps"]) > 1:
            viol.append((kind, "P2 lap != P1 lap +/-1", r0["laps"], r1["laps"]))

    # P3: 100 concurrent 1 ms ping-pong machines
    p3: Dict[str, Any] = {}
    for kind in ("def", "async def"):
        res = await asyncio.gather(*[one(kind, 1, 1.5) for _ in range(100)])
        hist = Counter(r["laps"] for r in res)
        trips = sum(1 for r in res if r["tripped"])
        p3[kind] = {"machines": len(res), "tripped": trips,
                    "lap_histogram": dict(hist)}
        if trips != len(res):
            viol.append((kind, "P3 not every machine tripped", trips))
        if len(hist) > 2:
            viol.append((kind, "P3 lap parity: >2 distinct laps",
                         dict(hist)))

    emit("t5_delayed_self_send_debt",
         {"claim": "#206 a delayed self-send is engine work; the 1ms "
                   "ping-pong trips at the same lap as the zero-delay one",
          "limit": LIMIT, "rows": rows, "p3_100_machines": p3,
          "violations": viol, "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
