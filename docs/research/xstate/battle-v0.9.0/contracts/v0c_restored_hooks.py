# -*- coding: utf-8 -*-
"""V0c: does a plugin attached to a RESTORED interpreter receive ordinary
runtime hooks (on_transition / on_action_execute), or only miss
`on_interpreter_start`?

Control: the identical event on a LIVE interpreter with the same plugin.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")

from xstate_statemachine import Interpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402


async def main():
    c = K.cfg("B1")
    # ---- control: live interpreter, same event ----
    m, i, p = await K.new_async(c, K.Stub(c, guard_vals={"passes_all_gates": True}))
    s0 = K.ids(i)
    await K.send(i, "VALIDATE")
    await K.quiesce(i, 3)
    live_states, live_tr, live_ac = K.ids(i), len(p.transitions), len(p.actions)
    K.rec("V0c.live_VALIDATE_moves", live_states != s0,
          "%s -> %s  transitions=%d actions=%d" % (s0, live_states, live_tr, live_ac))
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()

    # ---- restored from a snapshot taken at the SAME t0 state ----
    m2, i2, _ = await K.new_async(c, K.Stub(c, guard_vals={"passes_all_gates": True}))
    blob0 = i2.get_persisted_snapshot()
    if isinstance(blob0, dict):
        blob0 = json.dumps(blob0)
    await i2.stop()

    p2 = K.CvHooks()
    j = Interpreter.from_snapshot(blob0, K.build(c, K.Stub(c, guard_vals={"passes_all_gates": True})),
                                  clock=SimulatedClock(), minimum_version=3,
                                  plugins=[p2])
    await j.start()
    await K.quiesce(j, 2)
    r0 = K.ids(j)
    K.rec("V0c.restored_at_same_state", r0 == s0, "restored=%s live_t0=%s" % (r0, s0))
    await K.send(j, "VALIDATE")
    await K.quiesce(j, 3)
    r1 = K.ids(j)
    K.rec("V0c.restored_VALIDATE_moves", r1 != r0, "%s -> %s" % (r0, r1))
    K.rec("V0c.restored_plugin_gets_on_transition", len(p2.transitions) > 0,
          "transitions=%r" % (p2.transitions[:5],))
    K.rec("V0c.restored_plugin_gets_on_action_execute", len(p2.actions) > 0,
          "actions=%r" % (p2.actions[:8],))
    K.rec("V0c.restored_plugin_parity_with_live",
          len(p2.transitions) == live_tr and len(p2.actions) == live_ac,
          "restored tr=%d ac=%d | live tr=%d ac=%d"
          % (len(p2.transitions), len(p2.actions), live_tr, live_ac))
    K.rec("V0c.restored_missing_only_on_interpreter_start",
          p2.started == 0 and len(p2.transitions) > 0,
          "started=%d transitions=%d" % (p2.started, len(p2.transitions)))
    await j.stop()
    K.rec("V0c.restored_stop_fires_on_interpreter_stop", p2.stopped == 1,
          "stopped=%d" % p2.stopped)
    K.dump("v0c_restored_hooks.json")


asyncio.run(main())
