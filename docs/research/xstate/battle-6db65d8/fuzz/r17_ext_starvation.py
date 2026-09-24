"""R17 -- why are external priority `EXT` events not applied on the
`always_into_invoke` shape?

r16 found: root-level `EXT` handler, machine `status="running"` throughout,
`on_event_dropped` silent for EXT -- yet only 1 of 4000 EXT events ran its
action. Candidates:
  (1) the EXT events are queued and never dequeued (starvation by the
      machine's own completion chain on the priority lane);
  (2) the root handler stops matching in some configuration;
  (3) they are consumed but the action is skipped.

This probe distinguishes them by counting, per event: sends, `on_event_received`
hook fires, transitions taken, and action executions, plus the queue depths.
"""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()


class Spy(PluginBase):
    def on_event_received(self, interp, event):
        C[f"received:{getattr(event,'type',event)}"] += 1

    def on_event_dropped(self, interp, event, reason=None, **kw):
        C[f"dropped:{reason}:{getattr(event,'type',event)}"] += 1

    def on_transition(self, interp, f, t, ev):
        C[f"transition:{getattr(ev,'type',ev)}"] += 1


async def async_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def plain_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1
    C["action:extbump"] += 1


CFG = {
    "id": "m",
    "context": {"n": 0, "ext": 0},
    "maxIterations": 50,
    "on": {"EXT": {"actions": ["extbump"]}},
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "always": {"target": "b2", "guard": "g"},
            "initial": "b2",
            "states": {
                "b2": {
                    "invoke": {
                        "id": "s",
                        "src": "svc",
                        "onDone": {"target": "#m.a"},
                    }
                }
            },
        },
    },
}


async def run(async_svc_kind, n=500):
    C.clear()
    it = Interpreter(
        create_machine(
            dict(CFG),
            logic=MachineLogic(
                services={"svc": async_svc if async_svc_kind else plain_svc},
                actions={"extbump": extbump},
                guards={"g": lambda c, e: True},
            ),
        )
    )
    it.use(Spy())
    await asyncio.wait_for(it.start(), 10)
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    await asyncio.sleep(1.0)
    kind = "asyncdef" if async_svc_kind else "plaindef"
    print(f"== svc={kind}, {n} GO + {n} EXT(priority) ==")
    print(f"   status={it.status} ids={sorted(it.current_state_ids)} "
          f"last_error={type(it.last_error).__name__ if it.last_error else None}")
    print(f"   ext applied (context) = {(it.context or {}).get('ext')}")
    print(f"   EXT received={C['received:EXT']} transitions={C['transition:EXT']} "
          f"action_runs={C['action:extbump']}")
    print(f"   queue depths at end: inbox={it._event_queue.qsize()} "
          f"priority={len(it._priority_queue)} internal={len(it._internal_queue)}")
    top = {k: v for k, v in C.most_common(10)}
    print(f"   counters={top}")
    await it.stop()
    await asyncio.sleep(0.1)
    print(f"   after stop(): priority_queue={len(it._priority_queue)} "
          f"inbox={it._event_queue.qsize()}")


async def main():
    for a in (False, True):
        await run(a)


asyncio.run(main())
