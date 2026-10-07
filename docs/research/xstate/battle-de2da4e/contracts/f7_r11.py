# -*- coding: utf-8 -*-
"""F7: round-11 (#218-#222) probes against the CONTRACT charts on de2da4e.

STANDALONE: stdlib + xstate_statemachine only, no psutil, neutral cwd.
Pass 1 CV_SVC_STYLE=async, pass 2 CV_SVC_STYLE=def.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cvf as K  # noqa: E402
os.chdir("<home>")

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

try:
    from xstate_statemachine.exceptions import ReentrantWaitError
except Exception:  # pragma: no cover
    ReentrantWaitError = None


# ---------------------------------------------------------------- #219 ----
AUDIT = {}


def audit_catalogue_actions():
    """Does ANY catalogue action stub await send(wait=True) on its own
    interpreter?  Our stubs are generated (cvf.Stub.mk_a) and never call
    send at all, so the answer is structural: no catalogue action in
    B1-B5/B16-B20 is specified as a self-send-and-wait.  Recorded here so
    the claim is evidence, not assertion."""
    hits = []
    for bid in ["B1", "B2", "B3", "B4", "B5", "B16", "B17", "B18", "B19", "B20"]:
        c = K.cfg(bid)
        blob = json.dumps(c)
        # a catalogue action that needs a receipt would have to be modelled
        # as an explicit send with wait semantics; the JSON has no such key.
        for marker in ('"wait"', '"waitFor"', '"awaitReceipt"'):
            if marker in blob:
                hits.append((bid, marker))
        AUDIT[bid] = {"raise_delay": blob.count('"delay"'),
                      "send_priority": blob.count('"priority"')}
    K.rec("F7.219.audit.no_catalogue_self_wait", not hits, str(hits) or
          "no wait-receipt action in any of the 10 charts; AUDIT=%s" %
          json.dumps(AUDIT))


async def probe_219():
    """#219: an action awaiting send(wait=True) on its own interpreter
    must raise ReentrantWaitError (NEW), not hang."""
    cfg = {"id": "r", "initial": "a", "strictConfig": True,
           "states": {"a": {"entry": ["selfwait"], "on": {"P": "b"}}, "b": {}}}
    box = {}

    async def selfwait(i, ctx, e, ad):
        try:
            await i.send("P", wait=True)
            box["r"] = "returned"
        except Exception as ex:
            box["r"] = type(ex).__name__

    from xstate_statemachine import MachineLogic
    m = create_machine(cfg, logic=MachineLogic(actions={"selfwait": selfwait}),
                       strict_config=True)
    i = Interpreter(m, clock=SimulatedClock())
    try:
        await asyncio.wait_for(i.start(), 25)
        started = True
    except asyncio.TimeoutError:
        started = False
    K.rec("F7.219.async.no_hang", started, "box=%r" % box.get("r"))
    K.rec("F7.219.async.reentrant_error", box.get("r") == "ReentrantWaitError",
          "got %r" % box.get("r"))
    try:
        await asyncio.wait_for(i.stop(), 10)
    except Exception:
        pass

    # deferred receipt (ensure_future) is still allowed
    box2 = {}

    async def later(i, ctx, e, ad):
        box2["f"] = asyncio.ensure_future(i.send("P", wait=True))

    m2 = create_machine(json.loads(json.dumps(cfg)),
                        logic=MachineLogic(actions={"selfwait": later}),
                        strict_config=True)
    j = Interpreter(m2, clock=SimulatedClock())
    try:
        await asyncio.wait_for(j.start(), 25)
        await asyncio.sleep(0.1)
        await asyncio.wait_for(box2["f"], 10)
        ok, note = True, "deferred receipt resolved; states=%s" % K.ids(j)
    except Exception as e:
        ok, note = False, repr(e)[:160]
    K.rec("F7.219.async.deferred_receipt_ok", ok, note)
    try:
        await asyncio.wait_for(j.stop(), 10)
    except Exception:
        pass


def probe_219_sync():
    """Sync engine refuses the same shape (parity)."""
    from xstate_statemachine import MachineLogic
    cfg = {"id": "rs", "initial": "a", "strictConfig": True,
           "states": {"a": {"entry": ["selfwait"], "on": {"P": "b"}}, "b": {}}}
    box = {}

    def selfwait(i, ctx, e, ad):
        try:
            i.send("P", wait=True)
            box["r"] = "returned"
        except Exception as ex:
            box["r"] = type(ex).__name__

    m = create_machine(cfg, logic=MachineLogic(actions={"selfwait": selfwait}),
                       strict_config=True)
    s = SyncInterpreter(m, clock=SimulatedClock())
    s.start()
    K.rec("F7.219.sync.reentrant_error", box.get("r") == "ReentrantWaitError",
          "got %r" % box.get("r"))
    try:
        s.stop()
    except Exception:
        pass


if __name__ == "__main__":
    audit_catalogue_actions()
    asyncio.run(probe_219())
    probe_219_sync()
    K.dump("f7_r11.json")
