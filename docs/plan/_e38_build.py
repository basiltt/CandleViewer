# -*- coding: utf-8 -*-
import json, re
import _e38_epic, _e38_design, _e38_eng1, _e38_eng2, _e38_eng3, _e38_qa_sec
from _e38_gen import T

order = {"Epic": 0, "Spike": 1, "Task": 2, "Story": 2, "Chore": 3}
epic = [x for x in T if x["key"] == "E38"]
rest = sorted([x for x in T if x["key"] != "E38"], key=lambda x: x["key"])
out = epic + rest
assert len(epic) == 1

keys = {x["key"] for x in out}
KINDS = {"Epic", "Story", "Task", "Spike", "Bug", "Chore"}
COMPONENTS = {"chart-engine", "data-feeds", "indicators", "drawing-tools", "alerts", "backtesting",
              "scripting", "web", "api", "auth", "collaboration", "infra", "docs", "cross-cutting"}
PRI = {"P0 Critical", "P1 High", "P2 Medium", "P3 Low"}
PERSP = {"Product", "Architecture", "Development", "Test", "QA", "Security", "Compliance", "Ops"}
SECTIONS = ["## Context", "## Scope / Deliverables", "## Out of scope", "## Acceptance criteria",
            "## Technical notes / design", "## Test plan", "## Security notes",
            "## Accessibility notes", "## Performance notes", "## Observability",
            "## Definition of Done", "## Dependencies", "## Branch", "## References"]

seen = set()
for x in out:
    k = x["key"]
    assert k not in seen, k
    seen.add(k)
    assert x["kind"] in KINDS, k
    assert x["component"] in COMPONENTS, (k, x["component"])
    assert x["priority"] in PRI, k
    assert x["perspective"] in PERSP, k
    assert x["estimate"] in (1, 2, 3, 5, 8) or k == "E38", (k, x["estimate"])
    assert len(x["title"]) <= 80, k
    assert x["phase"] == "P3 Drawing & Alerts"
    assert x["milestone"] == "R3 Trading on demo"
    assert re.fullmatch(r"Sprint (1[4-9])", x["sprint"]), (k, x["sprint"])
    assert x["parent"] == (None if k == "E38" else "E38"), k
    assert any(l.startswith("priority/") for l in x["labels"]), k
    assert "area/paper-trading" in x["labels"], k
    for s in SECTIONS:
        assert s in x["body"], (k, s)
    for b in x["blocked_by"]:
        assert b in keys or re.fullmatch(r"E\d{2}(-[A-Z]\d{2})?", b), (k, b)
        assert b != k

# no self-epic dep, dependency sprints ordered for intra-epic links
sp = {x["key"]: int(x["sprint"].split()[1]) for x in out}
for x in out:
    if x["key"] == "E38":
        continue
    for b in x["blocked_by"]:
        if b in sp and b != "E38":
            assert sp[b] <= sp[x["key"]], (x["key"], b, sp[b], sp[x["key"]])

eng = sum(x["estimate"] for x in out if x["key"] != "E38" and x["key"][4] in "STK")
tot = sum(x["estimate"] for x in out if x["key"] != "E38")
assert out[0]["estimate"] == tot, (out[0]["estimate"], tot)

p = r"C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/plan/backlog/E38.json"
with open(p, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print("tickets", len(out), "eng pts", eng, "total pts", tot)
byk = {}
for x in out:
    byk[x["kind"]] = byk.get(x["kind"], 0) + 1
print(byk)
