"""An invalid binding module: guard registered as `async def`."""

from __future__ import annotations


async def _async_guard(*_args: object, **_kwargs: object) -> bool:
    return True


ACTIONS: dict[str, object] = {}
GUARDS = {"bad": _async_guard}
SERVICES: dict[str, object] = {}
