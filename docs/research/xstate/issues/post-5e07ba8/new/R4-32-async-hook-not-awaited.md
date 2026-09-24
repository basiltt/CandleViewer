---
r4: R4-32
title: "Bug: async-def plugin hook overrides are never awaited, and swallowed hook failures have no programmatic surface"
labels: [bug, severity/medium, area/plugins]
severity: Medium
repro_script: repro/R4-32_async_hook_not_awaited.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`_SafePlugin._guarded` (the wrapper installed for every plugin hook at
`use()` time) calls a hook attribute and returns its result with no check
for whether that result is a coroutine. `PluginBase`'s hooks are declared
as ordinary `def`, but nothing prevents a subclass from overriding one with
`async def` — a natural mistake for a codebase that is otherwise fully
async (the `Interpreter`/run loop). When that happens, `_guarded` calls the
coroutine function, gets back a coroutine object, and returns/discards it
without awaiting: the hook body never executes, and Python raises a
"coroutine ... was never awaited" `RuntimeWarning` as the only signal.
Separately — and orthogonally — when a *synchronous* hook raises (the
documented, intentional containment case), `_guarded` logs at ERROR and
swallows the exception with no counter or `last_plugin_error`-style
attribute: an ERROR log line is the only trace of a failed plugin hook,
invisible to any monitoring that isn't scraping logs.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Minimal reproduction

```python
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
```

## Observed behaviour

```
async hook body executed: 0
'never awaited' RuntimeWarning seen: True
ERROR log lines for the raising hook: 1
receipt reports success despite hook failure: True
interpreter exposes a plugin-error counter/last_plugin_error: False

OBSERVED: async hook body never ran (RuntimeWarning only), and a swallowed hook failure has no programmatic surface
EXPECTED: async-def hooks run (or are rejected at .use() time), and swallowed hook failures are exposed programmatically
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

XState v5's plugin/observer model (`stately.ai` inspection API,
https://stately.ai/docs/inspection) expects observer callbacks to run
reliably and be a debuggable surface; a callback that silently never
executes, with no error surfaced anywhere but a Python-internal
`RuntimeWarning`, defeats that expectation entirely — the plugin appears
registered and "working" (no exception at `.use()` time, no crash) but
does nothing. Separately, the library's own architecture comment for
`_SafePlugin` (`base_interpreter.py:184-197`) states its purpose is
containment — "Observability must never be able to break the thing it
observes" — but containment without any observable trace beyond a log line
means a compliance/audit-style plugin can fail silently forever with no
way for the hosting application to detect and alert on it.

## Root cause analysis

1. `base_interpreter.py:238-251` (`_SafePlugin._guarded`):
   ```python
   @functools.wraps(attribute)
   def _guarded(*args: Any, **kwargs: Any) -> Any:
       try:
           return attribute(*args, **kwargs)
       except Exception:
           logger.error(...)
           return None
   return _guarded
   ```
   `attribute(*args, **kwargs)` is called synchronously and its return
   value is handed straight back to the (synchronous) dispatch call site.
   For an `async def` override, `attribute(...)` does not run the body —
   it constructs and returns a coroutine object, which `_guarded` then
   discards, and which is dispatched from a synchronous call site (e.g.
   `on_transition` dispatch) with no `await` anywhere in the chain. Nothing
   here inspects `inspect.iscoroutinefunction(attribute)` /
   `asyncio.iscoroutine(result)`.

2. Same block, `except Exception: logger.error(...); return None` — by
   design, contains hook failures so a bad plugin cannot break the
   interpreter (confirmed working correctly for this purpose by
   `battle-5e07ba8/concurrency/e2_plugin_containment_edges.py`'s `v3`
   case: the receipt stays clean, `last_transition_ok` is `True`, and
   `last_error` is `None` — "an ERROR log line is the only trace"). No
   plugin-error counter, `last_plugin_error`, or similar attribute exists
   anywhere on `Interpreter`/`BaseInterpreter` to expose this
   programmatically.

Confirmed by `battle-5e07ba8/concurrency/e2_plugin_containment_edges.py`
(`v2_async_hook`: `async_hook_body_executed: 0` plus the never-awaited
`RuntimeWarning`; `v3_observability`: a raising sync hook leaves the
receipt clean with only 2 ERROR log lines as evidence in that probe's run).

## Impact

**General users:** `PluginBase`'s hooks are declared `def`, so an `async
def` override is partly user error, but it is an easy one to make in an
otherwise fully-async codebase, and the library gives zero feedback that
anything is wrong — no exception, no warning surfaced by the library
itself (only Python's generic GC-time `RuntimeWarning`, easy to miss in
production where warnings are frequently not surfaced). This is the lowest
blast-radius of the plugin-containment findings — no event or state loss —
but an audit/compliance plugin that silently never runs is a real
compliance hole, and a raising hook's failure being invisible outside logs
means monitoring built on interpreter state (not log scraping) cannot
detect a broken observability integration.

**Order-management scenario:** an order-audit plugin mistakenly written as
`async def on_transition(...)` (reasonable, since the rest of the
integration is async) silently never logs a single order transition, with
no signal to the team that their compliance trail has a gap — discovered
only much later, if at all, during an audit. Separately, a metrics-export
hook that starts raising (e.g. after a backend outage) leaves no
interpreter-visible signal to alert on; only an ERROR-level log line, which
may not be monitored the same way interpreter health metrics are.

## Proposed fix

- In `_guarded`, detect a coroutine-function hook at wrap time
  (`inspect.iscoroutinefunction(attribute)`) and either:
  - (a) raise a clear `TypeError` at `.use()` time (fail fast, not at
    first dispatch) telling the caller `PluginBase` hooks must be
    synchronous `def`, not `async def`; or
  - (b) properly schedule/await the coroutine (e.g. via
    `asyncio.ensure_future`/awaiting inline from an async dispatch path)
    if async hooks are meant to be supported going forward — this needs a
    design decision on whether the library wants to allow async hooks.
  Option (a) is the safer minimal fix: it turns silent no-ops into a clear,
  actionable error at registration time.
- Add a plugin-error counter (e.g. `Interpreter.plugin_error_count: int`)
  and/or `Interpreter.last_plugin_error: Optional[BaseException]`,
  incremented/set inside `_guarded`'s `except Exception` branch, so a
  hosting application can poll or assert on it without depending on log
  output.

Compatibility: additive for the counter/attribute; option (a) for
async-def hooks is a minor breaking change for any (currently silently
broken) caller already using an async hook override, but since that
caller's hook never ran anyway, surfacing the error is strictly an
improvement, not a regression in observable behavior.

## Acceptance criteria

- [ ] `repro/R4-32_async_hook_not_awaited.py` exits 0
- [ ] New test `tests/test_plugins.py::test_async_def_hook_override_rejected_or_awaited`
      asserts either a clear error at `.use()` time or that the hook body
      actually executes
- [ ] New test `tests/test_plugins.py::test_plugin_hook_failure_exposed_programmatically`
      asserts a raising hook is visible via a counter/`last_plugin_error`
      attribute, not only a log line

## Related

- R4-16 (same track/caveat noted in the register: these plugin-containment
  findings drive the library through shapes `PluginBase` does not declare
  — its hooks are `def`, and an async override or `CancelledError` from
  user code is not a vanilla-usage path — but the containment expectation
  is still fair since the library documents plugin containment)
- Register source ids: `battle-5e07ba8/concurrency/e2_plugin_containment_edges.py`

## Verification

- Date: 2026-09-19
- Python: 3.13.7
- Commit: `5e07ba8`
- Ran `repro/R4-32_async_hook_not_awaited.py` in a fresh process: output
  matched the Observed behaviour section verbatim; exit code 1.
- Confirmed `base_interpreter.py`'s `_SafePlugin._guarded` calls
  `attribute(*args, **kwargs)` and returns the result with no
  `inspect.iscoroutinefunction`/`asyncio.iscoroutine` check, and that the
  `except Exception: logger.error(...); return None` branch has no
  counter/`last_plugin_error`-style attribute anywhere on
  `Interpreter`/`BaseInterpreter` — matches the cited root cause.
- Fetched the cited XState inspection API doc
  (https://stately.ai/docs/inspection) via web fetch: it documents
  `actor.system.inspect(...)`/observer callbacks as a reliable, debuggable
  hook surface for transitions/events, consistent with the Expected
  behaviour section's characterization — no misrepresentation found.
- No duplicate open/closed GitHub issue found; issue `#37`
  ("cross-thread `send()` silently loses every event — returns an
  un-awaited coroutine with no error") is a related but distinct defect
  (a different code path: cross-thread event dispatch, not plugin hook
  dispatch) and does not duplicate this finding.
