import json

with open("E42.json", encoding="utf-8") as f:
    e42 = json.load(f)

for t in e42:
    if t["key"] == "E42-D05":
        t["body"] = t["body"].replace(
            "## Scope / Deliverables\n",
            "## Scope / Deliverables\n"
            "- Design pass for the E42-S08 statechart inspector screen (machine list, state "
            "diagram, event timeline, latch-acknowledge control), reusing this ticket's "
            "operations-screen visual language rather than a separate design track.\n",
            1,
        )
    if t["key"] == "E42-Q01":
        t["body"] = t["body"].replace(
            "## Scope / Deliverables\n",
            "## Scope / Deliverables\n"
            "- Black-box test plan and fixtures for E42-T07 (statechart inspector read API) and "
            "E42-S08 (inspector screen), including a seeded chain_trips-degraded machine fixture "
            "for the latch-acknowledge scenario.\n",
            1,
        )
    if t["key"] == "E42-Q04":
        t["body"] = t["body"].replace(
            "## Scope / Deliverables\n",
            "## Scope / Deliverables\n"
            "- Exploratory charter and regression-pack entry for the E42-S08 statechart inspector "
            "screen, covering the latch-acknowledge step-up gate.\n",
            1,
        )

epic = [t for t in e42 if t["key"] == "E42"][0]
before = epic["estimate"]
children = [t for t in e42 if t.get("parent") == "E42"]
epic["estimate"] = sum(t["estimate"] for t in children)
print("E42 before", before, "after", epic["estimate"])

with open("E42.json", "w", encoding="utf-8") as f:
    json.dump(e42, f, ensure_ascii=False, indent=2)
