# -*- coding: utf-8 -*-
"""V0b: isolate the two V0 signals.

(a) does `from_snapshot(plugins=[p])` + `start()` fire `on_interpreter_start`,
    and do plugins passed that way receive ordinary runtime hooks?
(b) B3 `leg` reaches `leg.error` + status=done at t0 with NO event sent.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")

from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402


async def a_plugins():
    c = K.cfg("B1")
    m, i, p = await K.new_async(c, K.Stub(c))
    K.rec("V0b.live_use_fires_start", p.started == 1,
          "live .use() started=%d" % p.started)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()

    # restore WITH plugins=
    p2 = K.CvHooks()
    j = Interpreter.from_snapshot(blob, K.build(c, K.Stub(c)),
                                  clock=SimulatedClock(), minimum_version=3,
                                  plugins=[p2])
    K.rec("V0b.plugins_kwarg_registers", len(j.plugins) == 1,
          "j.plugins=%r" % ([type(x).__name__ for x in j.plugins],))
    await j.start()
    await K.quiesce(j, 2)
    K.rec("V0b.restored_start_fires_on_interpreter_start", p2.started == 1,
          "started=%d (plugins= path)" % p2.started)
    # does it get ordinary runtime hooks?
    await K.send(j, "SUBMIT")
    await K.quiesce(j, 2)
    K.rec("V0b.plugins_kwarg_gets_runtime_hooks",
          len(p2.actions) > 0 or len(p2.transitions) > 0,
          "actions=%d transitions=%d" % (len(p2.actions), len(p2.transitions)))
    await j.stop()

    # control: same restore, but .use() AFTER from_snapshot
    p3 = K.CvHooks()
    j3 = Interpreter.from_snapshot(blob, K.build(c, K.Stub(c)),
                                   clock=SimulatedClock(), minimum_version=3)
    j3.use(p3)
    await j3.start()
    await K.quiesce(j3, 2)
    K.rec("V0b.control_use_after_restore_fires_start", p3.started == 1,
          "started=%d (.use() path)" % p3.started)
    await j3.stop()


def a_plugins_sync():
    c = K.cfg("B1")
    m, i, p = K.new_sync(c, K.Stub(c, sync=True))
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    i.stop()
    p2 = K.CvHooks()
    j = SyncInterpreter.from_snapshot(blob, K.build(c, K.Stub(c, sync=True)),
                                      clock=SimulatedClock(),
                                      minimum_version=3, plugins=[p2])
    K.rec("V0b.sync_plugins_kwarg_registers", len(j.plugins) == 1,
          "j.plugins=%r" % ([type(x).__name__ for x in j.plugins],))
    j.start()
    K.rec("V0b.sync_restored_start_fires_on_interpreter_start", p2.started == 1,
          "started=%d" % p2.started)
    j.stop()


async def b_b3():
    c = K.cfg("B3")
    st = K.Stub(c)
    m, i, p = await K.new_async(c, st)
    K.rec("V0b.B3.initial_not_terminal",
          i.status == "running" and K.ids(i) != ["leg.error"],
          "states=%s status=%s trans=%s acts=%s guards=%s"
          % (K.ids(i), i.status, p.transitions[:6], p.actions[:8],
             st.guard_calls[:8]))
    await i.stop()
    # with every guard TRUE instead of the default False
    st2 = K.Stub(c, guard_vals={g: True for g in st.guards})
    m2, i2, p2 = await K.new_async(c, st2)
    K.rec("V0b.B3.guards_true_not_terminal",
          i2.status == "running" and K.ids(i2) != ["leg.error"],
          "states=%s status=%s trans=%s"
          % (K.ids(i2), i2.status, p2.transitions[:6]))
    await i2.stop()


async def main():
    await a_plugins()
    a_plugins_sync()
    await b_b3()
    K.dump("v0b_signals.json")


asyncio.run(main())
