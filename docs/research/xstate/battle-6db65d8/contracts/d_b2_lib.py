# -*- coding: utf-8 -*-
"""B2 tables shared by the driver and the R6-03 probe."""
from __future__ import annotations
import cv221 as K

C2 = K.cfg("B2")
C3 = K.cfg("B3")


def count(key, d=1):
    def f(i, ctx, e, a):
        ctx[key] = int(ctx.get(key) or 0) + d
    return f


# =========================================================== B2 ============
B2_ACT = {
    "count_open": count("legs_open"),
    "count_failed": count("legs_failed"),
    "count_skipped": count("legs_skipped"),
    "mark_quiesced": lambda i, c, e, a: c.__setitem__("quiesced", True),
}
B2_G_BASE = {
    "all_non_skipped_open": lambda c, e: (
        c["legs_total"] > 0
        and c["legs_open"] + c["legs_skipped"] >= c["legs_total"]),
    "quiesced_and_zero_open": lambda c, e: c["quiesced"] and c["legs_open"] == 0,
    "quiesced_and_some_open": lambda c, e: c["quiesced"] and c["legs_open"] > 0,
    "some_open": lambda c, e: c["legs_open"] > 0,
    "policy_is_abort_on_first": False,
    "policy_all_or_none_and_any_failed": False,
    "unwind_complete": True,
}


def b2_stub(**kw):
    g = dict(B2_G_BASE); g.update(kw.pop("guard_vals", {}) or {})
    a = dict(B2_ACT); a.update(kw.pop("act_impl", {}) or {})
    st = K.Stub(C2, guard_vals=g, act_impl=a, **kw)
    return st


def with_total(n):
    c = K.copy.deepcopy(C2)
    c["context"]["legs_total"] = n
    return c


