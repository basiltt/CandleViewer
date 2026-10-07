---
id: DE-L3
title: "Bug: def action calling send(wait=True) receives the _Awaitable guard unawaited, silently"
labels: [bug, severity/low, actors]
severity: Low
repro_script: repro/DE-L3-repro.py
commit: de2da4e
verified: true
---

## Summary

This is one of the last items on the "make it perfect" list after twelve
rounds of adoption battle-testing — the library is already adopted and this
sits well inside "adopt with constraints". `#219`'s `ReentrantWaitError`
guard is correct and thoroughly matrix-tested for `async def` actions (see
our round-12 security track), but a **synchronous `def` action** that
calls `interpreter.send(..., wait=True)` gets back the internal
`_Awaitable` guard object as a plain, unawaited value — no exception, no
warning, and no usable receipt. The call is silently useless rather than
either working or failing loudly.

## Environment

- `_ref/xstate-statemachine` @ `de2da4e` (targeting 0.8.1; `__version__` still
  0.8.0)
- `.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, cwd `<home>`

## Minimal reproduction

```python
"""DE-L3 repro: a `def` action calling send(wait=True) gets the _Awaitable
guard unawaited, silently. STANDALONE: stdlib + xstate_statemachine only.
Run from cwd <home>.
"""
import sys, asyncio
sys.path.insert(
    0,
    "<workspace>/_ref/"
    "xstate-statemachine/src",
)
from xstate_statemachine import create_machine, MachineLogic, Interpreter

result = {}


def my_action(interp, context, event, action_def):
    # A synchronous action calling send(wait=True) on its own interpreter.
    # #219 makes the ASYNC-action shape raise ReentrantWaitError instead of
    # deadlocking -- this sync shape gets neither the receipt nor the error.
    r = interp.send("B", wait=True)
    result["type"] = type(r).__name__


cfg = {
    "id": "m",
    "initial": "s1",
    "actionErrorPolicy": "rollback",
    "states": {
        "s1": {"on": {"A": {"target": "s2", "actions": ["my_action"]}}},
        "s2": {"on": {"B": "s3"}},
        "s3": {"type": "final"},
    },
}
m = create_machine(cfg, logic=MachineLogic(actions={"my_action": my_action}))


async def main():
    i = Interpreter(m)
    await i.start()
    await i.send("A", wait=True)
    print("final status:", i.status, "last_error:", i.last_error)
    print("send(wait=True) returned:", result)
    # The defect: a `def` action asking for a receipt gets the internal
    # guard object back, unawaited, with no error raised anywhere.
    return result.get("type") == "_Awaitable" and i.last_error is None


reproduced = asyncio.run(main())
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
```

Output on `de2da4e`:

```
final status: done last_error: None
send(wait=True) returned: {'type': '_Awaitable'}
```

## Observed behaviour

`my_action` is a plain `def`, run by `_run_user_action` without `await`
(`interpreter.py:2254-2260`: `if inspect.iscoroutinefunction(impl): await
...; else: impl(...)`). Inside it, `interp.send("B", wait=True)` returns the
private `_Awaitable` object minted by `_guard_reentrant_await`
(`interpreter.py:1140-1151`) — a guard designed to raise `ReentrantWaitError`
only when it is *awaited* while the issuing action is still running. Because
the calling action is synchronous, nothing ever awaits it: the object is
assigned, inspected, and garbage-collected with no error and no
"coroutine/future was never awaited" style diagnostic. The machine proceeds
as if the call had simply been fire-and-forget, even though the caller wrote
`wait=True` and evidently expected a receipt.

## Expected behaviour

One of:
- `send(..., wait=True)` called from a synchronous action context raises
  immediately (loudly), the same way the async-action in-step self-await
  raises `ReentrantWaitError` — since a sync action structurally cannot
  await the guard either, so `wait=True` can never be honoured there.
- Or, at minimum, a warning (e.g. via `warnings.warn` or the existing
  `on_action_error`/logger channel) is emitted when a `wait=True` receipt is
  produced but the calling context is known to be unable to await it.

## Root cause analysis

- `interpreter.py:2254-2260` (`_run_user_action`): dispatches to a plain
  `impl(...)` call with no `await` when `impl` is not a coroutine function —
  there is no signal at the call site that `wait=True` was requested inside
  this synchronous frame.
- `interpreter.py:1140-1151` (`_guard_reentrant_award`'s `_Awaitable` class):
  the `ReentrantWaitError` check lives entirely inside `__await__`, which is
  only invoked by an `await` expression; a `def` action has no way to
  trigger it, so the guard is inert for that call shape.
- `interpreter.py:1062-1083` (documented as `send(priority=True,
  wait=True)`... "ask an urgent question") gives no special-casing for the
  caller being a sync action.

## Impact

Carried today as a lint observation (see our round-12 verdict note
our lint observation/our lint rule) rather than a filed defect, but it is a real silent-failure
mode: any `def` action that assumes `send(..., wait=True)` blocks for a
receipt gets neither the receipt nor an error — the bug in the calling code
is invisible until a downstream assumption (e.g. "the child has definitely
processed X by the time this action returns") quietly fails.

## Proposed fix

Detect at the `send(..., wait=True)` call site (or inside
`_guard_reentrant_await`) whether the current frame is inside a **synchronous**
action call for this interpreter (`_ACTIVE_ACTION_OWNER.get() is self` is
already tracked) and, if so, raise `ReentrantWaitError` (or a dedicated
`SyncActionCannotWaitError`) synchronously instead of returning an
`_Awaitable` that can never be awaited from that frame. Alternatively, emit
`warnings.warn(..., RuntimeWarning, stacklevel=2)` at the point the
`_Awaitable` is constructed for a sync-action caller, so the silence is at
least visible with `-W error` or default warning filters.

## Acceptance criteria

- A new test (e.g. `test_def_action_send_wait_true_raises_or_warns`) asserts
  that a synchronous `def` action calling `send(..., wait=True)` on its own
  interpreter either raises immediately or triggers a detectable warning,
  and does not silently return an inert `_Awaitable`.
- The existing `#219` `async def` action matrix (self-await raises,
  cross-interpreter resolves, 100-concurrent `ensure_future` resolves)
  continues to pass unchanged.

## Verification

- Repro run from the neutral cwd `<home>` with the `.venv-main`
  interpreter: **exit 1**, no `ImportError`, output as quoted above —
  `send(wait=True) returned: {'type': '_Awaitable'}`, `last_error: None`,
  the machine reaching `done` regardless, and `REPRODUCED: True`.
- The code block under "## Minimal reproduction" is **byte-identical** to
  `repro/DE-L3-repro.py` (1321 bytes, compared programmatically).
- Root-cause lines confirmed open in current source at `de2da4e`:
  - `interpreter.py:2254-2260` — `_run_user_action`'s dispatch, including
    `token = _ACTIVE_ACTION_OWNER.set(self)` at `2256`; the non-coroutine
    branch calls `impl(...)` with no `await` and no knowledge that the
    body requested `wait=True`.
  - `interpreter.py:1140-1151` — the `_Awaitable` guard, whose
    `ReentrantWaitError` check lives inside `__await__` (confirmed at
    `interpreter.py:1144`) and is therefore unreachable from a `def`
    action, which cannot await.
  - `interpreter.py:1062-1083` — the `send(..., wait=True)` docstring
    region; no special-casing for a synchronous calling frame.
- Contrast confirmed on the sync engine: `sync_interpreter.py:584` refuses
  the analogous shape eagerly (`if wait and self._is_processing: raise
  ReentrantWaitError(...)`), so the two engines disagree about a `def`
  action asking for a receipt — the async engine hands back an inert
  object, the sync engine raises.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `ReentrantWaitError`, `wait=True`,
  `_Awaitable`. Only `#219` (CLOSED); it addresses the `async def` shape
  and does not mention the `def` one.

## Related

- our round-12 verdict note lines 96, 266, 401 (our lint observation
  observation, contained by our lint rules lint)
- our round-12 security track (`#219` `ReentrantWaitError` matrix,
  async-only)
