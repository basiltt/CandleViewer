"""Verify issue #77 (N-03) on main @ 5e07ba8.

Prior disposition (post-3c527b0/77.md): criteria 1-5 fixed; criterion 6
("overflow raises rather than silently discarding") was the reopened
residual. CHANGELOG [Unreleased] claims budgeting now applies only to
*self-generated* work (raise / self-send / due timer / sync onDone), that
external batches of any size are processed in full, that the trip is
observable (receipt carries RunawayChainError, last_error set,
on_event_dropped(reason="chain_budget")), that `tripped` is per-chain
(#88), and that completions are never discarded even during a trip (#94).
"""

import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)


# --- Original N-03 repro: large external batch is not truncated ------------
CFG_BATCH = {
    "id": "bud",
    "initial": "a",
    "context": {"seen": 0},
    "states": {
        "a": {
            "on": {
                "T": {
                    "target": "a",
                    "actions": ["bump"],
                    "reenter": True,
                }
            }
        }
    },
}


def bump(i, ctx, event, action):
    ctx["seen"] = ctx.get("seen", 0) + 1


def crit_batch_not_truncated(n: int) -> int:
    i = SyncInterpreter(
        create_machine(CFG_BATCH, logic=MachineLogic(actions={"bump": bump}))
    )
    i.start()
    i.send_events(["T"] * n)
    seen, depth = i.context["seen"], i.queue_depth
    i.stop()
    return seen, depth


# --- Criterion 6: overflow of a genuine runaway is observable, not silent --
CFG_SPIN = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 10,
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "actions": [
                        "cnt",
                        {"type": "raise", "params": {"event": "SPIN"}},
                    ]
                }
            }
        }
    },
}


def crit6_overflow_observable() -> dict:
    dropped = []

    class Spy(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            dropped.append(reason)

    i = SyncInterpreter(
        create_machine(CFG_SPIN, logic=MachineLogic(actions={"cnt": bump}))
    ).use(Spy())
    i.start()
    r = i.send("SPIN", wait=True)
    out = {
        "receipt_error": type(r.error).__name__ if r.error else None,
        "last_transition_ok": i.last_transition_ok,
        "last_error": type(i.last_error).__name__ if i.last_error else None,
        "running": i.status == "running",
        "dropped_reasons": set(dropped),
    }
    i.stop()
    return out


# --- #88: tripped is per-chain, doesn't starve unrelated queued events -----
CFG_PERCHAIN = {
    "id": "m2",
    "initial": "a",
    "context": {"inner": 0, "spin": 0},
    "maxIterations": 50,
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "actions": [
                        "cs",
                        {"type": "raise", "params": {"event": "SPIN"}},
                    ]
                },
                "WORK": {
                    "actions": [
                        {"type": "raise", "params": {"event": "INNER"}}
                    ]
                },
                "INNER": {"actions": "ci"},
            }
        }
    },
}


def crit_per_chain() -> dict:
    i = SyncInterpreter(
        create_machine(
            CFG_PERCHAIN,
            logic=MachineLogic(
                actions={"cs": bump_key("spin"), "ci": bump_key("inner")}
            ),
        )
    )
    i.start()
    i.send_events(["SPIN"] + ["WORK"] * 5)
    out = {"inner": i.context["inner"], "spin": i.context["spin"]}
    i.stop()
    return out


def bump_key(key):
    def _fn(i, ctx, event, action):
        ctx[key] = ctx.get(key, 0) + 1

    return _fn


# --- #94: completions never discarded, even during a trip ------------------
CFG_COMPLETION = {
    "id": "m3",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 5,
    "states": {
        "a": {
            "invoke": {"src": "svc", "id": "svc", "onDone": "done"},
            "on": {
                "SPIN": {
                    "actions": [{"type": "raise", "params": {"event": "SPIN"}}]
                }
            },
        },
        "done": {},
    },
}


def crit_completion_survives() -> str:
    i = SyncInterpreter(
        create_machine(
            CFG_COMPLETION,
            logic=MachineLogic(services={"svc": lambda i, c, e: 1}),
        )
    )
    i.start()
    v = i.value
    i.stop()
    return v


def main() -> int:
    seen1501, depth1501 = crit_batch_not_truncated(1501)
    seen5000, depth5000 = crit_batch_not_truncated(5000)
    overflow = crit6_overflow_observable()
    per_chain = crit_per_chain()
    completion_value = crit_completion_survives()

    print(f"Batch 1501: seen={seen1501} queue_depth={depth1501} (expect 1501, 0)")
    print(f"Batch 5000: seen={seen5000} queue_depth={depth5000} (expect 5000, 0)")
    print("Overflow observable (criterion 6):", overflow)
    print("Per-chain (#88):", per_chain, "(expect inner=5, spin=51)")
    print("Completion survives trip (#94): value =", completion_value, "(expect 'done')")

    ok = (
        seen1501 == 1501 and depth1501 == 0
        and seen5000 == 5000 and depth5000 == 0
        and overflow["receipt_error"] == "RunawayChainError"
        and overflow["last_transition_ok"] is False
        and overflow["last_error"] == "RunawayChainError"
        and overflow["running"] is True
        and overflow["dropped_reasons"] == {"chain_budget"}
        and per_chain == {"inner": 5, "spin": 51}
        and completion_value == "done"
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
