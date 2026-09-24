---
r7: R7-13
title: "Bug: config-level `strict: true` does not gate event names, and a `\"*\"` handler makes `is_known_event()` return true for anything"
labels: [bug, severity/medium, area/validation, area/interpreter]
severity: Medium
engines: both
repro_script: repro/R7-13_config_strict_and_wildcard.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

Two related gaps:

1. Config-level `"strict": true` does not cause undeclared event **names**
   to be rejected — the strictness applies elsewhere, so a caller who sets
   it in the machine JSON believing it gates event names does not get that.
2. A wildcard `"*"` handler anywhere in the chart makes `is_known_event()`
   return `True` for **every** event type, so any conformance check built
   on that predicate is silently vacuous.

Standalone reproduction: `repro/R7-13_config_strict_and_wildcard.py`.

Combined effect: a project that adds `"*": {"actions": ["defer"]}`
scaffolding — a natural thing to write — silently disables its own
event-name enforcement.

## Environment

- Library commit: `221ce7c` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Engine: both

## Minimal reproduction

See `repro/R7-13_config_strict_and_wildcard.py` — a byte-for-byte copy is
kept alongside this issue. Part 1 builds a machine with `"strict": true` in
its config and no wildcard handler, constructs an `Interpreter` with no
explicit `strict=` kwarg (which should inherit `machine.strict`), and sends
an undeclared event. Part 2 builds a machine with a `"*"` handler, checks
`MachineNode.is_known_event()` directly, and sends an undeclared event
through an interpreter constructed with an *explicit* `strict=True`. Exits 1
if either gap reproduces, 0 if both are gated correctly.

## Observed

```
machine.strict = True
part1: TOTALLY_UNDECLARED -> UnknownEventError: Event 'TOTALLY_UNDECLARED' is not declared by machine 'p1'. Known events: KNOWN.
part2: is_known_event('TOTALLY_UNDECLARED') with a '*' handler present = True (known_events=['*', 'KNOWN'])
part2: TOTALLY_UNDECLARED ACCEPTED under explicit strict=True, running=True
```
Part 1 (config-level `strict` alone, no explicit interpreter kwarg, no
wildcard) is gated correctly in this minimal machine — `Interpreter(m)` does
read `machine.strict` (`base_interpreter.py:578`,
`self.strict = machine.strict if strict is None else bool(strict)`), so the
config-level flag reaches the interpreter here. Gap 2 (the wildcard defeating
`is_known_event()`, and therefore defeating `strict` enforcement even under
an *explicit* `Interpreter(strict=True)`) reproduces unconditionally: a `"*"`
handler makes the machine accept `TOTALLY_UNDECLARED` even though `strict`
is explicitly on. The project's own battle-tested contract fixture
(`g3_B13.json`, carrying both `"strict": true` and a `"*"` handler in its
`subscribing` state) additionally shows gap 1 in combination with a
wildcard: with the wildcard present, `NOT_A_REAL_EVENT`, `after.party`,
`done.invoke.bogus` and `xstate.bogus` are all ACCEPTED with
`last_error=None` under `Interpreter(m)` (no explicit `strict=` kwarg) — see
"Related"; removing the wildcard restores strict gating.

## Expected

This is XState v5's own documented contract for `is_known_event`-style
introspection: a wildcard transition means "this actor will accept and route
this event", not "this event name is part of the machine's declared
vocabulary" — XState v5 does not conflate a fallback wildcard handler with
event-name validation, and the two concerns (routing vs. declared-name
strictness) are meant to be independent. A caller who writes `"*":
{"actions": ["defer"]}` as catch-all scaffolding, and separately sets
`"strict": true` expecting undeclared names to be rejected, reasonably
expects the wildcard to change nothing about strictness.

## Root cause

`src/xstate_statemachine/models.py`, `is_known_event()`:
```python
known = self.known_events
if "*" in known or event_type in known:
    return True
```
The bare `"*"` wildcard is included in `known_events` and short-circuits the
check to `True` for any `event_type`, with no distinction between "a
transition exists that will catch this" and "this name is declared". Gap 1
(config-level `strict` not gating names in the combined case shown by the
project's own battle-tested B13 fixture) traces to the same predicate: once a
wildcard is present anywhere in the chart, `_check_strict`
(`base_interpreter.py:2054`, guarded by `if self.strict and not
self.machine.is_known_event(...)`) can never fire, because `is_known_event`
always returns `True`.

## Impact

General: any conformance lint or defensive `strict` setting built on
`is_known_event()` (directly, or indirectly via `Interpreter(strict=True)`)
is silently disabled by the presence of any wildcard handler anywhere in the
chart, with no warning at build time or at the point strict is set. Order-
management scenario: a control-plane or order-state machine that adds a `"*":
{"actions": ["log_unexpected"]}` handler as defensive scaffolding — a natural
and common pattern — silently disables its own `strict` event-name
enforcement project-wide, so a typo'd order event (`"CANCLE"` for `"CANCEL"`)
is silently accepted and routed through the wildcard handler instead of
being rejected as the contract violation it is.

## Proposed fix

Exclude a wildcard handler from `is_known_event()`'s decision so the
predicate answers "is this name declared?" rather than "is there any handler
that would match?" — i.e. do not include `"*"` itself in the set that makes
`is_known_event` return `True`; and either honour config-level `strict` for
event names independent of wildcard presence, or document clearly that a
wildcard handler exempts the chart from name-strictness.

## Acceptance criteria

- `test_wildcard_does_not_defeat_is_known_event`: for a machine with a `"*"`
  handler and no declaration of `"UNDECLARED_NAME"`, `machine.is_known_event
  ("UNDECLARED_NAME", user_sent=True)` returns `False`.
- `test_strict_true_rejects_undeclared_name_with_wildcard_present[def]` and
  `[async def]` (both engines; parametrised over whether the wildcard state
  also has an invoked service, to confirm the fix does not disturb dispatch):
  `Interpreter(strict=True)` / `SyncInterpreter(strict=True)` raise
  `UnknownEventError` for an undeclared name even when a `"*"` handler is
  present elsewhere in the chart.
- `test_wildcard_dispatch_unaffected`: the wildcard handler still catches and
  routes an undeclared event when `strict` is `False` (dispatch behaviour is
  unchanged; only the introspection predicate changes).

## Related

`spawnBlockingTimeout` is validated then dropped (no attribute on the built
machine), and unknown top-level config keys are accepted silently, so a typo
is a silent downgrade to the default. Both filed as Low items in the meta
issue. All three share a theme: **config keys that are accepted but not
enforceable by read-back**, which makes a conformance lint impossible to
write against the built machine. Register id `LIB-R6-strict` (carried); the
project's own battle-tested contract `g3_B13.json` (`strict: true` plus a
`"*"` handler in `subscribing`) demonstrates both gaps together in a
realistic chart, and `g3_wildcard.py` (`STAR-3`) confirms removing the
wildcard alone restores correct `strict` gating.

## Verification

- Date: 2026-09-20
- Python: 3.13.7
- Commit: 221ce7c
- Command: `python repro/R7-13_config_strict_and_wildcard.py`
- Exit code: 1 (reproduced — wildcard defeats is_known_event() and strict=True)
