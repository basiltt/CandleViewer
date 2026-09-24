# -*- coding: utf-8 -*-
"""W1b: triage the three anomalies from w1_contracts. STANDALONE (reuses w1 helpers by exec of its top half)."""
import asyncio, os, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
src = (HERE / "w1_contracts.py").read_text(encoding="utf-8").split("\nasync def main")[0]
g = {"__name__": "w1", "__file__": str(HERE / "w1_contracts.py")}; exec(src, g)
rec, run, cfg, Stub, settle, ids = g["rec"], g["run"], g["cfg"], g["Stub"], g["settle"], g["ids"]

async def main():
    # A: drained wait=True receipt -> Receipt.error is InterpreterStoppedError
    c = cfg("B20"); i, h = await run(c, Stub(c, {}), [])
    r = i.send_priority("EXPIRY_DUE"); await i.drain_pending()
    rc = await asyncio.wait_for(r, 5)
    rec("A.receipt_error_is_stopped", type(rc.error).__name__ == "InterpreterStoppedError",
        "receipt.error=%r changed=%s" % (rc.error, rc.changed)); await i.stop()
    # B: B17 deferred event re-offered: count on_event_received for one send, no drain
    c = cfg("B17"); i, h = await run(c, Stub(c, {"all_evidence_present": True}), [])
    await i.send("EMERGENCY_DISABLE"); await settle()
    await i.send("EVIDENCE_RECORDED"); await settle()
    await i.send("EVIDENCE_INVALIDATED"); await settle()
    n = h.recv.count("EMERGENCY_DISABLE")
    rec("B.defer_reoffers_on_each_transition(semantics)", n > 1,
        "one send -> received %d times; recv=%s" % (n, h.recv)); await i.stop()
    # C: B19 rollback of onDone action: does the invoke re-run forever?
    c = cfg("B19"); st = Stub(c, {}, raising=["store_exchange_state"])
    i, h = await run(c, st, ["SWEEP_DUE"])
    a = len(h.act_err); await asyncio.sleep(0.5); b = len(h.act_err)
    rec("C.rollback_onDone_loops", b > a, "act_err %d -> %d after 0.5s; chain=%d status=%s pend=%s"
        % (a, b, i.chain_trips, i.status, len(getattr(i, "pending_events", []) or [])))
    await i.stop()
asyncio.run(main())
