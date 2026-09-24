# -*- coding: utf-8 -*-
"""B13 ExchangeConnection: reconnect/resync + INV-B13-a..e. onUnhandled=error."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock


def _bump(i, c, e, a):
    c["attempt"] = c["attempt"] + 1


def _reset(i, c, e, a):
    c["attempt"] = 0
    c["backoff_ms"] = 500


def _backoff(i, c, e, a):
    c["backoff_ms"] = min(c["backoff_ms"] * 2, c["max_backoff_ms"])


def _pending(i, c, e, a):
    c["pending_topics"] = list(e.payload.get("topics", []))


def _subscribed(i, c, e, a):
    c["subscribed_topics"] = list(c["pending_topics"])


def _pong(i, c, e, a):
    c["last_pong_us"] = e.payload.get("us", 0)


IMPL = {"bump_attempt": _bump, "reset_backoff": _reset,
        "compute_jittered_backoff": _backoff, "set_pending_topics": _pending,
        "record_subscribed": _subscribed, "stamp_pong": _pong}


def mk(private=False, budget=False, svc=None, topics=("trade",)):
    cfg = H.load("B13")
    cfg["context"]["kind"] = "private" if private else "public"
    cfg["context"]["pending_topics"] = list(topics)
    st = H.Stub(cfg, guard_vals={"is_private": private,
                                 "connection_budget_exhausted": budget},
                svc=svc or {}, act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    it.use(tp)
    return it, st, tp


async def to_live(it):
    await it.send("CONNECT", wait=True)
    await quiesce(it)


@scenario("B13-happy-pub", "happy", "public: disconnected->connecting->subscribing->live")
async def happy_pub():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    ok = ids(it) == ["ws_conn.live"] and "ws_auth" not in st.svc_calls
    r = {"ok": ok, "states": ids(it), "svc": st.svc_calls,
         "subscribed": it.context["subscribed_topics"],
         "entry": [a for a in st.trace
                   if a in ("reset_backoff", "emit_feed_healthy", "arm_pong_deadline")]}
    await it.stop()
    return r


@scenario("B13-happy-priv", "happy", "private: inserts authenticating before subscribing")
async def happy_priv():
    it, st, tp = mk(private=True)
    await it.start()
    await to_live(it)
    r = {"ok": ids(it) == ["ws_conn.live"]
               and st.svc_calls[:3] == ["open_socket", "ws_auth", "subscribe_in_batches"],
         "states": ids(it), "svc": st.svc_calls}
    await it.stop()
    return r


@scenario("B13-a", "INV-B13-a", "budget exhausted -> budget_blocked, NO socket opened")
async def budget():
    it, st, tp = mk(budget=True)
    await it.start()
    await to_live(it)
    blocked = ids(it)
    opened = "open_socket" in st.svc_calls
    await it.send("BUDGET_RECHECK", wait=True)
    await quiesce(it)
    r = {"ok": blocked == ["ws_conn.budget_blocked"] and not opened
               and ids(it) == ["ws_conn.disconnected"],
         "blocked": blocked, "socket_opened": opened, "after_recheck": ids(it),
         "alert": st.trace.count("raise_conn_budget_alert")}
    await it.stop()
    return r


@scenario("B13-b", "INV-B13-b", "backoff doubles to max and resets only on live")
async def backoff():
    it, st, tp = mk(svc={"open_socket": RuntimeError("dial failed")})
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it)
    seq = []
    for _ in range(7):
        seq.append(it.context["backoff_ms"])
        await it.send("BACKOFF_DUE", wait=True)
        await quiesce(it)
    capped = it.context["backoff_ms"]
    st.svc["open_socket"] = {"ok": True}
    await it.send("BACKOFF_DUE", wait=True)
    await quiesce(it)
    live, after_reset = ids(it), it.context["backoff_ms"]
    mono = all(b <= a for b, a in zip(seq, seq[1:]))
    r = {"ok": mono and capped == 30000 and live == ["ws_conn.live"] and after_reset == 500,
         "backoff_seq": seq, "capped_at": capped, "live": live,
         "backoff_after_live": after_reset, "attempts": it.context["attempt"]}
    await it.stop()
    return r


@scenario("B13-c", "INV-B13-c", "subscribed_topics == pending_topics after subscribing")
async def topics():
    it, st, tp = mk(topics=("trade", "kline", "depth"))
    await it.start()
    await to_live(it)
    first = list(it.context["subscribed_topics"])
    await it.send("TOPICS_CHANGED", topics=["trade", "depth", "mark"], wait=True)
    await quiesce(it)
    r = {"ok": first == ["trade", "kline", "depth"]
               and it.context["subscribed_topics"] == ["trade", "depth", "mark"]
               and ids(it) == ["ws_conn.live"],
         "first": first, "after_change": it.context["subscribed_topics"],
         "pending": it.context["pending_topics"], "states": ids(it),
         "sub_calls": st.svc_calls.count("subscribe_in_batches")}
    await it.stop()
    return r


@scenario("B13-c2", "INV-B13-c", "partial batch subscribe -> back to backing_off, never live")
async def partial():
    it, st, tp = mk(topics=("a", "b"),
                    svc={"subscribe_in_batches": RuntimeError("partial: only a")})
    await it.start()
    await to_live(it)
    r = {"ok": ids(it) == ["ws_conn.backing_off"] and not it.context["subscribed_topics"],
         "states": ids(it), "subscribed": it.context["subscribed_topics"],
         "sub_error": st.trace.count("record_sub_error")}
    await it.stop()
    return r


@scenario("B13-recon", "INV-B13-b", "reconnect/resync: live->SOCKET_CLOSED->backoff->live, topics restored")
async def reconnect():
    it, st, tp = mk(topics=("trade", "kline"))
    await it.start()
    await to_live(it)
    t0 = list(it.context["subscribed_topics"])
    n_sub0 = st.svc_calls.count("subscribe_in_batches")
    await it.send("SOCKET_CLOSED", wait=True)
    await quiesce(it)
    backoff_state = ids(it)
    degraded = (st.trace.count("emit_feed_degraded"),
                st.trace.count("notify_dependents_degraded"))
    await it.send("BACKOFF_DUE", wait=True)
    await quiesce(it)
    r = {"ok": backoff_state == ["ws_conn.backing_off"] and ids(it) == ["ws_conn.live"]
               and it.context["subscribed_topics"] == t0
               and st.svc_calls.count("subscribe_in_batches") == n_sub0 + 1
               and degraded == (1, 1),
         "backoff_state": backoff_state, "relive": ids(it),
         "topics_before": t0, "topics_after": it.context["subscribed_topics"],
         "degraded_notifications": degraded, "svc_sequence": st.svc_calls}
    await it.stop()
    return r


@scenario("B13-pong", "INV-B13-e", "PONG re-arms; PONG_DEADLINE drops to backing_off")
async def pong():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    await it.send("PONG", us=111, wait=True)
    await quiesce(it)
    stamped = it.context["last_pong_us"]
    rearm = st.trace.count("rearm_pong_deadline")
    await it.send("PONG_DEADLINE", wait=True)
    await quiesce(it)
    r = {"ok": stamped == 111 and rearm == 1 and ids(it) == ["ws_conn.backing_off"]
               and st.trace.count("record_pong_timeout") == 1,
         "last_pong_us": stamped, "rearm_calls": rearm, "after_deadline": ids(it),
         "arm_calls": st.trace.count("arm_pong_deadline")}
    await it.stop()
    return r


@scenario("B13-stale", "INV-B13-b", "TOPIC_STALE forces reconnect")
async def stale():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    await it.send("TOPIC_STALE", topic="trade", wait=True)
    await quiesce(it)
    r = {"ok": ids(it) == ["ws_conn.backing_off"] and st.trace.count("record_staleness") == 1,
         "states": ids(it)}
    await it.stop()
    return r


@scenario("B13-shutdown", "happy", "SHUTDOWN from live -> closing -> closed (final)")
async def shutdown():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    await it.send("SHUTDOWN", wait=True)
    await quiesce(it)
    r = {"ok": ids(it) == ["ws_conn.closed"] and "close_socket" in st.svc_calls,
         "states": ids(it), "svc": st.svc_calls}
    await it.stop()
    return r


@scenario("B13-unh", "onUnhandled=error", "unhandled event must surface, not be swallowed")
async def unhandled():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    try:
        rcpt = await it.send("CONNECT", wait=True)
        err = "no raise; receipt=%r" % (rcpt,)
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:160])
    await quiesce(it)
    r = {"ok": "UnhandledEventError" in err or it.last_error is not None,
         "send_result": err, "last_error": repr(it.last_error)[:200],
         "unhandled_hook": tp.unhandled, "states": ids(it), "running": it.is_running}
    await it.stop()
    return r


@scenario("B13-strict", "strict=true", "undeclared event name must raise at the call site")
async def strict():
    it, st, tp = mk()
    await it.start()
    await to_live(it)
    out = {}
    for name in ("NOT_A_REAL_EVENT", "after.party", "done.invoke.bogus", "xstate.bogus"):
        try:
            await it.send(name, wait=True)
            await quiesce(it)
            out[name] = "ACCEPTED states=%s last_error=%r" % (ids(it), it.last_error)
        except Exception as e:
            out[name] = "%s: %s" % (type(e).__name__, str(e)[:120])
    r = {"ok": all("Error" in v for v in out.values()), "results": out, "states": ids(it)}
    await it.stop()
    return r


if __name__ == "__main__":
    sys.exit(run_all("b13"))
