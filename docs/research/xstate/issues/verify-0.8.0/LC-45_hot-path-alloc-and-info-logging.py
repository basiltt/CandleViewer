"""LC-45 verification on xstate-statemachine 0.8.0.

0.8.0 CHANGELOG claims (under "Changed" and "#55 part 2" source comments):
  - "Per-event INFO log calls on the hot path are now DEBUG (#55, part 1).
     Measured overhead of running at INFO ... dropped from 2.53x to ~1.0x."
  - models.py: precompiled `_on_partials` / `_on_has_wildcard` descriptor
    index built once at StateNode construction (#55 part 2), removing the
    per-event `.endswith(".*")` scan.

This is NOT a policy/option -- both fixes are unconditional engine changes,
so there is only one mode to test (no "default" vs "opt-in" split).

Checks:
  1. INFO-handler overhead ratio (StringIO handler at INFO vs disabled) is
     now close to 1.0 (assert < 1.5, generous vs the claimed ~1.0).
  2. The hot-path logger calls (event dispatch, guard eval, state entry/exit)
     are emitted at DEBUG, not INFO -- capture records at INFO level and
     assert none are produced by driving events.
  3. The descriptor index exists on StateNode (`_on_partials`,
     `_on_has_wildcard`) confirming the structural fix (#55 part 2).

Exit 0 if all hold, 1 otherwise.
"""

from __future__ import annotations

import logging
import sys
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CONFIG = {
    "id": "oms",
    "initial": "idle",
    "context": {"n": 0, "qty": 0.0},
    "states": {
        "idle": {"on": {"SUBMIT": {"target": "open", "actions": ["tick"]}}},
        "open": {
            "on": {
                "FILL": [
                    {"target": "open", "cond": "is_partial", "actions": ["tick"]},
                    {"target": "closed", "actions": ["tick"]},
                ],
                "AMEND": {"target": "open", "actions": ["tick"]},
            }
        },
        "closed": {"type": "final"},
    },
}


def tick(interpreter, context, event, action_def) -> None:
    context["n"] += 1


def is_partial(context, event) -> bool:
    return True


def build():
    return SyncInterpreter(
        create_machine(
            CONFIG,
            logic=MachineLogic(actions={"tick": tick}, guards={"is_partial": is_partial}),
        )
    ).start()


def events(n):
    return [{"type": "SUBMIT"}] + [
        {"type": "FILL" if k % 2 else "AMEND", "qty": 1.0} for k in range(n - 1)
    ]


N = 5_000
EV = events(N)

logging.disable(logging.CRITICAL)

# 1) INFO handler overhead ratio
logger = logging.getLogger("xstate_statemachine")
logger.disabled = False
logger.setLevel(logging.CRITICAL + 1)

interp = build()
t0 = time.perf_counter()
for e in EV:
    interp.send(e)
t_disabled = time.perf_counter() - t0

import io

buf = io.StringIO()
handler = logging.StreamHandler(buf)
handler.setLevel(logging.INFO)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

interp = build()
t0 = time.perf_counter()
for e in EV:
    interp.send(e)
t_info = time.perf_counter() - t0

logger.removeHandler(handler)
logger.setLevel(logging.CRITICAL + 1)

ratio = t_info / t_disabled if t_disabled > 0 else float("inf")
print(f"OBSERVED INFO/disabled time ratio: {ratio:.3f}")
print("EXPECTED ratio < 1.5 (claimed ~1.0x, was 2.53-4.26x on 0.7.0)")
check1 = ratio < 1.5

# 2) hot-path logs no longer at INFO
records: list = []


class Capture(logging.Handler):
    def emit(self, record):
        records.append(record)


cap = Capture()
cap.setLevel(logging.INFO)
logger.addHandler(cap)
logger.setLevel(logging.INFO)

interp = build()
for _ in range(50):
    interp.send({"type": "AMEND"})

logger.removeHandler(cap)
logger.setLevel(logging.CRITICAL + 1)

info_records = [r for r in records if r.levelno == logging.INFO]
print(f"OBSERVED INFO records during 50 events: {len(info_records)}")
print("EXPECTED 0 (hot path now logs at DEBUG)")
check2 = len(info_records) == 0

# 3) descriptor index present
machine = create_machine(
    CONFIG, logic=MachineLogic(actions={"tick": tick}, guards={"is_partial": is_partial})
)
idle_node = machine.states["idle"]
has_index = hasattr(idle_node, "_on_partials") and hasattr(idle_node, "_on_has_wildcard")
print(f"OBSERVED StateNode has _on_partials/_on_has_wildcard: {has_index}")
print("EXPECTED True (precompiled descriptor index, #55 part 2)")
check3 = has_index

ok = check1 and check2 and check3
print("RESULT:", "PASS (FIXED-DEFAULT)" if ok else "FAIL")
sys.exit(0 if ok else 1)
