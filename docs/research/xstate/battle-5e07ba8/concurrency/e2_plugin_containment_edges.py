"""(e) Residual edges of the `_SafePlugin` containment wrapper.

e1 establishes the headline answer: every one of the 10 hooks tested can
raise and the machine is unharmed -- transition commits, configuration
stays at exactly one leaf, `status` stays `running`, the next event works,
and a second plugin registered after the exploder still gets every
callback. That is not luck: `use()` (base_interpreter.py:917) wraps every
plugin in `_SafePlugin` (base_interpreter.py:184-252), whose `__getattr__`
returns a `_guarded` closure that catches `Exception`, logs with
`exc_info=True` and returns `None`. Containment is at the registration
boundary, so no dispatch site can forget it. This is good engineering.

This probe tests what the wrapper does NOT cover:

  V1  `BaseException` (KeyboardInterrupt / SystemExit / MemoryError /
      asyncio.CancelledError) from a hook -- `_guarded` catches `Exception`
      only, deliberately, but it is worth knowing which of those escape and
      where they land.
  V2  an `async def` hook: `_guarded` calls it and discards the returned
      coroutine, which is never awaited. Is the body ever run? Is the
      "never awaited" RuntimeWarning raised?
  V3  is a swallowed hook failure visible ANYWHERE programmatically --
      `last_error`, a counter, a hook-of-last-resort -- or is a log line at
      ERROR the only trace?
  V4  a hook that MUTATES the machine it observes (context, send) rather
      than raising.
  V5  a hook that blocks the loop (time.sleep) -- charged to the run loop.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
import warnings

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "context": {"n": 0, "tampered": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"BACK": {"target": "a"}, "GO": {"actions": ["bump"]}}},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


def machine():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


class _LogCount(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.n = 0
        self.msgs: list[str] = []

    def emit(self, record):  # noqa: A003
        m = record.getMessage()
        if "Plugin" in m and "raised in" in m:
            self.n += 1
            self.msgs.append(m[:120])


async def v1_baseexception(exc_cls) -> dict:
    class BadBase(PluginBase):
        def on_transition(self, i, f, t, tr):  # noqa: ANN001
            raise exc_cls("from a plugin hook")

    i = Interpreter(machine())
    i.use(BadBase())
    await i.start()
    caught = None
    try:
        r = await asyncio.wait_for(i.send("GO", wait=True), 5)
        receipt = (r.changed, repr(r.error))
    except BaseException as exc:  # noqa: BLE001
        caught = f"{type(exc).__name__}: {exc}"
        receipt = None
    await asyncio.sleep(0.05)
    out = {
        "exception": exc_cls.__name__,
        "escaped_to_caller": caught,
        "receipt": receipt,
        "states": sorted(i.current_state_ids),
        "status": i.status,
        "context_n": i.context["n"],
    }
    # A machine whose loop died may hang on stop(); bound it.
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as exc:  # noqa: BLE001
        out["stop_error"] = f"{type(exc).__name__}: {exc}"
    except asyncio.TimeoutError:
        out["stop_error"] = "stop() timed out"
    return out


async def v2_async_hook() -> dict:
    ran = {"v": 0}

    class AsyncHook(PluginBase):
        async def on_transition(self, i, f, t, tr):  # noqa: ANN001
            ran["v"] += 1

    i = Interpreter(machine())
    i.use(AsyncHook())
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await asyncio.wait_for(i.send("GO", wait=True), 5)
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0)
        msgs = sorted({str(x.message) for x in w})
    await i.stop()
    return {
        "async_hook_body_executed": ran["v"],
        "warnings": msgs,
        "note": "_guarded calls the hook and discards its return value.",
    }


async def v3_observability() -> dict:
    cap = _LogCount()
    logging.getLogger("xstate_statemachine.base_interpreter").addHandler(cap)
    logging.getLogger("xstate_statemachine").addHandler(cap)

    class Bad(PluginBase):
        def on_transition(self, i, f, t, tr):  # noqa: ANN001
            raise RuntimeError("audit sink is down")

    i = Interpreter(machine())
    i.use(Bad())
    await i.start()
    r = await asyncio.wait_for(i.send("GO", wait=True), 5)
    await asyncio.sleep(0.05)
    out = {
        "receipt_changed": r.changed,
        "receipt_error": repr(r.error),
        "last_transition_ok": i.last_transition_ok,
        "last_error": repr(i.last_error),
        "error_log_lines": cap.n,
        "log_sample": cap.msgs[:2],
        "programmatic_surface": (
            "none found: receipt clean, last_transition_ok True, "
            "last_error None -- an ERROR log line is the only trace"
        ),
    }
    await i.stop()
    logging.getLogger("xstate_statemachine.base_interpreter").removeHandler(cap)
    logging.getLogger("xstate_statemachine").removeHandler(cap)
    return out


async def v4_mutating_hook() -> dict:
    class Meddler(PluginBase):
        def on_transition(self, i, f, t, tr):  # noqa: ANN001
            i.context["tampered"] += 1  # an observer writing to context
            i.send("GO")  # an observer injecting an event

    i = Interpreter(machine())
    i.use(Meddler())
    await i.start()
    try:
        r = await asyncio.wait_for(i.send("GO", wait=True), 5)
        receipt = (r.changed, repr(r.error))
        timed_out = False
    except asyncio.TimeoutError:
        receipt = None
        timed_out = True
    await asyncio.sleep(0.2)
    out = {
        "timed_out": timed_out,
        "receipt": receipt,
        "context": dict(i.context),
        "states": sorted(i.current_state_ids),
        "status": i.status,
        "queue_depth": i.queue_depth,
    }
    try:
        await asyncio.wait_for(i.stop(), 5)
    except asyncio.TimeoutError:
        out["stop_error"] = "stop() timed out"
    return out


async def v5_blocking_hook() -> dict:
    class Blocker(PluginBase):
        def on_transition(self, i, f, t, tr):  # noqa: ANN001
            time.sleep(0.05)  # a synchronous metrics push

    i = Interpreter(machine())
    i.use(Blocker())
    await i.start()
    gaps = []
    stop = {"v": False}

    async def sampler():
        last = time.perf_counter()
        while not stop["v"]:
            await asyncio.sleep(0)
            now = time.perf_counter()
            gaps.append((now - last) * 1000)
            last = now

    s = asyncio.create_task(sampler())
    for _ in range(5):
        await asyncio.wait_for(i.send("GO", wait=True), 5)
        await asyncio.wait_for(i.send("BACK", wait=True), 5)
    stop["v"] = True
    await s
    await i.stop()
    return {
        "max_loop_stall_ms": round(max(gaps), 2) if gaps else None,
        "hook_sleep_ms": 50,
        "note": "a synchronous plugin hook is charged to the run-loop task",
    }


async def main():
    # V1 runs in e3_baseexception_case.py, one case per process: the first
    # BaseException kills the run loop (and for KeyboardInterrupt/SystemExit
    # the interpreter process itself), so the cases cannot share a loop.
    res = {
        "v1_baseexception": "see e3_baseexception_case.py (one case per process)"
    }
    res["v2_async_hook"] = await v2_async_hook()
    res["v3_observability"] = await v3_observability()
    res["v4_mutating_hook"] = await v4_mutating_hook()
    res["v5_blocking_hook"] = await v5_blocking_hook()
    emit("e2_plugin_containment_edges", res)


if __name__ == "__main__":
    asyncio.run(main())
