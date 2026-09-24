# -*- coding: utf-8 -*-
"""STANDALONE: is our catalogue Blocker C-07b still present on 19cb1f1?

C-07b: B18 kill_switch carries `onUnhandled: "error"`.  A `RELEASE` whose
guard denies it is an event the configuration cannot handle, so under the
"error" disposition the machine faults -- i.e. one wrong button press bricks
the kill switch, which can then never be released.

This runs B18's exact corrected shape (inlined, no file reads) with
CV=async|def, engages the switch, then sends a guard-denied RELEASE and
reports whether the interpreter is still usable afterwards.
stdlib + xstate_statemachine only.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

STYLE = os.environ.get("CV", "async")
#: "error" reproduces the catalogue as shipped; "defer" is the C-07b fix.
UNH = os.environ.get("UNH", "error")

CFG = {
    "id": "kill_switch", "initial": "clear",
    "actionErrorPolicy": "rollback", "onUnhandled": UNH,
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {"engaged_by": None, "cancel_working": False},
    "states": {
        "clear": {"on": {"ENGAGE": {
            "target": "#kill_switch.engaging",
            "actions": ["record_engagement"]}}},
        "engaging": {
            "entry": ["block_new_orders_immediately"],
            "always": [
                {"target": "#kill_switch.cancelling",
                 "guard": "cancel_working_requested"},
                {"target": "#kill_switch.engaged"}]},
        "cancelling": {"invoke": {
            "id": "cx", "src": "cancel_all_working_orders",
            "onDone": {"target": "#kill_switch.engaged"},
            "onError": {"target": "#kill_switch.engaged"}}},
        "engaged": {"on": {"RELEASE": {
            "target": "#kill_switch.clear",
            "guard": "owner_and_elevated",
            "actions": ["audit_kill_switch_released"]}}},
    },
}

ELEVATED = {"v": False}   # the operator is NOT elevated -> guard denies


class Hooks(PluginBase):
    def __init__(self):
        self.unhandled, self.errors = [], []

    def on_unhandled_event(self, i, e, ids, disposition):
        self.unhandled.append((e.type, disposition))

    def on_error(self, i, e):
        self.errors.append(type(e).__name__)


def act(n):
    def f(i, c, e, a):
        return None
    f.__name__ = n
    return f


def guard_owner(c, e):
    return bool(ELEVATED["v"])


def guard_cancel(c, e):
    return bool(c.get("cancel_working"))


def svc_def(i, c, e):
    return {"ok": True}


async def svc_async(i, c, e):
    return {"ok": True}


async def main():
    logic = MachineLogic(
        actions={n: act(n) for n in
                 ("record_engagement", "block_new_orders_immediately",
                  "audit_kill_switch_released")},
        guards={"owner_and_elevated": guard_owner,
                "cancel_working_requested": guard_cancel},
        services={"cancel_all_working_orders":
                  svc_def if STYLE == "def" else svc_async},
        strict=True)
    i = Interpreter(create_machine(CFG, logic=logic, strict_targets=True),
                    clock=SimulatedClock())
    p = Hooks()
    i.use(p)
    await i.start()
    await i.send("ENGAGE")
    await asyncio.sleep(0.3)
    engaged = sorted(i.current_state_ids)

    # --- the wrong button press: RELEASE while not elevated -------------
    try:
        await asyncio.wait_for(i.send("RELEASE", wait=True), 5)
        denied = "accepted"
    except Exception as e:
        denied = "raised:%s" % type(e).__name__
    await asyncio.sleep(0.3)
    mid = sorted(i.current_state_ids)
    status_mid, err_mid = i.status, i.error

    # --- now the RIGHT press: elevate and release ----------------------
    ELEVATED["v"] = True
    try:
        await asyncio.wait_for(i.send("RELEASE", wait=True), 5)
        second = "accepted"
    except Exception as e:
        second = "raised:%s" % type(e).__name__
    await asyncio.sleep(0.3)
    final = sorted(i.current_state_ids)

    print("style=%s onUnhandled=%s engaged=%s" % (STYLE, UNH, engaged))
    print("  denied_RELEASE=%s -> states=%s status=%s error=%r unhandled=%s"
          % (denied, mid, status_mid, err_mid, p.unhandled))
    print("  elevated_RELEASE=%s -> states=%s status=%s on_error=%s"
          % (second, final, i.status, p.errors))
    bricked = final != ["kill_switch.clear"]
    print("  C-07b PRESENT=%s (kill switch %s be released after a guard-denied "
          "press)" % (bricked, "CANNOT" if bricked else "can"))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))
    sys.exit(1 if bricked else 0)


asyncio.run(main())
