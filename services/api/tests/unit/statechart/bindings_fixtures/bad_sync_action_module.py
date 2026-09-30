"""An invalid binding module: action registered as plain `def` (CV-C67)."""

from __future__ import annotations


def _sync_action(*_args: object, **_kwargs: object) -> None:
    return None


ACTIONS = {"noop": _sync_action}
GUARDS: dict[str, object] = {}
SERVICES: dict[str, object] = {}
