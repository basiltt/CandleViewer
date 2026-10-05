"""Regenerate the E49-K01 root-cause cluster table from a JSON dump of GitHub issues.

Offline by design: reads a dump produced by
``gh issue list --label type/bug --state all --json number,title,labels,state,createdAt,closedAt``
and a human-confirmed assignment file (``clusters.json``). Keyword rules only *propose* a
cluster for unassigned defects (E49-K01 technical notes); confirmed assignments always win.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_PLANNING = re.compile(r"^\[E\d+(-[A-Z]\d+)?\]")
SINGLETON = "singleton"


def is_defect(issue: dict[str, Any]) -> bool:
    """Planning stories/spikes carry a bare ``[E49-S06]`` key; defects have a suffix or none."""
    return _PLANNING.match(str(issue["title"])) is None


def propose(title: str, rules: dict[str, list[str]]) -> str:
    low = title.lower()
    for name, words in rules.items():
        if any(w in low for w in words):
            return name
    return SINGLETON


def assign(
    issues: list[dict[str, Any]],
    confirmed: dict[str, list[int]],
    rules: dict[str, list[str]],
) -> dict[int, str]:
    by_number = {n: name for name, nums in confirmed.items() for n in nums}
    out: dict[int, str] = {}
    for issue in issues:
        if not is_defect(issue):
            continue
        number = int(issue["number"])
        out[number] = by_number.get(number) or propose(str(issue["title"]), rules)
    return out


def build_table(issues: list[dict[str, Any]], assignment: dict[int, str]) -> str:
    state = {int(i["number"]): str(i["state"]).upper() for i in issues}
    groups: dict[str, list[int]] = defaultdict(list)
    for number, name in assignment.items():
        groups[name].append(number)
    open_total = sum(1 for n in assignment if state[n] == "OPEN")
    lines = [
        "| Cluster | Open | Closed | Open share | Open members |",
        "|---|---:|---:|---:|---|",
    ]
    for name in sorted(groups, key=lambda g: (-sum(state[n] == "OPEN" for n in groups[g]), g)):
        nums = sorted(groups[name])
        opened = [n for n in nums if state[n] == "OPEN"]
        share = f"{100 * len(opened) / open_total:.0f}%" if open_total else "n/a"
        members = ", ".join(f"#{n}" for n in opened) or "-"
        lines.append(
            f"| {name} | {len(opened)} | {len(nums) - len(opened)} | {share} | {members} |"
        )
    clustered = sum(1 for n, g in assignment.items() if state[n] == "OPEN" and g != SINGLETON)
    pct = f"{100 * clustered / open_total:.0f}%" if open_total else "n/a"
    lines.append("")
    lines.append(f"Open defects: {open_total}; in a named cluster: {clustered} ({pct}).")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="JSON dump of issues")
    parser.add_argument(
        "--clusters",
        type=Path,
        default=Path(__file__).with_name("clusters.json"),
        help="confirmed assignment + proposal rules",
    )
    args = parser.parse_args(argv)
    issues = json.loads(args.dump.read_text(encoding="utf-8"))
    cfg = json.loads(args.clusters.read_text(encoding="utf-8"))
    table = build_table(issues, assign(issues, cfg["confirmed"], cfg["rules"]))
    print(table, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
