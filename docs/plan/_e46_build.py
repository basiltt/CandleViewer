# -*- coding: utf-8 -*-
import json, os, importlib
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backlog", "E46.json")
import _e46_gen  # writes epic + D01 D02 K01
base = json.load(open(OUT, encoding="utf-8"))
tickets = list(base)
for mod in ("_e46_eng1", "_e46_eng2", "_e46_stories", "_e46_qa", "_e46_sec"):
    tickets.extend(importlib.import_module(mod).tickets)
order = {"Epic":0,"D":1,"K":2,"S":3,"T":4,"Q":5,"X":6}
def sk(t):
    if t["key"] == "E46": return (0, "")
    return (order.get(t["key"][4], 9), t["key"])
tickets.sort(key=sk)
# epic estimate = sum of children
epic = tickets[0]
epic["estimate"] = sum(t["estimate"] for t in tickets[1:])
json.dump(tickets, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
keys = {t["key"] for t in tickets}
assert len(keys) == len(tickets), "dup keys"
eng = sum(t["estimate"] for t in tickets[1:] if not ({"design","qa","security"} & set(t["labels"])))
print("tickets:", len(tickets), "total:", epic["estimate"], "engineering:", eng)
for t in tickets[1:]:
    for b in t["blocked_by"]:
        if b.startswith("E46") and b not in keys: print("BAD DEP", t["key"], b)
