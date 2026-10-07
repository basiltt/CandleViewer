# -*- coding: utf-8 -*-
"""F8: #218 handle flatness, #221 restore->re-persist, #222 sticky trip,
plus the contract-chart timer/snapshot re-checks. STANDALONE."""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cvf as K  # noqa: E402
os.chdir("<home>")

from xstate_statemachine import (
    Interpreter, SyncInterpreter, MachineLogic, create_machine)
from xstate_statemachine.clock import SimulatedClock

BEATS = 200
ARM = {"type": "raise", "params": {"event": "BEAT", "delay": 10}}
HB = {"id": "hb", "initial": "up", "strictConfig": True,
      "states": {"up": {"entry": [ARM, "count"], "on": {"BEAT": "down"}},
                 "down": {"entry": [ARM, "count"], "on": {"BEAT": "up"}}}}


def handles(i):
    """Total live clock handles, summed across the per-owner buckets."""
    v = getattr(i, "_timer_handles", None)
    if isinstance(v, dict):
        return "_timer_handles", sum(len(x) for x in v.values())
    return "_timer_handles", (len(v) if v is not None else -1)


async def probe_218_async():
    box = {"n": 0}

    def count(i, ctx, e, ad):
        box["n"] += 1
    m = create_machine(json.loads(json.dumps(HB)),
                       logic=MachineLogic(actions={"count": count}),
                       strict_config=True)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    peak = 0
    for _ in range(BEATS):
        await i.clock.increment(10)
        for _ in range(3):
            await asyncio.sleep(0)
        peak = max(peak, handles(i)[1])
    attr, n = handles(i)
    K.rec("F8.218.async.handles_flat", 0 <= peak <= 1,
          "%s peak=%d final=%d beats=%d" % (attr, peak, n, box["n"]))
    K.rec("F8.218.async.beats_ran", box["n"] >= BEATS * 0.75,
          "%d/%d beats" % (box["n"], BEATS))
    await asyncio.wait_for(i.stop(), 10)


def probe_218_sync():
    box = {"n": 0}

    def count(i, ctx, e, ad):
        box["n"] += 1
    m = create_machine(json.loads(json.dumps(HB)),
                       logic=MachineLogic(actions={"count": count}),
                       strict_config=True)
    s = SyncInterpreter(m, clock=SimulatedClock())
    s.start()
    peak = 0
    for _ in range(BEATS):
        s.clock.increment(10)
        peak = max(peak, handles(s)[1])
    attr, n = handles(s)
    K.rec("F8.218.sync.handles_flat", 0 <= peak <= 1,
          "%s peak=%d final=%d beats=%d" % (attr, peak, n, box["n"]))
    K.rec("F8.218.sync.beats_ran", box["n"] >= BEATS * 0.75,
          "%d/%d beats" % (box["n"], BEATS))
    try:
        s.stop()
    except Exception:
        pass


async def probe_221():
    """#221: restore -> re-persist WITHOUT start() must keep armed sends."""
    def count(i, ctx, e, ad):
        pass
    mk = lambda: create_machine(json.loads(json.dumps(HB)),
                                logic=MachineLogic(actions={"count": count}),
                                strict_config=True)
    i = Interpreter(mk(), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.05)
    b1 = i.get_persisted_snapshot()
    b1 = b1 if isinstance(b1, str) else json.dumps(b1)
    n1 = len(json.loads(b1).get("scheduled_sends") or [])
    await asyncio.wait_for(i.stop(), 10)

    j = Interpreter.from_snapshot(b1, mk(), clock=SimulatedClock())
    b2 = j.get_persisted_snapshot()          # NO start()
    b2 = b2 if isinstance(b2, str) else json.dumps(b2)
    n2 = len(json.loads(b2).get("scheduled_sends") or [])
    K.rec("F8.221.armed_survives_repersist", n1 >= 1 and n2 == n1,
          "armed=%d re-persisted=%d" % (n1, n2))
    # verbatim?
    s1 = json.loads(b1)["scheduled_sends"]
    s2 = json.loads(b2)["scheduled_sends"]
    K.rec("F8.221.verbatim", s1 == s2, "%s vs %s" % (s1, s2))


async def probe_222():
    """#222: a chain-budget trip is sticky across a later benign event."""
    cfg = {"id": "ch", "initial": "a", "strictConfig": True,
           "maxIterations": 5,
           "states": {"a": {"entry": [{"type": "raise",
                                       "params": {"event": "SPIN"}}],
                            "on": {"SPIN": {"target": "a", "reenter": True},
                                   "OK": {"target": "b"}}},
                      "b": {}}}
    m = create_machine(cfg, logic=MachineLogic(actions={}), strict_config=True)
    i = Interpreter(m)   # real clock: the spin is within-step work
    seen = []

    from xstate_statemachine.plugins import PluginBase

    class P(PluginBase):
        def on_chain_budget_exceeded(self, interp, error, event):
            seen.append(repr(error)[:60])
    i.use(P())
    await i.start()
    for _ in range(20):
        await asyncio.sleep(0.02)
        if getattr(i, "chain_trips", 0):
            break
    t0 = getattr(i, "chain_trips", "MISSING")
    lat0 = getattr(i, "last_chain_error", "MISSING")
    K.rec("F8.222.trip_counted", isinstance(t0, int) and t0 >= 1,
          "chain_trips=%r latch=%r hook=%d" % (t0, lat0 is not None, len(seen)))
    K.rec("F8.222.hook_fired", len(seen) >= 1, str(seen[:2]))
    await K.send(i, "OK", wait=True)
    await asyncio.sleep(0.1)
    K.rec("F8.222.sticky_after_benign",
          getattr(i, "chain_trips", 0) >= 1 and
          getattr(i, "last_chain_error", None) is not None,
          "trips=%r latch=%r last_error=%r" % (
              getattr(i, "chain_trips", None),
              getattr(i, "last_chain_error", None) is not None,
              i.last_error is not None))
    i.clear_chain_error()
    K.rec("F8.222.clear_works",
          getattr(i, "last_chain_error", "x") is None and
          getattr(i, "chain_trips", 0) >= 1,
          "after clear: latch=%r trips=%r" % (
              getattr(i, "last_chain_error", "x"),
              getattr(i, "chain_trips", None)))
    await asyncio.wait_for(i.stop(), 10)


async def main():
    await probe_218_async()
    await probe_221()
    await probe_222()


# NOTE: the sync probe must run OUTSIDE a running event loop -- with a loop
# running, SimulatedClock.increment returns a `_MustAwait` sentinel.
probe_218_sync()
asyncio.run(main())
K.dump("f8_r11b.json")
