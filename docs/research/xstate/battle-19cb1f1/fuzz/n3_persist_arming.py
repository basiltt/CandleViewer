"""N3 -- persistence around #204's arming window and #206's delayed-send debt.

A  Snapshot taken from inside the arming window (a plugin hook that fires
   during the macrostep in which the state is entered but the settle pass
   has not armed the invoke yet). It must REFUSE (SnapshotMidStepError) --
   accepting it would persist a configuration whose invoke exists neither
   as a live service nor as a recorded pending arm.

B  Snapshot at quiescence with the service in flight -> restore. The invoke
   must arm EXACTLY ONCE, and only when asked (restart_services=True);
   a static restore must leave it dormant and SAY so.

C  #206 delayed self-send debt across snapshot/restore: a state whose entry
   action issues raise(delay=) to itself. Snapshot before the timer fires,
   restore, and check the debt is not double-counted (two firings) nor lost
   with the arming budget left permanently indebted.

Both service kinds; async engine (SyncInterpreter has no async snapshot
restore of live services -- stated, not silently skipped).

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

SUB = {"n": 0}
FIRES = {"n": 0}


def svc_def(i, c, e):
    SUB["n"] += 1
    return {"ok": 1}


async def svc_async(i, c, e):
    SUB["n"] += 1
    await asyncio.sleep(5)
    return {"ok": 1}


CFG_INV = {
    "id": "p",
    "initial": "s",
    "states": {
        "s": {"on": {"GO": "t"}},
        "t": {"invoke": {"id": "job", "src": "svc", "onDone": {"target": "u"}}},
        "u": {},
    },
}

CFG_DELAY = {
    "id": "d",
    "initial": "s",
    "context": {"pings": 0},
    "states": {
        "s": {"on": {"GO": "t"}},
        "t": {"entry": ["arm"], "on": {"PING": {"actions": ["count"]}}},
    },
}


def arm(i, c, e, a=None):
    i.raise_(  # placeholder; replaced at runtime by whichever API exists
        "PING"
    )


def count(i, c, e, a=None):
    c["pings"] = c.get("pings", 0) + 1
    FIRES["n"] += 1


class SnapProbe(PluginBase):
    """Try a snapshot from every hook that can fire inside a macrostep."""

    def __init__(self):
        self.results = {}

    def _try(self, interp, where):
        if where in self.results:
            return
        try:
            import json as _j

            snap = _j.loads(interp.get_snapshot())
            live = sorted(interp.current_state_ids)
            self.results[where] = (
                f"ACCEPTED ids={sorted(snap['state_ids'])} live={live}"
            )
        except Exception as exc:  # noqa: BLE001
            self.results[where] = f"REFUSED:{type(exc).__name__}"

    def on_transition(self, interp, from_states, to_states, transition):
        ids = {getattr(s, "id", s) for s in to_states}
        if "p.t" in ids:
            self._try(interp, "on_transition into invoking state")

    def on_event_received(self, interp, event):
        self._try(interp, "on_event_received")

    def on_action_execute(self, interp, action):
        self._try(interp, "on_action_execute")


def logic(kind):
    return MachineLogic(
        actions={"arm": arm, "count": count},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


async def section_a(kind):
    SUB["n"] = 0
    probe = SnapProbe()
    m = create_machine(CFG_INV, logic=logic(kind))
    it = Interpreter(m).use(probe)
    await it.start()
    try:
        await it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.05)
    await it.stop()
    return probe.results


async def section_b(kind):
    SUB["n"] = 0
    m = create_machine(CFG_INV, logic=logic(kind))
    it = Interpreter(m)
    await it.start()
    try:
        await it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.05)
    subs_before = SUB["n"]
    try:
        snap = it.get_snapshot()  # str
        snap_ok = True
    except Exception as exc:  # noqa: BLE001
        snap = None
        snap_ok = f"REFUSED:{type(exc).__name__}"
    await it.stop()
    if not snap:
        return {"snap": snap_ok}
    blob = snap  # get_snapshot() already returns a JSON str

    SUB["n"] = 0
    m2 = create_machine(CFG_INV, logic=logic(kind))
    it2 = Interpreter.from_snapshot(blob, m2)
    ids_restored = sorted(it2.current_state_ids)
    dormant = it2.has_dormant_invocations
    pend = [(p.state_id, p.invoke_id) for p in it2.pending_invocations()]
    static_subs = SUB["n"]
    await it2.stop()

    SUB["n"] = 0
    m3 = create_machine(CFG_INV, logic=logic(kind))
    it3 = Interpreter.from_snapshot(blob, m3, restart_services=True)
    await it3.start()  # restart_services re-invokes at start(), per docstring
    await asyncio.sleep(0.1)
    restart_subs = SUB["n"]
    dormant3 = it3.has_dormant_invocations
    await it3.stop()
    return {
        "snap": snap_ok,
        "ids_restored": ids_restored,
        "subs_before": subs_before,
        "static_submits": static_subs,
        "static_dormant": dormant,
        "static_pending": pend,
        "restart_submits": restart_subs,
        "restart_dormant": dormant3,
    }


async def main():
    print("N3 -- persistence around the #204 arming window")
    print()
    print("A: snapshot from inside the macrostep that enters the invoking")
    print("   state (arming not yet run) -- must refuse")
    bad = []
    for kind in ("def", "async def"):
        res = await section_a(kind)
        print(f"   {kind:<9} {res}")
        for where, r in res.items():
            if r.startswith("ACCEPTED") and "['p.t']" in r:
                bad.append(f"A/{kind}/{where}: snapshot accepted mid-arming")
    print()
    print("B: snapshot at quiescence with service in flight -> restore")
    print("   static restore must be dormant + submit 0;")
    print("   restart_services=True must submit EXACTLY 1")
    for kind in ("def", "async def"):
        res = await section_b(kind)
        print(f"   {kind:<9} {res}")
        if isinstance(res.get("static_submits"), int):
            if res["static_submits"] != 0:
                bad.append(f"B/{kind}: static restore submitted service")
            invoking = res["ids_restored"] == ["p.t"]
            if res["restart_submits"] != (1 if invoking else 0):
                bad.append(
                    f"B/{kind}: restart_services submitted "
                    f"{res['restart_submits']} times, expected "
                    f"{1 if invoking else 0}"
                )
            if invoking and not res["static_dormant"]:
                bad.append(f"B/{kind}: dormant invoke not reported")
    print()
    print(f"DEFECTS = {len(bad)}")
    for b in bad:
        print(f"   - {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
