"""Event-name coverage gate (E50-T05, MUST-10; 29-statechart-adoption-plan.md §1.7).

AST-scans every ``<gateway>.send(key, event)`` / ``.send_threadsafe(key, event)``
call site under ``services/api/candleviewer`` and fails when a *literal* event
name is not declared as a transition event in the target machine's descriptor
(``statechart/machines/BNN.<id>.machine.json``).

Resolution rules (conservative, offline, deterministic):

* machine: a literal key's part before ``:`` (``order:123``); otherwise the
  ``kind=`` the key expression was ``register``-ed under in the same file (or
  the file's sole registered kind). A machine naming no descriptor is a
  finding. Only if unresolvable is the event checked against the union of all
  machines (weakest fallback).
* wrappers: a function forwarding one of its parameters as the event of a send
  (``{"type": event, **p}``), directly or via another wrapper, is detected;
  its call sites with a literal event are checked against the machine the
  wrapper sends to.
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


def _event_node(node: ast.expr) -> ast.expr | None:
    """The expression carrying the event name (the value of ``type`` for dicts)."""
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values, strict=True):
            if _str(k) == "type":
                return v
        return None
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name == "Event":
            if node.args:
                return node.args[0]
            for kw in node.keywords:
                if kw.arg == "type":
                    return kw.value
        return None
    return node


def _event_name(node: ast.expr) -> str | None:
    inner = _event_node(node)
    return _str(inner) if inner is not None else None


def _callee(call: ast.Call) -> str | None:
    fn = call.func
    return fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)


def _is_gateway_send(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in SEND_METHODS
        and len(call.args) >= 2
    )


def _registrations(tree: ast.AST) -> dict[str, str]:
    """``{unparsed key expr: machine kind}`` from ``.register(key, ..., kind=lit)``."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "register"
            and n.args
        ):
            for kw in n.keywords:
                kind = _str(kw.value) if kw.arg == "kind" else None
                if kind is not None:
                    out[ast.unparse(n.args[0])] = kind
    return out


def _machine_for(key: ast.expr, regs: dict[str, str]) -> str | None:
    """Machine id a send key resolves to: literal ``<id>[:inst]``, a key
    expression registered under ``kind=``, else the file's sole registered kind."""
    lit = _str(key)
    if lit is not None:
        return lit.split(":", 1)[0]
    kind = regs.get(ast.unparse(key))
    if kind is None and len(set(regs.values())) == 1:
        kind = next(iter(regs.values()))
    return kind


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    return names[1:] if names and names[0] in ("self", "cls") else names


def _wrappers(trees: dict[str, ast.AST]) -> dict[str, tuple[int, str | None]]:
    """Functions forwarding a *parameter* as the event of a gateway send (directly
    or via another wrapper): ``{name: (call-arg index of the event, machine)}``."""
    found: dict[str, tuple[int, str | None]] = {}
    changed = True
    while changed:
        changed = False
        for tree in trees.values():
            regs = _registrations(tree)
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                params = _params(fn)
                for c in ast.walk(fn):
                    if not isinstance(c, ast.Call):
                        continue
                    callee = _callee(c)
                    if _is_gateway_send(c):
                        ev, machine = (
                            _event_node(c.args[1]),
                            _machine_for(c.args[0], regs),
                        )
                    elif callee in found and len(c.args) > found[callee][0]:
                        idx, machine = found[callee]
                        ev = c.args[idx]
                    else:
                        continue
                    if (
                        isinstance(ev, ast.Name)
                        and ev.id in params
                        and fn.name not in found
                    ):
                        found[fn.name] = (params.index(ev.id), machine)
                        changed = True
    return found


def _sites(
    tree: ast.AST, path: str, wrappers: dict[str, tuple[int, str | None]]
) -> list[Site]:
    regs = _registrations(tree)
    sites: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_gateway_send(node):
            event = _event_name(node.args[1])
            if event is not None:
                sites.append(
                    Site(path, node.lineno, _machine_for(node.args[0], regs), event)
                )
            continue
        callee = _callee(node)
        if callee in wrappers:
            idx, machine = wrappers[callee]
            if len(node.args) > idx and _str(node.args[idx]) is not None:
                sites.append(
                    Site(path, node.lineno, machine, str(_str(node.args[idx])))
                )
    return sites


def scan_source(source: str, path: str) -> list[Site]:
    tree = ast.parse(source, filename=path)
    return _sites(tree, path, _wrappers({path: tree}))


def scan_tree(root: Path = DEFAULT_SCAN) -> list[Site]:
    trees: dict[str, ast.AST] = {}
    for p in sorted(root.rglob("*.py")):
        if p.name in EXCLUDE_NAMES or "__pycache__" in p.parts:
            continue
        trees[p.as_posix()] = ast.parse(
            p.read_text(encoding="utf-8"), filename=p.as_posix()
        )
    wrappers = _wrappers(trees)
    return [s for path, t in trees.items() for s in _sites(t, path, wrappers)]


def check(sites: list[Site], descriptors: dict[str, set[str]]) -> list[str]:
    union = set().union(*descriptors.values()) if descriptors else set()
    findings: list[str] = []
    for s in sites:
        where = f"{s.path}:{s.line}"
        if s.key is None:
            if s.event not in union:
                findings.append(f"{where}: event '{s.event}' is declared by no machine")
            continue
        machine = s.key
        events = descriptors.get(machine)
        if events is None:
            findings.append(f"{where}: unknown machine '{machine}' (event '{s.event}')")
        elif s.event not in events:
            findings.append(
                f"{where}: event '{s.event}' is not declared by machine '{machine}'"
            )
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
