# -*- coding: utf-8 -*-
"""C-04 (B16 elevation) re-check @ c78ce99 -- STANDALONE, neutral cwd.

C-04 was REFUTED as a library defect in round 10 and retained as OUR
catalogue Blocker: `elevation.elevated.on` omits LOGOUT / IDLE_DEADLINE /
ABSOLUTE_DEADLINE, so a dead session stays elevated and STEP_UP_OK
re-elevates it.  This re-check asks only one question: does the symptom
still reproduce at c78ce99 (i.e. is the Blocker still ours and still open),
and does the CORRECTED chart still pass?

Exit 0 = status unchanged (defect ours, corrected usage clean).
"""
from __future__ import annotations
import asyncio, json, sys
from xstate_statemachine import (
    Interpreter, MachineLogic, SyncInterpreter, create_machine)
from xstate_statemachine.clock import SimulatedClock

BASE = {
    "id": "sess", "type": "parallel", "strict": True, "strictTargets": True,
    "context": {"elevated_until_us": None, "audit": 0},
    "states": {
        "session": {"initial": "active", "states": {
            "active": {"on": {"LOGOUT": "#sess.session.dead",
                              "IDLE_DEADLINE": "#sess.session.dead",
                              "ABSOLUTE_DEADLINE": "#sess.session.dead"}},
            "dead": {"type": "final"}}},
        "elevation": {"initial": "normal", "states": {
            "normal": {"on": {"STEP_UP_OK": {"target": "#sess.elevation.elevated",
                                             "actions": ["elevate"]}}},
            "elevated": {"on": {
                "REVOKE": {"target": "#sess.elevation.normal",
                           "actions": ["clear"]},
                # 🐞 C-04: the three session-killing events are NOT listed.
                "STEP_UP_OK": {"target": "#sess.elevation.elevated",
                               "reenter": True, "actions": ["elevate"]}}}}},
    },
}


def corrected():
    c = json.loads(json.dumps(BASE))
    el = c["states"]["elevation"]["states"]
    for ev in ("LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"):
        el["elevated"]["on"][ev] = {"target": "#sess.elevation.normal",
                                    "actions": ["clear"]}
    el["normal"]["on"]["STEP_UP_OK"] = [
        {"target": "#sess.elevation.elevated", "guard": "session_alive",
         "actions": ["elevate"]},
        {"actions": ["deny"]}]
    return c


def logic(alive):
    return MachineLogic(
        actions={
            "elevate": lambda i, c, e, a: (
                c.__setitem__("elevated_until_us", 9999999),
                c.__setitem__("audit", c["audit"] + 1)),
            "clear": lambda i, c, e, a: c.__setitem__("elevated_until_us", None),
            "deny": lambda i, c, e, a: None},
        guards={"session_alive": lambda c, e: alive["v"]})


def run_sync(cfg, kill):
    alive = {"v": True}
    i = SyncInterpreter(create_machine(json.loads(json.dumps(cfg)),
                                       logic=logic(alive)),
                        clock=SimulatedClock())
    i.start()
    i.send("STEP_UP_OK")
    i.send(kill)
    alive["v"] = False
    still = i.context["elevated_until_us"] is not None
    i.send("STEP_UP_OK")
    re_el = i.context["elevated_until_us"] is not None
    ids = sorted(i.current_state_ids)
    try:
        i.stop()
    except Exception:
        pass
    return {"still_elevated": still, "re_elevated_dead": re_el, "states": ids}


async def run_async(cfg, kill):
    alive = {"v": True}
    i = Interpreter(create_machine(json.loads(json.dumps(cfg)),
                                   logic=logic(alive)), clock=SimulatedClock())
    await i.start()
    for ev in ("STEP_UP_OK", kill):
        await i.send(ev)
        for _ in range(4):
            await asyncio.sleep(0.02)
    alive["v"] = False
    still = i.context["elevated_until_us"] is not None
    await i.send("STEP_UP_OK")
    for _ in range(6):
        await asyncio.sleep(0.02)
    re_el = i.context["elevated_until_us"] is not None
    out = {"still_elevated": still, "re_elevated_dead": re_el,
           "states": sorted(i.current_state_ids)}
    await i.stop()
    return out


async def main():
    rows, bad = [], 0
    for kill in ("LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"):
        for label, cfg, want in (("catalogued(C-04)", BASE, True),
                                 ("corrected", corrected(), False)):
            a = await run_async(cfg, kill)
            s = run_sync(cfg, kill)
            ok = (a["still_elevated"] == want and a["re_elevated_dead"] == want
                  and s["still_elevated"] == want
                  and s["re_elevated_dead"] == want)
            bad += 0 if ok else 1
            rows.append({"kill": kill, "chart": label, "expect_leak": want,
                         "async": a, "sync": s, "as_expected": ok})
    print(json.dumps(rows, indent=1))
    print("\nC-04 STATUS UNCHANGED (ours, open)" if not bad
          else "\nC-04 STATUS CHANGED -- investigate")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
