"""D11-semantics-3: #216 checks ONLY the top level; nested state keys are
silently dropped, including misspellings of BEHAVIOURAL keys.

#216 introduced KNOWN_MACHINE_KEYS + a did-you-mean WARNING, and
`strict_config=True` / `"strictConfig": true` to refuse. It is applied by
`validate_top_level_keys(config, ...)` to the ROOT dict only. A misspelling
one level down -- `entryy`, `onn`, `invok`, `afterr`, `alwayss`, `exitt` --
is dropped with NO warning and NO refusal even under `strict_config=True`,
and the state simply never does the thing. This is the same failure mode
#216 exists to prevent ("a misspelled key silently reverts to its
default"), one nesting level down, and it is strictly more dangerous:
a dropped `entry`/`invoke` removes behaviour rather than a policy.

Exit 1 == reproduced. Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio, copy, json, logging, sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

logging.disable(logging.CRITICAL)


def cfg(entry_key: str, on_key: str) -> Dict[str, Any]:
    return {
        "id": "n", "initial": "a",
        "states": {
            "a": {entry_key: "mark", on_key: {"GO": "b"}},
            "b": {"entry": "mark"},
        },
    }


async def run(entry_key: str, on_key: str, kind: str,
              strict_config: bool) -> Dict[str, Any]:
    fired: List[str] = []

    def mark(i, c, e, a):  # noqa: ANN001
        fired.append(getattr(e, "type", "?"))

    async def mark_a(i, c, e, a):  # noqa: ANN001
        fired.append(getattr(e, "type", "?"))

    lg = MachineLogic(actions={"mark": mark_a if kind == "async" else mark})
    try:
        mach = create_machine(cfg(entry_key, on_key), logic=lg,
                              strict_config=strict_config)
    except InvalidConfigError as exc:
        return {"refused": str(exc)[:120]}
    m = Interpreter(mach)
    await m.start(); await asyncio.sleep(0.05)
    await m.send("GO"); await asyncio.sleep(0.15)
    res = {"entry_fired": len(fired), "state": sorted(m.current_state_ids)}
    await m.stop()
    return res


async def main() -> int:
    out: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        out[f"correct/{kind}"] = await run("entry", "on", kind, False)
        for sc in (False, True):
            tag = "strict_config" if sc else "default"
            out[f"typo_entryy/{tag}/{kind}"] = await run("entryy", "on", kind, sc)
            out[f"typo_onn/{tag}/{kind}"] = await run("entry", "onn", kind, sc)
    repro = [
        k for k, v in out.items()
        if k.startswith("typo_") and "refused" not in v
        and (v.get("entry_fired") == 0 or not any("n.b" in s
                                                  for s in v.get("state", [])))
    ]
    out["REPRODUCED"] = bool(repro)
    out["silently_broken_cells"] = repro
    print(json.dumps(out, indent=1))
    return 1 if repro else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
