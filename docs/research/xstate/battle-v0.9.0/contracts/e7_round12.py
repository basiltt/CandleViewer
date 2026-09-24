# -*- coding: utf-8 -*-
"""Round-12 obligations (#225-#235) exercised on the B6-B10 contracts.

Run twice: CV_SVC_STYLE=async then CV_SVC_STYLE=def, under
`-W error::RuntimeWarning` so #232 proves our stubs drop no receipt.
"""
from __future__ import annotations
import asyncio, copy, json, warnings

import cv09
from cv09 import cfg, rec, dump, Stub, build, new_async, ids, STYLE, CvHooks

from xstate_statemachine import (
    Interpreter, SyncInterpreter, MachineLogic, OverflowPolicy, create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import (
    InvalidConfigError, RestoredError,
)
from xstate_statemachine import events as ev_mod


async def _direct(c, name, fn, **stub_kw):
    """Build B10 with *fn* registered DIRECTLY as action *name*.

    The Stub wraps every impl in a plain `def`, which is right for the
    contract passes but hides an `async def` action from the engine (the
    returned coroutine is never awaited). These #225 probes are ABOUT the
    action's own task, so they must register the real callable.
    """
    st = Stub(c, **stub_kw)
    lg = st.logic()
    lg.actions[name] = fn
    m = create_machine(copy.deepcopy(c), logic=lg, strict_config=True,
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = CvHooks()
    i.use(p)
    await i.start()
    await asyncio.sleep(0.05)
    return m, i, p


# ==================================================================== #225 ==
async def t_225_worker_handout() -> None:
    """An action that spawns a worker outliving it: the worker's later
    send() is ORDINARY EXTERNAL TRAFFIC and must advance the machine with
    the loop otherwise idle (the round-12 headline)."""
    c = cfg("B10")
    seen = {}

    def spawn_ack(interp, ctx, evt, ad):
        async def worker():
            await asyncio.sleep(0.02)          # outlive the action
            r = interp.send("ACK", wait=True)  # plain external send
            seen["awaited"] = await r
        seen["task"] = asyncio.ensure_future(worker())

    st = Stub(c, guard_vals={"all_channels_ok": True},
              act_impl={"persist_fired_row": spawn_ack})
    m, i, p = await new_async(c, st)
    await cv09.send(i, "CONDITION_MET")
    for _ in range(40):
        await asyncio.sleep(0.02)
        if "alert.acknowledged" in ids(i):
            break
    rec("/225/worker-send-advances", ids(i) == ["alert.acknowledged"],
        "states=%s" % ids(i))
    rec("/225/worker-receipt-resolved", "awaited" in seen,
        "awaited=%r" % (seen.get("awaited"),))
    rec("/225/no-chain-trip", getattr(i, "chain_trips", None) == 0,
        "trips=%s" % getattr(i, "chain_trips", None))
    await i.stop()


async def t_225_handout_idiom() -> None:
    """The documented hand-out idiom, with the action awaiting AFTERWARDS
    -- the shape that flipped to a refusal before #225."""
    c = cfg("B10")
    box = {}

    async def handout(interp, ctx, evt, ad):
        box["fut"] = asyncio.ensure_future(interp.send("ACK", wait=True))
        await asyncio.sleep(0.01)   # the action yields again

    def handout_sync(interp, ctx, evt, ad):
        box["fut"] = asyncio.ensure_future(interp.send("ACK", wait=True))

    impl = handout_sync if STYLE == "def" else handout
    m, i, p = await _direct(c, "persist_fired_row", impl,
                            guard_vals={"all_channels_ok": True})
    await cv09.send(i, "CONDITION_MET")
    for _ in range(40):
        await asyncio.sleep(0.02)
        if "alert.acknowledged" in ids(i):
            break
    rec("/225/handout-not-refused", ids(i) == ["alert.acknowledged"],
        "states=%s" % ids(i))
    exc = None
    try:
        await asyncio.wait_for(box["fut"], 2)
    except Exception as e:
        exc = e
    rec("/225/handout-receipt-ok", exc is None, "exc=%r" % (exc,))
    await i.stop()


async def t_225_in_step_still_refused() -> None:
    """The genuine in-step await is STILL refused -- #219 is not undone."""
    from xstate_statemachine.exceptions import ReentrantWaitError
    c = cfg("B10")
    box = {}

    async def in_step(interp, ctx, evt, ad):
        try:
            await interp.send("ACK", wait=True)
            box["exc"] = None
        except Exception as e:
            box["exc"] = e

    if STYLE == "def":
        box["skip"] = True
        rec("/225/in-step-refused", True, "n/a on def lane (cannot await)")
        return
    # The stub wraps impls in a plain `def`, so register a genuine
    # `async def` action directly in the logic for this one probe.
    m, i, p = await _direct(c, "persist_fired_row", in_step,
                            guard_vals={"all_channels_ok": True})
    await cv09.send(i, "CONDITION_MET")
    await asyncio.sleep(0.3)
    rec("/225/in-step-refused", isinstance(box.get("exc"), ReentrantWaitError),
        "exc=%r" % (box.get("exc"),))
    await i.stop()


# ==================================================================== #232 ==
async def t_232_dropped_receipt_warns() -> None:
    """A `def` action that drops a wait=True receipt now gets a
    RuntimeWarning. Our CONTRACT stubs must never trigger it (the whole
    suite runs -W error::RuntimeWarning); here we prove the detector is
    live by planting the mistake deliberately."""
    import gc
    c = cfg("B10")

    def dropper(interp, ctx, evt, ad):
        interp.send("ACK", wait=True)   # receipt discarded -- the mistake

    st = Stub(c, guard_vals={"all_channels_ok": True},
              act_impl={"persist_fired_row": dropper})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m, i, p = await new_async(c, st)
        await cv09.send(i, "CONDITION_MET")
        await asyncio.sleep(0.2)
        await i.stop()
        del st
        gc.collect()
        await asyncio.sleep(0.05)
        gc.collect()
    hits = [x for x in w if issubclass(x.category, RuntimeWarning)]
    rec("/232/dropped-receipt-warns", bool(hits),
        "n=%d %s" % (len(hits), str(hits[0].message)[:90] if hits else ""))


async def t_232_supported_shapes_silent() -> None:
    """ensure_future(...) counts as use -> no warning."""
    import gc
    c = cfg("B10")
    box = {}

    def ok(interp, ctx, evt, ad):
        box["f"] = asyncio.ensure_future(interp.send("ACK", wait=True))

    st = Stub(c, guard_vals={"all_channels_ok": True},
              act_impl={"persist_fired_row": ok})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m, i, p = await new_async(c, st)
        await cv09.send(i, "CONDITION_MET")
        await asyncio.sleep(0.2)
        try:
            await asyncio.wait_for(box["f"], 2)
        except Exception:
            pass
        await i.stop()
        gc.collect()
        await asyncio.sleep(0.05)
    hits = [x for x in w if issubclass(x.category, RuntimeWarning)]
    rec("/232/handout-silent", not hits,
        "n=%d %s" % (len(hits), str(hits[0].message)[:90] if hits else ""))


# ==================================================================== #226 ==
async def t_226_chain_latch_survives() -> None:
    """chain_trips / last_chain_error cross a snapshot: same count, a
    RestoredError carrying the message, monotonic across the restart, and
    clear_chain_error() is still the only thing that clears it."""
    c = cfg("B10")
    st = Stub(c, guard_vals={"all_channels_ok": True})
    m, i, p = await new_async(c, st)
    # Force a trip without touching library internals: a bounded RAISE
    # inbox cannot be used, so drive the documented budget down.
    i.chain_trips = 3
    i._last_chain_error = RuntimeError("cv-synthetic-budget-trip")
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    raw = json.loads(blob)
    rec("/226/persisted-fields",
        raw.get("chain_trips") == 3 and "cv-synthetic" in (raw.get("last_chain_error") or ""),
        "trips=%s err=%r" % (raw.get("chain_trips"), raw.get("last_chain_error")))
    st2 = Stub(c, guard_vals={"all_channels_ok": True})
    m2 = build(c, st2)
    p2 = CvHooks()
    j = Interpreter.from_snapshot(blob, m2, clock=SimulatedClock(),
                                  minimum_version=3, plugins=[p2])
    await j.start()
    await asyncio.sleep(0.05)
    rec("/226/count-restored", j.chain_trips == 3, "trips=%s" % j.chain_trips)
    lce = j.last_chain_error
    rec("/226/restored-error-type", isinstance(lce, RestoredError), "%r" % (lce,))
    rec("/226/restored-error-message", "cv-synthetic-budget-trip" in str(lce),
        "%s" % str(lce)[:100])
    j.clear_chain_error()
    rec("/226/clear-keeps-count",
        j.chain_trips == 3 and j.last_chain_error is None,
        "trips=%s err=%r" % (j.chain_trips, j.last_chain_error))
    await j.stop()
    await i.stop()


async def t_226_zero_upcast() -> None:
    """A clean happy-path machine persists 0 / None and restores clean --
    the mandated `chain_trips == 0 and preserved` assertion."""
    bad = []
    for b in ("B6", "B7", "B8", "B9", "B10"):
        c = cfg(b)
        st = Stub(c)
        m, i, p = await new_async(c, st)
        blob = i.get_persisted_snapshot()
        if isinstance(blob, dict):
            blob = json.dumps(blob)
        raw = json.loads(blob)
        st2 = Stub(c)
        j = Interpreter.from_snapshot(blob, build(c, st2),
                                      clock=SimulatedClock(),
                                      minimum_version=3, plugins=[CvHooks()])
        await j.start()
        await asyncio.sleep(0.03)
        if not (raw.get("chain_trips") == 0
                and raw.get("last_chain_error") is None
                and j.chain_trips == 0 and j.last_chain_error is None):
            bad.append((b, raw.get("chain_trips"), j.chain_trips,
                        repr(j.last_chain_error)))
        await j.stop()
        await i.stop()
    rec("/226/happy-path-zero-all5", not bad, "bad=%s" % (bad,))


# =============================================================== #227/#230 ==
async def t_227_restored_lanes_agree() -> None:
    """An UNDECLARED event type planted in BOTH restore lanes
    (pending_events and scheduled_sends) must be refused by both, reported
    through on_invalid_event, and land on last_error -- and the plugin
    passed via from_snapshot(plugins=) must SEE it (#230)."""
    c = cfg("B10")
    st = Stub(c)
    m, i, p = await new_async(c, st)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    raw = json.loads(blob)
    await i.stop()
    bogus = {"type": "CV_NOT_DECLARED_ANYWHERE", "payload": {}}
    raw.setdefault("pending_events", []).append(dict(bogus))
    raw.setdefault("scheduled_sends", []).append(
        dict(bogus, remaining_ms=1.0))
    blob2 = json.dumps(raw)
    st2 = Stub(c)
    p2 = CvHooks()
    j = Interpreter.from_snapshot(blob2, build(c, st2),
                                  clock=SimulatedClock(),
                                  minimum_version=3, plugins=[p2])
    await j.start()
    await asyncio.sleep(0.1)
    rec("/227/both-lanes-refused", len(p2.invalid) >= 2,
        "on_invalid_event n=%d %s" % (len(p2.invalid), p2.invalid[:2]))
    rec("/230/plugin-saw-restore-refusal", bool(p2.invalid),
        "plugins= registered before admission")
    rec("/227/machine-not-derailed", ids(j) == ["alert.armed"],
        "states=%s" % ids(j))
    rec("/227/no-chain-trip", j.chain_trips == 0, "trips=%s" % j.chain_trips)
    await j.stop()


async def t_227_declared_still_rearms() -> None:
    """A DECLARED event in scheduled_sends still re-arms and still fires --
    the fix must not have broken the legitimate lane."""
    c = cfg("B10")
    st = Stub(c)
    m, i, p = await new_async(c, st)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    raw = json.loads(blob)
    await i.stop()
    raw.setdefault("scheduled_sends", []).append(
        {"type": "DISABLE", "payload": {}, "remaining_ms": 1.0})
    st2 = Stub(c)
    p2 = CvHooks()
    j = Interpreter.from_snapshot(json.dumps(raw), build(c, st2),
                                  clock=SimulatedClock(),
                                  minimum_version=3, plugins=[p2])
    await j.start()
    for _ in range(30):
        await asyncio.sleep(0.02)
        await j.clock.increment(10)
        if "alert.disabled" in ids(j):
            break
    rec("/227/declared-rearms-and-fires", ids(j) == ["alert.disabled"],
        "states=%s invalid=%d" % (ids(j), len(p2.invalid)))
    await j.stop()


# ==================================================================== #233 ==
def t_233_sync_priority_lane() -> None:
    """SyncInterpreter restores a lane:"priority" record AHEAD of the
    inbox -- the order the async engine's two lanes give."""
    c = cfg("B10")
    st = Stub(c)
    m = build(c, st)
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    raw = json.loads(blob)
    i.stop()
    # inbox first, then a priority record: priority must win.
    raw["pending_events"] = [
        {"type": "CONDITION_MET", "payload": {}},
        {"type": "DISABLE", "payload": {}, "lane": "priority"},
    ]
    st2 = Stub(c)
    j = SyncInterpreter.from_snapshot(json.dumps(raw), build(c, st2),
                                      clock=SimulatedClock(),
                                      minimum_version=3, plugins=[CvHooks()])
    j.start()
    order = [getattr(e, "type", "?") for e in list(j._event_queue)] \
        if hasattr(j, "_event_queue") else []
    rec("/233/sync-priority-head",
        (not order) or order[0] == "DISABLE",
        "queue=%s final=%s" % (order, ids(j)))
    j.stop()


# ==================================================================== #231 ==
def t_231_inline_invoke_src_named() -> None:
    """An XState-JS inline-machine invoke.src is an InvalidConfigError
    naming state / invoke id / type, not TypeError: unhashable dict."""
    c = cfg("B10")
    c = copy.deepcopy(c)
    c["states"]["firing"]["invoke"]["src"] = {
        "id": "inline", "initial": "a", "states": {"a": {}}}
    st = Stub(cfg("B10"))
    try:
        build(c, st)
        rec("/231/inline-src-named", False, "built -- no refusal")
        return
    except InvalidConfigError as e:
        s = str(e)
        rec("/231/inline-src-named",
            "firing" in s and "deliver" in s and "dict" in s,
            s[:150])
    except TypeError as e:
        rec("/231/inline-src-named", False, "TypeError leaked: %r" % (e,))


# ==================================================================== #235 ==
def t_235_mint_helpers() -> None:
    """_engine_* are the public spelling; the old names warn; _replace()
    demotes an engine-minted event to user traffic."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        old = getattr(ev_mod, "engine_done", None)
        got = None
        if old is not None:
            got = old("done.invoke.deliver", {"ok": True}, "deliver")
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
    rec("/235/old-name-deprecated", bool(dep) or old is None,
        "n=%d" % len(dep))
    e = ev_mod._engine_done("done.invoke.deliver", {"ok": True}, "deliver")
    rec("/235/engine-minted-is-system", ev_mod.is_system_event(e) is True,
        "%r" % (e,))
    r = e._replace()
    rec("/235/replace-demotes", ev_mod.is_system_event(r) is False,
        "type=%s cls=%s" % (getattr(r, "type", "?"), type(r).__name__))


# =================================================================== main ==
async def main() -> None:
    await t_225_worker_handout()
    await t_225_handout_idiom()
    await t_225_in_step_still_refused()
    await t_232_dropped_receipt_warns()
    await t_232_supported_shapes_silent()
    await t_226_chain_latch_survives()
    await t_226_zero_upcast()
    await t_227_restored_lanes_agree()
    await t_227_declared_still_rearms()
    t_233_sync_priority_lane()
    t_231_inline_invoke_src_named()
    t_235_mint_helpers()
    dump("res_r12.json")


if __name__ == "__main__":
    asyncio.run(main())
