"""Event-name coverage gate (E50-T05, MUST-10; 29-statechart-adoption-plan.md §1.7).

AST-scans every ``<gateway>.send(key, event)`` / ``.send_threadsafe(key, event)``
call site under ``services/api/candleviewer`` and fails when a *literal* event
name is not declared as a transition event in the target machine's descriptor
(``statechart/machines/BNN.<id>.machine.json``).

Resolution rules (conservative, offline, deterministic):

* machine key: a string literal, matched on the part before ``:`` (instance
  ids look like ``order:123``) against a machine ``id``. A literal key that
  names no machine is itself a finding. A non-literal key is checked against
  the union of all machines' events.
* event name: a string literal, a ``{"type": "<lit>"}`` dict, or an
  ``Event("<lit>")`` / ``Event(type="<lit>")`` call. Non-literal events cannot
  be checked statically and are skipped.

Exit 0 = clean, 1 = findings, 2 = usage error.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MACHINES = _ROOT / "services/api/candleviewer/statechart/machines"
DEFAULT_SCAN = _ROOT / "services/api/candleviewer"
SEND_METHODS = frozenset({"send", "send_threadsafe"})
#: The gateway implementation itself forwards a variable, never a literal.
EXCLUDE_NAMES = frozenset({"gateway.py"})


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    key: str | None
    event: str


def _walk_events(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "on" and isinstance(v, dict):
                out.update(e for e in v if e != "*" and not e.startswith("xstate."))
            _walk_events(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_events(v, out)


def load_descriptors(machines: Path = DEFAULT_MACHINES) -> dict[str, set[str]]:
    """``{machine id: declared event names}`` from every committed chart."""
    result: dict[str, set[str]] = {}
    for p in sorted(machines.glob("B*.machine.json")):
        chart = json.loads(p.read_text(encoding="utf-8"))
        events: set[str] = set()
        _walk_events(chart, events)
        result[str(chart.get("id", p.name.split(".")[1]))] = events
    return result


def _str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _event_name(node: ast.expr) -> str | None:
    lit = _str(node)
    if lit is not None:
        return lit
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values, strict=True):
            if _str(k) == "type":
                return _str(v)
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name == "Event":
            if node.args:
                return _str(node.args[0])
            for kw in node.keywords:
                if kw.arg == "type":
                    return _str(kw.value)
    return None


def scan_source(source: str, path: str) -> list[Site]:
    sites: list[Site] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in SEND_METHODS
            and len(node.args) >= 2
        ):
            continue
        event = _event_name(node.args[1])
        if event is not None:
            sites.append(Site(path, node.lineno, _str(node.args[0]), event))
    return sites


def scan_tree(root: Path = DEFAULT_SCAN) -> list[Site]:
    sites: list[Site] = []
    for p in sorted(root.rglob("*.py")):
        if p.name in EXCLUDE_NAMES or "__pycache__" in p.parts:
            continue
        sites.extend(scan_source(p.read_text(encoding="utf-8"), p.as_posix()))
    return sites


def check(sites: list[Site], descriptors: dict[str, set[str]]) -> list[str]:
    union = set().union(*descriptors.values()) if descriptors else set()
    findings: list[str] = []
    for s in sites:
        where = f"{s.path}:{s.line}"
        if s.key is None:
            if s.event not in union:
                findings.append(f"{where}: event '{s.event}' is declared by no machine")
            continue
        machine = s.key.split(":", 1)[0]
        events = descriptors.get(machine)
        if events is None:
            findings.append(f"{where}: unknown machine '{machine}' (event '{s.event}')")
        elif s.event not in events:
            findings.append(f"{where}: event '{s.event}' is not declared by machine '{machine}'")
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--machines", type=Path, default=DEFAULT_MACHINES)
    ap.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    args = ap.parse_args(argv)
    if not args.machines.is_dir() or not args.scan.is_dir():
        print("event-coverage: machines/scan directory missing", file=sys.stderr)
        return 2
    descriptors = load_descriptors(args.machines)
    sites = scan_tree(args.scan)
    findings = check(sites, descriptors)
    for f in findings:
        print(f"event-coverage: {f}")
    print(
        f"event-coverage: {len(sites)} call site(s), {len(descriptors)} machine(s), "
        f"{len(findings)} finding(s)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
