"""A valid binding module: coroutine actions/services, sync guards."""

from __future__ import annotations


async def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _always_true(*_args: object, **_kwargs: object) -> bool:
    return True


ACTIONS = {"noop": _noop}
GUARDS = {"always_true": _always_true}
SERVICES = {"svc": _noop}
