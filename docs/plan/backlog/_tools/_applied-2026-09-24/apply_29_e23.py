import json

new_ticket = {
    "key": "E23-T06",
    "kind": "Chore",
    "title": "Assert CvdEngine/delta aggregation exclusion from the statechart catalogue (CV-LINT-HOTPATH, BENCH-2)",
    "labels": ["type/tech", "area/order-flow", "priority/p2", "statechart"],
    "component": "data-feeds",
    "phase": "P2 Data & Indicators",
    "sprint": "Sprint 11",
    "priority": "P2 Medium",
    "perspective": "Development",
    "risk": "None",
    "estimate": 1,
    "parent": "E23",
    "blocked_by": ["E50-T11", "E23-T01"],
    "milestone": "R2 Order-flow beta",
    "body": (
        "## Context\n"
        "`xstate-statemachine==0.9.1` is adopted completely (ADR-0016 Accepted) for every catalogue "
        "lifecycle B1-B20, but per-tick rule/aggregation evaluation stays plain code: BENCH-2 "
        "measured 381 ev/s against the statechart runtime versus the 2,000 ev/s CVD/delta needs "
        "(`29-statechart-adoption-plan.md` §4d). `CvdEngine` and delta aggregation are explicitly "
        "excluded from the catalogue (§3), and this Chore makes that exclusion a checked invariant "
        "instead of a comment.\n\n"
        "## Scope / Deliverables\n"
        "- A `CV-LINT-HOTPATH` fixture (extending the `tools/lint_statecharts.py` AST lint owned by "
        "`E50-T11`) that fails CI if `CvdEngine`, delta-aggregation modules, or any per-trade "
        "footprint path imports `xstate_statemachine`, `statechart.factory`, or `statechart.gateway`.\n"
        "- A short BENCH-2 note added to the ADR-0017 draft (the CVD/footprint architecture ADR) "
        "recording the 381 ev/s vs 2,000 ev/s measurement as the permanent reason for the exclusion.\n\n"
        "## Out of scope\n"
        "- Re-running BENCH-2 itself - already measured in the xstate battle research; this Chore "
        "only encodes the conclusion as a lint fixture and a doc note.\n"
        "- Any other hot-path exclusion (order book reconstruction, paper matcher) - those get their "
        "own `CV-LINT-HOTPATH` fixture entries under the epics that own them.\n\n"
        "## Acceptance criteria\n"
        "```gherkin\n"
        "Scenario: Lint fails on an accidental statechart import in the hot path\n"
        "  Given a change adds `from candleviewer.statechart import factory` inside CvdEngine\n"
        "  When CV-LINT-HOTPATH runs\n"
        "  Then CI fails with a message naming BENCH-2 as the reason\n"
        "\n"
        "Scenario: Lint passes on the unmodified engine\n"
        "  Given CvdEngine and delta aggregation as implemented in E23-T01\n"
        "  When CV-LINT-HOTPATH runs\n"
        "  Then it passes\n"
        "```\n\n"
        "## Technical notes / design\n"
        "The fixture is an AST walk (same tooling as `E50-T11`'s other lints) over the "
        "`data-feeds`/CVD module tree, denylisting the statechart package paths. It runs in the "
        "same CI job as the other `CV-LINT-*` checks, not as a separate pipeline.\n\n"
        "## Test plan\n"
        "Unit: fixture fires on a synthetic import, fixture is silent on the real tree. CI: wired "
        "into the existing lint job alongside `CV-LINT-IMPORT`/`CV-LINT-REMINT`.\n\n"
        "## Security notes\n"
        "None beyond the general hot-path integrity this Chore protects.\n\n"
        "## Accessibility notes\n"
        "N/A (build-time lint).\n\n"
        "## Performance notes\n"
        "This Chore is the guardrail for the 2,000 ev/s throughput requirement itself: it exists so "
        "the requirement cannot be silently regressed by an in-scope-looking refactor.\n\n"
        "## Observability\n"
        "CI failure output only; no runtime metric.\n\n"
        "## Definition of Done\n"
        "Per `02-definition-of-ready-done.md` §3.2; fixture merged into `tools/lint_statecharts.py` "
        "and green in CI; ADR-0017 draft carries the BENCH-2 note.\n\n"
        "## Dependencies\n"
        "Blocked by **E50-T11** (lint module) and **E23-T01** (the engine it checks).\n\n"
        "## Branch\n"
        "`chore/e23-cvd-hotpath-lint`\n\n"
        "## References\n"
        "`docs/plan/29-statechart-adoption-plan.md` §3, §4d; "
        "`docs/research/xstate/bench/bench_c_timers_v2.py`; `docs/research/xstate/79-r14-final-readiness-verdict.md` §7.\n"
    ),
}

with open("E23.json", encoding="utf-8") as f:
    e23 = json.load(f)

if not any(t["key"] == "E23-T06" for t in e23):
    e23.append(new_ticket)

epic = [t for t in e23 if t["key"] == "E23"][0]
before = epic["estimate"]
children = [t for t in e23 if t.get("parent") == "E23"]
epic["estimate"] = sum(t["estimate"] for t in children)
print("E23 before", before, "after", epic["estimate"])

with open("E23.json", "w", encoding="utf-8") as f:
    json.dump(e23, f, ensure_ascii=False, indent=2)
