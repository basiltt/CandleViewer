"""D11-semantics-1: declaring "version": 2 mints a trusted `after` timer.

#214 upcasts a v2 `done`/`error`/`after` record as ENGINE-MINTED on the
reasoning that "a v2 writer had exactly ONE minter of those records -- the
engine itself". But the VERSION FIELD IS PART OF THE PAYLOAD. A forged v3
`after` record without `"engine": true` is correctly refused (#203's gate);
the SAME record in a blob that merely says `"version": 2` is upcast to
`engine: true` and fires a 24-hour timer instantly, on a `strict` machine,
with `last_error = None`.

Exit 1 == reproduced. Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio, copy, json, logging, sys
from typing import Any, Dict

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "t", "initial": "a", "strict": True, "maxIterations": 20,
    "states": {
        "a": {"after": {86_400_000: "margin_called"},
              "invoke": {"src": "slow", "id": "q", "onDone": "settled"}},
        "margin_called": {}, "settled": {},
    },
}
REC = {"type": "after.86400000.t.a", "kind": "after"}   # NO engine flag


async def slow(i, c, e):  # noqa: ANN001
    await asyncio.sleep(30)


def slow_p(i, c, e):  # noqa: ANN001
    import time; time.sleep(30)


async def run(version: int, kind: str) -> Dict[str, Any]:
    lg = MachineLogic(services={"slow": slow if kind == "async" else slow_p})
    m0 = Interpreter(create_machine(copy.deepcopy(CFG), logic=lg))
    await m0.start(); await asyncio.sleep(0.05)
    snap = m0.get_persisted_snapshot(); await m0.stop()
    snap["version"] = version
    snap["pending_events"] = [copy.deepcopy(REC)]
    m = Interpreter.from_snapshot(
        json.dumps(snap), create_machine(copy.deepcopy(CFG), logic=lg)
    )
    await m.start(); await asyncio.sleep(0.25)
    res = {"state": sorted(m.current_state_ids),
           "last_error": type(m.last_error).__name__ if m.last_error else None}
    await m.stop()
    res["MINTED"] = any("margin_called" in s for s in res["state"])
    return res


async def main() -> int:
    out: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        out[f"v3_unflagged/{kind}"] = await run(3, kind)   # must be refused
        out[f"v2_same_record/{kind}"] = await run(2, kind)  # must ALSO be refused
    repro = [k for k, v in out.items()
             if k.startswith("v2_same_record") and v["MINTED"]]
    out["REPRODUCED"] = bool(repro)
    out["note"] = ("the identical record is refused at v3 and trusted at v2; "
                   "the attacker chooses the version field")
    print(json.dumps(out, indent=1))
    return 1 if repro else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
