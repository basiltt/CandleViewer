"""STANDALONE: #216 config-key fuzz + strict_config bypass attempts.

A  top-level misspellings of every policy key, default mode: WARNING +
   did-you-mean, value dropped?
B  strict_config=True kwarg and "strictConfig": true in-config.
C  bypass vectors: x- prefix, case variants, whitespace/unicode
   look-alikes, non-str keys, nested dict smuggling.
D  NESTED state-level unknown keys -- documented behaviour.
"""

import io
import json
import logging
import sys

from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError


def build(cfg, **kw):
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("xstate_statemachine")
    lg.addHandler(h)
    lvl = lg.level
    lg.setLevel(logging.WARNING)
    try:
        m = create_machine(cfg, **kw)
        return ("built", m, buf.getvalue())
    except Exception as exc:  # noqa: BLE001
        return ("refused", type(exc).__name__, buf.getvalue() or str(exc)[:90])
    finally:
        lg.removeHandler(h)
        lg.setLevel(lvl)


BASE = {"id": "k", "initial": "a", "context": {}, "states": {"a": {}}}


def cfg(extra=None, **kw):
    c = dict(BASE)
    c["states"] = {"a": {}}
    if extra:
        c.update(extra)
    c.update(kw)
    return c


def section_a():
    cases = [
        ("actionErrorPolicyy", "rollback"),
        ("Strict", True),
        ("maxIteration", 5),
        ("onUnhandledEvent", "error"),
        ("guardErrorPolicyy", "raise"),
        ("spawnBlockingTimeoutMs", 1234),
        ("strictTarget", False),
    ]
    for key, val in cases:
        res = build(cfg(**{key: val}))
        warned = "unknown top-level key" in (res[2] or "")
        hint = "did you mean" in (res[2] or "")
        print("A %-24s -> %-7s warned=%s hint=%s" % (key, res[0], warned, hint),
              flush=True)
    # value actually dropped?
    m = create_machine(cfg(maxIteration=5))
    print("A declared value dropped: machine.max_iterations =",
          m.max_iterations, "(declared 5 under a typo'd key)", flush=True)


def section_b():
    res = build(cfg(actionErrorPolicyy="rollback"), strict_config=True)
    print("B strict_config=True ->", res[0], res[1] if res[0] == "refused"
          else "BUILT (NOT REFUSED)", flush=True)
    res = build(cfg(actionErrorPolicyy="rollback", strictConfig=True))
    print("B in-config strictConfig:true ->", res[0],
          res[1] if res[0] == "refused" else "BUILT (NOT REFUSED)", flush=True)
    # precedence: kwarg False vs config True
    res = build(cfg(actionErrorPolicyy="x", strictConfig=True),
                strict_config=False)
    print("B kwarg False overrides config True ->", res[0], flush=True)


def section_c():
    vectors = [
        ("x- prefix hides a typo'd policy", {"x-actionErrorPolicy": "rollback"}),
        ("x-strict smuggle", {"x-strict": True}),
        ("case variant ACTIONERRORPOLICY", {"ACTIONERRORPOLICY": "rollback"}),
        ("trailing space 'strict '", {"strict ": True}),
        ("unicode look-alike 'strіct' (Cyrillic i)", {"strіct": True}),
        ("zero-width in key", {"stri​ct": True}),
        ("non-str key 1", {1: "x"}),
        ("meta carries a policy", {"meta": {"strict": True}}),
    ]
    for name, extra in vectors:
        res = build(cfg(extra), strict_config=True)
        print("C %-44s strict_config=True -> %s %s"
              % (name, res[0], res[1] if res[0] == "refused" else ""),
              flush=True)


def section_d():
    nested = dict(BASE)
    nested["states"] = {
        "a": {"entrry": [], "onn": {"GO": {"target": "b"}},
              "afterr": {100: {"target": "b"}}, "unknownThing": 5},
        "b": {},
    }
    res = build(nested, strict_config=True)
    print("D nested (state-level) unknown keys, strict_config=True ->",
          res[0], res[1] if res[0] == "refused" else "BUILT", flush=True)
    print("D   warning text:", (res[2] or "<none>").strip()[:120], flush=True)
    if res[0] == "built":
        m = res[1]
        a = m.get_state_by_id("k.a")
        print("D   'onn' transition reachable:", bool(a.on),
              "-- the declared handler silently vanished", flush=True)


if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
