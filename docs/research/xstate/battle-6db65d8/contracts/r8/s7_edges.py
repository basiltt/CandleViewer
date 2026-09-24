# -*- coding: utf-8 -*-
"""s7: (a) #186 asymmetry -- emptied `state_ids` is accepted while emptied
`configuration` is refused; does it restore correctly or silently drift?
(b) #182 initial-descent refusal, using a synthetic root entry action on the
contract machines (which have no entry on their initial states)."""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from d import CTL
from h import Stub, TraceP, build, cfg_of, ids, SETTLE
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

R = {}
GOK = {"cancel_working_requested": True, "flatten_requested": True,
       "all_accounts_flat": True, "owner_and_elevated": True,
       "owner_and_elevated_and_acknowledged_residual": True}


async def state_ids_edge(kind):
    """Take a snapshot in a NON-initial state, empty state_ids, restore."""
    cfg = cfg_of("B18")
    st = Stub(cfg, kind=kind, guard_vals=dict(GOK, all_accounts_flat=False))
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    await interp.start(); await asyncio.sleep(SETTLE)
    await asyncio.wait_for(interp.send("ENGAGE", wait=True), 5)
    await asyncio.sleep(SETTLE)
    good_ids = ids(interp)
    blob = interp.get_persisted_snapshot()
    await interp.stop()
    out = {"kind": kind, "snapshot_taken_at": good_ids,
           "blob_configuration": blob.get("configuration"),
           "blob_state_ids": blob.get("state_ids")}

    async def restore(name, mut):
        b2 = json.loads(json.dumps(blob))
        mut(b2)
        try:
            st2 = Stub(cfg, kind=kind,
                       guard_vals=dict(GOK, all_accounts_flat=False))
            m2 = build(cfg, st2)
            i2 = Interpreter.from_snapshot(json.dumps(b2), m2,
                                           clock=SimulatedClock())
            await i2.start(); await asyncio.sleep(SETTLE)
            out[name] = {"accepted": True, "restored_ids": ids(i2),
                         "matches_original": ids(i2) == good_ids,
                         "status": i2.status}
            await i2.stop()
        except Exception as e:                                   # noqa: BLE001
            out[name] = {"accepted": False,
                         "error": f"{type(e).__name__}: {str(e)[:120]}"}

    await restore("baseline", lambda d: None)
    await restore("state_ids_emptied", lambda d: d.__setitem__("state_ids", []))
    await restore("state_ids_absent", lambda d: d.pop("state_ids", None))
    await restore("state_ids_rewritten",
                  lambda d: d.__setitem__("state_ids", ["kill_switch.clear"]))
    return out


async def initial_descent(kind):
    """#182: snapshot from an action that runs during start()'s descent."""
    cfg = cfg_of("B18")
    cfg["states"]["clear"]["entry"] = ["probe_entry"]
    res = {}

    def impl(interp, ctx, evt, ad):
        try:
            interp.get_persisted_snapshot()
            res["result"] = "ACCEPTED"
        except Exception as e:                                   # noqa: BLE001
            res["result"] = type(e).__name__
            res["child"] = getattr(e, "child", "ABSENT")

    st = Stub(cfg, kind=kind, guard_vals=GOK, act_impl={"probe_entry": impl})
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    await interp.start(); await asyncio.sleep(SETTLE)
    res["fired"] = "probe_entry" in st.trace
    res["kind"] = kind
    await interp.stop()
    return res


async def main():
    for kind in ("async", "sync"):
        R[f"state_ids_{kind}"] = await state_ids_edge(kind)
        R[f"initial_descent_{kind}"] = await initial_descent(kind)
    for k, v in R.items():
        print(k, json.dumps(v, default=str)[:600], flush=True)

asyncio.run(main())
json.dump(R, open("results/s7_edges.json", "w", encoding="utf-8"),
          indent=2, default=str)
