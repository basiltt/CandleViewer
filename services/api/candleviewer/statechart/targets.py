"""Absolute-target resolution and rejection (E50-T01 acceptance criterion 2).

Runs before `create_machine` ever sees the chart (belt-and-braces ahead of
the library's own `strictTargets`). Catalogue convention
(28-statechart-catalogue.md §1.5): "targets are written absolutely in the
JSON (`#order.lifecycle.filled`)". This module enforces that convention and
resolves every declared target against the tree of state ids the chart
itself declares, so a typo'd or relative target is a registry-time failure.
"""

from __future__ import annotations

from typing import Any


class TargetFinding:
    """One rejected transition target, path-named for the error message."""

    __slots__ = ("machine", "path", "reason", "target")

    def __init__(self, machine: str, path: str, target: str, reason: str) -> None:
        self.machine = machine
        self.path = path
        self.target = target
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.machine} {self.path}: target {self.target!r} {self.reason}"


def _transition_dicts(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    return [item for item in items if isinstance(item, dict)]


def _collect_state_ids(node: dict[str, Any], prefix: str, out: set[str]) -> None:
    """Every absolute id a state node can be targeted by: `#<machine>` plus
    a dotted path per nesting level, mirroring the library's `#id`/dotted
    resolution (`resolver.py`)."""
    out.add(prefix)
    states = node.get("states")
    if isinstance(states, dict):
        for key, child in states.items():
            if isinstance(child, dict):
                _collect_state_ids(child, f"{prefix}.{key}", out)


def _collect_targets(
    machine: str, path: str, node: dict[str, Any], out: list[tuple[str, str]]
) -> None:
    """Yield `(path, target)` for every transition target in the tree,
    including inline `invoke.src` machines (same CV-C57 descent as keys.py)."""
    on = node.get("on")
    if isinstance(on, dict):
        for event, raw in on.items():
            for t in _transition_dicts(raw):
                target = t.get("target")
                if isinstance(target, str):
                    out.append((f"{path}.on['{event}']", target))
    for t in _transition_dicts(node.get("always")):
        target = t.get("target")
        if isinstance(target, str):
            out.append((f"{path}.always", target))
    after = node.get("after")
    if isinstance(after, dict):
        for delay, raw in after.items():
            for t in _transition_dicts(raw):
                target = t.get("target")
                if isinstance(target, str):
                    out.append((f"{path}.after[{delay!r}]", target))
    for t in _transition_dicts(node.get("onDone")):
        target = t.get("target")
        if isinstance(target, str):
            out.append((f"{path}.onDone", target))
    invoke = node.get("invoke")
    invokes = invoke if isinstance(invoke, list) else [invoke]
    for i, inv in enumerate(invokes):
        if not isinstance(inv, dict):
            continue
        ipath = f"{path}.invoke[{inv.get('id', i)}]"
        for label in ("onDone", "onError"):
            for t in _transition_dicts(inv.get(label)):
                target = t.get("target")
                if isinstance(target, str):
                    out.append((f"{ipath}.{label}", target))
        src = inv.get("src")
        if isinstance(src, dict):
            _collect_targets(machine, f"{ipath}.src", src, out)
    states = node.get("states")
    if isinstance(states, dict):
        for key, child in states.items():
            if isinstance(child, dict):
                _collect_targets(machine, f"{path}.states.{key}", child, out)


def find_target_findings(chart: dict[str, Any]) -> list[TargetFinding]:
    """Reject every relative (`.child`) or unresolvable (`#b01.nope`) target.

    Only absolute `#<id>` targets naming a state that actually exists in
    *chart* are accepted — the catalogue's own convention, enforced here
    rather than left to the library's `strictTargets` runtime check.
    """
    machine_id = str(chart.get("id", "<machine>"))
    known_ids: set[str] = set()
    _collect_state_ids(chart, machine_id, known_ids)

    targets: list[tuple[str, str]] = []
    _collect_targets(machine_id, machine_id, chart, targets)

    findings: list[TargetFinding] = []
    for path, target in targets:
        if not target.startswith("#"):
            findings.append(
                TargetFinding(
                    machine_id,
                    path,
                    target,
                    "is relative — catalogue convention requires an absolute "
                    "'#id' target (28-statechart-catalogue.md §1.5)",
                )
            )
            continue
        resolved = target[1:]
        if resolved not in known_ids:
            findings.append(
                TargetFinding(machine_id, path, target, "does not resolve to any known state")
            )
    return findings
