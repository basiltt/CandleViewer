"""Binding module for `test_plugins.py` (`test.plugins_min`)."""

from __future__ import annotations

from typing import Any

from candleviewer.statechart.bindings import register_binding_module

#: `probe` records the sink length at the moment its body runs, so the
#: write-ahead test can prove the `ahead` row already existed.
PROBE: dict[str, Any] = {"sink": None, "seen": []}


async def _probe(*_args: object, **_kwargs: object) -> None:
    sink = PROBE["sink"]
    PROBE["seen"].append(list(sink.rows) if sink is not None else None)


async def _boom(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("boom")


async def _ping_self(interpreter: Any, *_args: object, **_kwargs: object) -> None:
    interpreter.send("PING")


async def _drop_receipt(interpreter: Any, *_args: object, **_kwargs: object) -> None:
    interpreter.send("NOOP", wait=True)  # receipt deliberately discarded (CV-C69)


ACTIONS = {"probe": _probe, "boom": _boom, "ping_self": _ping_self, "drop_receipt": _drop_receipt}
GUARDS: dict[str, object] = {}
SERVICES: dict[str, object] = {}

register_binding_module("test.plugins_min", __name__)
