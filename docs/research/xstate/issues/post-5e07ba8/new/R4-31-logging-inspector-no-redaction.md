---
r4: R4-31
title: "Docs/Security: shipped LoggingInspector reference plugin logs context and event payloads unredacted at INFO"
labels: [documentation, severity/medium, area/plugins]
severity: Medium
repro_script: repro/R4-31_logging_inspector_no_redaction.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`LoggingInspector`, the library's own shipped, docs-endorsed reference
observability plugin, logs the full interpreter context and event payload
at `INFO` level with no redaction, denylist, or opt-out. Any secret placed
in machine context (API keys, tokens) or sent as part of an event payload
(passwords, PII) is written verbatim to whatever log sink the application
uses the moment `LoggingInspector` is attached — which is exactly the
"quick start" way most users are shown to observe an interpreter. This is
not attacker-exploitable against the library itself, but it is a real
disclosure vector the instant this reference code is adopted as shown.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`

## Current behaviour and why it is insufficient

`plugins.py:448-485` (`LoggingInspector.on_transition`):
```python
if from_ids != to_ids:
    logger.info(
        "🕵️ [INSPECT] Transition: %s -> %s on Event '%s'",
        sorted(list(from_ids)), sorted(list(to_ids)), transition.event,
    )
    logger.info("🕵️ [INSPECT] New Context: %s", interpreter.context)
elif transition.actions:
    logger.info(
        "🕵️ [INSPECT] Internal transition on Event '%s'", transition.event,
    )
    logger.info("🕵️ [INSPECT] New Context: %s", interpreter.context)
```
and `plugins.py:420-446` (`on_event_received`):
```python
if isinstance(event, Event):
    data_to_log = event.payload
elif isinstance(event, ErrorEvent):
    data_to_log = event.error
else:
    data_to_log = getattr(event, "data", None)
message = f"🕵️ [INSPECT] Event Received: {event.type}"
if data_to_log is not None:
    message += f" | Data: {data_to_log}"
logger.info(message)
```
Both call sites log the raw value — `interpreter.context` and the event's
`payload`/`data`/`error` — with `%s` formatting and no filtering. There is
no hook, config flag, or key denylist to redact specific keys, and no
docstring warning against production use.

```python
"""R4-31: LoggingInspector (the library's shipped, docs-endorsed reference
plugin) logs full context and event payloads at INFO with no redaction.

plugins.py:443-446 logs `data_to_log` (the raw event payload/error) at INFO
in `on_event_received`, and plugins.py:477/484 log `interpreter.context`
verbatim at INFO in `on_transition`. There is no redaction hook, key
denylist, or opt-out -- any secret placed in context or an event payload
(API keys, passwords, PII) lands in application logs the moment a caller
attaches this reference plugin, which the library's own docs point to as
the example inspector.

EXPECTED: reference logging/observability code shipped by the library
should not put raw secret VALUES into INFO logs by default (or should
clearly document/require an explicit opt-in and redaction mechanism).
OBSERVED: `LoggingInspector` logs `{'api_key': 'sk-live-SECRET123'}` and
`{'password': 'hunter2'}` verbatim.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import logging

from xstate_statemachine import LoggingInspector, MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"api_key": "sk-live-SECRET123"},
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        self.lines.append(record.getMessage())


def main() -> int:
    cap = _Capture()
    logger = logging.getLogger("xstate_statemachine")
    logger.addHandler(cap)
    logger.setLevel(logging.INFO)

    machine = create_machine(CFG, logic=MachineLogic())
    interp = SyncInterpreter(machine)
    interp.use(LoggingInspector())
    interp.start()
    interp.send("GO", password="hunter2")

    logger.removeHandler(cap)

    secret_lines = [
        ln for ln in cap.lines if "sk-live-SECRET123" in ln or "hunter2" in ln
    ]

    print("Captured INFO log lines from LoggingInspector:")
    for ln in cap.lines:
        print(" ", ln)

    defect_present = len(secret_lines) > 0
    print(f"\nlines containing raw secret values: {len(secret_lines)}")
    print(
        "\nOBSERVED:",
        "secret values leaked into INFO logs verbatim"
        if defect_present
        else "no secret values found in logs",
    )
    print(
        "EXPECTED: context/event payload values are not logged unredacted "
        "by the shipped reference LoggingInspector"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
Captured INFO log lines from LoggingInspector:
  🧠 Initializing MachineLogic container...
  ✅ MachineLogic initialized with 0 actions, 0 guards, and 0 services.
  🧠 Using explicitly provided MachineLogic instance.
  🕵️  Validating core machine configuration structure...
  ✅ Configuration structure for machine 'm' is valid.
  🏭 Assembling final MachineNode for 'm'...
  🧠 Initializing BaseInterpreter for machine 'm'...
  ✅ BaseInterpreter 'm' initialized. Status: 'uninitialized'.
  ⛓️ Initializing Synchronous Interpreter... 🚀
  ✅ Synchronous Interpreter 'm' initialized. 🎉
  🔌 Plugin 'LoggingInspector' registered with interpreter 'm'.
  🏁 Starting sync interpreter 'm'...
  🕵️ [INSPECT] Transition: [] -> ['m.a'] on Event '___xstate_statemachine_init___'
  🕵️ [INSPECT] New Context: {'api_key': 'sk-live-SECRET123'}
  ✨ Sync interpreter 'm' started. Current states: {'m.a'}
  🕵️ [INSPECT] Event Received: GO | Data: {'password': 'hunter2'}
  🕵️ [INSPECT] Transition: ['m.a'] -> ['m.b'] on Event 'GO'
  🕵️ [INSPECT] New Context: {'api_key': 'sk-live-SECRET123'}

lines containing raw secret values: 3

OBSERVED: secret values leaked into INFO logs verbatim
EXPECTED: context/event payload values are not logged unredacted by the shipped reference LoggingInspector
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

There is no formal SCXML/XState spec requirement here — this is a library
documentation/reference-implementation-quality issue. General secure-logging
practice (and the spirit of the library's own containment work elsewhere,
e.g. `_SafePlugin`'s isolation of plugin failures) is that a bundled
"batteries included" reference plugin should not, by default, write
unredacted secret-shaped values to a standard log stream at INFO — the
level most deployments enable in production. At minimum, the library
should document this loudly in `LoggingInspector`'s docstring and/or
default to logging structural information (context **keys**, event
**type**) rather than full values.

## Root cause analysis

`plugins.py:443-446` and `plugins.py:477, 484` pass `interpreter.context`
and the event's payload/data/error object straight into `logger.info(...)`
with `%s` formatting, with no redaction hook, key denylist, or size/shape
limiting. This is not a logic bug (nothing here is incorrect state-machine
behaviour) — it is a defect in a shipped reference implementation that
users are expected to copy or subclass verbatim, per the library's docs.

## Impact

**General users:** any application that follows the library's own example
and attaches `LoggingInspector` for development convenience, then leaves it
attached (or a near-identical custom plugin modeled on it) in a staging or
production environment where INFO-level logs are captured/shipped to a
log-aggregation service, exposes whatever is in context/event payloads to
that log pipeline and anyone with read access to it.

**Order-management scenario:** an order-processing interpreter carrying
`api_key`, customer PII, or payment-adjacent fields (order totals, account
identifiers) in context — realistic for a stateful order workflow — would
have all of that written to INFO logs the moment `LoggingInspector` (or a
lightly-modified copy) is used for observability, turning a debugging aid
into a compliance/PCI-adjacent exposure surface.

## Proposed API/text

- Add an optional redaction mechanism to `LoggingInspector`: a
  constructor parameter such as `redact_keys: set[str] | None` (with a
  sensible default denylist — `password`, `token`, `secret`, `api_key`,
  `authorization`, etc.) that masks matching keys' values (e.g.
  `"***REDACTED***"`) before logging, and/or a `log_values: bool = False`
  flag that defaults to logging only context/payload **keys**, not values,
  requiring an explicit opt-in to log full values.
- Add a prominent docstring warning on `LoggingInspector` itself: "This
  reference plugin logs full context and event payloads at INFO with no
  redaction. Do not use it unmodified in an environment where context or
  event payloads may contain secrets or PII; supply `redact_keys` or
  subclass and override the logging calls."
- Optionally, document the same caveat in the top-level plugin/observability
  docs page (wherever `LoggingInspector` is first introduced as an example).

Compatibility: additive — default behaviour for existing callers is
unchanged unless they opt into the new default-safer mode; if the default
is flipped to `log_values=False`, that is a minor behavioural change worth
flagging in the changelog since existing dashboards relying on the current
verbose output would need `log_values=True` to keep it.

## Acceptance criteria

- [ ] `repro/R4-31_logging_inspector_no_redaction.py` exits 0 (no longer
      finds unredacted secret values in the captured log lines, once
      `redact_keys`/`log_values` defaults are applied — or the test is
      updated to reflect the newly documented, explicit opt-in required to
      log full values)
- [ ] New test `tests/test_plugins.py::test_logging_inspector_redacts_denylisted_keys`
- [ ] `LoggingInspector`'s docstring documents the redaction mechanism and
      warns against unmodified production use with secret-bearing context

## Related

- Register source: re-derived this pass in a standalone script (no prior
  battle-track script cited)

## Verification

- Date: 2026-09-19
- Python: 3.13.7
- Commit: `5e07ba8`
- Ran `repro/R4-31_logging_inspector_no_redaction.py` in a fresh process
  (required no code changes on the fixed side; the test still targets
  logger name `xstate_statemachine`, which is correct because
  `plugins.py`'s module logger is obtained via
  `logging.getLogger("xstate_statemachine")`/child logger under that
  namespace — output matched the Observed behaviour section verbatim, exit
  code 1).
- Confirmed `plugins.py`'s `LoggingInspector.on_event_received` and
  `on_transition` log `data_to_log`/`interpreter.context` straight into
  `logger.info(...)` with `%s` formatting and no redaction hook or key
  denylist — matches the cited root cause.
- This is a documentation/reference-implementation-quality finding with no
  formal spec citation to fetch; no XState/SCXML URL was cited in Expected
  behaviour to verify.
- No duplicate open/closed GitHub issue found
  (`gh issue list --search "LoggingInspector redaction"` returned no
  match).
