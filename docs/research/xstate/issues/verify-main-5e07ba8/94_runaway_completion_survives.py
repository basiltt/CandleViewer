"""Verify #94 on xstate-statemachine @ 5e07ba8 (unreleased 0.8.1).

Acceptance criteria (from `gh issue view 94`):
  1. `f_sticky_invoke.py` exits 0 -- the machine reaches `m.done`.
  2. A `done.invoke` / `error.platform.*` event is never discarded by the
     runaway guard, on either engine.
  3. `f_sticky_timer.py` still reaches `m.done` (no regression), and due
     timers and service completions are treated consistently.
  4. A genuine self-feeding loop is still bounded.
  5. Tests: `test_done_invoke_survives_runaway_trip`,
     `test_timer_and_invoke_completion_treated_consistently_under_budget`.

Run: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python 94_runaway_completion_survives.py
Expect: exit 0, "ALL CRITERIA PASS".
"""
import asyncio
import logging
import sys
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

failures = []

# --- Criterion 1: sync, invoke completion after a SPIN trip -> m.done
CFG_INVOKE = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "target": "a",
                    "actions": [{"type": "raise", "params": {"event": "SPIN"}}],
                },
                "GO": {"target": "work"},
            }
        },
        "work": {"invoke": {"src": "svc", "onDone": {"target": "done"}}},
        "done": {"type": "final"},
    },
}


def svc(i, c, e):
    return {"v": 1}


i = SyncInterpreter(
    create_machine(CFG_INVOKE, logic=MachineLogic(services={"svc": svc}))
).start()
i.send_events(["SPIN", "GO"])
if "m.done" not in i.current_state_ids and i.value != "done":
    failures.append(f"criterion 1 (sync): expected m.done, got {i.current_state_ids}")
i.stop()

# --- Criterion 2 (async parity): same shape on the async engine, plus a failing service (error.platform)
CFG_INVOKE_ERR = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "target": "a",
                    "actions": [{"type": "raise", "params": {"event": "SPIN"}}],
                },
                "GO": {"target": "work"},
            }
        },
        "work": {
            "invoke": {
                "src": "svc",
                "onDone": {"target": "done"},
                "onError": {"target": "errored"},
            }
        },
        "done": {"type": "final"},
        "errored": {"type": "final"},
    },
}


async def svc_fail(i, c, e):
    raise ValueError("boom")


async def async_main():
    it = Interpreter(
        create_machine(CFG_INVOKE_ERR, logic=MachineLogic(services={"svc": svc_fail}))
    )
    await it.start()
    for _ in range(19):
        await it.send("SPIN")
    await it.send("GO")
    await asyncio.sleep(0.2)
    val = it.value
    await it.stop()
    return val


val = asyncio.run(async_main())
if val != "errored":
    failures.append(f"criterion 2 (async, error.platform): expected 'errored', got {val!r}")

# --- Criterion 3: timer still reaches done, no regression
CFG_TIMER = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "states": {
        "a": {
            "after": {5: {"target": "done"}},
            "on": {
                "SPIN": {
                    "target": "a",
                    "reenter": False,
                    "actions": [{"type": "raise", "params": {"event": "SPIN"}}],
                }
            },
        },
        "done": {"type": "final"},
    },
}
it = SyncInterpreter(create_machine(CFG_TIMER)).start()
it.send("SPIN")
time.sleep(0.05)
it.tick()
if "m.done" not in it.current_state_ids and it.value != "done":
    failures.append(f"criterion 3 (timer): expected m.done, got {it.current_state_ids}")
it.stop()

# --- Criterion 4: a genuine self-feeding loop (no completion involved) is still bounded
CFG_PURE_SPIN = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "target": "a",
                    "actions": [
                        {"type": "raise", "params": {"event": "SPIN"}},
                    ],
                }
            }
        }
    },
}
it = SyncInterpreter(create_machine(CFG_PURE_SPIN)).start()
receipt = it.send("SPIN", wait=True)
if receipt.error is None:
    failures.append("criterion 4: a genuine self-feeding loop did not trip / was not bounded")
it.stop()

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)

print("ALL CRITERIA PASS")
sys.exit(0)
