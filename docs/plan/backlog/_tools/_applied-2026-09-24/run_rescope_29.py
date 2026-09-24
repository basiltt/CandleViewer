"""Re-scope E29/E32/E33 tickets per docs/plan/29-statechart-adoption-plan.md SS4c/4d.
Run: py -3 backlog/_tools/run_rescope_29.py
"""
import json
import re
from datetime import date

TODAY = date.today().isoformat()
BASE = "."

# key -> (bn, machine_id, file, new_estimate or None)
RESCOPE = {
    "E29-T03": ("B1", "order", "B01.order.machine.json", 3),
    "E29-T04": ("B1", "order", "B01.order.machine.json", None),
    "E29-T05": ("B1", "order", "B01.order.machine.json", None),
    "E29-T06": ("B1", "order", "B01.order.machine.json", None),
    "E29-T08": ("B1", "order", "B01.order.machine.json", 1),
    "E32-T01": ("B8", "position_protection", "B08.position_protection.machine.json", 3),
    "E32-T02": ("B8", "position_protection", "B08.position_protection.machine.json", 1),
    "E32-S01": ("B8/B1", "position_protection", "B08.position_protection.machine.json", 3),
    "E33-T01": ("B4-B7", "algo_supervisor", "B04.oco.machine.json (+B05/B06/B07)", 3),
    "E33-S01": ("B4", "oco", "B04.oco.machine.json", 3),
    "E33-S02": ("B5", "iceberg", "B05.iceberg.machine.json", 3),
    "E33-S03": ("B6", "twap", "B06.twap.machine.json", 3),
    "E33-S04": ("B7", "chase", "B07.chase.machine.json", 3),
    "E33-T02": ("B4-B7", "algo_supervisor", "machines.algo.state", 2),
}

WHY = {
    "E29-T03": "The `frozenset` transition table, `IllegalTransition` and S6 terminal immutability become the chart plus `strict`. S1-S9 bindings, `apply_execution` and the write-ahead `CvAuditPlugin` wiring stay.",
    "E29-T04": "Transport and rounding. It sends via the gateway only.",
    "E29-T05": "Maps pushes to events; `(ts_exec, seq)` ordering stays in bindings (MUSTNOT-04).",
    "E29-T06": "It feeds B19 events; the logic is I/O.",
    "E29-T08": "The detection is the chart's coarse `after:` (>=250 ms tolerant) plus `cv_machine_*` metrics from E50-T60.",
    "E32-T01": "The protection region becomes a chart with the B610-OC-CD03 attempt counter; the choke-point guard stays.",
    "E32-T02": "The watchdog is a chart state plus a coarse `after:`.",
    "E32-S01": "The bracket child lifecycle rides B1 and B8 charts; partial-fill sizing stays.",
    "E33-T01": "The state store and resume come from persistence restore. `MonotonicScheduler` (hard timing) stays in plain code.",
    "E33-S01": "The race and settle logic is chart-defined.",
    "E33-S02": "The tranche lifecycle is in the chart; the release timing is the scheduler.",
    "E33-S03": "Same as S02, with the interval timing on the scheduler.",
    "E33-S04": "The anti-runaway bounds become chart guards; repricing stays on the scheduler.",
    "E33-T02": "The audit events come from `CvAuditPlugin`; the WS projection is `machines.algo.state` (29 SS4d).",
}

EXTRA_BLOCKERS = {
    "E29-T03": ["E50-T59", "E50-S01", "E50-T49"],
    "E29-T04": ["E50-T59", "E50-S01"],
    "E29-T05": ["E50-T59", "E50-S01"],
    "E29-T06": ["E50-T59", "E50-S01"],
    "E29-T08": ["E50-T59", "E50-S01", "E50-T60"],
    "E32-T01": ["E50-T59", "E50-S02"],
    "E32-T02": ["E50-T59", "E50-S02", "E50-T60"],
    "E32-S01": ["E50-T59", "E50-S01", "E50-S02", "E50-T49"],
    "E33-T01": ["E50-T59", "E50-S01", "E50-T49"],
    "E33-S01": ["E50-T59", "E50-S01", "E50-T49"],
    "E33-S02": ["E50-T59", "E50-S02", "E50-T49"],
    "E33-S03": ["E50-T59", "E50-S02", "E50-T49"],
    "E33-S04": ["E50-T59", "E50-S02", "E50-T49"],
    "E33-T02": ["E50-T59", "E50-T60"],
}


def rescope_banner(bn, why):
    return (
        f"> **Re-scoped {TODAY} for full xstate-statemachine adoption (ADR-0016 Accepted):** "
        f"this ticket's lifecycle is now built directly on `xstate-statemachine` 0.9.1 via "
        f"`statechart.factory` from the first line of code (catalogue {bn}). No in-house shim, "
        f"no dual-runtime harness, no hand-rolled state enum/transition table. {why}"
    )


def replace_section(body, heading, new_lines_block, mode="append"):
    """mode='append' adds new_lines_block at end of the section (before next '## ').
    mode='prepend' adds it right after the heading line."""
    pat = re.compile(rf"(^## {re.escape(heading)}\n)", re.M)
    m = pat.search(body)
    if not m:
        raise ValueError(f"heading not found: {heading}")
    start = m.end()
    nxt = body.find("\n## ", start)
    end = nxt if nxt != -1 else len(body)
    section = body[start:end]
    if mode == "prepend":
        new_section = new_lines_block.rstrip("\n") + "\n" + section.lstrip("\n")
    else:
        new_section = section.rstrip("\n") + "\n" + new_lines_block.rstrip("\n") + "\n"
    return body[:start] + new_section + body[end:]


def bn_num(bn):
    m = re.match(r"B(\d+)", bn)
    return m.group(1).zfill(2) if m else bn


def build_scope_bullets(bn, mid, file):
    bnn = bn_num(bn)
    return "\n".join([
        f"- Implement the `{bn}` lifecycle as `statechart/machines/{file}` (committed by E50-S01/S02, hash-locked). Do not hand-write the state enum or transition table.",
        f"- Build it only through `statechart.factory.build('{mid}', lane=...)`, and restore it only through `statechart.persistence.restore`.",
        f"- Write guards, actions and services in `statechart/bindings/{bnn}_{mid}.py` as a `MachineLogic`. Everything is `async def`, and services are idempotent under re-entry.",
        f"- Add `tests/xstate_contract/test_{bnn}_{mid}.py`, which becomes a member of the blocking gate.",
        "- All sends go through `statechart.gateway`.",
    ]) + "\n"


def build_tech_note(bn):
    return (
        f"Normative contract: `28-statechart-catalogue.md` §{bn}.1-.8. Mandatory config: "
        "29-statechart-adoption-plan §1.2 (79-r14 §7 FINAL block). Hot-path parts listed in "
        "29 §3 stay plain code.\n"
    )


def build_test_plan(bn):
    return "\n".join([
        "- Pure-API unit tests of the binding module with a `SimulatedClock`.",
        f"- Contract-suite membership, covering both spellings and every §{bn}.7 invariant.",
        "- A snapshot round-trip (persist->restore) at every quiescence point the ticket introduces, plus a refused restore on a hash or HMAC mismatch.",
    ]) + "\n"


def build_dod():
    return (
        "- [ ] `machine_hash` committed in `machine_hashes.lock`; `tools/lint_statecharts.py` "
        "green; `tests/xstate_contract` green; no import of `xstate_statemachine` outside "
        "`statechart/`.\n"
    )


def strip_legacy_language(body):
    replacements = [
        (r"hand-rolled state machine", "library-backed statechart"),
        (r"enum \+ transition table", "library-backed statechart"),
        (r"\bshim\b", "adopted library"),
        (r"dual-runtime", "single-runtime"),
    ]
    for pat, repl in replacements:
        body = re.sub(pat, repl, body, flags=re.I)
    return body


def process(fname, keys):
    path = f"{BASE}/{fname}"
    with open(path, encoding="utf-8") as f:
        tickets = json.load(f)
    by_key = {t["key"]: t for t in tickets}
    report = []
    for key in keys:
        t = by_key[key]
        bn, mid, file, new_est = RESCOPE[key]
        why = WHY[key]
        old_est = t.get("estimate", 0)
        body = t["body"]
        body = strip_legacy_language(body)
        body = replace_section(body, "Scope / Deliverables", build_scope_bullets(bn, mid, file))
        body = replace_section(body, "Technical notes / design", build_tech_note(bn))
        body = replace_section(body, "Test plan", build_test_plan(bn))
        body = replace_section(body, "Definition of Done", build_dod())
        banner = rescope_banner(bn, why)
        body = banner + "\n\n" + body
        t["body"] = body
        if "statechart" not in t.get("labels", []):
            t.setdefault("labels", []).append("statechart")
        bb = set(t.get("blocked_by") or [])
        bb.update(EXTRA_BLOCKERS.get(key, []))
        t["blocked_by"] = sorted(bb)
        if new_est is not None:
            t["estimate"] = new_est
        report.append((key, old_est, t["estimate"]))
    # recompute epic estimate = sum of children
    epic = [t for t in tickets if t["kind"] == "Epic"][0]
    kids_total = sum(t.get("estimate", 0) for t in tickets if t["kind"] != "Epic")
    old_epic_est = epic.get("estimate")
    epic["estimate"] = kids_total
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return report, old_epic_est, kids_total


if __name__ == "__main__":
    all_reports = {}
    for fname, keys in [
        ("E29.json", ["E29-T03", "E29-T04", "E29-T05", "E29-T06", "E29-T08"]),
        ("E32.json", ["E32-T01", "E32-T02", "E32-S01"]),
        ("E33.json", ["E33-T01", "E33-S01", "E33-S02", "E33-S03", "E33-S04", "E33-T02"]),
    ]:
        rep, old_epic, new_epic = process(fname, keys)
        all_reports[fname] = (rep, old_epic, new_epic)

    for fname, (rep, old_epic, new_epic) in all_reports.items():
        print(f"== {fname} ==")
        for key, old, new in rep:
            print(f"  {key}: {old} -> {new}")
        print(f"  EPIC estimate: {old_epic} -> {new_epic}")

