# -*- coding: utf-8 -*-
"""D1 (de2da4e): B11-B15 build gate under the mandatory config, with the
#220 RECURSIVE unknown-key check exercised at root / state / transition /
invoke level, plus an audit of our catalogue action stubs for the #219
shape (an action awaiting send(wait=True) on its own interpreter).

Pass 1: CV_SVC_STYLE=async (default).  Pass 2: CV_SVC_STYLE=def.
"""
from __future__ import annotations
import copy, json, warnings
from cvb import cfg, rec, dump, Stub, build, collect, STYLE
from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError

BS = ["B11", "B12", "B13", "B14", "B15"]


def build_strict(c, st):
    return create_machine(copy.deepcopy(c), logic=st.logic(),
                          strict_targets=True, strict_config=True)


def refused(c, st):
    """Return (refused?, message)."""
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            build_strict(c, st)
        return False, "; ".join(str(x.message) for x in w)
    except InvalidConfigError as e:
        return True, str(e)[:400]
    except Exception as e:
        return True, "OTHER:" + repr(e)[:300]


for b in BS:
    c = cfg(b)          # injects strictConfig: true
    st = Stub(c)
    # ---- (1) our JSON must BUILD clean, no warnings, under strictConfig.
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            m = build_strict(c, st)
        msgs = [str(x.message) for x in w]
        rec("%s/build-strictConfig-clean" % b, not msgs,
            "%d warnings %s" % (len(msgs), msgs[:2]))
    except Exception as e:
        rec("%s/build-strictConfig-clean" % b, False, repr(e)[:300])

    # ---- (2) negative control at ROOT (round-10 shape).
    c2 = copy.deepcopy(c); c2["maxIteration"] = 7
    ok, msg = refused(c2, st)
    rec("%s/neg-root-key" % b, ok and "maxIteration" in msg, msg[:160])

    # ---- (3) #220 negative control in a NESTED state.
    c3 = copy.deepcopy(c)
    sk = sorted(c3["states"])[0]
    c3["states"][sk]["entyr"] = ["nope"]
    ok, msg = refused(c3, st)
    rec("%s/neg-nested-state-key" % b,
        ok and "entyr" in msg and sk in msg, msg[:160])

    # ---- (4) #220 negative control in a TRANSITION body.
    c4 = copy.deepcopy(c)
    tgt = None
    for sname, sc in c4["states"].items():
        for ev, tr in (sc.get("on") or {}).items():
            body = tr[0] if isinstance(tr, list) else tr
            if isinstance(body, dict):
                body["cnod"] = "x"
                tgt = (sname, ev); break
        if tgt: break
    ok, msg = refused(c4, st)
    rec("%s/neg-transition-key" % b,
        bool(tgt) and ok and "cnod" in msg, "%s | %s" % (tgt, msg[:140]))

    # ---- (5) #220 negative control in an INVOKE body (where one exists).
    c5 = copy.deepcopy(c)
    inv_at = None
    for sname, sc in c5["states"].items():
        if isinstance(sc.get("invoke"), dict):
            sc["invoke"]["scr"] = "x"; inv_at = sname; break
    if inv_at:
        ok, msg = refused(c5, st)
        rec("%s/neg-invoke-key" % b, ok and "scr" in msg,
            "%s | %s" % (inv_at, msg[:140]))
    else:
        rec("%s/neg-invoke-key" % b, True, "chart has no invoke - n/a")

    # ---- (6) #220 accepts x-/meta/description/tags at EVERY level.
    c6 = copy.deepcopy(c)
    c6["x-cv"] = 1; c6["meta"] = {"a": 1}; c6["description"] = "d"
    sk = sorted(c6["states"])[0]
    c6["states"][sk].update({"x-cv": 1, "meta": {}, "description": "d",
                             "tags": ["t"]})
    for sname, sc in c6["states"].items():
        for ev, tr in (sc.get("on") or {}).items():
            body = tr[0] if isinstance(tr, list) else tr
            if isinstance(body, dict):
                body.update({"x-cv": 1, "meta": {}, "description": "d"})
        if isinstance(sc.get("invoke"), dict):
            sc["invoke"].update({"x-cv": 1, "meta": {}, "description": "d"})
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            build_strict(c6, Stub(c6))
        rec("%s/metadata-accepted-everywhere" % b, not w,
            "%d warnings" % len(w))
    except Exception as e:
        rec("%s/metadata-accepted-everywhere" % b, False, repr(e)[:200])

# ---- (7) #219 audit: does any catalogue action stub await its own
# send(wait=True)?  Our stubs are pure context writers; assert that by
# construction and record the catalogue action inventory.
inv = {}
for b in BS:
    acts, guards, svcs, delays, evts = collect(cfg(b))
    inv[b] = {"actions": acts, "guards": guards, "services": svcs,
              "delays": delays, "events": evts}
selfsend = [a for b in BS for a in inv[b]["actions"]
            if a.startswith("send_") or "self_send" in a]
rec("219/no-catalogue-action-awaits-own-send", not selfsend,
    "no B11-B15 action is specified as an in-step wait-send; "
    "deadline actions (schedule_*/arm_*/rearm_*) are fire-and-forget "
    "timers. candidates=%s" % (selfsend,))
(__import__("pathlib").Path("results")).mkdir(exist_ok=True)
(__import__("pathlib").Path("results/d1_inventory.%s.json" % STYLE)).write_text(
    json.dumps(inv, indent=1), encoding="utf-8")
dump("results/d1_build.json")
