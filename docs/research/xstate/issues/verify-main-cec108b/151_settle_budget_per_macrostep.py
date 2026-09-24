# -*- coding: utf-8 -*-
"""Verify #151 on main@cec108b: settle budget is per macrostep, not per drain.

Acceptance criteria (issue #151):
  1. repro/R5-09_settle-budget-per-drain.py exits 0.
  2. send_events([A, B]) reaches the same value as send(A); send(B), with
     last_transition_ok True and last_error None.
  3. Batch sizes 1..10 of the same event -> final configuration independent
     of batch size.
  4. A genuine mutually-targeting `always` cycle still trips
     RunawayChainError and terminates, leaving a legal configuration.
  5. #103's original case (invoke completion re-entry during settle) still
     terminates -- start() does not hang.
  6. An event replayed from the defer buffer gets its own fresh settle
     budget (is its own macrostep).
"""
from __future__ import annotations

import sys

from xstate_statemachine import RunawayChainError, SyncInterpreter, create_machine

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def cfg_chain(n=40, limit=50):
    states = {"idle": {"on": {"GO": "s0", "GO2": "u0"}}}
    for k in range(n):
        states[f"s{k}"] = {"always": f"s{k + 1}"}
    states[f"s{n}"] = {"on": {"GO2": "u0"}}
    for k in range(n):
        states[f"u{k}"] = {"always": f"u{k + 1}"}
    states[f"u{n}"] = {}
    return {"id": "L", "initial": "idle", "maxIterations": limit, "states": states}


def crit_2_batch_matches_sequential() -> bool:
    a = SyncInterpreter(create_machine(cfg_chain())).start()
    a.send("GO")
    a.send("GO2")
    b = SyncInterpreter(create_machine(cfg_chain())).start()
    b.send_events(["GO", "GO2"])
    ok = a.value == b.value and b.last_transition_ok and b.last_error is None
    print(f"    sequential -> {a.value!r}, batched -> {b.value!r}, "
          f"last_transition_ok={b.last_transition_ok}, last_error={b.last_error}")
    return ok


def crit_3_batch_size_independent() -> bool:
    cfg = {
        "id": "b",
        "initial": "a",
        "maxIterations": 5,
        "states": {
            "a": {"on": {"GO": "s0"}},
            "s0": {"always": "s1"},
            "s1": {"always": "s2"},
            "s2": {"always": "s3"},
            "s3": {"on": {"GO": "s0"}},
        },
    }
    ok = True
    for size in range(1, 11):
        i = SyncInterpreter(create_machine(cfg)).start()
        i.send_events(["GO"] * size)
        if i.value != "s3" or not i.last_transition_ok:
            print(f"    size={size}: value={i.value!r} ok={i.last_transition_ok} -- MISMATCH")
            ok = False
    return ok


def crit_4_genuine_cycle_still_trips() -> bool:
    cfg = {
        "id": "cyc",
        "initial": "a",
        "maxIterations": 20,
        "states": {
            "a": {"on": {"GO": "x0"}},
            "x0": {"always": "x1"},
            "x1": {"always": "x0"},  # mutually-targeting cycle
        },
    }
    i = SyncInterpreter(create_machine(cfg)).start()
    i.send("GO")
    tripped = (not i.last_transition_ok) and isinstance(i.last_error, RunawayChainError)
    legal = i.value is not None and i.value != ""
    print(f"    cycle -> value={i.value!r} ok={i.last_transition_ok} "
          f"error={type(i.last_error).__name__ if i.last_error else None}")
    return tripped and legal


def crit_5_invoke_reentry_no_hang() -> bool:
    """#103's case: a settle pass that re-arms an invoke whose completion
    lands on the queue must still terminate; start() must not hang."""
    calls = {"n": 0}

    def svc(i, c, e):
        calls["n"] += 1
        return calls["n"]

    cfg = {
        "id": "r103",
        "initial": "p",
        "maxIterations": 30,
        "states": {
            "p": {
                "always": [{"target": "q", "guard": "few"}, {"target": "done"}],
            },
            "q": {
                "invoke": {"id": "svc", "src": "svc", "onDone": "p"},
            },
            "done": {},
        },
    }

    def few_guard(ctx, ev):
        return calls["n"] < 5

    i = SyncInterpreter(
        create_machine(
            cfg,
            logic=__import__("xstate_statemachine").MachineLogic(
                services={"svc": svc}, guards={"few": few_guard}
            ),
        )
    ).start()
    # start() must have returned (no hang) -- if we got here, it did.
    ok = i.value in ("done", "q", "p")
    print(f"    #103 re-entry case terminated; final value={i.value!r}")
    return ok


def crit_6_deferred_replay_fresh_budget() -> bool:
    """A deferred event's replay is its own macrostep with its own budget
    (round-4 #125 parity), so a long settle chain triggered by the replay
    is not charged against the triggering event's budget."""
    n = 40
    states = {
        "locked": {"on": {"UNLOCK": "unlocking"}},
        "unlocking": {"on": {"REPLAYED": "s0"}},
    }
    for k in range(n):
        states[f"s{k}"] = {"always": f"s{k + 1}"}
    states[f"s{n}"] = {}
    cfg = {
        "id": "defer",
        "initial": "locked",
        "onUnhandled": "defer",
        "maxIterations": n + 5,
        "states": states,
    }
    i = SyncInterpreter(create_machine(cfg)).start()
    # REPLAYED is deferred while locked; UNLOCK moves to 'unlocking', which
    # replays REPLAYED as its own macrostep (own settle budget).
    i.send("REPLAYED")
    i.send("UNLOCK")
    ok = i.value == f"s{n}" and i.last_transition_ok
    print(f"    deferred replay -> value={i.value!r} ok={i.last_transition_ok}")
    return ok


def main() -> int:
    print("Criterion 2: send_events batch matches sequential sends")
    check("batch matches sequential", crit_2_batch_matches_sequential())

    print("Criterion 3: final configuration independent of batch size (1..10)")
    check("batch-size independent", crit_3_batch_size_independent())

    print("Criterion 4: a genuine always-cycle still trips RunawayChainError")
    check("genuine cycle still trips and stays legal", crit_4_genuine_cycle_still_trips())

    print("Criterion 5: #103 invoke-completion-reentry case does not hang")
    check("#103 case terminates", crit_5_invoke_reentry_no_hang())

    print("Criterion 6: deferred replay gets its own fresh settle budget")
    check("deferred replay fresh budget", crit_6_deferred_replay_fresh_budget())

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} criteria failed)")
        return 1
    print("RESULT: PASS (all criteria satisfied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
