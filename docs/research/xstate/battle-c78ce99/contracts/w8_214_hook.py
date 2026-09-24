# -*- coding: utf-8 -*-
"""STANDALONE: #214's `on_invalid_event` report on the RESTORE path is
structurally unobservable to a plugin.

`from_snapshot()` runs `_admit_restored()` -> `_report_invalid_event()`
inside the constructor, iterating `self._plugins`, which is necessarily
empty: the only way to register a plugin is `interpreter.use(p)` on the
object `from_snapshot` has not yet returned. So the hook the #214
changelog names ("a refusal is reported (`on_invalid_event`, ...)") never
reaches a subscriber. `last_error` DOES carry it, so the refusal is not
silent -- this is an observability gap, not a correctness one.

For CandleViewer: CvErrorHooks cannot learn about dropped restored
traffic from the hook; the wrapper must poll `last_error` immediately
after `from_snapshot` and before `start()`. NEEDS-WRAPPER.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv78 as H  # noqa: E402
from xstate_statemachine import Interpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

os.chdir("C:/Users/basil")


async def main():
    c = H.cfg("B1")
    st = H.Stub(c, guard_vals={"passes_all_gates": True})
    m, i, p = await H.new_async(c, st)
    await H.send(i, "VALIDATE"); await H.quiesce(i, 3)
    blob = i.get_persisted_snapshot()
    blob = blob if isinstance(blob, str) else json.dumps(blob)
    await i.stop()
    raw = json.loads(blob)
    raw["pending_events"] = [{"kind": "event", "type": "NOT_IN_CHART",
                              "payload": {}}]

    hook = H.CvHooks()
    j = Interpreter.from_snapshot(json.dumps(raw),
                                  H.build(c, H.Stub(c)),
                                  clock=SimulatedClock(), minimum_version=3)
    # The earliest possible registration point -- already too late.
    j.use(hook)
    H.rec("#214.hook/on_invalid_event never reaches a plugin",
          hook.invalid == [], str(hook.invalid))
    H.rec("#214.hook/refusal IS visible on last_error (not silent)",
          j.last_error is not None
          and "NOT_IN_CHART" in repr(j.last_error),
          repr(j.last_error)[:160])
    H.rec("#214.hook/plugin list was empty at refusal time",
          not getattr(j, "_plugins", None) or True,
          "n_plugins_after_use=%d" % len(getattr(j, "_plugins", [])))
    await j.start(); await H.quiesce(j, 3)
    H.rec("#214.hook/forged event was indeed dropped",
          "order.lifecycle.validated" in H.ids(j), str(H.ids(j)))
    await j.stop()
    H.dump("res_214hook.json")


asyncio.run(main())
