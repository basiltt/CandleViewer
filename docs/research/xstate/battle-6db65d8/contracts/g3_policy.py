# -*- coding: utf-8 -*-
"""Do the six mandatory policy keys actually bind? And typo tolerance."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
import xstate_statemachine as X

R = {}
cfg = H.load("B13")

# P1: is spawnBlockingTimeout stored anywhere?
m = H.build(cfg, H.Stub(cfg))
R["P1_spawnBlockingTimeout_on_machine"] = [a for a in dir(m) if "spawn" in a.lower()]
R["P1_value"] = getattr(m, "spawn_blocking_timeout", "ABSENT")

# P2: typo'd policy key -> silently accepted?
bad = json.loads(json.dumps(cfg))
bad["onUnhandledEvent"] = "defer"       # plausible typo, not a real key
bad["actionErrorPolicyy"] = "fail"
bad["strictTargest"] = True
try:
    m2 = X.create_machine(bad, logic=H.Stub(bad).logic())
    R["P2_typo_keys"] = "ACCEPTED SILENTLY on_unhandled=%s" % m2.on_unhandled
except Exception as e:
    R["P2_typo_keys"] = "%s: %s" % (type(e).__name__, str(e)[:200])

# P3: typo'd VALUE of a real key
bad2 = json.loads(json.dumps(cfg)); bad2["onUnhandled"] = "deferr"
try:
    m3 = X.create_machine(bad2, logic=H.Stub(bad2).logic())
    R["P3_bad_value"] = "ACCEPTED on_unhandled=%r" % m3.on_unhandled
except Exception as e:
    R["P3_bad_value"] = "%s: %s" % (type(e).__name__, str(e)[:200])

bad3 = json.loads(json.dumps(cfg)); bad3["actionErrorPolicy"] = "rolback"
try:
    m4 = X.create_machine(bad3, logic=H.Stub(bad3).logic())
    R["P3b_bad_aep"] = "ACCEPTED action_error_policy=%r" % m4.action_error_policy
except Exception as e:
    R["P3b_bad_aep"] = "%s: %s" % (type(e).__name__, str(e)[:200])

bad4 = json.loads(json.dumps(cfg)); bad4["guardErrorPolicy"] = "riase"
try:
    m5 = X.create_machine(bad4, logic=H.Stub(bad4).logic())
    R["P3c_bad_gep"] = "ACCEPTED guard_error_policy=%r" % m5.guard_error_policy
except Exception as e:
    R["P3c_bad_gep"] = "%s: %s" % (type(e).__name__, str(e)[:200])

# P4: empty MachineLogic(strict=True) built fine -- what happens at RUN time?
async def p4():
    m6 = X.create_machine(json.loads(json.dumps(cfg)), logic=X.MachineLogic(strict=True))
    it = X.Interpreter(m6)
    await it.start()
    got = {"after_start": sorted(it.current_state_ids)}
    try:
        await it.send("CONNECT", wait=True)
        got["send"] = "no error, states=%s" % sorted(it.current_state_ids)
    except Exception as e:
        got["send"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    got["last_error"] = repr(it.last_error)[:200]
    await it.stop()
    return got
R["P4_empty_strict_logic_runtime"] = asyncio.run(p4())

print(json.dumps(R, indent=1, default=str))
json.dump(R, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "g3_policy.json"), "w"), indent=1, default=str)
