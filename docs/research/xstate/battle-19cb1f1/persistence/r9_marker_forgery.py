# -*- coding: utf-8 -*-
"""R9 -- security: can user code forge the engine-completion marker?

Round 7 moved the chain-budget accounting from *timing* to *provenance*
(#180): an event counts against the budget iff the ENGINE minted it. The
authority is `Event._provenance is _ENGINE_MARK` (`events.py:125-135`), an
`init=False`, `compare=False`, `repr=False` field holding a module-private
sentinel. That makes the marker the security boundary for two things at once:

  * `system` (bypasses `strict` / `onUnhandled` / the `"*"` matcher, #85), and
  * chain-budget exemption vs. charging (#180).

A user who can mint a `system=True` event can both smuggle an undeclared
event past `strict` AND make their own traffic uncharged (or charge someone
else's). This probe enumerates the realistic routes:

  1. `Event(type=..., system=True)`                      -- removed by #85
  2. subclass `Event` and override the `system` property
  3. `dataclasses.replace()` on a genuine engine event
  4. direct assignment to `_provenance` / `__dict__` / `object.__setattr__`
  5. `copy.copy` / `copy.deepcopy` / pickle round-trip of a genuine event
  6. reading the sentinel back off any genuinely-system event reachable from
     a public hook, then stamping it onto an attacker event
  7. `sendTo` of a captured `DoneEvent`
  8. persistence: a hand-written snapshot `pending_events` record claiming
     an engine-minted kind (the #79/#85 laundering route)

For each: does the forged event report `system=True`, and does it reach the
machine as a system event?
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import pickle

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import AfterEvent, DoneEvent, Event
from xstate_statemachine.plugins import PluginBase

FORGED: list[str] = []
CAPTURED: dict = {}


def report(route: str, ok_forged: bool, detail: str = "") -> None:
    print("  %-46s %s %s"
          % (route, "FORGED  <-- BREACH" if ok_forged else "refused", detail))
    if ok_forged:
        FORGED.append(route)


SPEC = {
    "id": "sec",
    "initial": "a",
    "strict": True,
    "onUnhandled": "error",
    "states": {
        "a": {
            "invoke": [{"id": "k", "src": "svc", "onDone": {"target": "b"}}],
            "on": {"KNOWN": "b"},
        },
        "b": {"on": {"KNOWN": "a"}},
    },
}


class Grab(PluginBase):
    """Captures a genuine ENGINE-minted event from a public hook."""

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        pass

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        CAPTURED.setdefault("dropped", event)

    def on_action_execute(self, interp, action):  # noqa: ANN001
        pass


async def capture_engine_event():
    """Obtain a real system event the way user code actually can."""
    seen = {}

    def stash(i, c, e, a):  # noqa: ANN001
        if getattr(e, "system", False):
            seen.setdefault("ev", e)

    async def svc(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"r": 1}

    spec = json.loads(json.dumps(SPEC))
    spec["states"]["a"]["invoke"][0]["onDone"] = {"target": "b",
                                                  "actions": ["stash"]}
    m = create_machine(spec, logic=MachineLogic(actions={"stash": stash},
                                                services={"svc": svc}))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start(children_timeout=1.0)
    await asyncio.sleep(0.1)
    await i.stop()
    return seen.get("ev")


async def main() -> None:
    print("=== can user code mint a system=True event? ===")

    # 1. the removed constructor parameter (#85)
    try:
        e = Event(type="X", system=True)  # type: ignore[call-arg]
        report("1. Event(type=..., system=True)", bool(e.system))
    except TypeError as exc:
        report("1. Event(type=..., system=True)", False,
               f"TypeError: {str(exc)[:46]}")

    # 2. subclass overriding the property
    class Evil(Event):
        @property
        def system(self):  # noqa: ANN001
            return True

    ev2 = Evil(type="X")
    report("2. Event subclass overriding .system", bool(ev2.system),
           "(the OBJECT lies; see the end-to-end test below)")

    # 3. dataclasses.replace on a genuine engine event
    genuine = await capture_engine_event()
    print("  [captured a genuine engine event: %r system=%s]"
          % (getattr(genuine, "type", None), getattr(genuine, "system", None)))
    if isinstance(genuine, Event):
        try:
            r = dataclasses.replace(genuine, type="EVIL")
            report("3. dataclasses.replace(genuine, type=...)", bool(r.system))
        except Exception as exc:  # noqa: BLE001
            report("3. dataclasses.replace(genuine, type=...)", False,
                   type(exc).__name__)
    else:
        report("3. dataclasses.replace(genuine, ...)", False,
               "genuine completion is not an Event dataclass (%s)"
               % type(genuine).__name__)

    # 4. direct attribute assignment
    ev4 = Event(type="X")
    for how, fn in (
        ("_provenance =", lambda e: setattr(e, "_provenance", object())),
        ("__dict__ update", lambda e: e.__dict__.update(_provenance=object())),
        ("object.__setattr__",
         lambda e: object.__setattr__(e, "_provenance", object())),
    ):
        e = Event(type="X")
        try:
            fn(e)
            report(f"4. {how} (arbitrary sentinel)", bool(e.system))
        except Exception as exc:  # noqa: BLE001
            report(f"4. {how}", False, type(exc).__name__)

    # 5. copy / deepcopy / pickle of a genuine event
    if isinstance(genuine, Event):
        for how, fn in (("copy.copy", copy.copy),
                        ("copy.deepcopy", copy.deepcopy),
                        ("pickle round-trip",
                         lambda x: pickle.loads(pickle.dumps(x)))):
            try:
                c = fn(genuine)
                # a copy of a genuine system event that stays system is FINE;
                # the breach is being able to then RETYPE it.
                keeps = bool(getattr(c, "system", False))
                try:
                    object.__setattr__(c, "type", "EVIL")
                    retyped = bool(getattr(c, "system", False))
                except Exception:  # noqa: BLE001
                    retyped = False
                report(f"5. {how} then retype to 'EVIL'", retyped,
                       f"(copy keeps system={keeps})")
            except Exception as exc:  # noqa: BLE001
                report(f"5. {how}", False, type(exc).__name__)

    # 6. steal the sentinel off a genuine event, stamp it on ours
    if genuine is not None:
        mark = getattr(genuine, "_provenance", None)
        ev6 = Event(type="EVIL")
        try:
            object.__setattr__(ev6, "_provenance", mark)
            report("6. steal _provenance off a genuine event", bool(ev6.system),
                   f"(sentinel reachable from user code: {mark is not None})")
        except Exception as exc:  # noqa: BLE001
            report("6. steal _provenance", False, type(exc).__name__)

    # ---- END-TO-END: does a forged event actually BYPASS strict? -------
    print("\n=== end-to-end: does the forged event bypass strict/onUnhandled? ===")

    async def send_and_watch(ev, label: str) -> None:
        async def svc(i, c, e):  # noqa: ANN001
            await asyncio.sleep(3600)

        m = create_machine(json.loads(json.dumps(SPEC)),
                           logic=MachineLogic(services={"svc": svc}))
        i = Interpreter(m, clock=SimulatedClock())
        i.use(Grab())
        await i.start(children_timeout=0.2)
        try:
            await i.send(ev)
        except Exception as exc:  # noqa: BLE001
            print("  %-46s raised %s (enforced)"
                  % (label, type(exc).__name__))
            await i.stop()
            return
        await asyncio.sleep(0.05)
        killed = i.status == "error" or i.error is not None
        print("  %-46s status=%s error=%s"
              % (label, i.status, (str(i.error)[:44] if i.error else None)))
        if not killed:
            print("       ^ an UNDECLARED event was NOT enforced")
            FORGED.append(label)
        await i.stop()

    # control: a plain undeclared event MUST be enforced by strict/error
    await send_and_watch(Event(type="UNDECLARED"), "control: plain UNDECLARED")

    class Evil2(Event):
        @property
        def system(self):  # noqa: ANN001
            return True

    await send_and_watch(Evil2(type="UNDECLARED"), "subclass claiming system=True")

    ev = Event(type="UNDECLARED")
    try:
        object.__setattr__(ev, "_provenance", object())
    except Exception:  # noqa: BLE001
        pass
    await send_and_watch(ev, "forged _provenance sentinel")

    if genuine is not None:
        ev = Event(type="UNDECLARED")
        try:
            object.__setattr__(ev, "_provenance",
                               getattr(genuine, "_provenance", None))
            await send_and_watch(ev, "STOLEN genuine _provenance sentinel")
        except Exception as exc:  # noqa: BLE001
            print("  stolen-sentinel route unavailable: %s" % type(exc).__name__)

    # 7. sendTo a captured DoneEvent
    print("\n=== 7. replay a captured DoneEvent ===")
    d = DoneEvent(type="done.invoke.k", data={"r": 1}, src="k")
    print("  DoneEvent(...) constructed by user code: system=%s"
          % getattr(d, "system", "<no attr>"))
    await send_and_watch(d, "user-constructed DoneEvent")

    # 8. persistence laundering: a pending_events record claiming a
    #    system-shaped type restores as... what?
    print("\n=== 8. snapshot pending_events laundering ===")

    async def svc8(i, c, e):  # noqa: ANN001
        await asyncio.sleep(3600)

    m = create_machine(json.loads(json.dumps(SPEC)),
                       logic=MachineLogic(services={"svc": svc8}))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start(children_timeout=0.2)
    blob = i.get_persisted_snapshot()
    await i.stop()
    for kind, rec in (
        ("done.invoke", {"type": "done.invoke.k", "kind": "done",
                          "data": {"r": 1}, "src": "k"}),
        ("after", {"type": "after.50.sec.a", "kind": "after"}),
        ("plain undeclared", {"type": "UNDECLARED", "kind": "event",
                               "payload": {}}),
    ):
        b = json.loads(json.dumps(blob, default=str))
        b["pending_events"] = [rec]
        try:
            r = Interpreter.from_snapshot(json.dumps(b),
                                          create_machine(
                                              json.loads(json.dumps(SPEC)),
                                              logic=MachineLogic(
                                                  services={"svc": svc8})))
        except Exception as exc:  # noqa: BLE001
            print("  %-22s restore REFUSED %s" % (kind, type(exc).__name__))
            continue
        ev = r.pending_events[0] if r.pending_events else None
        print("  %-22s restored as %-12s system=%s"
              % (kind, type(ev).__name__, getattr(ev, "system", "<n/a>")))
        if getattr(ev, "system", False):
            FORGED.append(f"8. snapshot laundering via {kind}")

    print("\nBREACHES:", FORGED if FORGED else "none")
    print("VERDICT:", "FAIL" if FORGED else "PASS")


asyncio.run(main())
