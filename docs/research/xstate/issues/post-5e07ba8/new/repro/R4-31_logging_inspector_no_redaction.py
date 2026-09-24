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
