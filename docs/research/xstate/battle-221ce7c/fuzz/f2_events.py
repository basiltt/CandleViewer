"""F2 -- event-sequence fuzzer.

Drives a generated machine with a random event sequence and checks, after
every send, a set of invariants that must hold for an order-management
system:

  B1. **No unexpected exception type.** Any error out of `send` /
      `send_events` / `send_threadsafe` must be in ``ALLOWED_SEND_ERRORS``.
      A `TypeError`/`AttributeError`/`KeyError` is a defect.
  B2. **The configuration stays atomic.** Every active leaf must be
      atomic/final, every active node's parent must be active, and a
      compound state must have exactly one active child while a parallel
      state must have ALL of them active. An empty configuration on a
      running machine is a violation.
  B3. **No accepted event vanishes silently.** For every event `send`
      returned normally on, at least one observer must have fired:
      `on_event_received`, or `on_unhandled_event`, or `on_event_dropped`.
      "Accepted and then nothing happened, with no hook" is the silent
      failure the adoption standard forbids.
  B4. **`status` stays coherent.** A machine that has not been stopped and
      has no error must be `running`; `status` must be one of the four
      documented values.
  B5. **`last_error` agrees with `last_transition_ok`.** If
      `last_transition_ok` is False, `last_error` must be set (an
      additive 0.8.1 guarantee).

Event alphabet deliberately includes the hostile shapes the brief names:
unknown names, reserved/engine-shaped names, huge payloads, non-str types,
None, and malformed dict forms.

Usage:
    python f2_events.py [--cases N] [--seed S] [--engine sync|async|both]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import seed as hseed
from hypothesis import strategies as st

from common import ALLOWED_SEND_ERRORS, OUT, Recorder, exc_sig  # noqa: E402
import spin_oracle  # noqa: E402  (installs the anti-hang budget)
from spin_oracle import Spin  # noqa: E402
from gen_config import EVENTS, make_logic, valid_machine  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Event,
    Interpreter,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore")

REC = Recorder("F2 event-sequence fuzzer")
SPIN_LIMIT = 20000


# -----------------------------------------------------------------------------
# 👁️ Observer: records every hook the engine fires, per event
# -----------------------------------------------------------------------------
class Watcher(PluginBase):
    def __init__(self) -> None:
        self.received: list = []
        self.unhandled: list = []
        self.dropped: list = []
        self.errors: list = []
        self.transitions = 0

    def reset(self) -> None:
        self.received.clear()
        self.unhandled.clear()
        self.dropped.clear()
        self.errors.clear()
        self.transitions = 0

    def on_event_received(self, interp, event):  # noqa: D102
        self.received.append(getattr(event, "type", repr(event)))

    def on_unhandled_event(self, interp, event, *a, **k):  # noqa: D102
        self.unhandled.append(getattr(event, "type", repr(event)))

    def on_event_dropped(self, interp, event, reason=None, *a, **k):  # noqa: D102
        self.dropped.append((getattr(event, "type", repr(event)), reason))

    def on_transition(self, *a, **k):  # noqa: D102
        self.transitions += 1

    def on_error(self, interp, error, *a, **k):  # noqa: D102
        self.errors.append(type(error).__name__)


# -----------------------------------------------------------------------------
# ✉️ Hostile event alphabet
# -----------------------------------------------------------------------------
RESERVED_SHAPED = [
    "done.invoke.NEVER",
    "done.state.NOPE",
    "error.platform.NOPE",
    "after.9999999",
    "xstate.whatever",
    "___xstate_forged",
    "done.review",  # #79's example: a legitimate business name
]

MALFORMED_EVENTS = [
    None,
    123,
    12.5,
    True,
    b"BYTES",
    [],
    ["GO"],
    (),
    {"no_type_key": 1},
    {"type": None},
    {"type": 123},
    {"type": ""},
    {"type": "GO", "payload": "not-a-dict"},
    set(),
    object(),
]


@st.composite
def an_event(draw):
    """One event to send, plus a tag describing its class."""
    kind = draw(
        st.sampled_from(
            [
                "known",
                "known",
                "known",
                "unknown",
                "reserved",
                "malformed",
                "huge",
                "obj",
                "unicode",
            ]
        )
    )
    if kind == "known":
        return ("known", draw(st.sampled_from(EVENTS)))
    if kind == "unknown":
        return ("unknown", draw(st.sampled_from(["NOPE", "typo", "", " "])))
    if kind == "reserved":
        return ("reserved", draw(st.sampled_from(RESERVED_SHAPED)))
    if kind == "malformed":
        i = draw(st.integers(min_value=0, max_value=len(MALFORMED_EVENTS) - 1))
        return ("malformed", MALFORMED_EVENTS[i])
    if kind == "huge":
        n = draw(st.sampled_from([1000, 50000]))
        return (
            "huge",
            {"type": draw(st.sampled_from(EVENTS)), "blob": "x" * n},
        )
    if kind == "obj":
        return (
            "obj",
            Event(type=draw(st.sampled_from(EVENTS + ["NOPE"])), payload={"k": 1}),
        )
    return ("unicode", draw(st.sampled_from(["GØ", "事件", "\x00NUL", "💥"])))


# -----------------------------------------------------------------------------
# 🔬 Invariants
# -----------------------------------------------------------------------------
def check_configuration(interp) -> str:
    """B2: returns "" when the configuration is legal, else a reason."""
    active = set(interp._active_state_nodes)
    if interp.status != "running":
        return ""
    if not active:
        return "empty configuration on a running machine"
    for node in active:
        if node.parent is not None and node.parent not in active:
            return f"active node {node.id} whose parent {node.parent.id} is inactive"
    for node in active:
        kids = getattr(node, "states", None)
        if not kids:
            continue
        active_kids = [c for c in kids.values() if c in active]
        if node.type == "parallel":
            if len(active_kids) != len(kids):
                return (
                    f"parallel {node.id}: {len(active_kids)}/{len(kids)} "
                    f"regions active"
                )
        else:
            if len(active_kids) != 1:
                return (
                    f"compound {node.id}: {len(active_kids)} active children "
                    f"(expected exactly 1)"
                )
    leaves = [
        n
        for n in active
        if not getattr(n, "states", None)
    ]
    if not leaves:
        return "no atomic leaf in the configuration"
    return ""


VALID_STATUS = {"uninitialized", "running", "stopped", "error", "done"}


def check_after_send(interp, watcher, tag, ev, sent_ok, repro) -> None:
    """Applies B2 / B3 / B4 / B5 and records any violation."""
    reason = check_configuration(interp)
    if reason:
        REC.bump("inv.B2.non_atomic")
        REC.record(
            "B2-illegal-configuration",
            reason.split(":")[0],
            f"after {tag} event {ev!r}: {reason}",
            repro,
            len(json.dumps(repro, default=str)),
        )

    if interp.status not in VALID_STATUS:
        REC.bump("inv.B4.bad_status")
        REC.record(
            "B4-undocumented-status",
            str(interp.status),
            f"status={interp.status!r} is not one of {sorted(VALID_STATUS)}",
            repro,
            len(json.dumps(repro, default=str)),
        )

    if sent_ok and tag in ("known", "obj"):
        saw = (
            watcher.received
            or watcher.unhandled
            or watcher.dropped
            or watcher.transitions
        )
        if not saw:
            REC.bump("inv.B3.silent_loss")
            REC.record(
                "B3-accepted-event-with-no-observer",
                tag,
                f"send({ev!r}) returned normally; no on_event_received / "
                f"on_unhandled_event / on_event_dropped / on_transition fired",
                repro,
                len(json.dumps(repro, default=str)),
            )

    if interp.last_transition_ok is False and interp.last_error is None:
        REC.bump("inv.B5.error_missing")
        REC.record(
            "B5-failed-step-without-last_error",
            "last_error-None",
            "last_transition_ok is False but last_error is None",
            repro,
            len(json.dumps(repro, default=str)),
        )


# -----------------------------------------------------------------------------
# 🏃 One sync trial
# -----------------------------------------------------------------------------
def trial_sync(cfg, events, strict) -> None:
    REC.cases += 1
    repro = {
        "engine": "sync",
        "strict": strict,
        "config": cfg,
        "events": [
            e if isinstance(e, (str, int, float, bool, type(None), dict, list))
            else repr(e)
            for _, e in events
        ],
        "tags": [t for t, _ in events],
    }
    try:
        machine = create_machine(cfg, logic=make_logic(sync=True))
    except Exception:
        REC.bump("setup.build_rejected")
        return
    watcher = Watcher()
    spin_oracle._STATE["n"] = 0
    spin_oracle._STATE["limit"] = SPIN_LIMIT
    try:
        interp = SyncInterpreter(machine, strict=strict)
        interp.use(watcher)
        interp.start()
    except Spin:
        REC.bump("setup.start_never_settles")
        return
    except Exception:
        REC.bump("setup.start_failed")
        return

    for tag, ev in events:
        watcher.reset()
        spin_oracle._STATE["n"] = 0
        sent_ok = False
        try:
            interp.send(ev)
            sent_ok = True
            REC.bump(f"send.{tag}.ok")
        except Spin:
            REC.bump(f"send.{tag}.never_settles")
            REC.record(
                "B1-send-does-not-terminate",
                tag,
                f"send({ev!r}) exceeded {SPIN_LIMIT} selections without "
                f"settling",
                repro,
                len(json.dumps(repro, default=str)),
            )
            break
        except ALLOWED_SEND_ERRORS:
            REC.bump(f"send.{tag}.typed_error")
        except RecursionError as exc:
            REC.bump(f"send.{tag}.recursion")
            REC.record(
                "B1-untyped-send-error",
                f"{tag}/RecursionError",
                f"send({ev!r}) -> RecursionError",
                repro,
                len(json.dumps(repro, default=str)),
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            REC.bump(f"send.{tag}.untyped")
            REC.record(
                "B1-untyped-send-error",
                f"{tag}/{exc_sig(exc)}",
                f"send({ev!r}) -> {type(exc).__name__}: {exc}",
                repro,
                len(json.dumps(repro, default=str)),
                exc,
            )
        check_after_send(interp, watcher, tag, ev, sent_ok, repro)

    try:
        interp.stop()
    except Exception:
        REC.bump("teardown.stop_failed")


# -----------------------------------------------------------------------------
# 🏃 One async trial
# -----------------------------------------------------------------------------
async def trial_async(cfg, events, strict) -> None:
    REC.cases += 1
    repro = {
        "engine": "async",
        "strict": strict,
        "config": cfg,
        "events": [
            e if isinstance(e, (str, int, float, bool, type(None), dict, list))
            else repr(e)
            for _, e in events
        ],
        "tags": [t for t, _ in events],
    }
    try:
        machine = create_machine(cfg, logic=make_logic(sync=False))
    except Exception:
        REC.bump("setup.build_rejected")
        return
    watcher = Watcher()
    spin_oracle._STATE["n"] = 0
    spin_oracle._STATE["limit"] = SPIN_LIMIT
    try:
        interp = Interpreter(machine, strict=strict)
        interp.use(watcher)
        await asyncio.wait_for(interp.start(), timeout=5)
    except (Spin, asyncio.TimeoutError):
        REC.bump("setup.start_never_settles")
        return
    except Exception:
        REC.bump("setup.start_failed")
        return

    for tag, ev in events:
        watcher.reset()
        spin_oracle._STATE["n"] = 0
        sent_ok = False
        try:
            await asyncio.wait_for(interp.send(ev, wait=True), timeout=5)
            sent_ok = True
            REC.bump(f"send.{tag}.ok")
        except (Spin, asyncio.TimeoutError):
            REC.bump(f"send.{tag}.never_settles")
            REC.record(
                "B1-send-does-not-terminate",
                f"async/{tag}",
                f"await send({ev!r}, wait=True) did not resolve",
                repro,
                len(json.dumps(repro, default=str)),
            )
            break
        except ALLOWED_SEND_ERRORS:
            REC.bump(f"send.{tag}.typed_error")
        except Exception as exc:  # noqa: BLE001
            REC.bump(f"send.{tag}.untyped")
            REC.record(
                "B1-untyped-send-error",
                f"async/{tag}/{exc_sig(exc)}",
                f"send({ev!r}) -> {type(exc).__name__}: {exc}",
                repro,
                len(json.dumps(repro, default=str)),
                exc,
            )
        check_after_send(interp, watcher, tag, ev, sent_ok, repro)

    try:
        await asyncio.wait_for(interp.stop(), timeout=5)
    except Exception:
        REC.bump("teardown.stop_failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260918)
    ap.add_argument(
        "--engine", choices=["sync", "async", "both"], default="both"
    )
    ap.add_argument("--out", default="f2_events.json")
    args = ap.parse_args()

    common = dict(
        deadline=None,
        suppress_health_check=list(HealthCheck),
        phases=[Phase.generate],
        database=None,
    )
    n_sync = args.cases if args.engine == "sync" else (
        0 if args.engine == "async" else int(args.cases * 0.8)
    )
    n_async = args.cases - n_sync

    if n_sync:

        @hseed(args.seed)
        @settings(max_examples=n_sync, **common)
        @given(
            valid_machine(max_depth=3),
            st.lists(an_event(), min_size=1, max_size=8),
            st.booleans(),
        )
        def run_sync(cfg, events, strict):
            trial_sync(cfg, events, strict)

        run_sync()

    if n_async:
        loop = asyncio.new_event_loop()

        @hseed(args.seed + 7)
        @settings(max_examples=n_async, **common)
        @given(
            valid_machine(max_depth=3),
            st.lists(an_event(), min_size=1, max_size=5),
            st.booleans(),
        )
        def run_async(cfg, events, strict):
            loop.run_until_complete(trial_async(cfg, events, strict))

        run_async()
        loop.close()

    REC.report()
    REC.dump(os.path.join(OUT, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
