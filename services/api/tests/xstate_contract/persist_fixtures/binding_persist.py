"""Minimal binding module for `test_persistence.py` (`persist_min`)."""

from __future__ import annotations

from typing import Any

from candleviewer.statechart.bindings import register_binding_module


async def record(_interp: Any, context: dict[str, Any], event: Any, _action: Any) -> None:
    context["seen"] = [*context.get("seen", []), event.payload.get("n")]


ACTIONS = {"record": record}
GUARDS: dict[str, object] = {}
SERVICES: dict[str, object] = {}

register_binding_module("persist_min", __name__)
