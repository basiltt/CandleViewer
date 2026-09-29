"""CV-C57: the registry's own recursive `KNOWN_MACHINE_KEYS` walk (E50-T01).

The upstream `xstate_statemachine.validation` module (round 12, `#220`) added
a recursive unknown-key check over `states` / `on` / `always` / `after` /
`onDone` / `invoke.onDone` / `invoke.onError` — but it does **not** descend
into an inline `invoke.src` machine definition (a `dict` value for `src`
rather than a string service name). That is the one hole the catalogue
records against CV-C57 (28-statechart-catalogue.md §1.3b, "Q-5"): "the
recursion does not descend into an inline-machine `invoke.src`". This module
is the wrapper's own check, re-grounded on exactly that hole, and it
additionally runs stand-alone (no `MachineNode` construction, no
`xstate_statemachine` import at all — CV-LINT-IMPORT) so it can gate
`create_machine` from outside the library.
"""

from __future__ import annotations

import difflib
from typing import Any

#: Keys accepted at every level, never behavioural (mirrors the library's
#: own `_METADATA_KEYS`, kept in lock-step by the fixture suite).
_METADATA_KEYS: frozenset[str] = frozenset({"meta", "description", "tags"})

#: Every key a state node may carry (mirrors library `KNOWN_STATE_KEYS`).
STATE_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "initial",
        "states",
        "type",
        "output",
        "on",
        "entry",
        "exit",
        "after",
        "always",
        "invoke",
        "onDone",
        "history",
        "target",
    }
    | _METADATA_KEYS
)

#: Root adds `context` and the policy keys (mirrors library `KNOWN_ROOT_KEYS`).
ROOT_KEYS: frozenset[str] = STATE_KEYS | frozenset(
    {
        "context",
        "version",
        "actionErrorPolicy",
        "guardErrorPolicy",
        "onUnhandled",
        "maxIterations",
        "spawnBlockingTimeout",
        "strict",
        "strictTargets",
        "strictConfig",
    }
)

#: Back-compat / ticket-literal name (CV-C57 names it `KNOWN_MACHINE_KEYS`).
KNOWN_MACHINE_KEYS: frozenset[str] = ROOT_KEYS

TRANSITION_KEYS: frozenset[str] = (
    frozenset({"target", "actions", "guard", "cond", "internal", "reenter"}) | _METADATA_KEYS
)

INVOKE_KEYS: frozenset[str] = (
    frozenset({"id", "src", "input", "systemId", "onDone", "onError"}) | _METADATA_KEYS
)


class KeyFinding:
    """One path-named unknown-key finding."""

    __slots__ = ("key", "machine", "path", "suggestion")

    def __init__(self, machine: str, path: str, key: str, suggestion: str | None) -> None:
        self.machine = machine
        self.path = path
        self.key = key
        self.suggestion = suggestion

    def __str__(self) -> str:
        hint = f" (did you mean '{self.suggestion}'?)" if self.suggestion else ""
        return f"{self.machine} {self.path}: '{self.key}'{hint}"


def _hints(machine: str, path: str, obj: dict[str, Any], known: frozenset[str]) -> list[KeyFinding]:
    findings: list[KeyFinding] = []
    for key in sorted(obj):
        if not isinstance(key, str) or key in known or key.startswith("x-"):
            continue
        close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.6)
        findings.append(KeyFinding(machine, path, key, close[0] if close else None))
    return findings


def _transition_dicts(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    return [item for item in items if isinstance(item, dict)]


def _walk_transitions(machine: str, path: str, node: dict[str, Any], out: list[KeyFinding]) -> None:
    on = node.get("on")
    if isinstance(on, dict):
        for event, raw in on.items():
            for t in _transition_dicts(raw):
                out.extend(_hints(machine, f"{path}.on['{event}']", t, TRANSITION_KEYS))
    for t in _transition_dicts(node.get("always")):
        out.extend(_hints(machine, f"{path}.always", t, TRANSITION_KEYS))
    after = node.get("after")
    if isinstance(after, dict):
        for delay, raw in after.items():
            for t in _transition_dicts(raw):
                out.extend(_hints(machine, f"{path}.after[{delay!r}]", t, TRANSITION_KEYS))
    for t in _transition_dicts(node.get("onDone")):
        out.extend(_hints(machine, f"{path}.onDone", t, TRANSITION_KEYS))


def _walk_invokes(machine: str, path: str, node: dict[str, Any], out: list[KeyFinding]) -> None:
    """Recurse through `invoke`, including CV-C57's own hole: an inline
    `invoke.src` **machine definition** (a `dict`, not a string service
    name). The upstream library never looks inside it at all; we do."""
    invoke = node.get("invoke")
    invokes = invoke if isinstance(invoke, list) else [invoke]
    for i, inv in enumerate(invokes):
        if not isinstance(inv, dict):
            continue
        ipath = f"{path}.invoke[{inv.get('id', i)}]"
        out.extend(_hints(machine, ipath, inv, INVOKE_KEYS))
        for label in ("onDone", "onError"):
            for t in _transition_dicts(inv.get(label)):
                out.extend(_hints(machine, f"{ipath}.{label}", t, TRANSITION_KEYS))
        src = inv.get("src")
        if isinstance(src, dict):
            # CV-C57: descend into the inline machine as a full state node —
            # the exact gap left open by the upstream recursion (Q-5).
            _walk_node(machine, f"{ipath}.src", src, out, is_root=True)


def _walk_node(
    machine: str,
    path: str,
    node: dict[str, Any],
    out: list[KeyFinding],
    *,
    is_root: bool,
) -> None:
    known = ROOT_KEYS if is_root else STATE_KEYS
    out.extend(_hints(machine, path, node, known))
    _walk_transitions(machine, path, node, out)
    _walk_invokes(machine, path, node, out)
    states = node.get("states")
    if isinstance(states, dict):
        for key, child in states.items():
            if isinstance(child, dict):
                _walk_node(machine, f"{path}.states.{key}", child, out, is_root=False)


def find_unknown_keys(chart: dict[str, Any]) -> list[KeyFinding]:
    """CV-C57: the full recursive `KNOWN_MACHINE_KEYS` walk over *chart*.

    Covers the root, every nested state (including parallel regions), every
    transition body (`on` / `always` / `after` / `onDone`), every `invoke`
    entry's own keys and its `onDone` / `onError`, and — the hole upstream
    leaves open — every inline `invoke.src` machine definition, recursively.
    """
    machine = str(chart.get("id", "<machine>"))
    findings: list[KeyFinding] = []
    _walk_node(machine, machine, chart, findings, is_root=True)
    return findings
