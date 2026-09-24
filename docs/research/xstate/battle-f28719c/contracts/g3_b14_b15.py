# -*- coding: utf-8 -*-
"""B14 Book health + B15 PaperMatcher liquidation."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock


# ------------------------------------------------------------------ B14 ----
def _buf(i, c, e, a):
    c["buffered_deltas"] = list(c["buffered_deltas"]) + [e.payload.get("seq")]


def _inst(i, c, e, a):
    c["snapshot_seq"] = e.payload.get("seq")
    c["last_seq"] = e.payload.get("seq")


def _replay(i, c, e, a):
    keep = [s for s in c["buffered_deltas"] if s > c["snapshot_seq"]]
    c.setdefault("_replayed", []).extend(keep)
    if keep:
        c["last_seq"] = max(keep)
    c["buffered_deltas"] = []


def _apply(i, c, e, a):
    c["last_seq"] = e.payload.get("seq")
    c.setdefault("_applied", []).append(e.payload.get("seq"))


def _clear(i, c, e, a):
    c["buffered_deltas"] = []


def _bump(i, c, e, a):
    c["resync_count"] = c["resync_count"] + 1


def _stamp(i, c, e, a):
    c["desynced_since_us"] = e.payload.get("us", 1)


B14_IMPL = {"buffer_delta": _buf, "install_snapshot": _inst,
            "replay_buffered_deltas_after_seq": _replay, "apply_delta": _apply,
            "clear_buffer": _clear, "bump_resync_count": _bump, "stamp_desync": _stamp}


def mk14():
    cfg = H.load("B14")
    st = H.Stub(cfg, act_impl=B14_IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    it.use(tp)
    return it, st, tp


@scenario("B14-happy", "happy", "init->snapshot_pending->live; buffered deltas replayed after snapshot_seq")
async def b14_happy():
    it, st, tp = mk14()
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await quiesce(it)
    pending = ids(it)
    for s in (5, 6, 7):
        await it.send("DELTA", seq=s, wait=True)
    await quiesce(it)
    buffered = list(it.context["buffered_deltas"])
    await it.send("SNAPSHOT", seq=6, wait=True)
    await quiesce(it)
    r = {"ok": pending == ["book.snapshot_pending"] and buffered == [5, 6, 7]
               and ids(it) == ["book.live"]
               and it.context.get("_replayed") == [7] and it.context["last_seq"] == 7,
         "pending": pending, "buffered": buffered, "live": ids(it),
         "replayed": it.context.get("_replayed"), "last_seq": it.context["last_seq"]}
    await it.stop()
    return r


@scenario("B14-c", "INV-B14-c", "SEQUENCE_GAP drops state and re-snapshots; no delta across a gap")
async def b14_gap():
    it, st, tp = mk14()
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await quiesce(it)
    await it.send("SNAPSHOT", seq=1, wait=True)
    await quiesce(it)
    await it.send("DELTA", seq=2, wait=True)
    await quiesce(it)
    applied_before = list(it.context.get("_applied", []))
    await it.send("SEQUENCE_GAP", us=42, wait=True)
    await quiesce(it)
    after = ids(it)
    r = {"ok": after == ["book.snapshot_pending"]
               and it.context["resync_count"] >= 1
               and it.context["desynced_since_us"] == 42
               and it.context["buffered_deltas"] == []
               and list(it.context.get("_applied", [])) == applied_before,
         "after_gap": after, "resync_count": it.context["resync_count"],
         "desynced_since_us": it.context["desynced_since_us"],
         "buffer_cleared": it.context["buffered_deltas"],
         "applied": it.context.get("_applied"),
         "transitions": tp.transitions[-4:]}
    await it.stop()
    return r


@scenario("B14-d", "INV-B14-d", "buffer is BOUNDED while awaiting a snapshot")
async def b14_bound():
    it, st, tp = mk14()
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await quiesce(it)
    N = 1000
    for s in range(N):
        await it.send("DELTA", seq=s, wait=True)
    await quiesce(it, 10)
    n = len(it.context["buffered_deltas"])
    r = {"ok": n < N,
         "sent": N, "buffered_len": n, "dropped_by_engine": list(tp.dropped)[:3],
         "note": ("buffer grew 1:1 with input -- INV-B14-d 'bounded' is NOT "
                  "expressed anywhere in the B14 JSON; buffer_delta is an "
                  "unbounded list append"),
         "states": ids(it)}
    await it.stop()
    return r


@scenario("B14-timeout", "INV-B14-e", "SNAPSHOT_TIMEOUT re-enters snapshot_pending and counts a resync")
async def b14_timeout():
    it, st, tp = mk14()
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await quiesce(it)
    await it.send("DELTA", seq=9, wait=True)
    await quiesce(it)
    n0 = it.context["resync_count"]
    await it.send("SNAPSHOT_TIMEOUT", wait=True)
    await quiesce(it)
    r = {"ok": ids(it) == ["book.snapshot_pending"]
               and it.context["resync_count"] == n0 + 1
               and it.context["buffered_deltas"] == []
               and st.trace.count("request_snapshot") == 2,
         "states": ids(it), "resync": (n0, it.context["resync_count"]),
         "buffer": it.context["buffered_deltas"],
         "request_snapshot_calls": st.trace.count("request_snapshot")}
    await it.stop()
    return r


@scenario("B14-unh", "onUnhandled=error", "DELTA arriving in `desynced` transient window")
async def b14_unh():
    it, st, tp = mk14()
    await it.start()
    await it.send("SUBSCRIBE", wait=True)
    await quiesce(it)
    await it.send("SNAPSHOT", seq=1, wait=True)
    await quiesce(it)
    await it.send("SEQUENCE_GAP", wait=True)
    await quiesce(it)
    # UNSUBSCRIBE is only legal in `live`; we are in snapshot_pending -> fatal?
    rc = await it.send("UNSUBSCRIBE", wait=True)
    await quiesce(it)
    r = {"ok": it.is_running,
         "running": it.is_running, "status": it.status,
         "receipt": repr(rc), "last_error": repr(it.last_error),
         "hook": tp.unhandled, "states": ids(it)}
    await it.stop()
    return r


# ------------------------------------------------------------------ B15 ----
def _haircut(i, c, e, a):
    c["equity"] = "0"
    c.setdefault("_journal", []).append("haircut")


def _journal(i, c, e, a):
    c.setdefault("_journal", []).append("journal")


B15_IMPL = {"apply_liquidation_haircut": _haircut, "write_liquidation_journal": _journal}


def mk15(liq=False, below=False, above=False):
    cfg = H.load("B15")
    st = H.Stub(cfg, guard_vals={"mark_crossed_liq_price": liq,
                                 "below_maintenance_margin": below,
                                 "above_maintenance_margin": above},
                act_impl=B15_IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    it.use(tp)
    return it, st, tp


@scenario("B15-happy", "happy", "active -> margin_call -> back to active")
async def b15_happy():
    it, st, tp = mk15(below=True)
    await it.start()
    await it.send("MARK_UPDATE", px=1, wait=True)
    await quiesce(it)
    mc = ids(it)
    st.guard_vals.update(below_maintenance_margin=False, above_maintenance_margin=True)
    await it.send("MARK_UPDATE", px=2, wait=True)
    await quiesce(it)
    r = {"ok": mc == ["paper_account.margin_call"] and ids(it) == ["paper_account.active"]
               and st.trace.count("emit_margin_warning") == 1,
         "margin_call": mc, "recovered": ids(it)}
    await it.stop()
    return r


@scenario("B15-b", "INV-B15-b", "liquidated is terminal; a favourable mark cannot revive")
async def b15_terminal():
    it, st, tp = mk15(liq=True)
    await it.start()
    await it.send("MARK_UPDATE", px=1, wait=True)
    await quiesce(it)
    liq = ids(it)
    st.guard_vals.update(liq=False, mark_crossed_liq_price=False, above_maintenance_margin=True)
    rc = None
    try:
        rc = await it.send("MARK_UPDATE", px=999, wait=True)
        await quiesce(it)
        post = "accepted"
    except Exception as e:
        post = "%s: %s" % (type(e).__name__, str(e)[:120])
    r = {"ok": liq == ["paper_account.liquidated"] and ids(it) == ["paper_account.liquidated"],
         "liquidated": liq, "after_favourable_mark": ids(it),
         "post": post, "receipt": repr(rc), "running": it.is_running}
    await it.stop()
    return r


@scenario("B15-c", "INV-B15-c", "journal written before the terminal transition settles")
async def b15_journal():
    it, st, tp = mk15(liq=True)
    await it.start()
    await it.send("MARK_UPDATE", px=1, wait=True)
    await quiesce(it)
    j = it.context.get("_journal")
    r = {"ok": j == ["haircut", "journal"] and ids(it) == ["paper_account.liquidated"],
         "journal": j, "final": ids(it), "trace": st.trace}
    await it.stop()
    return r


@scenario("B15-prio", "INV-B15-a", "liquidation preempts a busy inbox via send_priority")
async def b15_priority():
    it, st, tp = mk15(below=True)
    await it.start()
    # flood with non-liquidating marks
    for k in range(50):
        await it.send("MARK_UPDATE", px=k)
    st.guard_vals.update(mark_crossed_liq_price=True)
    await it.send_priority("MARK_UPDATE", px=-1)
    await quiesce(it, 12)
    r = {"ok": ids(it) == ["paper_account.liquidated"],
         "final": ids(it), "journal": it.context.get("_journal"),
         "queue_depth": it.queue_depth}
    await it.stop()
    return r


if __name__ == "__main__":
    sys.exit(run_all("b14_b15"))
