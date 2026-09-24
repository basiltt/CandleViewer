"""Force every plain-`def` service in a script into an `async def` service.

Import this module BEFORE the script under test.  It patches
``MachineLogic.__init__`` so that every *callable* service (child-machine
services are left alone) is wrapped in a coroutine function that awaits a
zero-delay sleep and then calls the original.  This exercises the coroutine
publication lane (`_invoke_service_task` -> `_publish_completion`) that the
round-6 suites were structurally blind to.

Usage:
    python -c "import asyncify, runpy; runpy.run_module('s3_fuzz_livelock', run_name='__main__')"
"""

from __future__ import annotations

import asyncio
import functools
import inspect

from xstate_statemachine import machine_logic as _ml


def _wrap(fn):
    if not callable(fn) or inspect.iscoroutinefunction(fn):
        return fn
    if not (inspect.isfunction(fn) or inspect.ismethod(fn) or isinstance(fn, functools.partial)):
        return fn  # e.g. a MachineNode used as an invoked child

    @functools.wraps(fn)
    async def _async(*a, **k):  # noqa: ANN002, ANN003
        await asyncio.sleep(0)
        return fn(*a, **k)

    _async.__xs_asyncified__ = True
    return _async


_orig = _ml.MachineLogic.__init__


@functools.wraps(_orig)
def _patched(self, *a, **k):  # noqa: ANN002, ANN003
    _orig(self, *a, **k)
    try:
        svcs = self.services
    except AttributeError:
        return
    if isinstance(svcs, dict):
        for name, fn in list(svcs.items()):
            svcs[name] = _wrap(fn)


_ml.MachineLogic.__init__ = _patched
print("[asyncify] services forced to async def")
