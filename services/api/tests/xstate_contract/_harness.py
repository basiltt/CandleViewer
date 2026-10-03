"""tests/xstate_contract/_harness.py — chart-driven contract harness (E50-T31).

The blocking gate (29-statechart-adoption-plan.md §1.7) is generated from the
committed `machines/*.machine.json` contracts, never from a hand-kept list:

* `transition_cases(chart)` enumerates every arm the chart declares — event
  arms under `on` (state and root), `always` arms and invoke `onDone` /
  `onError` arms — with the guard assignment that selects exactly that arm
  (earlier guarded arms denied, the arm's own guard allowed).
* `park(...)` writes a derived copy of the chart to `tmp_path` whose
  `initial` chain points at the source state (arms untouched), then builds
  it through `cv.statechart.factory.build()` only (C-2.19).
* Bindings are replaced per test: guards by the forced assignment, actions
  by recorders, services by a never-completing coroutine (or by a done /
  failing coroutine for the arm under test). Both service spellings of the
  §1.7 matrix are produced by `spell()`.

Business logic stays with the owning epics: this harness checks the chart
contract on the library runtime, not the stub bodies.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import importlib
import inspect
import json
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest
from xstate_statemachine import PluginBase, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.config import Lane
from candleviewer.statechart.factory import BuildResult
from candleviewer.statechart.registry import Registry

Spelling = Literal["async_def", "def_coroutine"]
SPELLINGS: tuple[Spelling, ...] = ("async_def", "def_coroutine")
ArmKind = Literal["on", "always", "onDone", "onError"]

#: Settle budget: yields that let an invoked service complete and its
#: `done.invoke` / `error.platform` event drain (no wall-clock sleeps).
_SETTLE_YIELDS = 64


@dataclass(frozen=True, slots=True)
class TransitionCase:
    """One declared arm: from *source* (dotted path, "" = root) on *event*."""

    machine: str
    source: str
    kind: ArmKind
    event: str
    index: int
    target: str | None
    guards: dict[str, bool] = field(default_factory=dict)
    invoke_src: str | None = None

    @property
    def id(self) -> str:
        where = self.source or "<root>"
        return f"{self.machine}:{where}:{self.kind}:{self.event}[{self.index}]"


def walk(node: dict[str, Any], prefix: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield `(dotted_path, node)` for every descendant state."""
    for name, child in (node.get("states") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        yield path, child
        yield from walk(child, path)


def _arms(spec: Any) -> list[dict[str, Any]]:
    items = spec if isinstance(spec, list) else [spec]
    return [{"target": a} if isinstance(a, str) else dict(a) for a in items]


def _guard_plan(arms: list[dict[str, Any]], index: int) -> dict[str, bool] | None:
    """Guards that select arm *index*: earlier guarded arms False, own True.

    Returns None when the plan is contradictory (the same guard name would
    have to be both True and False) — such an arm is unreachable by guard
    forcing alone and is reported by `test_every_arm_is_drivable`.
    """
    plan: dict[str, bool] = {}
    for arm in arms[:index]:
        if arm.get("guard"):
            plan[str(arm["guard"])] = False
    own = arms[index].get("guard")
    if own:
        if plan.get(str(own)) is False:
            return None
        plan[str(own)] = True
    return plan


def _state_arms(machine: str, path: str, node: dict[str, Any]) -> Iterator[TransitionCase]:
    for event, spec in (node.get("on") or {}).items():
        arms = _arms(spec)
        for i, arm in enumerate(arms):
            plan = _guard_plan(arms, i)
            if plan is not None:
                yield TransitionCase(machine, path, "on", event, i, arm.get("target"), plan)
    if "always" in node:
        arms = _arms(node["always"])
        for i, arm in enumerate(arms):
            plan = _guard_plan(arms, i)
            if plan is not None:
                yield TransitionCase(machine, path, "always", "", i, arm.get("target"), plan)
    inv = node.get("invoke")
    if isinstance(inv, dict):
        for kind in ("onDone", "onError"):
            if kind not in inv:
                continue
            arms = _arms(inv[kind])
            for i, arm in enumerate(arms):
                plan = _guard_plan(arms, i)
                if plan is not None:
                    yield TransitionCase(
                        machine, path, kind, kind, i, arm.get("target"), plan, str(inv["src"])
                    )


def transition_cases(machine: str, chart: dict[str, Any]) -> list[TransitionCase]:
    """Every declared arm of *chart*. Root arms are parked at the first
    quiescence point (a chart initial may `always`-chase into a final)."""
    rest = stable_states(chart)[0]
    cases = [dataclasses.replace(c, source=rest) for c in _state_arms(machine, "", chart)]
    for path, node in walk(chart):
        cases.extend(_state_arms(machine, path, node))
    return cases


def denied_cases(machine: str, chart: dict[str, Any]) -> list[TransitionCase]:
    """Event groups with at least one guarded arm, every guard denied: the
    denial is observable and the event lands on the ordered unguarded
    fall-through (or is deferred) — it never bricks the machine."""
    out: list[TransitionCase] = []
    for path, node in [("", chart), *walk(chart)]:
        for event, spec in (node.get("on") or {}).items():
            arms = _arms(spec)
            guarded = [a for a in arms if a.get("guard")]
            if guarded:
                plan = {str(a["guard"]): False for a in guarded}
                fall = next((a for a in arms if not a.get("guard")), None)
                target = fall.get("target") if fall else None
                out.append(TransitionCase(machine, path, "on", event, -1, target, plan))
    return out


def stable_states(chart: dict[str, Any]) -> list[str]:
    """Leaf, non-final paths without an `always` arm — the quiescence points
    a running machine can rest in. Inside a parallel node each region leaf
    is parked on its own (sibling regions stay at their initial)."""
    out: list[str] = []

    def rec(node: dict[str, Any], prefix: str) -> None:
        for name, child in (node.get("states") or {}).items():
            path = f"{prefix}.{name}" if prefix else name
            if child.get("states"):
                rec(child, path)
            elif child.get("type") != "final" and "always" not in child:
                out.append(path)

    rec(chart, "")
    return out


def all_events(chart: dict[str, Any]) -> set[str]:
    events: set[str] = set()
    for _path, node in [("", chart), *walk(chart)]:
        events.update((node.get("on") or {}).keys())
    return events


# ---------------------------------------------------------------------------
# Binding instrumentation (both §1.7 service spellings)
# ---------------------------------------------------------------------------


def spell(fn: Callable[..., Awaitable[Any]], spelling: Spelling) -> Callable[..., Awaitable[Any]]:
    """Return *fn* as `async def` or as a plain `def` returning a coroutine.

    The `def` spelling is marked with `inspect.markcoroutinefunction` — the
    only way a `def` passes the CV-C67 loader check, and exactly the shape
    the library must await rather than drop (a dropped coroutine surfaces
    as a RuntimeWarning, which the gate runs as an error).
    """
    if spelling == "async_def":

        async def _async(*a: Any, **k: Any) -> Any:
            return await fn(*a, **k)

        return _async

    def _plain(*a: Any, **k: Any) -> Awaitable[Any]:
        return fn(*a, **k)

    return inspect.markcoroutinefunction(_plain)


async def _hang(*_a: object, **_k: object) -> None:
    await asyncio.Event().wait()


async def _done(*_a: object, **_k: object) -> dict[str, Any]:
    return {}


async def _fail(*_a: object, **_k: object) -> None:
    raise RuntimeError("contract-suite forced service failure")


@dataclass
class Instrumented:
    """Recorded action calls for one built machine."""

    actions: list[str] = field(default_factory=list)
    guards: list[tuple[str, bool]] = field(default_factory=list)


def instrument(
    machine: str,
    monkeypatch: pytest.MonkeyPatch,
    spelling: Spelling,
    *,
    guards: dict[str, bool] | None = None,
    service_mode: dict[str, Callable[..., Awaitable[Any]]] | None = None,
) -> Instrumented:
    """Replace the machine's binding maps in place (restored by monkeypatch)."""
    module = importlib.import_module(binding_module(machine))
    rec = Instrumented()
    plan = guards or {}

    def _action(name: str) -> Callable[..., Awaitable[Any]]:
        async def _record(*_a: object, **_k: object) -> None:
            rec.actions.append(name)

        return spell(_record, spelling)

    def _guard(name: str) -> Callable[..., bool]:
        def _decide(*_a: object, **_k: object) -> bool:
            result = plan.get(name, False)
            rec.guards.append((name, result))
            return result

        return _decide

    for name in list(module.ACTIONS):
        monkeypatch.setitem(module.ACTIONS, name, _action(name))
    for name in list(module.GUARDS):
        monkeypatch.setitem(module.GUARDS, name, _guard(name))
    modes = service_mode or {}
    for name in list(module.SERVICES):
        monkeypatch.setitem(module.SERVICES, name, spell(modes.get(name, _hang), spelling))
    return rec


def service_for(case: TransitionCase) -> dict[str, Callable[..., Awaitable[Any]]]:
    if case.invoke_src is None:
        return {}
    return {case.invoke_src: _done if case.kind == "onDone" else _fail}


_BINDINGS_DIR = Path(__file__).resolve().parents[2] / "candleviewer" / "statechart" / "bindings"


def binding_module(machine: str) -> str:
    """`candleviewer.statechart.bindings.bNN_<machine>` (by file name)."""
    hits = sorted(_BINDINGS_DIR.glob(f"b[0-9][0-9]_{machine}.py"))
    if len(hits) != 1:
        raise LookupError(f"no unique binding module for machine '{machine}': {hits}")
    return f"candleviewer.statechart.bindings.{hits[0].stem}"


# ---------------------------------------------------------------------------
# Parking + driving through cv.statechart.factory.build()
# ---------------------------------------------------------------------------

_ORDER = {"trade_group", "leg", "oco", "iceberg", "twap", "chase", "rule_instance", "order"}
_CONTROL = {"kill_switch", "live_gate", "risk_lockout"}


def lane_of(machine: str) -> Lane:
    if machine in _ORDER:
        return "order"
    return "control" if machine in _CONTROL else "platform"


def derive(chart: dict[str, Any], source: str) -> dict[str, Any]:
    """Copy *chart* with `initial` re-pointed along *source* (arms untouched).

    A parallel ancestor has no `initial`; its region is selected by keeping
    the sibling regions at their own initial states."""
    out = copy.deepcopy(chart)
    if not source:
        return out
    node: dict[str, Any] = out
    for part in source.split("."):
        if node.get("type") != "parallel":
            node["initial"] = part
        node = node["states"][part]
    return out


class Charts:
    """Derived-chart registries, validated once per `(machine, source)`.

    Registry construction runs full JSON-Schema validation; doing that per
    test would blow the §1.7 60 s budget. Files live under a session
    `tmp_path_factory` directory (C-13.7: no filesystem outside tmp)."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[tuple[str, str], Registry] = {}

    def registry(self, machine: str, chart: dict[str, Any], source: str) -> Registry:
        key = (machine, source)
        if key not in self._cache:
            d = self._root / f"{machine}__{source.replace('.', '__') or 'root'}"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{machine}.machine.json").write_text(json.dumps(derive(chart, source)), "utf-8")
            self._cache[key] = Registry(machines_dir=d)
        return self._cache[key]


async def park(machine: str, chart: dict[str, Any], source: str, charts: Charts) -> BuildResult:
    """Build *chart* parked at *source* through the factory; `always` arms
    settle exactly as in production."""
    return await build(
        machine,
        clock=SimulatedClock(),
        lane=lane_of(machine),
        registry=charts.registry(machine, chart, source),
        plugins=(AuditTap(),),
    )


async def settle() -> None:
    for _ in range(_SETTLE_YIELDS):
        await asyncio.sleep(0)


class AuditTap(PluginBase[Any]):
    """Collects the observable audit trail the suite asserts against."""

    def __init__(self) -> None:
        self.transitions: list[tuple[str, frozenset[str]]] = []
        self.unhandled: list[str] = []
        self.denied: list[str] = []

    def on_transition(self, interpreter: Any, from_states: Any, to_states: Any, tr: Any) -> None:
        ids = frozenset(str(n.id) for n in to_states)
        self.transitions.append((str(getattr(tr, "event", "")), ids))

    def on_unhandled_event(self, interpreter: Any, event: Any, *_a: Any) -> None:
        self.unhandled.append(str(getattr(event, "type", event)))

    def on_guard_evaluated(self, interpreter: Any, name: str, event: Any, result: bool) -> None:
        if not result:
            self.denied.append(name)


def tap(result: BuildResult) -> AuditTap:
    for p in result.interpreter._plugins:
        inner = getattr(p, "_plugin", p)
        if isinstance(inner, AuditTap):
            return inner
    raise LookupError("AuditTap not attached")


def resolve_target(machine: str, source: str, target: str) -> str:
    """Chart target -> absolute state id (`#id.path` or sibling name)."""
    if target.startswith("#"):
        return target[1:]
    parent = source.rsplit(".", 1)[0] if "." in source else ""
    return f"{machine}.{parent}.{target}" if parent else f"{machine}.{target}"


# ---------------------------------------------------------------------------
# Persist -> restore collaborators (in-memory, deterministic, no I/O)
# ---------------------------------------------------------------------------


class Keys:
    def __init__(self) -> None:
        self._k = {"k1": b"\x07" * 32}

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return self._k[key_id]


class Repo:
    def __init__(self) -> None:
        self.rows: dict[Any, Any] = {}

    async def write_snapshot(self, key: Any, envelope: Any) -> None:
        self.rows[key] = envelope


class Audit:
    def __init__(self) -> None:
        self.quarantined: list[str] = []
        self.refused: list[str] = []

    async def drain_error(self, key: Any, error: str) -> None: ...

    async def persist_refused(self, key: Any, reason: str) -> None:
        self.refused.append(reason)

    async def quarantine(self, key: Any, envelope: Any, reason: str) -> None:
        self.quarantined.append(reason)


class Pager:
    def __init__(self) -> None:
        self.pages: list[str] = []

    async def page(self, key: Any, severity: str, message: str) -> None:
        self.pages.append(severity)


def unhandled_probe(chart: dict[str, Any]) -> tuple[str, str | None]:
    """`(stable_leaf, event)`: a declared event no arm on the leaf's
    ancestry handles (static; parallel siblings rest at their initial).
    `event` is None when the chart is total (every leaf handles every event)."""
    events = all_events(chart)
    for leaf in stable_states(chart):
        node, handled = chart, set((chart.get("on") or {}).keys())
        for part in leaf.split("."):
            node = node["states"][part]
            handled |= set((node.get("on") or {}).keys())
        if chart.get("type") == "parallel":
            own = leaf.split(".")[0]
            for name, region in chart["states"].items():
                cur = region
                while name != own and cur is not None:
                    handled |= set((cur.get("on") or {}).keys())
                    init = cur.get("initial")
                    cur = cur["states"][init] if init else None
        rest = sorted(events - handled)
        if rest:
            return leaf, rest[0]
    return stable_states(chart)[0], None  # total chart: nothing can go unhandled


# ---------------------------------------------------------------------------
# Structural invariant helpers (chart-provable halves of §Bn.7)
# ---------------------------------------------------------------------------


def node_at(chart: dict[str, Any], path: str) -> dict[str, Any]:
    node = chart
    for part in path.split("."):
        node = node["states"][part]
    return node


def find_state(chart: dict[str, Any], name: str) -> str:
    """Dotted path of the unique state called *name*."""
    hits = [p for p, _n in walk(chart) if p.rsplit(".", 1)[-1] == name]
    if len(hits) != 1:
        raise LookupError(f"{chart['id']}: state '{name}' matches {hits}")
    return hits[0]


def exits(chart: dict[str, Any], path: str) -> list[tuple[str, str | None, str | None]]:
    """`(event, guard, target)` for every arm declared ON the state at
    *path* (not ancestors) whose target leaves it."""
    node = node_at(chart, path)
    me = f"{chart['id']}.{path}"
    out: list[tuple[str, str | None, str | None]] = []
    groups = list((node.get("on") or {}).items())
    if "always" in node:
        groups.append(("always", node["always"]))
    inv = node.get("invoke")
    if isinstance(inv, dict):
        groups += [(k, inv[k]) for k in ("onDone", "onError") if k in inv]
    for event, spec in groups:
        for arm in _arms(spec):
            tgt = arm.get("target")
            if tgt is None:
                continue
            absolute = resolve_target(str(chart["id"]), path, str(tgt))
            if absolute != me and not absolute.startswith(me + "."):
                out.append((event, arm.get("guard"), absolute))
    return out


def is_terminal(chart: dict[str, Any], path: str) -> bool:
    """Final, or no arm on the state leaves it."""
    node = node_at(chart, path)
    return node.get("type") == "final" or not exits(chart, path)


def entry_of(chart: dict[str, Any], path: str) -> list[str]:
    raw = node_at(chart, path).get("entry") or []
    return [str(a if isinstance(a, str) else a.get("type")) for a in raw]
