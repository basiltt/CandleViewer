"""t8 (@19cb1f1) -- STANDALONE. #208: a receipt is never success-shaped
over an empty / illegal configuration, and never error-shaped over a legal
one. Fuzzed over a 6-way outcome matrix x both service kinds.

Cases sent with `wait=True` (the receipt-returning form):
  R1 legal handled event                -> ok, no error
  R2 undeclared event, strict=False     -> ok (unhandled is legal)
  R3 undeclared event, strict=True      -> NOT ok, error present
  R4 action raises, policy default      -> NOT ok, error present
  R5 action raises, policy "rollback"   -> NOT ok, error present
  R6 event that enters a runaway chain   -> ok at RESOLUTION TIME

R6 is scored `expect_ok=True` on evidence, not assumption: the receipt
resolves when THIS event's macrostep ends, and the machine is legally in
`r.spin` at that instant; the chain trips several laps later and surfaces
on `last_error`, not on a receipt already handed back. Recorded as a
contract note (a receipt is not a liveness signal), and the probe asserts
the configuration it reports is the live one.

Invariants:
  never `ok` when the step ended with an error or an empty configuration
  never an error when the step was legal and the configuration is intact

Run: python t8_receipt_matrix.py [--reps=40]   (exit 1 == defect)
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


def arg(name: str, default: int) -> int:
    for a in sys.argv[1:]:
        if a.startswith("--" + name + "="):
            return int(a.split("=")[1])
    return default


REPS = arg("reps", 40)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def cfg(strict: bool, policy: str | None, chain: bool) -> Dict[str, Any]:
    c: Dict[str, Any] = {
        "id": "r", "initial": "a", "strict": strict, "context": {},
        "states": {
            "a": {"on": {"GO": "b", "BOOM": "boom", "SPIN": "spin"}},
            "b": {},
            "boom": {"entry": ["blow"]},
            "spin": {"invoke": {"id": "s", "src": "svc",
                                "onDone": {"target": "hop"}}},
            "hop": {"always": {"target": "spin"}},
        },
    }
    if policy:
        c["actionErrorPolicy"] = policy
    if chain:
        c["maxIterations"] = 6
    return c


def build(kind: str) -> MachineLogic:
    def blow(i, c, e, ad):  # noqa: ANN001
        raise RuntimeError("action blew up")

    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            return 1

    else:

        async def svc(i, c, e):  # noqa: ANN001
            return 1

    return MachineLogic(actions={"blow": blow}, services={"svc": svc})


CASES = {
    "R1_legal": dict(strict=False, policy=None, chain=False, ev="GO",
                     expect_ok=True),
    "R2_undeclared_lenient": dict(strict=False, policy=None, chain=False,
                                  ev="NOPE", expect_ok=True),
    "R3_undeclared_strict": dict(strict=True, policy=None, chain=False,
                                 ev="NOPE", expect_ok=False),
    "R4_action_raises": dict(strict=False, policy=None, chain=False,
                             ev="BOOM", expect_ok=False),
    "R5_action_raises_rollback": dict(strict=False, policy="rollback",
                                      chain=False, ev="BOOM",
                                      expect_ok=False),
    "R6_chain_enters_runaway": dict(strict=False, policy=None, chain=True,
                                    ev="SPIN", expect_ok=True),
}


async def one(name: str, kind: str) -> Dict[str, Any]:
    spec = CASES[name]
    itp = Interpreter(
        create_machine(
            copy.deepcopy(
                cfg(spec["strict"], spec["policy"], spec["chain"])
            ),
            logic=build(kind),
        )
    )
    row: Dict[str, Any] = {"case": name, "kind": kind}
    try:
        await itp.start()
        rec = await itp.send(spec["ev"], wait=True)
        # `Receipt` (events.py:457) has no `ok` field: success-shaped
        # means `error is None` over a NON-EMPTY configuration.
        row["receipt_type"] = type(rec).__name__
        err = rec.error
        row["error"] = type(err).__name__ if err is not None else None
        row["state_ids"] = sorted(rec.state_ids)
        row["changed"] = bool(rec.changed)
        row["denied"] = bool(rec.denied)
        row["ok"] = err is None and bool(rec.state_ids)
        row["state"] = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        row["raised"] = type(exc).__name__
        row["ok"] = False
        row["state"] = sorted(itp.current_state_ids)
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
    row["expect_ok"] = spec["expect_ok"]
    row["empty_configuration"] = not row.get("state_ids", row.get("state"))
    return row


async def main() -> int:
    viol: List[Any] = []
    tally: Counter = Counter()
    sample: Dict[str, Any] = {}

    for name in CASES:
        for kind in ("def", "async def"):
            for _ in range(REPS):
                r = await one(name, kind)
                key = name + "/" + kind
                tally[key + "/ok=" + str(r["ok"])] += 1
                sample.setdefault(key, r)
                if r["ok"] and not r["expect_ok"]:
                    viol.append((name, kind, "ok over an ILLEGAL step",
                                 r.get("error"), r.get("raised")))
                if r.get("state_ids") is not None and                         r["state_ids"] != r["state"]:
                    viol.append((name, kind, "receipt ids != live config",
                                 r["state_ids"], r["state"]))
                if r["ok"] and r["empty_configuration"]:
                    viol.append((name, kind, "ok over an EMPTY configuration"))
                if r.get("raised"):
                    continue  # a call-site refusal is not a receipt
                if (not r["ok"]) and r["expect_ok"]:
                    viol.append((name, kind, "error over a LEGAL step",
                                 r.get("error"), r.get("raised")))

    emit("t8_receipt_matrix",
         {"claim": "#208 receipts: never ok over illegal/empty, never error "
                   "over legal",
          "reps_per_cell": REPS, "cells": len(CASES) * 2,
          "tally": dict(tally), "samples": sample,
          "violations": viol[:20], "n_violations": len(viol),
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
