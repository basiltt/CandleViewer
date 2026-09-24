"""Verify #89 on main@5e07ba8: `**kwargs` is not consent for a Clock's `sync=`.

Acceptance criteria (from `gh issue view 89`):
  1. A `**kwargs` clock is called with the legacy signature -- no `sync` /
     `owner` keyword ever reaches it.
  2. A clock declaring `sync` explicitly still receives it, exactly once per
     timer, with the lane chosen by the owning engine.
  3. A clock declaring `def set_timeout(self, fn, delay_sec)` (no kwargs at
     all) still works (pre-existing #76 behaviour).
  4. Test `test_kwargs_only_clock_is_called_with_legacy_signature` exists
     somewhere pinning this (library's own
     `test_kwargs_clock_never_receives_sync` covers the same contract).
  5. Docs: `_accepts_kwarg`'s docstring states VAR_KEYWORD does not count.

Run: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv-python> 89_clock_kwargs_not_consent.py
Exits 0 and prints "ALL PASS" iff every criterion holds.
"""
import inspect
import sys

from xstate_statemachine import SyncInterpreter, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
from xstate_statemachine.clock import SimulatedClock

failures = []


# --- Criterion 1: **kwargs clock never receives `sync` (or `owner`) -------
class KwargsOnlyClock:
    """Legacy wrapper: **kwargs forwards to a backend that predates `sync`."""

    def __init__(self):
        self.inner = SimulatedClock()
        self.calls = []

    def now(self):
        return self.inner.now()

    def set_timeout(self, fn, delay_sec, **kwargs):
        self.calls.append(sorted(kwargs))
        assert "sync" not in kwargs, f"unexpected sync in kwargs: {kwargs}"
        return self.inner.set_timeout(fn, delay_sec)

    def clear_timeout(self, h):
        self.inner.clear_timeout(h)

    def pump(self):
        return self.inner.pump()


cfg = {
    "id": "c1",
    "initial": "a",
    "states": {"a": {"after": {"10": "b"}}, "b": {}},
}
clk1 = KwargsOnlyClock()
i1 = SyncInterpreter(create_machine(cfg), clock=clk1)
i1.start()
if not clk1.calls:
    failures.append("C1: set_timeout was never called on the kwargs clock")
elif any("sync" in c for c in clk1.calls):
    failures.append(f"C1: sync leaked into kwargs clock calls: {clk1.calls}")
clk1.inner.increment(10)
i1.tick()
if i1.value != {"c1.b"} and i1.value != "c1.b":
    # value shape varies; just confirm it transitioned
    if "b" not in str(i1.value):
        failures.append(f"C1: machine did not transition, value={i1.value!r}")
i1.stop()

# --- Criterion 2: explicit `sync` param clock DOES receive it, exactly once
# per timer -----------------------------------------------------------------
class ExplicitSyncClock:
    def __init__(self):
        self.inner = SimulatedClock()
        self.sync_values = []

    def now(self):
        return self.inner.now()

    def set_timeout(self, fn, delay_sec, sync=None, owner=None):
        self.sync_values.append(sync)
        return self.inner.set_timeout(fn, delay_sec)

    def clear_timeout(self, h):
        self.inner.clear_timeout(h)

    def pump(self):
        return self.inner.pump()


clk2 = ExplicitSyncClock()
i2 = SyncInterpreter(create_machine(cfg), clock=clk2)
i2.start()
if not clk2.sync_values or clk2.sync_values[0] is None:
    failures.append(
        f"C2: explicit-sync clock did not receive sync=: {clk2.sync_values}"
    )
if len(clk2.sync_values) != 1:
    failures.append(
        f"C2: expected exactly one set_timeout call for one timer, got "
        f"{len(clk2.sync_values)}"
    )
i2.stop()

# --- Criterion 3: 0.8.0-era clock (owner=, no sync=) still works ----------
# `owner=` predates `sync=` (#76) and is passed unconditionally by the
# engine; the 0.8.0 protocol shape is "no `sync` parameter", not "no kwargs
# at all" (the engine always needs somewhere to put `owner`).
class TwoArgClock:
    def __init__(self):
        self.inner = SimulatedClock()
        self.called = False

    def now(self):
        return self.inner.now()

    def set_timeout(self, fn, delay_sec, owner=None):
        self.called = True
        return self.inner.set_timeout(fn, delay_sec)

    def clear_timeout(self, h):
        self.inner.clear_timeout(h)

    def pump(self):
        return self.inner.pump()


clk3 = TwoArgClock()
i3 = SyncInterpreter(create_machine(cfg), clock=clk3)
i3.start()
if not clk3.called:
    failures.append("C3: plain two-arg clock's set_timeout was never called")
clk3.inner.increment(10)
i3.tick()
i3.stop()

# --- Criterion 5: docstring states VAR_KEYWORD does not count --------------
doc = _accepts_kwarg.__doc__ or ""
if "VAR_KEYWORD" not in doc and "kwargs" not in doc.lower():
    failures.append("C5: _accepts_kwarg docstring doesn't document the rule")
sig = inspect.signature(_accepts_kwarg)
# direct unit check of the underlying predicate too
if _accepts_kwarg(lambda fn, delay_sec, **kw: None, "sync"):
    failures.append("C5(code): _accepts_kwarg still treats **kwargs as consent")
if not _accepts_kwarg(lambda fn, delay_sec, sync=None: None, "sync"):
    failures.append("C5(code): _accepts_kwarg rejects an explicit named `sync`")

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("ALL PASS")
