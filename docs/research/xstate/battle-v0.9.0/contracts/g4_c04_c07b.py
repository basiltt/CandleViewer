# -*- coding: utf-8 -*-
"""G4: re-check C-04 (B16 session/elevation) and C-07b (B18 kill switch) on
v0.9.0/main.

C-04 (R12-13): the four revocation events do not drop the parallel
`elevation` region, so a dead session stays elevated / can be re-elevated.
Round-12 correction: the root hoist alone fixes only 9/12 lanes -- the
region-level `elevated.on.REVOKE` handler must ALSO be deleted, because the
deeper handler outranks the root arm.

C-07b (R12-14): a guard-denied RELEASE under root `onUnhandled: "error"`
makes the kill switch fatal and permanently bricked.

Both are OUR-CONTRACT and config-only. This re-runs the confirmation AND the
fix proof on 0.9.0, all four kill events.
STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, copy, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")

KILLERS = ["LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE", "REVOKE"]


def patch_b16(c, delete_region_revoke=True):
    c = copy.deepcopy(c)
    el = c["states"]["elevation"]
    el.setdefault("states", {})["dead"] = {"type": "final"}
    c.setdefault("on", {})
    for ev in KILLERS:
        c["on"][ev] = {"target": ".elevation.dead"}
    if delete_region_revoke:
        # ROUND-12 CORRECTION: without this the deeper handler outranks the
        # root arm and REVOKE lands in `normal`, re-elevatable.
        el["states"]["elevated"]["on"].pop("REVOKE", None)
    arm = el["states"]["elevated"]["on"].get("STEP_UP_OK")
    if isinstance(arm, dict):
        acts = list(arm.get("actions") or [])
        if "audit_step_up" not in acts:
            arm["actions"] = acts + ["audit_step_up"]
    return c


def patch_b18(c):
    c = copy.deepcopy(c)
    c["onUnhandled"] = "defer"
    eng = c["states"]["engaged"]
    rel = eng["on"]["RELEASE"]
    arms = rel if isinstance(rel, list) else [rel]
    eng["on"]["RELEASE"] = arms + [{"actions": ["audit_release_denied"]}]
    return c


async def _b16_lane(cfg, ev, reelevate=False):
    """Drive one kill lane; return the leaf ids after the kill (and, if
    asked, after a follow-up STEP_UP_OK)."""
    script = ["MFA_OK", "REQUEST", "STEP_UP_OK", ev]
    if reelevate:
        script.append("STEP_UP_OK")
    r = await K.drive(cfg, K.Stub(cfg), script, snapshots=False)
    return [s.split(".", 1)[1] for s in r["states"]], r


async def c04_confirm():
    """C-04 has TWO shapes: LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE leave
    the region flatly `elevated`; REVOKE instead lands in `normal` where a
    later STEP_UP_OK RE-elevates an already-dead session. Both are the bug."""
    base = K.cfg("B16")
    stuck, reelev = [], []
    for ev in KILLERS:
        leaves, r = await _b16_lane(base, ev)
        if "elevation.elevated" in leaves:
            stuck.append((ev, leaves))
            continue
        leaves2, r2 = await _b16_lane(base, ev, reelevate=True)
        if "elevation.elevated" in leaves2:
            reelev.append((ev, leaves, leaves2))
    K.rec("G4.C04.still_reproduces_on_0_9_0",
          len(stuck) + len(reelev) == len(KILLERS),
          "%d/%d kill events break: stuck-elevated=%s ; re-elevatable=%s"
          % (len(stuck) + len(reelev), len(KILLERS),
             [e for e, _ in stuck], [e for e, _, _ in reelev]))


async def c04_root_hoist_alone_is_insufficient():
    """The amended acceptance criterion, re-proved on 0.9.0."""
    half = patch_b16(K.cfg("B16"), delete_region_revoke=False)
    leaves, r = await _b16_lane(half, "REVOKE", reelevate=True)
    K.rec("G4.C04.root_hoist_alone_leaves_REVOKE_broken",
          "elevation.elevated" in leaves,
          "REVOKE + STEP_UP_OK under root-hoist-only -> %s (re-elevated a "
          "dead session)" % leaves)


async def c04_fix():
    fixed = patch_b16(K.cfg("B16"))
    try:
        K.build(fixed, K.Stub(fixed))
        K.rec("G4.C04.fixed_builds_strictConfig", True, "")
    except Exception as e:
        K.rec("G4.C04.fixed_builds_strictConfig", False, repr(e)[:250])
        return
    bad = []
    for ev in KILLERS:
        leaves, r = await _b16_lane(fixed, ev, reelevate=True)
        if "elevation.elevated" in leaves:
            bad.append((ev, leaves))
    K.rec("G4.C04.corrected_fix_closes_all_4", not bad,
          "still elevated after: %s" % bad if bad
          else "all 4 kill events drop elevation AND resist re-elevation")


async def c07b_confirm():
    base = K.cfg("B18")
    st = K.Stub(base, guard_vals={"owner_and_elevated": False})
    m, i, p = await K.new_async(base, st)
    await K.send(i, "ENGAGE", cancel_working=True, flatten=True)
    await K.quiesce(i, 2)
    engaged = K.ids(i)
    await K.send(i, "RELEASE", timeout=3.0)
    await K.quiesce(i, 2)
    denied_status, denied_err = i.status, repr(i.error)[:120]
    st.guard_vals["owner_and_elevated"] = True
    await K.send(i, "RELEASE", timeout=3.0)
    await K.quiesce(i, 3)
    final = K.ids(i)
    K.rec("G4.C07b.denied_release_is_fatal_on_0_9_0",
          denied_status != "running",
          "status after guard-denied RELEASE=%r err=%s" % (denied_status,
                                                           denied_err))
    K.rec("G4.C07b.bricked_authorised_release_dropped", final == engaged,
          "engaged=%s -> after authorised RELEASE=%s (bricked=%s)"
          % (engaged, final, final == engaged))
    try:
        await asyncio.wait_for(i.stop(), 10)
    except Exception:
        pass


async def c07b_fix():
    fixed = patch_b18(K.cfg("B18"))
    try:
        K.build(fixed, K.Stub(fixed))
        K.rec("G4.C07b.fixed_builds_strictConfig", True, "")
    except Exception as e:
        K.rec("G4.C07b.fixed_builds_strictConfig", False, repr(e)[:250])
        return
    st = K.Stub(fixed, guard_vals={"owner_and_elevated": False})
    m, i, p = await K.new_async(fixed, st)
    await K.send(i, "ENGAGE", cancel_working=True, flatten=True)
    await K.quiesce(i, 2)
    engaged = K.ids(i)
    await K.send(i, "RELEASE", timeout=3.0)
    await K.quiesce(i, 2)
    denied_status = i.status
    st.guard_vals["owner_and_elevated"] = True
    await K.send(i, "RELEASE", timeout=3.0)
    await K.quiesce(i, 3)
    final = K.ids(i)
    K.rec("G4.C07b.fix_denied_not_fatal", denied_status == "running",
          "status=%r states=%s" % (denied_status, engaged))
    K.rec("G4.C07b.fix_unbricks", final != engaged,
          "engaged=%s -> final=%s" % (engaged, final))
    K.rec("G4.C07b.fix_audits_denial",
          "audit_release_denied" in p.actions,
          "acts=%s" % p.actions[-6:])
    K.rec("G4.C07b.fix_chain_clean", getattr(i, "chain_trips", -1) == 0,
          "chain_trips=%r" % getattr(i, "chain_trips", None))
    try:
        await asyncio.wait_for(i.stop(), 10)
    except Exception:
        pass


async def main():
    for fn in (c04_confirm, c04_root_hoist_alone_is_insufficient, c04_fix,
               c07b_confirm, c07b_fix):
        try:
            await asyncio.wait_for(fn(), 90)
        except Exception as e:
            K.rec("G4.%s.EXC" % fn.__name__, False, repr(e)[:300])
    K.dump("res_g4_c04_c07b.json")


asyncio.run(main())
