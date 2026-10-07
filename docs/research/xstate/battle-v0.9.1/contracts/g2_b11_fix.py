# -*- coding: utf-8 -*-
"""G2: root-cause + fix proof for the two B11 findings seen in G1.

FINDING-1 (OUR-CONTRACT): `degraded.on.STREAM_HEALTHY` ranks an
`all_streams_healthy` guard AHEAD of the `mark_stream_healthy` action, so the
guard reads the PRE-action context in which the stream is still unhealthy.
The recovery arm can therefore never be taken: B11 is a one-way trip into
`degraded`. XState v5 / SCXML both evaluate guards against the context before
the transition's actions run, so this is our chart, not the engine.

FINDING-2 (OUR-CONTRACT): `degraded` has no `GAP_DETECTED` handler, and root
`onUnhandled: "defer"` swallows it -- gap telemetry stops exactly while the
session is degraded, which is when gaps happen.

Both are closed by logic/config-only edits, proven below on both engines.
STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, copy, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
from g1_b11_b12 import b11_stub, _bad  # noqa: E402
os.chdir("<home>")

SCRIPT = [
    ("REASON_ADDED", {"reason": "user"}),
    ("STREAM_UNHEALTHY", {"stream": "trades"}),
    ("STREAM_HEALTHY", {"stream": "trades"}),
    ("GAP_DETECTED", {}),
    ("REASON_REMOVED", {}),
    ("LINGER_DUE", {}),
]


async def confirm_root_cause():
    """Prove the guard sees the PRE-action context."""
    c = K.cfg("B11")
    seen = []

    def spy(ctx, e):
        seen.append(dict(ctx.get("streams_healthy") or {}))
        return all((ctx.get("streams_healthy") or {}).values())

    st = b11_stub(c, guard_vals={"all_streams_healthy": spy})
    r = await K.drive(c, st, SCRIPT[:3], snapshots=False)
    K.rec("G2.B11.rootcause.guard_sees_pre_action_ctx",
          seen and seen[-1].get("trades") is False,
          "guard saw streams_healthy=%s -> stayed %s" % (seen, r["states"]))
    K.rec("G2.B11.rootcause.wedged_in_degraded",
          r["states"] == ["recording.degraded"], "states=%s" % r["states"])


def fix_guard(c):
    """No config change needed for FINDING-1: the guard is OUR code and must
    be written event-aware -- 'every stream healthy once THIS event is
    applied'. This is the NEEDS-WRAPPER shape the OMS must ship."""
    return c


def event_aware_guard(ctx, e):
    h = dict(ctx.get("streams_healthy") or {})
    s = getattr(e, "payload", {}).get("stream")
    if s is not None:
        h[s] = True
    return bool(h) and all(h.values())


def event_aware_reasons_remain(ctx, e):
    """Same class as FINDING-1: `REASON_REMOVED` ranks `reasons_remain`
    ahead of its own `remove_reason` action, so the guard counts the reason
    that is about to be dropped. Must be read as 'reasons remaining AFTER
    this removal'."""
    return len(ctx.get("reasons") or []) - 1 > 0


def fix_gap(c):
    """FINDING-2 config-only: degraded also counts gaps."""
    c = copy.deepcopy(c)
    c["states"]["degraded"]["on"]["GAP_DETECTED"] = {
        "actions": ["bump_gap_count", "emit_gap_metric"]}
    return c


async def fix_proof():
    c = fix_gap(K.cfg("B11"))
    st = b11_stub(c, guard_vals={
        "all_streams_healthy": event_aware_guard,
        "reasons_remain": event_aware_reasons_remain})
    r = await K.drive(c, st, SCRIPT)
    K.rec("G2.B11.fixed.lands_stopped", r["states"] == ["recording.stopped"],
          "states=%s ctx=%s" % (r["states"], r["context"]))
    K.rec("G2.B11.fixed.gap_counted", r["context"]["gap_count_24h"] == 1,
          "gap=%r" % r["context"]["gap_count_24h"])
    K.rec("G2.B11.fixed.both_services_ran",
          r["svc_calls"] == ["subscribe_streams", "unsubscribe_and_flush"],
          "svc=%s" % r["svc_calls"])
    K.rec("G2.B11.fixed.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))
    K.rec("G2.B11.fixed.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])
    K.rec("G2.B11.fixed.no_fatal",
          r["status"] == "running" and r["error"] is None,
          "status=%s err=%s" % (r["status"], r["error"]))
    K.rec("G2.B11.fixed.recovered_to_recording",
          r["actions"].count("emit_recording_metric") == 2,
          "recording entries=%d acts=%s"
          % (r["actions"].count("emit_recording_metric"), r["actions"]))


def fix_proof_sync():
    """Sync-engine parity on the fixed chart."""
    c = fix_gap(K.cfg("B11"))
    st = b11_stub(c, guard_vals={
        "all_streams_healthy": event_aware_guard,
        "reasons_remain": event_aware_reasons_remain}, sync=True)
    r = K.drive_sync(c, st, SCRIPT)
    K.rec("G2.B11.fixed.sync_parity", r["states"] == ["recording.stopped"]
          and r["context"]["gap_count_24h"] == 1,
          "states=%s gap=%r svc=%s" % (r["states"],
                                       r["context"]["gap_count_24h"],
                                       r["svc_calls"]))
    K.rec("G2.B11.fixed.sync_chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])


async def main():
    for fn in (confirm_root_cause, fix_proof):
        try:
            await asyncio.wait_for(fn(), 60)
        except Exception as e:
            K.rec("G2.%s.EXC" % fn.__name__, False, repr(e)[:300])
    try:
        fix_proof_sync()
    except Exception as e:
        K.rec("G2.fix_proof_sync.EXC", False, repr(e)[:300])
    K.dump("res_g2_b11_fix.json")


asyncio.run(main())
