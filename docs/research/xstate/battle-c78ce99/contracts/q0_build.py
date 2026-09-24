# -*- coding: utf-8 -*-
"""q0: B6-B10 build + policy read-back + strictConfig audit @ c78ce99.

Run: q0_build.py [async|def]
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]
import cvc78 as H
from cvc78 import Stub
from xstate_statemachine.validation import KNOWN_MACHINE_KEYS
from xstate_statemachine.exceptions import InvalidConfigError

rec = H.rec
BS = ["B6", "B7", "B8", "B9", "B10"]
POLICY = {
    "B6": ("rollback", "defer", "raise"), "B7": ("rollback", "defer", "raise"),
    "B8": ("fail", "defer", "raise"), "B9": ("rollback", "defer", "raise"),
    "B10": ("rollback", "defer", "raise"),
}


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


async def main():
    for b in BS:
        c = H.cfg(b)
        # --- #216 our-contract audit: unknown top-level keys ---
        unknown = sorted(k for k in c if k not in KNOWN_MACHINE_KEYS
                         and not k.startswith("x-"))
        rec("%s/#216 no unknown top-level keys" % b, not unknown, str(unknown))
        # --- build under strict_config=True ---
        st = S(c)
        try:
            m = H.build(c, st)
            built = True
            err = ""
        except Exception as e:
            m = None
            built = False
            err = repr(e)[:160]
        rec("%s/build strict_config=True" % b, built, err)
        if not built:
            continue
        ae, ou, ge = POLICY[b]
        got = (getattr(m, "action_error_policy", None),
               getattr(m, "on_unhandled", None),
               getattr(m, "guard_error_policy", None))
        got = tuple(getattr(g, "value", g) for g in got)
        rec("%s/policy read-back" % b, got == (ae, ou, ge), str(got))
        rec("%s/strict+strictTargets" % b,
            bool(getattr(m, "strict", False)) and
            bool(getattr(m, "strict_targets", False)),
            "strict=%s targets=%s" % (getattr(m, "strict", None),
                                      getattr(m, "strict_targets", None)))
        # --- config-level "strictConfig": true also refuses a typo ---
        c2 = json.loads(json.dumps(c))
        c2["strictConfig"] = True
        c2["actionErrorPolicyy"] = "continue"
        try:
            H.build(c2, S(c2), strict_config=None)
            caught = "no-raise"
        except InvalidConfigError as e:
            caught = "InvalidConfigError"
        except Exception as e:
            caught = repr(e)[:80]
        rec("%s/#216 typo refused via config strictConfig" % b,
            caught == "InvalidConfigError", caught)
        # --- start configuration ---
        st2 = S(c)
        _, i, p = await H.new_async(c, st2)
        rec("%s/start config" % b, bool(H.ids(i)),
            "%s | status=%s" % (H.ids(i), i.status))
        H.RESULTS["[%s]%s/start-ids" % (STYLE, b)] = {
            "pass": True, "note": str(H.ids(i))}
        await i.stop()
    H.dump("q0_build.json")


asyncio.run(main())
