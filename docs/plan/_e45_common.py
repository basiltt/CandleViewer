# -*- coding: utf-8 -*-
"""Shared helpers for the E45 backlog generator."""
import json, os

MS = "R4 Live enablement"
PH = "P4 Backtesting & Scripting"
KEYS = ["key","kind","title","labels","component","phase","sprint","priority",
        "perspective","risk","estimate","parent","blocked_by","milestone","body"]

def mk(**kw):
    for k in KEYS:
        assert k in kw, (kw.get("key"), "missing", k)
    assert len(kw) == len(KEYS), (kw.get("key"), "extra keys")
    return kw

def dump(name, tickets):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backlog", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tickets, f, indent=1, ensure_ascii=False)
    print(name, len(tickets))
