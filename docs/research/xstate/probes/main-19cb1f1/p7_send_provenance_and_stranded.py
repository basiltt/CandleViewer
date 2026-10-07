"""P7 (#206 / #207): provenance of delayed sends from outside; stranded
hook exactly-once and payload correctness.

Q1 #206 classification: `_schedule_send`'s `self_armed` is
   `actor is self and self._processing`. A delayed self-send issued while
   the machine is IDLE (a caller's own timer, `send_threadsafe`) must stay
   external -- never charged, never shed. 30 of them at maxIterations=3.
Q2 #206 debt leak: arm a delayed self-send then STOP before it fires --
   does stop() settle cleanly (no hang, no pending task warning)?
Q3 #207 exactly-once: count `on_invocation_stranded` calls for a single
   cut on both engines; check state_id / invoke_id / error.stranded agree.
Q4 #207 no false positive: a clean chart whose service completes normally
   fires the hook zero times.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"<workspace>/_ref"
    r"/xstate-statemachine/src"
)
sys.path.insert(0, SRC)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class _Spy(PluginBase):
    def __init__(self):
        self.dropped = []
        self.stranded = []

    def on_event_dropped(self, i, event, reason):
        self.dropped.append((event.type, reason))

    def on_invocation_stranded(self, i, state_id, invoke_id, error):
        self.stranded.append(
            (state_id, invoke_id, type(error).__name__,
             tuple(getattr(error, "stranded", ())))
        )


def _mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


COUNT = {
    "id": "c",
    "initial": "a",
    "maxIterations": 3,
    "context": {"n": 0},
    "states": {"a": {"on": {"EV": {"actions": ["tick"]}}}},
}
_TICK = MachineLogic(
    actions={"tick": lambda i, c, e, a: c.__setitem__("n", c["n"] + 1)}
)


async def q1_external_delayed_selfsend():
    i = Interpreter(_mk(COUNT, logic=_TICK)).use(spy := _Spy())
    await i.start()
    # Issued from OUTSIDE any action: the loop is idle, `_processing` False.
    for _ in range(30):
        await i._deliver(i, i._prepare_event("EV"), 5, None)
    await asyncio.sleep(0.6)
    out = (i.context["n"], spy.dropped[:2], type(i.last_error).__name__)
    await i.stop()
    return out


async def q2_stop_before_fire():
    i = Interpreter(_mk(COUNT, logic=_TICK))
    await i.start()
    await i._deliver(i, i._prepare_event("EV"), 5000, None)
    await asyncio.wait_for(i.stop(), timeout=5)
    return i.status, i.context["n"]


STRAND = {
    "id": "spin",
    "initial": "a",
    "maxIterations": 3,
    "actionErrorPolicy": "rollback",
    "states": {
        "a": {
            "invoke": [
                {"id": "k", "src": "svc",
                 "onDone": {"target": "b", "actions": ["blow"]}}
            ]
        },
        "b": {"always": {"target": "a"}},
    },
}


def _strand_logic(kind):
    def blow(*a):
        raise RuntimeError("rollback")

    def s(i, c, e):
        return 1

    async def a(i, c, e):
        await asyncio.sleep(0)
        return 1

    return MachineLogic(
        actions={"blow": blow},
        services={"svc": a if kind == "async def" else s},
    )


async def q3_async(kind):
    i = Interpreter(_mk(STRAND, logic=_strand_logic(kind))).use(spy := _Spy())
    await i.start()
    await asyncio.sleep(0.6)
    out = (len(spy.stranded), sorted(set(spy.stranded)),
           i.has_dormant_invocations)
    await i.stop()
    return out


def q3_sync():
    spy = _Spy()
    i = SyncInterpreter(_mk(STRAND, logic=_strand_logic("def"))).use(spy)
    i.start()
    return (len(spy.stranded), sorted(set(spy.stranded)),
            i.has_dormant_invocations)


async def q4_clean(kind):
    cfg = {
        "id": "ok",
        "initial": "a",
        "states": {
            "a": {"invoke": [{"id": "k", "src": "svc",
                              "onDone": {"target": "b"}}]},
            "b": {},
        },
    }
    i = Interpreter(_mk(cfg, logic=_strand_logic(kind))).use(spy := _Spy())
    await i.start()
    await asyncio.sleep(0.3)
    out = (len(spy.stranded), sorted(i.current_state_ids),
           i.has_dormant_invocations)
    await i.stop()
    return out


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


if __name__ == "__main__":
    print("SRC:", SRC)
    print("Q1 external delayed x30    :", _run(q1_external_delayed_selfsend()))
    print("Q2 stop before fire        :", _run(q2_stop_before_fire()))
    for k in ("def", "async def"):
        print(f"Q3 stranded async [{k:9}] :", _run(q3_async(k)))
    print("Q3 stranded sync  [def      ]:", q3_sync())
    print("Q4 clean completion        :", _run(q4_clean("def")))
