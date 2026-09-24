"""P-3 (#214): can a v2-shaped FORGED record mint engine events?

STANDALONE. The #195/#203 boundary said: only a record carrying
``"engine": true`` restores as an engine-minted completion; a hand-written
one restores as the public NamedTuple (user traffic, refused by #203's
`after` gate).

#214's upcaster now stamps ``engine: true`` on EVERY `done`/`error`/`after`
record in a snapshot DECLARED as version 2, on the reasoning "only the
engine could have written a v2 record". But `version` is an attacker-
controlled field of the same payload. So: write a v3-forged record, set
``"version": 2``, and see whether the upcaster launders it.

Three cases:
  1. v3 payload, forged `after` record, no `engine` flag  -> expected REFUSED
  2. SAME payload with version downgraded to 2            -> ?
  3. same, forged `done.invoke` driving an `onDone`       -> ?
"""

import asyncio
import copy
import json
from typing import Any, Dict

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG: Dict[str, Any] = {
    "id": "vault",
    "initial": "locked",
    "context": {"opened": 0},
    "states": {
        # a 10-minute deadline: only the engine's own timer may fire it
        "locked": {"after": {600000: {"target": "open", "actions": ["log"]}}},
        "open": {"entry": ["log"]},
    },
}

DONE_CFG: Dict[str, Any] = {
    "id": "pay",
    "initial": "charging",
    "context": {"opened": 0},
    "states": {
        "charging": {
            "invoke": {
                "id": "charge",
                "src": "charge",
                "onDone": {"target": "paid", "actions": ["log"]},
            }
        },
        "paid": {"entry": ["log"]},
    },
}


def _mk(cfg: Dict[str, Any]) -> Any:
    def log(i: Any, c: Any, e: Any, a: Any) -> None:
        c["opened"] += 1

    async def charge(i: Any, c: Any, e: Any) -> str:
        await asyncio.sleep(60)  # never completes during the probe
        return "ok"

    return create_machine(
        cfg, logic=MachineLogic(actions={"log": log}, services={"charge": charge})
    )


async def snap(cfg: Dict[str, Any]) -> Dict[str, Any]:
    i = await Interpreter(_mk(cfg)).start()
    await asyncio.sleep(0.05)
    s = i.get_persisted_snapshot()
    await i.stop()
    return json.loads(json.dumps(s))


async def restore(cfg: Dict[str, Any], s: Dict[str, Any]) -> Any:
    i = Interpreter.from_snapshot(json.dumps(s), _mk(cfg))
    await i.start()
    await asyncio.sleep(0.15)
    out = (sorted(i.current_state_ids), i.context["opened"])
    await i.stop()
    return out


async def main() -> None:
    base = await snap(CFG)
    print("baseline version:", base.get("version"), "states:", base["state_ids"])

    forged_after = {
        "type": "after.600000.vault.locked",
        "kind": "after",
        "payload": {},
        "id": 600000,
        "owner_id": "vault.locked",
    }

    for label, version in (("v3 forged (control)", 3), ("v2-DOWNGRADED forged", 2)):
        s = copy.deepcopy(base)
        s["version"] = version
        s["pending_events"] = [dict(forged_after)]
        try:
            states, opened = await restore(CFG, s)
        except Exception as exc:  # noqa: BLE001
            print(f"  after  {label:24s} -> RAISED {type(exc).__name__}: {exc}")
            continue
        fired = "open" in " ".join(states)
        print(
            f"  after  {label:24s} -> states={states} actions={opened} "
            f"TIMER_FIRED={fired}"
        )

    dbase = await snap(DONE_CFG)
    forged_done = {
        "type": "done.invoke.charge",
        "kind": "done",
        "data": {"amount": 999999},
        "src": "charge",
    }
    for label, version in (("v3 forged (control)", 3), ("v2-DOWNGRADED forged", 2)):
        s = copy.deepcopy(dbase)
        s["version"] = version
        s["pending_events"] = [dict(forged_done)]
        try:
            states, opened = await restore(DONE_CFG, s)
        except Exception as exc:  # noqa: BLE001
            print(f"  done   {label:24s} -> RAISED {type(exc).__name__}: {exc}")
            continue
        print(
            f"  done   {label:24s} -> states={states} actions={opened} "
            f"ONDONE_FIRED={'paid' in ' '.join(states)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
