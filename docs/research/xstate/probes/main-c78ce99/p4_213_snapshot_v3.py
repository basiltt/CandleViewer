"""P-4 (#213): snapshot v3 `scheduled_sends`.

STANDALONE. Questions:
  a) does an armed delayed self-raise survive and re-arm? (the fix)
  b) is the remaining delay computed against the SIMULATED clock, and does a
     restore onto a fresh SimulatedClock get a sane remaining delay?
  c) does a cancelled send leave a record?
  d) does `machine_hash` / `check_shape` cover the new field? is a
     `scheduled_sends` record with a forged huge/negative remaining accepted?
  e) ordering: are re-armed sends visible before or after the initial descent
     re-runs? does a restore double-arm (snapshot entry action re-arming +
     the restored record)?
"""

import asyncio
import json
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.persistence import SNAPSHOT_VERSION

# only exit from `waiting` is a delayed self-raise armed on entry
CFG: Dict[str, Any] = {
    "id": "park",
    "initial": "waiting",
    "context": {"n": 0},
    "states": {
        "waiting": {
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": "WAKE", "delay": 300, "id": "w"},
                }
            ],
            "on": {"WAKE": "done_"},
        },
        "done_": {"entry": ["tick"]},
    },
}

CANCEL_CFG: Dict[str, Any] = {
    "id": "canc",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": "WAKE", "delay": 500, "id": "w"},
                }
            ],
            "on": {"STOPIT": "b", "WAKE": "b"},
        },
        "b": {"entry": [{"type": "cancel", "params": {"sendId": "w"}}]},
    },
}


def _mk(cfg: Dict[str, Any]) -> Any:
    def tick(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    return create_machine(cfg, logic=MachineLogic(actions={"tick": tick}))


async def main() -> None:
    print("SNAPSHOT_VERSION =", SNAPSHOT_VERSION)

    # (a) round trip
    i = await Interpreter(_mk(CFG)).start()
    await asyncio.sleep(0.10)
    s = json.loads(json.dumps(i.get_persisted_snapshot()))
    await i.stop()
    ss: List[Dict[str, Any]] = s.get("scheduled_sends") or []
    print("a) scheduled_sends:", ss)
    print("   hash in snapshot:", s.get("machine_hash"))

    r = Interpreter.from_snapshot(json.dumps(s), _mk(CFG))
    await r.start()
    print("   right after start():", sorted(r.current_state_ids))
    await asyncio.sleep(0.45)
    print("   after 0.45s:", sorted(r.current_state_ids), "n =", r.context["n"])
    await r.stop()

    # (a2) control: restore WITHOUT the field (the pre-#213 wedge)
    s2 = json.loads(json.dumps(s))
    s2["scheduled_sends"] = []
    r2 = Interpreter.from_snapshot(json.dumps(s2), _mk(CFG))
    await r2.start()
    await asyncio.sleep(0.45)
    print("   control (field stripped):", sorted(r2.current_state_ids))
    await r2.stop()

    # (c) cancelled send leaves no record
    c = await Interpreter(_mk(CANCEL_CFG)).start()
    await asyncio.sleep(0.05)
    before = len(c.get_persisted_snapshot().get("scheduled_sends") or [])
    await c.send("STOPIT")
    await asyncio.sleep(0.05)
    after = c.get_persisted_snapshot().get("scheduled_sends") or []
    print(f"c) armed={before} after cancel={after}")

    # (d) forged records
    for label, rec in (
        (
            "remaining -1e9",
            {"type": "WAKE", "kind": "event", "payload": {}, "remaining_ms": -1e9},
        ),
        (
            "remaining 1e18",
            {"type": "WAKE", "kind": "event", "payload": {}, "remaining_ms": 1e18},
        ),
        (
            "remaining 'abc'",
            {"type": "WAKE", "kind": "event", "payload": {}, "remaining_ms": "abc"},
        ),
        (
            "forged engine after",
            {
                "type": "after.600000.park.waiting",
                "kind": "after",
                "engine": True,
                "remaining_ms": 0,
            },
        ),
    ):
        s3 = json.loads(json.dumps(s))
        s3["scheduled_sends"] = [rec]
        try:
            x = Interpreter.from_snapshot(json.dumps(s3), _mk(CFG))
            await x.start()
            await asyncio.sleep(0.2)
            print(
                f"d) {label:22s} -> ACCEPTED, states={sorted(x.current_state_ids)}"
            )
            await x.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"d) {label:22s} -> {type(exc).__name__}: {str(exc)[:90]}")

    # (d2) does machine_hash change when scheduled_sends does? (it is a
    # STRUCTURE hash, so no -- confirm it is not integrity over the field)
    print("d2) hash is structural only:", s.get("machine_hash") == s2.get("machine_hash"))

    # (e) sync engine parity
    sy = SyncInterpreter(_mk(CFG)).start()
    sy.tick()
    sn = json.loads(json.dumps(sy.get_persisted_snapshot()))
    sy.stop()
    print("e) sync scheduled_sends:", sn.get("scheduled_sends"))
    sr = SyncInterpreter.from_snapshot(json.dumps(sn), _mk(CFG))
    sr.start()
    print("   sync restored states:", sorted(sr.current_state_ids))


if __name__ == "__main__":
    asyncio.run(main())
