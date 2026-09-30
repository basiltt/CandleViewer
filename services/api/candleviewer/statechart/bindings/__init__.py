"""candleviewer.statechart.bindings — the binding-map loader (E50-T59).

One binding module per catalogue machine, `bindings/b<NN>_<name>.py`,
exposing three plain dicts at module scope:

    ACTIONS:  dict[str, Callable[..., Awaitable[None]]]
    GUARDS:   dict[str, Callable[..., bool]]
    SERVICES: dict[str, Callable[..., Awaitable[Any]]]

`load_binding_maps(machine_key)` imports that module fresh-looked-up and
asserts every action/service callable is `asyncio.iscoroutinefunction`
(CV-C67, CV-LINT-CORO): a plain `def` wrapper around an `async def` drops
the returned coroutine silently (R13-21) — the single most expensive bug
class this catalogue found. Guards stay synchronous by contract (the
library evaluates them inline, never awaited); a guard implemented as
`async def` is rejected for the opposite reason — it would silently never
run either.

This module deliberately never imports `xstate_statemachine` — CV-LINT-
IMPORT only exempts `factory.py`/`persistence.py`. It returns plain dicts;
`factory.py` is the only place a fresh `MachineLogic(strict=True)` is
constructed from them (CV-C18: one spelling per implementation, a fresh
`MachineLogic` per `create_machine()` call).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from typing import Any, NamedTuple

#: `machine_key` (chart `id`, e.g. "B01.order") -> binding module name.
#: Populated as each B01..B20 binding lands; a key with no entry here is a
#: `MachineNotFoundError` at bind time, not an import error.
_MODULE_BY_KEY: dict[str, str] = {}


class BindingLoadError(Exception):
    """Raised when a binding module is missing, malformed, or violates
    CV-C18 / CV-C67 (non-coroutine action/service, async guard)."""


def register_binding_module(machine_key: str, module_name: str) -> None:
    """Called once by each `bindings/b<NN>_<name>.py` module at import
    time, so `load_binding` can resolve `machine_key` -> module without a
    hard-coded switch statement here."""
    _MODULE_BY_KEY[machine_key] = module_name


def _assert_coroutine_functions(label: str, mapping: dict[str, Callable[..., Any]]) -> None:
    for name, fn in mapping.items():
        if not asyncio.iscoroutinefunction(fn):
            raise BindingLoadError(
                f"{label}['{name}'] must be an `async def` registered "
                "directly (CV-C67) — a sync `def` wrapper silently drops "
                "the coroutine and never runs it"
            )


def _assert_sync_guards(mapping: dict[str, Callable[..., Any]]) -> None:
    for name, fn in mapping.items():
        if asyncio.iscoroutinefunction(fn):
            raise BindingLoadError(
                f"guards['{name}'] must be a plain synchronous callable — "
                "the library evaluates guards inline and never awaits them, "
                "so an `async def` guard silently never runs"
            )


class BindingMaps(NamedTuple):
    """Plain-dict output of `load_binding_maps` — no runtime type in sight,
    so this module stays outside CV-LINT-IMPORT's allow-list."""

    actions: dict[str, Callable[..., Any]]
    guards: dict[str, Callable[..., Any]]
    services: dict[str, Callable[..., Any]]


def load_binding_maps(machine_key: str) -> BindingMaps:
    """Import `bindings/b<NN>_<name>.py` for *machine_key* (registered via
    `register_binding_module`) and return its `ACTIONS`/`GUARDS`/`SERVICES`
    dicts, having asserted the CV-C67 coroutine-function shape on each.

    Returns fresh `dict` copies each call (CV-C18: callers build a fresh
    `MachineLogic` from these, never reuse one across `create_machine()`).
    """
    module_name = _MODULE_BY_KEY.get(machine_key)
    if module_name is None:
        raise BindingLoadError(f"no binding module registered for '{machine_key}'")

    module = importlib.import_module(module_name)

    actions: dict[str, Callable[..., Any]] = dict(getattr(module, "ACTIONS", {}))
    guards: dict[str, Callable[..., Any]] = dict(getattr(module, "GUARDS", {}))
    services: dict[str, Callable[..., Any]] = dict(getattr(module, "SERVICES", {}))

    _assert_coroutine_functions("actions", actions)
    _assert_sync_guards(guards)
    _assert_coroutine_functions("services", services)

    return BindingMaps(actions=actions, guards=guards, services=services)
