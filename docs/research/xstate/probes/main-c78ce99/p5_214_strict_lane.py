"""P-5 (#214): strict on restore, lane ordering, and the scheduled_sends gap.

STANDALONE. Questions:
  a) is a restored user event refused by `strict` reported on `last_error` /
     `on_invalid_event`, and dropped?
  b) is a `scheduled_sends` record ALSO checked against strict? (#214 wires
     `_admit_restored` into the `pending_events` loop only.)
  c) lane: does a `lane: "priority"` record restore ahead of the inbox?
     Can a FORGED `lane: "priority"` tag promote plain user traffic?
"""

import asyncio
import json
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

CFG: Dict[str, Any] = {
    "id": "strictm",
    "initial": "a",
    "strict": True,
    "context": {"log": []},
    "states": {
        "a": {"on": {"KNOWN": "b", "WAKE": "b"}},
        "b": {"entry": ["mark"]},
    },
}

ORDER_CFG: Dict[str, Any] = {
    "id": "ord",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"on": {"P": {"actions": ["mark"]}, "Q": {"actions": ["mark"]}}}
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.invalid: List[str] = []

    def on_invalid_event(self, interpreter: Any, error: Any) -> None:
        self.invalid.append(str(error)[:60])


def _mk(cfg: Dict[str, Any]) -> Any:
    def mark(i: Any, c: Any, e: Any, a: Any) -> None:
        c["log"].append(e.type)

    return create_machine(cfg, logic=MachineLogic(actions={"mark": mark}))


async def base_snapshot(cfg: Dict[str, Any]) -> Dict[str, Any]:
    i = await Interpreter(_mk(cfg)).start()
    s = json.loads(json.dumps(i.get_persisted_snapshot()))
    await i.stop()
    return s


async def main() -> None:
    base = await base_snapshot(CFG)

    # (a) unknown user event in pending_events under strict
    s = json.loads(json.dumps(base))
    s["pending_events"] = [{"type": "BOGUS", "kind": "event", "payload": {}}]
    spy = Spy()
    r = Interpreter.from_snapshot(json.dumps(s), _mk(CFG)).use(spy)
    print("a) last_error BEFORE start():", type(r.last_error).__name__ if r.last_error else None)
    print("   last_transition_ok:", r.last_transition_ok)
    print("   on_invalid_event seen at restore time:", spy.invalid)
    await r.start()
    await asyncio.sleep(0.1)
    print("   after start(): states =", sorted(r.current_state_ids))
    await r.stop()

    # (b) the SAME unknown event smuggled through scheduled_sends
    s2 = json.loads(json.dumps(base))
    s2["scheduled_sends"] = [
        {"type": "BOGUS", "kind": "event", "payload": {}, "remaining_ms": 1}
    ]
    spy2 = Spy()
    r2 = Interpreter.from_snapshot(json.dumps(s2), _mk(CFG)).use(spy2)
    await r2.start()
    await asyncio.sleep(0.15)
    print("b) scheduled_sends BOGUS under strict: err =",
          type(r2.last_error).__name__ if r2.last_error else None,
          "invalid hook =", spy2.invalid)
    await r2.stop()

    # (b2) a KNOWN event via scheduled_sends still drives a transition
    s2b = json.loads(json.dumps(base))
    s2b["scheduled_sends"] = [
        {"type": "WAKE", "kind": "event", "payload": {}, "remaining_ms": 1}
    ]
    r2b = Interpreter.from_snapshot(json.dumps(s2b), _mk(CFG))
    await r2b.start()
    await asyncio.sleep(0.15)
    print("   known WAKE via scheduled_sends ->", sorted(r2b.current_state_ids))
    await r2b.stop()

    # (c) lane ordering: persisted order P(inbox) then Q(forged priority)
    obase = await base_snapshot(ORDER_CFG)
    s3 = json.loads(json.dumps(obase))
    s3["pending_events"] = [
        {"type": "P", "kind": "event", "payload": {}},
        {"type": "Q", "kind": "event", "payload": {}, "lane": "priority"},
    ]
    r3 = Interpreter.from_snapshot(json.dumps(s3), _mk(ORDER_CFG))
    await r3.start()
    await asyncio.sleep(0.15)
    print("c) persisted [P inbox, Q forged-priority] -> processed", r3.context["log"])
    await r3.stop()


if __name__ == "__main__":
    asyncio.run(main())
