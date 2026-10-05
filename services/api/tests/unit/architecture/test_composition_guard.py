"""E49-K01-F4: composition guard for the `unwired-component` defect cluster.

A module that is built but never wired into `create_app()` / the lifespan /
the statechart loader is invisible to its own unit tests. Everything here is
discovered by scanning the package, so a NEW unwired module fails and names
itself. Intentional exceptions live in `composition_allowlist.json` (reason +
ticket per entry); stale entries fail too, so the list can only shrink.

`openapi_pending` is a FROZEN baseline (163 ops; was 169 before main served alerts), ticket
``E49-K01-F4-baseline``. It may only shrink: new entries must carry a real
ticket (``#123`` or ``E12-S03``) and the total may never exceed the baseline,
so to add an operation either serve it or file a ticket and fix the count.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

import candleviewer.statechart.bindings as bindings_pkg
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import (
    PUBLIC_OPERATIONAL_ROUTES,
    declared_operations,
    served_operations,
)
from candleviewer.app import _SUPERVISOR_ORDER, AppContext, create_app
from candleviewer.statechart.registry import Registry

PKG = Path(bindings_pkg.__file__).resolve().parents[2]
API_DIR = PKG / "api"
MAIN_TREE = ast.parse((PKG / "main.py").read_text(encoding="utf-8"))
PENDING_BASELINE = 163
BASELINE_TICKET = "E49-K01-F4-baseline"
REAL_TICKET = re.compile(r"^#\d+$|^E\d\d-[A-Z]\d\d$")
ALLOW: dict[str, dict[str, dict[str, str]]] = json.loads(
    (Path(__file__).with_name("composition_allowlist.json")).read_text(encoding="utf-8")
)


def _allowed(section: str) -> set[str]:
    entries = ALLOW[section]
    for key, meta in entries.items():
        assert meta.get("reason") and meta.get("ticket"), f"{section}:{key} needs reason+ticket"
    return set(entries)


def _started_ctx_modules() -> set[str]:
    """Names X for which main.py contains a real call expression ``ctx.X.start(...)``."""
    out: set[str] = set()
    for node in ast.walk(MAIN_TREE):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "ctx"
        ):
            out.add(node.func.value.attr)
    return out


def _app_state_fetched_in_main() -> set[str]:
    """Names N read via ``getattr(app.state, "N", ...)`` in main.py (when it calls .start())."""
    names: set[str] = set()
    has_start = False
    for node in ast.walk(MAIN_TREE):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "start":
            has_start = True
        f, a = node.func, node.args
        if (
            isinstance(f, ast.Name)
            and f.id == "getattr"
            and len(a) >= 2
            and isinstance(a[0], ast.Attribute)
            and a[0].attr == "state"
            and isinstance(a[0].value, ast.Name)
            and a[0].value.id == "app"
            and isinstance(a[1], ast.Constant)
            and isinstance(a[1].value, str)
        ):
            names.add(a[1].value)
    return names if has_start else set()


@pytest.fixture(scope="module")
def app() -> Any:
    return create_app()


def _endpoint_modules(routes: Any) -> set[str]:
    out: set[str] = set()
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            out |= _endpoint_modules(inner.routes)
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            out.add(endpoint.__module__)
    return out


def _modules_building_routers() -> set[str]:
    found: set[str] = set()
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "APIRouter"
            ):
                found.add(f"candleviewer.api.{path.stem}")
    return found


def test_every_api_router_module_is_included_in_app(app: Any) -> None:
    wired = _endpoint_modules(app.routes)
    unwired = _modules_building_routers() - wired - _allowed("routers")
    msg = f"api modules build an APIRouter but create_app() never includes it: {sorted(unwired)}"
    assert not unwired, msg
    stale = _allowed("routers") & wired
    assert not stale, f"allow-list entries now wired, remove them: {sorted(stale)}"


def test_every_startable_context_module_is_in_supervisor_or_lifespan(app: Any) -> None:
    ctx = app.state.app_context
    order = set(_SUPERVISOR_ORDER)
    names = {f.name for f in dataclasses.fields(AppContext)}
    assert order <= names, f"supervisor lists unknown modules: {sorted(order - names)}"
    started = _started_ctx_modules()
    unstarted = []
    for name in sorted(names - order):
        obj = getattr(ctx, name)
        if callable(getattr(obj, "start", None)) and name not in started:
            unstarted.append(name)
    unstarted = sorted(set(unstarted) - _allowed("context_modules"))
    assert not unstarted, f"AppContext modules never started by Supervisor/lifespan: {unstarted}"


def test_every_app_state_task_is_started_by_lifespan(app: Any) -> None:
    fetched = _app_state_fetched_in_main()
    unstarted = []
    for name, obj in app.state._state.items():
        if name == "app_context" or not callable(getattr(obj, "start", None)):
            continue
        if name not in fetched:
            unstarted.append(f"app.state.{name}")
    unstarted = sorted(set(unstarted) - _allowed("state_tasks"))
    assert not unstarted, f"background components set on app.state but never started: {unstarted}"


def test_every_statechart_binding_module_is_registered() -> None:
    files = sorted(p.stem for p in Path(bindings_pkg.__file__).parent.glob("b[0-9][0-9]_*.py"))
    for stem in files:
        importlib.import_module(f"candleviewer.statechart.bindings.{stem}")
    registered = set(bindings_pkg._MODULE_BY_KEY.values())
    missing = [s for s in files if f"candleviewer.statechart.bindings.{s}" not in registered]
    assert not missing, f"binding modules that never call register_binding_module: {missing}"
    machine_names = {k.split(".")[-1] for k in Registry().keys()}
    no_binding = sorted(machine_names - set(bindings_pkg._MODULE_BY_KEY) - _allowed("machines"))
    assert not no_binding, f"machine JSON contracts with no registered binding: {no_binding}"


def test_openapi_operations_are_served_or_explicitly_pending(app: Any) -> None:
    spec = load_openapi_spec()
    declared = {f"{m} {p}" for m, p in declared_operations(spec)}
    served = {f"{m} {p}" for m, p in served_operations(app)}
    pending = declared - served - _allowed("openapi_pending")
    msg = f"new contract operations neither served nor allow-listed: {sorted(pending)}"
    assert not pending, msg
    stale = _allowed("openapi_pending") & served
    assert not stale, f"now implemented, drop from allow-list: {sorted(stale)}"
    rogue = {op for op in served - declared if op.split(" ", 1)[1] not in PUBLIC_OPERATIONAL_ROUTES}
    assert not rogue, f"served but undeclared operations: {sorted(rogue)}"


def test_openapi_pending_list_is_a_shrinking_baseline() -> None:
    pending = ALLOW["openapi_pending"]
    assert len(pending) <= PENDING_BASELINE, (
        f"openapi_pending grew to {len(pending)} (> {PENDING_BASELINE}): serve the operation "
        "or file a ticket and justify; the baseline may only shrink"
    )
    bad = sorted(
        k
        for k, m in pending.items()
        if m["ticket"] != BASELINE_TICKET and not REAL_TICKET.fullmatch(m["ticket"])
    )
    assert not bad, f"new pending entries need a real ticket (#123 or E12-S03): {bad}"
    baseline = [k for k, m in pending.items() if m["ticket"] == BASELINE_TICKET]
    assert len(baseline) <= PENDING_BASELINE
