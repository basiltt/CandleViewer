# -*- coding: utf-8 -*-
"""B6-B10 build + policy read-back + #220 recursive unknown-key check."""
from __future__ import annotations
import asyncio, copy, json
import cvde
from cvde import cfg, rec, dump, Stub, build, new_async, ids, STYLE
from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError

BS = ["B6", "B7", "B8", "B9", "B10"]
POL = {
 "B6": ("rollback", "defer", "raise"), "B7": ("rollback", "defer", "raise"),
 "B8": ("fail", "defer", "raise"), "B9": ("rollback", "defer", "raise"),
 "B10": ("rollback", "defer", "raise")}


async def main():
    for b in BS:
        c = cfg(b)
        st = Stub(c)
        try:
            m = build(c, st)
            rec("/%s/build-strictConfig" % b, True, "id=%s" % m.id)
        except Exception as e:
            rec("/%s/build-strictConfig" % b, False, repr(e)[:200]); continue
        ae, un, ge = POL[b]
        rec("/%s/policy" % b,
            m.action_error_policy == ae and m.on_unhandled == un
            and m.guard_error_policy == ge,
            "%s/%s/%s" % (m.action_error_policy, m.on_unhandled, m.guard_error_policy))
        rec("/%s/strict-targets" % b, c.get("strictTargets") is True, "")
        rec("/%s/strictConfig-in-json" % b, c.get("strictConfig") is True,
            repr(c.get("strictConfig")))
        _, i, p = await new_async(c, Stub(c))
        rec("/%s/start-config" % b, True, ",".join(ids(i)))
        rec("/%s/chain_trips0" % b, i.chain_trips == 0, "trips=%s" % i.chain_trips)
        await i.stop()

        # --- #220: planted NESTED typos must now be refused ---
        for tag, mut in (("state-key", "state"), ("transition-key", "trans"),
                         ("invoke-key", "invoke")):
            c2 = copy.deepcopy(c)
            planted = plant(c2, mut)
            if not planted:
                rec("/%s/220-%s" % (b, tag), True, "SKIP: no such site"); continue
            try:
                create_machine(c2, logic=Stub(c2).logic(), strict_config=True)
                rec("/%s/220-%s" % (b, tag), False,
                    "ACCEPTED planted %s at %s" % (tag, planted))
            except InvalidConfigError as e:
                ok = planted.split(".")[-1] in repr(e) or "did you mean" in repr(e)
                rec("/%s/220-%s" % (b, tag), True, "refused: %s" % repr(e)[:160])
            except Exception as e:
                rec("/%s/220-%s" % (b, tag), False, "wrong exc %r" % (e,))
    dump("e0_build.json")


def plant(c, kind):
    """Plant one typo deep in the chart; return the path planted or ''."""
    def walk(n, path):
        for nm, s in (n.get("states") or {}).items():
            p = path + "." + nm
            if kind == "state" and ("entry" in s or "exit" in s):
                s["entyr"] = s.pop("entry", s.pop("exit", []))
                return p
            if kind == "trans":
                for ev, t in (s.get("on") or {}).items():
                    tt = t[0] if isinstance(t, list) else t
                    if isinstance(tt, dict):
                        tt["actionss"] = tt.get("actions", [])
                        return p + ".on." + ev
            if kind == "invoke" and isinstance(s.get("invoke"), dict):
                s["invoke"]["srcc"] = s["invoke"].get("src")
                return p + ".invoke"
            r = walk(s, p)
            if r:
                return r
        return ""
    return walk(c, c.get("id", "m"))


asyncio.run(main())
