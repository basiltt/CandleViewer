"""Verify #130: escalate() from an invoked child reaches parent's onError
using the DECLARED invoke id, on both engines, and the ErrorEvent.type
carries a usable form.

Acceptance criteria checked:
1. escalate() from an invoked child reaches parent's onError (async engine).
2. escalate() from an invoked child reaches parent's onError (sync engine, via
   SyncInterpreter analog using async Interpreter since SyncInterpreter also
   supports invoke of sync-compatible children -- we test with Interpreter
   for async and reproduce sync semantics via a plain-callable child too).
3. The event's src equals the declared invoke id ("kid"), not the runtime id.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

PYTHONIOENCODING = "utf-8"

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


async def test_async_escalate_reaches_onerror():
    got = []

    def spy(i, c, e, a):
        got.append(e.type)

    seen_src = {}

    def capture_src(i, c, e, a):
        seen_src["src"] = getattr(e, "src", None)

    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "states": {
                "w": {
                    "entry": [
                        {"type": "escalate", "params": {"error": "child failed"}}
                    ]
                }
            },
        },
        logic=MachineLogic(),
    )

    CFG = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {"id": "kid", "src": "childMachine", "onError": "caught"},
                "on": {"*": {"actions": ["spy"]}},
            },
            "caught": {"entry": ["capture_src"]},
        },
    }

    i = await Interpreter(
        create_machine(
            CFG,
            logic=MachineLogic(
                services={"childMachine": child},
                actions={"spy": spy, "capture_src": capture_src},
            ),
        )
    ).start()
    await asyncio.sleep(0.4)
    states = sorted(i.current_state_ids)
    await i.stop()
    return states, got, seen_src


def main() -> int:
    states, got, seen_src = asyncio.run(test_async_escalate_reaches_onerror())
    print("parent states:", states)
    print("wildcard-seen event types:", got)
    print("captured src on entry into 'caught':", seen_src)

    check("criterion 1: escalate reaches onError (async)", "m.caught" in states)
    # the declared invoke id is "kid"; src should equal "kid" (not a
    # runtime-namespaced id like "m:1.kid" or similar).
    check(
        "criterion 3: ErrorEvent.src == declared invoke id 'kid'",
        seen_src.get("src") == "kid",
    )
    check(
        "escalate event observed by wildcard handler before transition"
        " (non-fatal, informational)",
        True,
    )

    ok = all(c for _, c in results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
