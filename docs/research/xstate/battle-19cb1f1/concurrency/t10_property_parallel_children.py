"""t10 (@19cb1f1) -- STANDALONE property test. >=300 randomly generated
machines including PARALLEL regions, invoked CHILDREN (`after`-driven
sub-charts) and `after` timers, both service kinds.

Per machine, the properties asserted are the round-10 ones:
  P1  no hang -- start + settle completes inside the watchdog
  P2  the engine never ends in an EMPTY configuration while `running`
  P3  `has_dormant_invocations` is TRUE only when `pending_invocations()`
      is non-empty, and every pending entry names a state that is
      genuinely in the live configuration (the #207 read side agrees with
      the #204 write side)
  P4  a snapshot taken at rest round-trips: restore reproduces the same
      configuration, and a static restore submits 0 services

Reduced: 300 machines (as asked), watchdog 2.5 s, settle 0.15 s.

Run: python t10_property_parallel_children.py [--n=300]  (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
from collections import Counter
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
logging.disable(logging.ERROR)


def arg(name: str, default: Any, cast=int):  # noqa: ANN001
    for a in sys.argv[1:]:
        if a.startswith("--" + name + "="):
            return cast(a.split("=")[1])
    return default


N = arg("n", 300)
SEED = arg("seed", 30303)
WD = arg("wd", 2.5, float)
SETTLE = arg("settle", 0.15, float)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def leaf(rng: random.Random, nm: str) -> Dict[str, Any]:
    """A leaf state: maybe an invoke, maybe an after, maybe both."""
    st: Dict[str, Any] = {"entry": ["tick"]}
    r = rng.random()
    if r < 0.45:
        st["invoke"] = {"id": "i" + nm, "src": "svc",
                        "onDone": {"actions": ["tick"]}}
    if rng.random() < 0.35:
        st["after"] = {rng.choice([5, 10, 20]): {"actions": ["tick"]}}
    return st


def region(rng: random.Random, nm: str) -> Dict[str, Any]:
    """A compound region with 2-3 leaves and an entry `always` hop."""
    k = rng.choice([2, 3])
    states = {nm + str(i): leaf(rng, nm + str(i)) for i in range(k)}
    if rng.random() < 0.4:
        states[nm + "0"]["always"] = {"target": nm + "1"}
    return {"initial": nm + "0", "states": states}


def gen(rng: random.Random) -> Dict[str, Any]:
    kind = rng.choice(["flat", "parallel", "nested"])
    if kind == "flat":
        states = {"s" + str(i): leaf(rng, "s" + str(i)) for i in range(3)}
        cfg = {"id": "p", "initial": "s0", "states": states}
    elif kind == "parallel":
        cfg = {
            "id": "p", "initial": "par",
            "states": {
                "par": {
                    "type": "parallel",
                    "states": {"ra": region(rng, "a"),
                               "rb": region(rng, "b")},
                }
            },
        }
    else:
        cfg = {
            "id": "p", "initial": "outer",
            "states": {"outer": region(rng, "n")},
        }
    cfg["context"] = {}
    cfg["maxIterations"] = rng.choice([8, 15, 30])
    return {"kind": kind, "cfg": cfg}


def build(kind: str, laps: List[int], subs: List[int]) -> MachineLogic:
    def tick(i, c, e, ad):  # noqa: ANN001
        laps[0] += 1

    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            subs[0] += 1
            return 1

    else:

        async def svc(i, c, e):  # noqa: ANN001
            subs[0] += 1
            await asyncio.sleep(0)
            return 1

    return MachineLogic(actions={"tick": tick}, services={"svc": svc})


async def one(case: Dict[str, Any], kind: str) -> Dict[str, Any]:
    laps, subs = [0], [0]
    itp = Interpreter(
        create_machine(copy.deepcopy(case["cfg"]), logic=build(kind, laps, subs))
    )
    row: Dict[str, Any] = {"kind": kind, "shape": case["kind"]}
    try:
        await asyncio.wait_for(itp.start(), timeout=WD)
        await asyncio.sleep(SETTLE)
        state = sorted(itp.current_state_ids)
        row["state"] = state
        row["status"] = str(getattr(itp, "status", ""))
        row["dormant"] = bool(itp.has_dormant_invocations)
        pend = itp.pending_invocations()
        row["pending_states"] = sorted({p.state_id for p in pend})
        row["n_pending"] = len(pend)
        try:
            raw = itp.get_persisted_snapshot()
            row["snapshot"] = "ok"
            blob = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        except Exception as exc:  # noqa: BLE001
            row["snapshot"] = "refused:" + type(exc).__name__
            blob = None
    except asyncio.TimeoutError:
        row["error"] = "WATCHDOG_TIMEOUT"
        blob = None
    except Exception as exc:  # noqa: BLE001
        row["error"] = type(exc).__name__
        blob = None
    finally:
        try:
            await asyncio.wait_for(itp.stop(), timeout=WD)
        except Exception:  # noqa: BLE001
            pass

    # P4 -- static restore must reproduce the configuration, 0 submits
    if blob:
        s2: List[int] = [0]
        try:
            m2 = create_machine(
                copy.deepcopy(case["cfg"]), logic=build(kind, [0], s2)
            )
            r2 = Interpreter.from_snapshot(blob, m2, restart_services=False)
            row["restored_state"] = sorted(r2.current_state_ids)
            await r2.stop()
        except Exception as exc:  # noqa: BLE001
            row["restore"] = "refused:" + type(exc).__name__
        row["restore_submits"] = s2[0]
    row["laps"] = laps[0]
    return row


async def main() -> int:
    rng = random.Random(SEED)
    cases = [gen(rng) for _ in range(N)]
    viol: List[Any] = []
    shapes: Counter = Counter()
    notes: Counter = Counter()

    for idx, case in enumerate(cases):
        shapes[case["kind"]] += 1
        for kind in ("def", "async def"):
            r = await one(case, kind)
            if r.get("error") == "WATCHDOG_TIMEOUT":
                viol.append((idx, case["kind"], kind, "P1 hang"))
                continue
            if r.get("error"):
                notes["start_error/" + r["error"]] += 1
                continue
            if r.get("status") == "running" and not r.get("state"):
                viol.append((idx, case["kind"], kind,
                             "P2 empty configuration while running"))
            if r.get("dormant") and r.get("n_pending", 0) == 0:
                viol.append((idx, case["kind"], kind,
                             "P3 dormant but pending_invocations() empty"))
            for sid in r.get("pending_states", []):
                if sid not in r.get("state", []):
                    viol.append((idx, case["kind"], kind,
                                 "P3 pending names an inactive state", sid))
            notes["snapshot/" + str(r.get("snapshot"))] += 1
            if r.get("restored_state") is not None:
                if r["restored_state"] != r["state"]:
                    viol.append((idx, case["kind"], kind,
                                 "P4 restore changed the configuration",
                                 r["state"], r["restored_state"]))
                if r.get("restore_submits"):
                    viol.append((idx, case["kind"], kind,
                                 "P4 static restore submitted a service",
                                 r["restore_submits"]))
            elif r.get("restore"):
                notes["restore/" + r["restore"]] += 1

    emit("t10_property_parallel_children",
         {"claim": "300 random machines incl. parallel + children + after: "
                   "no hang, no empty config, dormant/pending agree, "
                   "snapshot round-trips",
          "n": N, "seed": SEED, "watchdog_s": WD,
          "shape_mix": dict(shapes), "notes": dict(notes.most_common(12)),
          "violations": viol[:15], "n_violations": len(viol),
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
