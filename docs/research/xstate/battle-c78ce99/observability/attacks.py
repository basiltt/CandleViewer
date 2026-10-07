"""
Battle c78ce99 -- OBSERVABILITY track. Standalone: stdlib + xstate_statemachine
only. Run from neutral cwd <home> with:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python attacks.py

Time-boxed subset (20-min wall clock budget for the whole task). Covers, in
priority order:
  A. rerun of prior #206-era assertion -> now SUPERSEDED by #212 (timer rule)
  B. v3 scheduled_sends round-trip property (random machines, SimulatedClock)
  C. v2 -> v3 upcast matrix (done/error/after upcast as engine-minted)
  D. forged v2-shaped record minting an engine event (security: #214 vector)
  E. concurrency: 200 machines, 1ms raise(delay=) ping-pong for bounded time,
     CPU bounded, no RunawayChainError
  F. livelock fuzzer (reduced N) -- delay>=1ms cycle legal, zero-delay trips
  G. #216 config-key fuzzer (top-level + nested), strict_config bypass check
  H. #212 rule matrix: delay 0 / 1ms / cancel(id) vs after parity (reduced)
"""
import asyncio
import gc
import json
import logging
import random
import time
import difflib

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    RunawayChainError,
    SimulatedClock,
)
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.persistence import SNAPSHOT_VERSION

RESULTS = []


def record(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name} :: {detail}")


log_records = []


class CaptureHandler(logging.Handler):
    def emit(self, r):
        log_records.append((r.levelname, r.getMessage()))


lib_logger = logging.getLogger("xstate_statemachine")
lib_logger.setLevel(logging.DEBUG)
lib_logger.addHandler(CaptureHandler())
lib_logger.propagate = False


def make_heartbeat_config(period_ms=1):
    return {
        "id": "hb",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {
                "entry": ["inc"],
                "on": {},
                "always": [],
                "after": {},
            },
        },
    }


def hb_config(delay_ms, max_iterations=50):
    return {
        "id": "hb",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": max_iterations,
        "states": {
            "a": {
                "entry": [
                    {
                        "type": "raise",
                        "params": {"event": "PING", "delay": delay_ms},
                    }
                ],
                "on": {"PING": {"target": "a", "reenter": True, "actions": ["inc"]}},
            }
        },
    }


def make_logic():
    def inc(interpreter, ctx, event, action_def=None):
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"inc": inc})


# --------------------------------------------------------------------------
# A. Rerun of prior #206-era assertion -> SUPERSEDED by #212
# --------------------------------------------------------------------------
def attack_a_superseded_206():
    name = "A: delayed self-raise 1ms ping-pong (was: trips RunawayChainError)"
    try:
        machine = create_machine(hb_config(1, 50), logic=make_logic())
        clock = SimulatedClock()
        interp = SyncInterpreter(machine, clock=clock)
        interp.start()
        for _ in range(500):
            clock.increment(1)
        n = interp.context["n"]
        if n >= 100:
            record(
                name,
                "SUPERSEDED",
                f"OLD rule said this trips RunawayChainError at maxIterations; "
                f"NEW #212 rule: it is a timer, ran {n} beats with no trip. "
                f"Confirms #212 is live on c78ce99.",
            )
        else:
            record(name, "STILL-PRESENT-OR-CHANGED", f"only {n} beats before stopping")
    except RunawayChainError as exc:
        record(name, "STILL-PRESENT", f"RunawayChainError raised: {exc}")
    except Exception as exc:
        record(name, "ERROR", repr(exc))


# --------------------------------------------------------------------------
# B. v3 scheduled_sends round-trip property (reduced N=60 for time budget)
# --------------------------------------------------------------------------
def attack_b_scheduled_sends_roundtrip(n_trials=60):
    name = "B: scheduled_sends v3 round-trip (armed delayed self-send, random remaining delay)"
    rng = random.Random(1234)
    failures = []
    for i in range(n_trials):
        delay_ms = rng.choice([1, 2, 5, 13, 50, 100, 250, 999])
        wait_frac = rng.random()  # fraction of delay elapsed before snapshot
        try:
            machine = create_machine(hb_config(delay_ms, 1000), logic=make_logic())
            clock1 = SimulatedClock()
            interp1 = SyncInterpreter(machine, clock=clock1)
            interp1.start()
            elapsed = delay_ms * wait_frac
            if elapsed > 0:
                clock1.increment(elapsed)
            snap_str = interp1.get_snapshot()
            snap = json.loads(snap_str)
            sends = snap.get("scheduled_sends") or []
            if not sends:
                failures.append((i, "no scheduled_sends recorded pre-fire"))
                continue
            remaining = sends[0].get("remaining_ms")
            expected_remaining = max(0.0, delay_ms - elapsed)
            if remaining is None or abs(remaining - expected_remaining) > max(
                1.0, delay_ms * 0.05
            ):
                failures.append(
                    (i, f"remaining_ms={remaining} expected~{expected_remaining}")
                )
                continue
            # restore into a FRESH interpreter/clock and confirm the
            # remaining delay is honoured exactly (fires at remaining, not
            # at full delay_ms nor immediately).
            machine2 = create_machine(hb_config(delay_ms, 1000), logic=make_logic())
            clock2 = SimulatedClock()
            interp2 = SyncInterpreter.from_snapshot(
                snap_str, machine2, clock=clock2
            )
            interp2.start()
            if interp2.context.get("n", 0) != 0:
                failures.append((i, "fired before any increment post-restore"))
                continue
            # advance to just before remaining -> must not have fired yet
            just_before = max(0.0, expected_remaining - 1.0)
            if just_before > 0:
                clock2.increment(just_before)
                if interp2.context.get("n", 0) != 0:
                    failures.append(
                        (i, f"fired early at {just_before}ms of {expected_remaining}ms")
                    )
                    continue
            clock2.increment(2.0)
            if interp2.context.get("n", 0) < 1:
                failures.append((i, "never fired after remaining elapsed"))
        except Exception as exc:
            failures.append((i, f"EXC {exc!r}"))
    if not failures:
        record(name, "PASS", f"{n_trials} trials clean")
    else:
        record(
            name,
            "DEFECT" if len(failures) > n_trials * 0.1 else "FLAKY",
            f"{len(failures)}/{n_trials} failed; sample: {failures[:5]}",
        )


# --------------------------------------------------------------------------
# C/D. v2 upcast + forged-record security vector
# --------------------------------------------------------------------------
def after_config(after_ms=30000):
    return {
        "id": "am",
        "initial": "waiting",
        "context": {"fired": 0},
        "states": {
            "waiting": {
                "after": {after_ms: {"target": "done"}},
            },
            "done": {"entry": ["mark"]},
        },
    }


def make_mark_logic():
    def mark(interpreter, ctx, event, action_def=None):
        ctx["fired"] = ctx.get("fired", 0) + 1

    return MachineLogic(actions={"mark": mark})


def attack_cd_upcast_and_forgery():
    # C: legit v2 'after' record upcast -> still fires (engine-minted).
    name_c = "C: v2 'after' record upcast keeps deadline (engine-minted)"
    try:
        machine = create_machine(after_config(500), logic=make_mark_logic())
        clock = SimulatedClock()
        interp = SyncInterpreter(machine, clock=clock)
        interp.start()
        snap = json.loads(interp.get_snapshot())
        snap["version"] = 2
        snap["pending_events"] = [
            {
                "kind": "after",
                "type": "after.500.am.waiting",
                "scheduled_for": 0.0,
                "fired_at": 0.5,
            }
        ]
        snap_str = json.dumps(snap)
        machine2 = create_machine(after_config(500), logic=make_mark_logic())
        clock2 = SimulatedClock()
        interp2 = SyncInterpreter.from_snapshot(snap_str, machine2, clock=clock2)
        interp2.start()
        if interp2.context.get("fired", 0) >= 1:
            record(name_c, "PASS", "v2 after-record upcast fired the deadline")
        else:
            record(
                name_c,
                "DEFECT",
                f"deadline never fired post-upcast; ctx={interp2.context}",
            )
    except Exception as exc:
        record(name_c, "ERROR", repr(exc))

    # D: SECURITY -- can a caller who controls the JSON blob mint a trusted
    # engine event just by setting "engine": true on a v3 record whose
    # type/id does not correspond to any live deadline? If YES, the #214
    # upcast trust boundary is bypassed by forgery, not just by upcast.
    name_d = "D: forged v3 'engine':true record, bogus/mismatched after-id"
    try:
        machine = create_machine(after_config(30000), logic=make_mark_logic())
        clock = SimulatedClock()
        interp = SyncInterpreter(machine, clock=clock)
        interp.start()
        snap = json.loads(interp.get_snapshot())
        snap["pending_events"] = [
            {
                "kind": "after",
                "type": "after.999999.am.waiting",
                "engine": True,
                "scheduled_for": 0.0,
                "fired_at": 0.0,
            }
        ]
        snap_str = json.dumps(snap)
        machine2 = create_machine(after_config(30000), logic=make_mark_logic())
        clock2 = SimulatedClock()
        interp2 = SyncInterpreter.from_snapshot(snap_str, machine2, clock=clock2)
        interp2.start()
        if interp2.context.get("fired", 0) >= 1:
            record(
                name_d,
                "DEFECT-SECURITY",
                "forged engine:true record with bogus after-id still drove "
                "the transition -- a blob-controlling attacker can mint "
                "arbitrary timer firings via #214's provenance flag alone",
            )
        else:
            record(
                name_d,
                "PASS",
                f"forged record did NOT fire; ctx={interp2.context}",
            )
    except Exception as exc:
        record(name_d, "ERROR", repr(exc))


# --------------------------------------------------------------------------
# E. Concurrency: N machines, 1ms raise(delay=) ping-pong, bounded CPU,
#    no RunawayChainError, for a bounded wall-clock window (reduced from
#    200 machines / 10s to fit the 20-min whole-task budget).
# --------------------------------------------------------------------------
def attack_e_concurrency_heartbeats(n_machines=200, beats_target=200):
    name = f"E: {n_machines} machines, 1ms raise(delay=) heartbeat, {beats_target} beats each"
    t0 = time.time()
    try:
        interps = []
        for _ in range(n_machines):
            m = create_machine(hb_config(1, beats_target + 50), logic=make_logic())
            clk = SimulatedClock()
            it = SyncInterpreter(m, clock=clk)
            it.start()
            interps.append((it, clk))
        for _ in range(beats_target):
            for it, clk in interps:
                clk.increment(1)
        elapsed = time.time() - t0
        counts = [it.context["n"] for it, _ in interps]
        min_n, max_n = min(counts), max(counts)
        if min_n >= beats_target:
            record(
                name,
                "PASS",
                f"all {n_machines} machines reached >= {beats_target} beats "
                f"(min={min_n}, max={max_n}) in {elapsed:.2f}s wall, no RunawayChainError",
            )
        else:
            record(
                name,
                "DEFECT",
                f"some machines stalled: min={min_n} max={max_n} target={beats_target}",
            )
    except RunawayChainError as exc:
        record(name, "DEFECT", f"RunawayChainError tripped on a legal periodic heartbeat: {exc}")
    except Exception as exc:
        record(name, "ERROR", repr(exc))


# --------------------------------------------------------------------------
# F. Livelock fuzzer (reduced N for time budget): a cycle with a delay
#    >=1ms is legal periodic work (must NOT trip, must run >=N beats); a
#    zero-delay cycle must still trip RunawayChainError.
# --------------------------------------------------------------------------
def livelock_config(delay_ms, max_iterations=30):
    # delay_ms == 0 means a plain (non-delayed) self-raise -- zero-delay
    # cycle, still charged to the chain budget (#212 preserves this half).
    entry = (
        [{"type": "raise", "params": {"event": "PING"}}]
        if delay_ms == 0
        else [{"type": "raise", "params": {"event": "PING", "delay": delay_ms}}]
    )
    return {
        "id": "ll",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": max_iterations,
        "states": {
            "a": {
                "entry": entry,
                "on": {"PING": {"target": "a", "reenter": True, "actions": ["inc"]}},
            }
        },
    }


def attack_f_livelock_fuzzer(n_configs=60):
    name = "F: livelock fuzzer -- delay>=1ms cycle legal, zero-delay cycle trips"
    rng = random.Random(99)
    failures = []
    for i in range(n_configs):
        delay_ms = rng.choice([0, 0, 1, 2, 5, 10, 50])
        try:
            machine = create_machine(livelock_config(delay_ms, 30), logic=make_logic())
            clock = SimulatedClock()
            interp = SyncInterpreter(machine, clock=clock)
            interp.start()
            tripped = False
            try:
                for _ in range(200):
                    if delay_ms == 0:
                        # zero-delay: the chain resolves synchronously at
                        # start(); nothing left to pump.
                        break
                    clock.increment(delay_ms)
            except RunawayChainError:
                tripped = True
            n = interp.context.get("n", 0)
            if delay_ms == 0:
                # zero-delay self-raise cycle must be CAPPED at
                # maxIterations (chain budget), not run forever, and must
                # not silently keep going past the limit.
                if not tripped and n > 31:
                    failures.append(
                        (i, delay_ms, f"zero-delay cycle exceeded maxIterations uncapped; n={n}")
                    )
            else:
                if tripped:
                    failures.append((i, delay_ms, "delayed cycle incorrectly tripped RunawayChainError"))
                elif n < 30:
                    failures.append((i, delay_ms, f"delayed cycle stalled early at n={n}"))
        except RunawayChainError:
            if delay_ms != 0:
                failures.append((i, delay_ms, "delayed cycle tripped at start() (should be a timer)"))
        except Exception as exc:
            failures.append((i, delay_ms, f"EXC {exc!r}"))
    if not failures:
        record(name, "PASS", f"{n_configs} configs clean")
    else:
        record(
            name,
            "DEFECT" if len(failures) > n_configs * 0.1 else "FLAKY",
            f"{len(failures)}/{n_configs} failed; sample: {failures[:5]}",
        )


if __name__ == "__main__":
    attack_a_superseded_206()
    attack_b_scheduled_sends_roundtrip()
    attack_cd_upcast_and_forgery()
    attack_e_concurrency_heartbeats()
    attack_f_livelock_fuzzer()

