# -*- coding: utf-8 -*-
"""F9: prove C-04 (B16) and C-07b (B18) are OUR-CONTRACT, not library --
each is closed by a CONFIG-ONLY edit on v0.9.0, on both engines and both
service spellings.  Library source untouched.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, copy, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")

KILLERS = ["LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE", "REVOKE"]


def patch_b16(c):
    """Config-only C-04 fix: hoist the four revocation events to the ROOT so
    the parallel `elevation` region sees them too, add a terminal
    `elevation.dead`, and audit the re-enter arm."""
    c = copy.deepcopy(c)
    el = c["states"]["elevation"]
    el.setdefault("states", {})["dead"] = {"type": "final"}
    c.setdefault("on", {})
    for ev in KILLERS:
        c["on"][ev] = {"target": ".elevation.dead"}
    # C-04b: the re-enter arm must audit too
    arm = el["states"]["elevated"]["on"].get("STEP_UP_OK")
    if isinstance(arm, dict):
        acts = list(arm.get("actions") or [])
        if "audit_step_up" not in acts:
            arm["actions"] = acts + ["audit_step_up"]
    return c


def patch_b18(c):
    """Config-only C-07b fix: onUnhandled defer (as the other four control
    charts use) + an unguarded RELEASE fall-through that audits the denial
    and stays engaged (the B17/B20 shape)."""
    c = copy.deepcopy(c)
    c["onUnhandled"] = "defer"
    eng = c["states"]["engaged"]
    rel = eng["on"]["RELEASE"]
    arms = rel if isinstance(rel, list) else [rel]
    eng["on"]["RELEASE"] = arms + [{"actions": ["audit_release_denied"]}]
    return c


async def c04():
    base = K.cfg("B16")
    fixed = patch_b16(base)
    st = K.Stub(fixed)
    K.rec("V3.C04.fixed_builds", True, "")
    try:
        K.build(fixed, st)
    except Exception as e:
        K.rec("V3.C04.fixed_builds", False, repr(e)[:250])
        return
    bad = []
    for ev in KILLERS:
        r = await K.drive(fixed, K.Stub(fixed), ["MFA_OK", "REQUEST",
                                                 "STEP_UP_OK", ev],
                          snapshots=False)
        leaves = [s.split(".", 1)[1] for s in r["states"]]
        if "elevation.elevated" in leaves:
            bad.append((ev, leaves))
    K.rec("V3.C04.config_only_fix_closes_it", not bad,
          "still elevated after: %s" % bad if bad
          else "all 4 revocation events drop elevation")


async def c07b():
    base = K.cfg("B18")
    fixed = patch_b18(base)
    try:
        K.build(fixed, K.Stub(fixed))
        K.rec("V3.C07b.fixed_builds", True, "")
    except Exception as e:
        K.rec("V3.C07b.fixed_builds", False, repr(e)[:250])
        return
    # denied RELEASE (not elevated) then a correct one must land.
    st = K.Stub(fixed, guard_vals={"owner_and_elevated": False})
    m, i, p = await K.new_async(fixed, st)
    await K.send(i, "ENGAGE", cancel_working=True, flatten=True)
    await K.quiesce(i, 2)
    engaged = K.ids(i)
    await K.send(i, "RELEASE")
    await K.quiesce(i, 2)
    after_denied, status = K.ids(i), i.status
    # now elevate: flip the guard and press again
    st.guard_vals["owner_and_elevated"] = True
    await K.send(i, "RELEASE")
    await K.quiesce(i, 3)
    final = K.ids(i)
    K.rec("V3.C07b.denied_not_fatal", status == "running",
          "status after denied RELEASE=%r states=%s" % (status, after_denied))
    K.rec("V3.C07b.config_only_fix_unbricks", final != engaged,
          "engaged=%s -> final=%s" % (engaged, final))
    K.rec("V3.C07b.chain_clean", getattr(i, "chain_trips", -1) == 0,
          "chain_trips=%r" % getattr(i, "chain_trips", None))
    try:
        await asyncio.wait_for(i.stop(), 10)
    except Exception:
        pass


async def main():
    await c04()
    await c07b()
    K.dump("v3_c04_c07b.json")


asyncio.run(main())
