# -*- coding: utf-8 -*-
"""s6: persistence edges on the contract machines --
#182 snapshot from an initial-descent entry action, #187 from an action hook,
#185 null machine_hash on a versioned blob, #186 configuration vs state_ids."""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from d import CTL
from h import Stub, TraceP, build, cfg_of, ids, SETTLE
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

R = {}
GOK = {"cancel_working_requested": True, "flatten_requested": True,
       "all_accounts_flat": True, "owner_and_elevated": True,
       "owner_and_elevated_and_acknowledged_residual": True}


async def snap_from_entry(b, kind, action, gv):
    """#182/#187: snapshot attempted from inside an action -> must be refused."""
    cfg = cfg_of(b)
    out = {}

    def impl(interp, ctx, evt, ad):
        try:
            interp.get_persisted_snapshot()
            out["result"] = "ACCEPTED"
        except Exception as e:                                   # noqa: BLE001
            out["result"] = type(e).__name__
            out["child_flag"] = getattr(e, "child", "ABSENT")

    st = Stub(cfg, kind=kind, guard_vals=gv, act_impl={action: impl})
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    await interp.start(); await asyncio.sleep(SETTLE)
    if action not in st.trace:
        try:
            await asyncio.wait_for(interp.send("ENGAGE", wait=True), 5)
        except Exception:
            pass
        await asyncio.sleep(SETTLE)
    try:
        await asyncio.wait_for(interp.stop(), 5)
    except Exception:
        pass
    out["fired"] = action in st.trace
    out["kind"] = kind
    return out


async def blob_edges(b, kind, gv):
    cfg = cfg_of(b)
    st = Stub(cfg, kind=kind, guard_vals=gv)
    m = build(cfg, st)
    interp = Interpreter(m, clock=SimulatedClock(), **CTL)
    await interp.start(); await asyncio.sleep(SETTLE)
    blob = interp.get_persisted_snapshot()
    await interp.stop()
    rows = {"fields": sorted(blob.keys()),
            "version": blob.get("version"),
            "has_hash": "machine_hash" in blob}

    def attempt(name, mut):
        b2 = json.loads(json.dumps(blob))
        mut(b2)
        try:
            Interpreter.from_snapshot(json.dumps(b2), m,
                                      clock=SimulatedClock())
            rows[name] = "ACCEPTED"
        except Exception as e:                                   # noqa: BLE001
            rows[name] = f"{type(e).__name__}: {str(e)[:110]}"

    attempt("baseline", lambda d: None)
    attempt("hash_null", lambda d: d.__setitem__("machine_hash", None))
    attempt("hash_absent", lambda d: d.pop("machine_hash", None))
    attempt("hash_wrong", lambda d: d.__setitem__("machine_hash", "deadbeef"))
    attempt("config_emptied", lambda d: d.__setitem__("configuration", []))
    attempt("config_rewritten",
            lambda d: d.__setitem__("configuration", ["kill_switch.engaged"]))
    attempt("state_ids_emptied", lambda d: d.__setitem__("state_ids", []))
    rows["kind"] = kind
    return rows


async def main():
    for kind in ("async", "sync"):
        R[f"b18_snap_in_entry_{kind}"] = await snap_from_entry(
            "B18", kind, "block_new_orders_immediately", GOK)
        R[f"b19_snap_initial_descent_{kind}"] = await snap_from_entry(
            "B19", kind, "clear_divergences",
            {"auto_remediate_allowed": True})
        R[f"b18_blob_{kind}"] = await blob_edges("B18", kind, GOK)
    for k, v in R.items():
        print(k, json.dumps(v, default=str)[:420], flush=True)

asyncio.run(main())
json.dump(R, open("results/s6_persist.json", "w", encoding="utf-8"),
          indent=2, default=str)
