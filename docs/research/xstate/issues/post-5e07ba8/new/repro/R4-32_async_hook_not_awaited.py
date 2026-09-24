"""R4-32: an `async def` plugin hook override is never awaited by
`_SafePlugin._guarded`, and a contained (swallowed) hook failure has no
programmatic surface.

`_guarded` (base_interpreter.py:238-251) calls `attribute(*args, **kwargs)`
and returns the result -- with no `inspect.iscoroutine`/`iscoroutinefunction`
check. If a user overrides a hook with `async def` (a natural mistake:
`PluginBase`'s hooks are declared `def`, and nothing stops a subclass from
making one async), calling it only produces a coroutine object; the hook
body never executes, and Python emits a "coroutine was never awaited"
RuntimeWarning with no other signal. Separately, when a *synchronous* hook
raises, `_guarded` logs at ERROR and swallows the exception (by design,
for containment) -- but there is no counter, `last_plugin_error`, or other
programmatic surface: an ERROR log line is the only trace, invisible to an
audit/compliance flow that isn't watching logs.

EXPECTED: an async-def hook override either runs its body (properly
awaited) or is rejected at `.use()` time with a clear error; a swallowed
plugin-hook failure is exposed programmatically, not just via a log line.
OBSERVED: the async hook body never executes (execution counter stays 0)
and a "coroutine ... was never awaited" RuntimeWarning fires; a raising
sync hook leaves no programmatic trace besides an ERROR log line.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import warnings

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


class AsyncHook(PluginBase):
    """A natural-looking, but incorrect (async def), hook override."""

    def __init__(self):
        self.ran = 0

    async def on_transition(self, i, f, t, tr):  # noqa: ANN001
        self.ran += 1


class RaisingHook(PluginBase):
    def on_transition(self, i, f, t, tr):  # noqa: ANN001
        raise RuntimeError("audit sink is down")


class _ErrorLogCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.n = 0

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        if "Plugin" in record.getMessage() and "raised in" in record.getMessage():
            self.n += 1


async def main() -> int:
    # --- Part 1: async-def hook is never awaited -----------------------
    async_hook = AsyncHook()
    i1 = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i1.use(async_hook)
    await i1.start()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await asyncio.wait_for(i1.send("GO", wait=True), 5)
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0)
        never_awaited = any(
            "never awaited" in str(w.message) for w in caught
        )
    await i1.stop()

    # --- Part 2: swallowed hook failure has no programmatic surface ----
    cap = _ErrorLogCounter()
    logging.getLogger("xstate_statemachine").addHandler(cap)
    i2 = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i2.use(RaisingHook())
    await i2.start()
    r = await asyncio.wait_for(i2.send("GO", wait=True), 5)
    await asyncio.sleep(0.05)
    logging.getLogger("xstate_statemachine").removeHandler(cap)
    has_last_error_attr = hasattr(i2, "last_plugin_error") or hasattr(
        i2, "plugin_error_count"
    )
    receipt_clean = r.changed and r.error is None
    await i2.stop()

    print(f"async hook body executed: {async_hook.ran}")
    print(f"'never awaited' RuntimeWarning seen: {never_awaited}")
    print(f"ERROR log lines for the raising hook: {cap.n}")
    print(f"receipt reports success despite hook failure: {receipt_clean}")
    print(
        f"interpreter exposes a plugin-error counter/last_plugin_error: "
        f"{has_last_error_attr}"
    )

    defect_present = (
        async_hook.ran == 0
        and never_awaited
        and cap.n > 0
        and receipt_clean
        and not has_last_error_attr
    )
    print(
        "\nOBSERVED:",
        "async hook body never ran (RuntimeWarning only), and a swallowed "
        "hook failure has no programmatic surface"
        if defect_present
        else "hooks were handled correctly",
    )
    print(
        "EXPECTED: async-def hooks run (or are rejected at .use() time), "
        "and swallowed hook failures are exposed programmatically"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
