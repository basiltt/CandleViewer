# -*- coding: utf-8 -*-
"""#220 recursive unknown-key gate over B16-B20 (de2da4e). Pass 1 async, pass 2 def."""
import copy, json, sys, warnings
from cvde import cfg, rec, dump, Stub, build, STYLE
from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError

BS = ["B16", "B17", "B18", "B19", "B20"]


def first_state_path(c):
    """Return (dict, label) of the first nested state dict we can plant into."""
    st = c.get("states") or {}
    k = sorted(st)[0]
    return st[k], k


for b in BS:
    c = cfg(b)
    st = Stub(c)
    # (1) as-carried, strict_config kwarg + config-level "strictConfig": true
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            build(c, st)
        rec("%s/build-strictConfig" % b, True, "clean, %d warnings" % len(w))
    except Exception as e:
        rec("%s/build-strictConfig" % b, False, repr(e)[:300])

    # (2) negative control at ROOT (round-10 shape, must still refuse)
    c2 = copy.deepcopy(c); c2["actionErrorPolicyy"] = c2.get("actionErrorPolicy")
    try:
        build(c2, Stub(c2)); rec("%s/neg-root-typo" % b, False, "ACCEPTED")
    except InvalidConfigError as e:
        rec("%s/neg-root-typo" % b, True, repr(e)[:160])
    except Exception as e:
        rec("%s/neg-root-typo" % b, False, "wrong exc " + repr(e)[:160])

    # (3) NEW #220 negative control: typo in a NESTED state ('entyr'/'onn')
    c3 = copy.deepcopy(c); tgt, lbl = first_state_path(c3)
    tgt["entyr"] = ["noop"]; tgt["onn"] = {"NOPE": {"target": "#x"}}
    try:
        build(c3, Stub(c3)); rec("%s/neg-nested-typo" % b, False,
                                 "ACCEPTED nested entyr/onn in state %r" % lbl)
    except InvalidConfigError as e:
        msg = str(e)
        named = ("entyr" in msg and "onn" in msg and lbl in msg)
        rec("%s/neg-nested-typo" % b, True,
            "refused; path-named=%s | %s" % (named, msg[:200]))
    except Exception as e:
        rec("%s/neg-nested-typo" % b, False, "wrong exc " + repr(e)[:160])

    # (4) x-/meta/description/tags accepted at nested level
    c4 = copy.deepcopy(c); tgt, lbl = first_state_path(c4)
    tgt["x-cv-owner"] = "risk"; tgt["meta"] = {"a": 1}
    tgt["description"] = "d"; tgt.setdefault("tags", [])
    try:
        build(c4, Stub(c4)); rec("%s/nested-meta-ok" % b, True, "accepted in %r" % lbl)
    except Exception as e:
        rec("%s/nested-meta-ok" % b, False, repr(e)[:200])

dump("d0_build.json")
