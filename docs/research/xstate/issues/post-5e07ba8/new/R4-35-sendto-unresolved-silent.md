---
r4: R4-35
title: "Bug: sendTo with an unresolvable target silently drops the event with no observable signal"
labels: [bug, severity/low, area/plugins, area/events]
severity: Low
repro_script: repro/R4-35_sendto_unresolved_silent.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

When a `sendTo` action's target cannot be resolved to a live actor (e.g. a
config typo referencing a nonexistent invoke id), the engine logs a
`logger.warning` and returns without delivering the event -- but it does not
fire `plugin.on_event_dropped`, does not set `last_error`, and the
transition that contained the `sendTo` completes as an ordinary successful,
error-free step. The result (`Receipt(changed=False, error=None,
deferred=False)`, `last_transition_ok=True`, `last_error=None`) is
indistinguishable from a config with no `sendTo` at all. Individually Low
severity because it requires a pre-existing config typo, but it compounds
`R4-20` (escalate is similarly unroutable): both actor-messaging failure
paths in the engine are silent.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
"""R4-35: `sendTo` with an unresolvable target silently drops the event --
no error, no receipt failure, no plugin hook."""
import asyncio
import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "m",
    "initial": "s",
    "states": {
        "s": {
            "on": {
                "GO": {
                    "actions": [
                        {"type": "sendTo", "params": {"to": "no_such_actor", "event": {"type": "PING"}}}
                    ]
                }
            }
        }
    },
}


class Accountant(PluginBase):
    def __init__(self) -> None:
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.dropped.append((event.type, reason))


async def main() -> int:
    acc = Accountant()
    i = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(acc)
    await i.start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    last_error = getattr(i, "last_error", None)
    print("OBSERVED receipt        :", r)
    print("OBSERVED last_transition_ok:", i.last_transition_ok)
    print("OBSERVED last_error     :", last_error)
    print("OBSERVED status         :", i.status)
    print("OBSERVED on_event_dropped:", acc.dropped)
    print(
        "EXPECTED: an unresolved sendTo target fires on_event_dropped (and/or "
        "sets last_error), matching the other drop paths (queue_full, "
        "not_running, chain_budget)."
    )
    ok = bool(acc.dropped)
    print("RESULT:", "PASS" if ok else "FAIL (silent drop: no on_event_dropped)")
    await i.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED receipt        : Receipt(state_ids=frozenset({'m.s'}), changed=False, error=None, deferred=False)
OBSERVED last_transition_ok: True
OBSERVED last_error     : None
OBSERVED status         : running
OBSERVED on_event_dropped: []
EXPECTED: an unresolved sendTo target fires on_event_dropped (and/or sets last_error), matching the other drop paths (queue_full, not_running, chain_budget).
RESULT: FAIL (silent drop: no on_event_dropped)
```

Every observable field says the step succeeded cleanly; the dropped `PING`
event that should have gone to `no_such_actor` leaves no trace anywhere in
the public API or the plugin hooks.

## Expected behaviour

The engine's own established convention (already applied to inbox-full,
not-running, and runaway-chain drops -- see `R4-15`) is that an event which
was accepted for delivery but did not reach its destination fires
`plugin.on_event_dropped(self, event, reason)`. `sendTo` targeting a name
that resolves to nothing is exactly this class of event: it was accepted
(the action ran) but never delivered. It should not be silently
indistinguishable from a no-op.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:2656-2662`, the `SEND_TO`
branch of the action dispatcher:

```python
elif canonical == SEND_TO:
    actor = self._resolve_actor_target(params.get("to"), event)
    if actor is None:
        logger.warning(
            "⚠️ sendTo could not resolve target %r; event dropped.",
            params.get("to"),
        )
        return
    target_event = self._resolve_event_spec(params.get("event"), event)
    delay = self._resolve_delay(params.get("delay"), event)
    await self._deliver(actor, target_event, delay, params.get("id"))
```

On an unresolved target the branch logs and returns -- there is no
`for plugin in self._plugins: plugin.on_event_dropped(...)` call, unlike the
`DROP_NEWEST` inbox-full path (`interpreter.py:849-863`) which does call it
for the analogous "accepted but not delivered" situation. The log line's own
comment ("event dropped") acknowledges the semantics but the code does not
act on them via the plugin hook.

## Impact

**General users.** A `sendTo` typo (wrong invoke id, wrong actor reference,
a child that already stopped) produces a transition that reports full
success on every field the public API exposes. Nothing short of reading log
output at the right log level reveals the failure, and `logger.warning` is
frequently filtered out or unmonitored in production. Automated tests
asserting "the transition completed without error" will pass even though the
intended message was never sent.

**Concrete order-management scenario.** An order machine's cancellation
handler forwards a `CANCEL` message to a child order-routing actor via
`sendTo: {to: "router"}`inside an action; if the router's declared id has
drifted from the actual invoke id (a rename in one file, not the other), the
cancellation silently vanishes while the parent's transition -- and the
receipt returned to whichever caller requested the cancel -- both report
success. The order is never actually cancelled.

## Proposed fix

**Design.** Fire `on_event_dropped` (and set `last_error`) on an unresolved
`sendTo` target, matching the other drop paths.

1. In the `SEND_TO` branch (`base_interpreter.py:2656-2662`), when
   `actor is None`, in addition to the existing `logger.warning`, call
   `for plugin in self._plugins: plugin.on_event_dropped(self, target_event,
   "sendto_unresolved")` using the (constructed) target event so
   observers see what would have been sent and to whom.
2. Consider also setting `self.last_error` (or a lighter-weight
   `self.last_transition_ok = False`) for this case, or introduce a
   dedicated field, so a caller inspecting only the receipt/interpreter state
   (not plugin hooks) can also detect it -- to be decided against how
   `last_error` is used for other non-fatal-but-notable conditions elsewhere
   in the engine.
3. Apply the same treatment to `forwardTo`'s analogous unresolved-target
   branch (`base_interpreter.py:2680-2684`), which has the identical gap.

**Compatibility.** Additive; no signature changes. Any plugin not
implementing `on_event_dropped` is unaffected (base class default is a
no-op).

**Alternatives considered.**
1. *Raise an exception instead.* Rejected: `sendTo` targets can legitimately
   be transient (a child that finished a moment before the send), so a hard
   raise would be too strict for the common, benign race; the drop-hook
   convention already accommodates this distinction (log + hook, not raise).

## Acceptance criteria

- [ ] An unresolved `sendTo` target fires `plugin.on_event_dropped(...)`
      with a distinct reason (`"sendto_unresolved"`).
- [ ] The analogous `forwardTo` unresolved-target path gets the same
      treatment.
- [ ] `repro/R4-35_sendto_unresolved_silent.py` exits `0`.
- [ ] `tests/test_sendto_drops.py::test_unresolved_sendto_fires_on_event_dropped`
- [ ] `tests/test_sendto_drops.py::test_unresolved_forwardto_fires_on_event_dropped`

## Related

- Register row `R4-35` (filed Low, stands as filed).
- Evidence: `battle-5e07ba8/semantics/repro/d5_sendto_unresolved.py`.
- **`R4-20`** -- `escalate()` is also unroutable; together both
  actor-messaging paths in the engine are silent on failure.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-35_sendto_unresolved_silent.py` in a fresh process: exit code
  `1`, output matches the Observed section verbatim (receipt reports
  `changed=False, error=None`, `last_transition_ok=True`, `last_error=None`,
  `on_event_dropped=[]` for an unresolvable `sendTo` target).
- Root cause confirmed: `base_interpreter.py`'s `SEND_TO` branch --
  `if actor is None: logger.warning(...); return` -- with no
  `plugin.on_event_dropped(...)` call, unlike the `DROP_NEWEST` inbox-full
  path in `interpreter.py` which does call it for the analogous
  "accepted but not delivered" case.
- No XState-doc claim to verify (this is an engine-internal
  observability-contract consistency question -- matching this library's own
  established `on_event_dropped` convention -- not an XState v5 spec claim).
- Duplicate check: `gh issue list --search "sendTo unresolved"` surfaces
  **#40** ("`sendTo` cannot address an actor by its `invoke` `id` or
  `systemId`; the event is silently dropped") -- a related but *distinct*
  defect (target-resolution capability gap: `sendTo` can't reach a
  correctly-configured actor at all) from this one (an *already-broken*
  target, e.g. a typo, produces no observable signal). No overlap in root
  cause or repro; both remain filed separately, consistent with the register.
- Self-contained; no project-name/label leak.
