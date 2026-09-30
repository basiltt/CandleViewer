"""tests/unit/statechart/factory_fixtures/binding_min.py — minimal binding
module for `test_factory.py`'s happy-path fixture (`test.factory_min`)."""

from __future__ import annotations

from candleviewer.statechart.bindings import register_binding_module


async def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _always_true(*_args: object, **_kwargs: object) -> bool:
    return True


ACTIONS = {"noop": _noop}
GUARDS = {"always_true": _always_true}
SERVICES: dict[str, object] = {}

register_binding_module("test.factory_min", __name__)
