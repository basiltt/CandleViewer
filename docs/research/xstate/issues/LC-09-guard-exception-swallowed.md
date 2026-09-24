---
lc: LC-09
title: "Improvement: A guard that raises is swallowed as `False` and is invisible to every observer"
labels: [enhancement, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-09_guard-exception-swallowed.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

When a guard predicate raises, the interpreter catches the exception and evaluates the guard as `False`. This is documented and defensible in isolation — but it makes a *crashing* guard and a *legitimately-failing* guard completely indistinguishable, including to plugins: `on_guard_evaluated` reports `result=False` in both cases, and there is no `on_guard_error` hook. In an `or`-style guard array (`[{target: primary, guard: risk_ok}, {target: fallback}]`) the crash therefore falls through to the permissive branch with no signal anywhere except an `logger.exception` line.

We are not asking for the default to change. We are asking for the failure to be **distinguishable** — via a `guard_error_policy` option and, at minimum, a plugin hook.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local editable install (`pip install -e .`)
- Python: 3.13.7 (CPython, MSC v.1944 64-bit)
- OS: Windows 11
- Interpreter under test: `xstate_statemachine.interpreter.Interpreter` (async), with a `PluginBase` subclass observing `on_guard_evaluated`

## Minimal reproduction

```python
"""LC-09 repro: a guard that raises is swallowed and reported as `False`.

A crashing risk check and a legitimately-failing risk check are indistinguishable
to every observer: same selected transition, no exception, and the plugin hook
`on_guard_evaluated` reports result=False in both cases. There is no
`on_guard_error` hook, so the defect is invisible.
"""

import asyncio
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.plugins import PluginBase


class GuardSpy(PluginBase):
    def __init__(self) -> None:
        self.seen = []

    def on_guard_evaluated(self, interpreter, guard_type, event, result):  # noqa: ANN001
        self.seen.append((guard_type, result))


def build(guard_fn):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": [
                        {"target": "primary", "guard": "risk_ok"},
                        {"target": "fallback"},
                    ]
                }
            },
            "primary": {},
            "fallback": {},
        },
    }
    return create_machine(cfg, logic=MachineLogic(guards={"risk_ok": guard_fn}))


async def run(guard_fn):
    spy = GuardSpy()
    interp = Interpreter(build(guard_fn))
    interp.use(spy)
    await interp.start()
    raised = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    out = {"state": sorted(interp.current_state_ids), "raised": raised, "plugin": spy.seen}
    await interp.stop()
    return out


async def main() -> int:
    def falsy(c, e):  # noqa: ANN001
        return False

    def boom(c, e):  # noqa: ANN001
        raise ValueError("risk service unreachable")

    a = await run(falsy)
    b = await run(boom)
    print(f"OBSERVED: guard returns False -> {a}")
    print(f"OBSERVED: guard RAISES       -> {b}")
    print("EXPECTED: the two cases are distinguishable (raise, or on_guard_error hook)")
    ok = a != b
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

Verbatim output (exit code 1):

```
OBSERVED: guard returns False -> {'state': ['m.fallback'], 'raised': None, 'plugin': [('risk_ok', False)]}
OBSERVED: guard RAISES       -> {'state': ['m.fallback'], 'raised': None, 'plugin': [('risk_ok', False)]}
EXPECTED: the two cases are distinguishable (raise, or on_guard_error hook)
RESULT: FAIL
```

The two dictionaries are byte-identical. Every programmatically accessible surface — resulting state, exception, and the plugin's view of the evaluation — is the same whether the guard returned `False` or raised `ValueError("risk service unreachable")`. The only difference is a `logger.exception` line on the `xstate_statemachine` logger, which carries no structured event a metrics pipeline can alert on.

Corroborating observations:

- The swallow itself is the *documented* behaviour (see the architecture comment quoted below), so this is filed as an Improvement rather than a Bug: the ask is observability and a policy knob, not a change of default.
- The related effect for actions: `on_transition` fires as a *success* even when the transition's actions raised, so a failed action is equally indistinguishable from a clean one.

## Expected behaviour

XState v5 — https://stately.ai/docs/guards — treats a guard as a predicate and does not define exception-swallowing:

> Guards should be pure, synchronous functions that return either `true` or `false`.

**Verified empirically against XState 5.33.0** (Node 20.14.0) with the exact analogue of the repro config — a guard array whose first guard throws:

```js
const m = createMachine({ id:'m', initial:'s', states:{
  s:{ on:{ GO:[ { target:'primary', guard:()=>{ throw new Error('boom') } },
                { target:'fallback' } ] } }, primary:{}, fallback:{} } });
const a = createActor(m);
a.subscribe({ error: (e) => console.log('actor error:', e.message) });
a.start(); a.send({ type:'GO' });
console.log(a.getSnapshot().value, a.getSnapshot().status);
```

```
actor error: Unable to evaluate guard in transition for event 'GO' in state node 'm.s':
boom
guard state: "s" status: error
```

XState does **not** fall through to the unguarded `fallback` branch. The throw propagates to the actor's error channel, the snapshot `status` becomes `error`, and the state is unchanged. This library instead selects `fallback` and reports `status` healthy — so the divergence is not merely one of observability but of which transition is taken.

SCXML's B.2 "Conditional Expressions" likewise specifies that an error evaluating a `cond` raises `error.execution` **on the internal event queue** — i.e. the failure becomes an observable event in the system, not a silent `false`.

The common thread: the failure must be *surfaced* somewhere. Today it is surfaced nowhere except a log line. The expected contract:

1. A configurable policy so an application can choose `false` (today's default), `true`, or `raise`.
2. Regardless of the policy, a structured notification — `on_guard_error` on `PluginBase` — so the failure is observable without changing transition semantics.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:2903-2925`, in the guard-evaluation path:

```python
# 🏛️ Architecture decision: a guard is a *predicate supplied by the
# user*, so a raised exception is a defect in that predicate rather
# than a machine-level failure. Per the documented contract it
# evaluates to `False`, blocking this transition while leaving the
# machine responsive and allowing any lower-priority transition (e.g.
# an unguarded fallback in the same `on` array) to be considered.
# A *missing* guard still raises above — that is a configuration
# error, not a runtime condition, and must fail loudly.
try:
    params = self._resolve_params(guard.params, event)
    result = bool(
        self._call_with_optional_params(
            guard_callable, self.context, event, params
        )
    )
except Exception:
    logger.exception(
        "🔥 Guard '%s' raised an exception while evaluating event "
        "'%s'; treating it as False.",
        guard.type,
        event.type,
    )
    result = False
```

The reasoning is sound as far as it goes — keeping the machine responsive is the right instinct, and a *missing* guard still raises `ImplementationMissingError` a few lines above (`:2895-2899`), which correctly distinguishes configuration errors from runtime ones. Two things are missing.

**1. The policy is hard-coded.** `result = False` is the only possible outcome. For a deny-polarity guard (`risk_ok`) `False` is the safe direction; for an allow-polarity guard (`is_halted`, `breach_detected`) `False` is the *unsafe* direction, and the author has no way to say so. Which coercion is "fail-safe" is a property of the application's guard polarity, not of the library.

**2. The failure is unobservable.** Immediately after, at `:2933-2935`:

```python
for plugin in self._plugins:
    plugin.on_guard_evaluated(self, guard.type, event, result)
```

Plugins are told `result=False` with no indication that the value is synthetic. `PluginBase` (`plugins.py:70-260`) has gained `on_action_error` (0.6.0) but has **no** `on_guard_error` — so the one extension point designed for observability cannot see this. `logger.exception` is the sole record, and a log line is not something a metrics pipeline can reliably alert on.

The interaction with guard arrays makes it worse: because evaluation continues to the next candidate transition, a crashed guard silently *promotes* the next branch. Combined with LC-10 (guards continue to be evaluated after a branch has been selected), a single crashing guard can change which branch wins with no trace.

## Impact

**General users.** The library offers no way to tell "the business rule said no" from "the code implementing the business rule is broken". Any guard touching I/O, external state, optional context keys, or anything that can raise `KeyError`/`AttributeError`/`TimeoutError` is affected — which is most non-trivial guards. A guard broken by a refactor (a renamed context key raising `KeyError`) does not fail any test that asserts only on the resulting state, because the fallback branch is usually the one the test expects anyway. The bug manifests as a machine that has quietly stopped enforcing a rule.

**CandleViewer trading OMS.** This is our B8/B17/B20 blocker. Our live trading gate is written as a guard array:

```
on: { SUBMIT: [ { target: "submitting", guard: "risk_ok" },
                { target: "rejected" } ] }
```

`risk_ok` consults the position-limit service and the daily-loss ledger. If that call raises — service unreachable, a schema change producing `KeyError`, a `Decimal` conversion error on a malformed fill — the guard evaluates `False`, the order routes to `rejected`, and superficially that looks fail-safe. The real damage is on the other polarity: our kill-switch and risk-lockout machines (B18, B20) use `breach_detected`-style *allow* guards, where `False` means "no breach — keep trading". A crashing breach detector therefore silently disables the lockout, and `on_guard_evaluated` reports a perfectly ordinary `False` to our telemetry, identical to the thousands of legitimate no-breach evaluations per minute. We have no metric that can distinguish them and no alert that can fire. Our workaround (house rule A6: every guard is deny-polarity and wraps its own body in `try/except`, returning the safe value explicitly) is enforceable only by code review, and one guard that forgets it re-opens the hole invisibly.

## Current workaround and why it is insufficient

Every guard must defensively wrap itself:

```python
def risk_ok(context, event) -> bool:
    try:
        return _position_limit_ok(context) and _daily_loss_ok(context)
    except Exception:
        metrics.increment("cv_guard_error_total", tags={"guard": "risk_ok"})
        return False          # explicit deny-polarity choice
```

Insufficient because:

1. **It is unenforceable.** Nothing in the library or the type system requires it. A new guard added without the wrapper silently rejoins the broken behaviour, and the failure is invisible precisely in the case where review missed it.
2. **It is per-guard boilerplate.** Every guard in every machine repeats the same five lines. The obvious fix — a decorator — still has to be applied by hand.
3. **It cannot express `raise`.** Some guards genuinely should halt the machine rather than pick a branch. There is no way to opt into that.
4. **It does not help third-party or built-in guards.** `is_state_in` guards and any guard supplied by a library the application does not own cannot be wrapped.
5. **It duplicates logic that has to agree with the transition order.** The "safe" return value depends on the guard's position in the `on` array, so the workaround couples guard implementations to config layout.

## Proposed API

**1. `guard_error_policy` — a machine/interpreter option.**

```python
from xstate_statemachine import create_machine, MachineLogic
from xstate_statemachine.interpreter import Interpreter

interp = Interpreter(machine, guard_error_policy="raise")
```

- `"false"` *(default — today's behaviour, fully backwards compatible)*: coerce to `False`, log, fire `on_guard_error`.
- `"true"`: coerce to `True`. For allow-polarity guards where "unknown" must block the permissive branch.
- `"raise"`: re-raise. The async run loop's existing `except` handler (`interpreter.py:479`) keeps the interpreter alive and logs; with LC-48's `on_transition_failed` the event is also reported. `SyncInterpreter` propagates to the caller, matching its existing contract for `ImplementationMissingError`.

Settable per machine (config key `guard_error_policy`) and overridable per interpreter, with the interpreter winning. A per-guard override is a plausible future extension but is not required here.

**2. `PluginBase.on_guard_error` — the minimum viable fix.** Additive, no semantic change, valuable on its own even if the policy option is rejected:

```python
class PluginBase:
    def on_guard_error(
        self,
        interpreter: "BaseInterpreter",
        guard_type: str,
        event: Event,
        error: Exception,
    ) -> None:
        """Called when a guard predicate raises. The transition outcome is
        determined by `guard_error_policy`; this hook always fires."""
```

Fired from the `except` block at `base_interpreter.py:2918` before the policy is applied. `on_guard_evaluated` should additionally receive the synthetic result so an existing plugin can correlate the two.

**Sketch of the change** at `base_interpreter.py:2911-2925`:

```python
try:
    params = self._resolve_params(guard.params, event)
    result = bool(self._call_with_optional_params(
        guard_callable, self.context, event, params))
except Exception as exc:
    logger.exception(
        "🔥 Guard '%s' raised while evaluating event '%s'; policy=%s.",
        guard.type, event.type, self._guard_error_policy,
    )
    for plugin in self._plugins:
        plugin.on_guard_error(self, guard.type, event, exc)
    if self._guard_error_policy == "raise":
        raise
    result = self._guard_error_policy == "true"
```

**Usage example — the CandleViewer kill switch, correctly fail-safe:**

```python
machine = create_machine(
    {
        "id": "kill_switch",
        "initial": "trading",
        "guard_error_policy": "true",  # an unknown breach state must LOCK OUT
        "states": {
            "trading": {
                "on": {"TICK": [
                    {"target": "locked_out", "guard": "breach_detected"},
                    {"target": "trading"},
                ]}
            },
            "locked_out": {"type": "final"},
        },
    },
    logic=MachineLogic(guards={"breach_detected": breach_detected}),
)


class GuardErrorMetrics(PluginBase):
    def on_guard_error(self, interpreter, guard_type, event, error):
        metrics.increment(
            "cv_machine_guard_errors_total",
            tags={"machine": interpreter.id, "guard": guard_type,
                  "error": type(error).__name__},
        )


interp = Interpreter(machine)
interp.use(GuardErrorMetrics())
```

A crashing `breach_detected` now locks out trading *and* increments an alertable counter, instead of silently returning `False` and continuing to trade.

**Backwards compatibility.** Default `"false"` preserves 0.7.0 semantics exactly; no existing machine changes behaviour. `on_guard_error` has a no-op default on `PluginBase`, so existing plugins are unaffected. No deprecation is needed. The documented contract in the `base_interpreter.py:2903-2910` comment should be updated to describe the policy and to state that the hook always fires.

## Acceptance criteria

- [ ] `guard_error_policy` accepts `"false"` (default), `"true"` and `"raise"`; an invalid value raises at `create_machine()` / interpreter construction.
- [ ] Default behaviour is byte-identical to 0.7.0: the existing test suite passes unchanged.
- [ ] `"true"` selects the guarded branch when the guard raises; `"raise"` propagates.
- [ ] Under `"raise"`, the async `Interpreter` stays running (the run loop logs and continues) and `SyncInterpreter` propagates to the caller.
- [ ] `PluginBase.on_guard_error` is declared with a no-op default and fires under **all three** policies.
- [ ] The interpreter-level option overrides the machine-config value.
- [ ] `repro/LC-09_guard-exception-swallowed.py` exits 0.
- [ ] Docs updated: the guards page gains a "when a guard raises" section documenting the policy and the hook.
- [ ] Tests added under `tests/`:
  - `tests/test_guards.py::test_raising_guard_defaults_to_false`
  - `tests/test_guards.py::test_guard_error_policy_true_selects_guarded_branch`
  - `tests/test_guards.py::test_guard_error_policy_raise_propagates_in_sync_interpreter`
  - `tests/test_guards.py::test_guard_error_policy_raise_keeps_async_interpreter_running`
  - `tests/test_guards.py::test_invalid_guard_error_policy_rejected_at_create`
  - `tests/test_plugins.py::test_on_guard_error_fires_under_every_policy`
  - `tests/test_plugins.py::test_raising_guard_is_distinguishable_from_false_guard`

## Related

- **LC-10** — guards continue to be evaluated after a branch has been selected (probe A6); both concern guard-array evaluation and should be fixed together, as short-circuiting changes which guards can crash.
- **LC-48** — no error-observability hooks (`on_transition_failed`, `on_guard_error`, unhandled-event signal); `on_guard_error` here is the guard-specific slice of that issue.
- **LC-08** — unknown targets unvalidated; the same "degrade to a no-op, log it, tell nobody" philosophy.

## Verification

Independently re-verified on **2026-09-15**.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11
- `repro/LC-09_guard-exception-swallowed.py` run in a fresh process → **exit code 1**, output matches the Observed section verbatim; the two result dicts are byte-identical.
- Root-cause citations confirmed against source: guard `try/except` at `base_interpreter.py:2911-2925` with `result = False` at `:2925`, architecture comment at `:2903-2910`, `ImplementationMissingError` for a missing guard at `:2895-2899`, `on_guard_evaluated` fan-out at `:2933-2935`. `plugins.py` declares `on_action_error` but no `on_guard_error` — confirmed by grep.
- Expected behaviour confirmed empirically against **XState 5.33.0** (Node 20.14.0): a throwing guard in a guard array does **not** fall through to the unguarded branch; the error reaches the actor's error channel, `status` becomes `error`, and the state stays `"s"`. Noted in the Expected section as a semantic divergence, not only an observability gap.
