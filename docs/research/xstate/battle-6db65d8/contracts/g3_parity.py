# -*- coding: utf-8 -*-
"""Step 4: SyncInterpreter parity (informational). Same scripts, both engines."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, SyncInterpreter
from xstate_statemachine.clock import SimulatedClock
import g3_snapshot as S

H._REG.clear()


def sync_stub(b):
    """Sync engine needs non-coroutine services."""
    mkstub, script = S.SCRIPTS[b]
    st = mkstub()
    plain = {}
    for n, v in list(st.svc.items()):
        plain[n] = v
    st.svc = plain
    return st, script


async def async_run(b):
    mkstub, script = S.SCRIPTS[b]
    cfg = H.load(b)
    st = mkstub()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    await it.start()
    await quiesce(it)
    seq = [ids(it)]
    for ev, p in script:
        try:
            await it.send(ev, wait=True, **p)
        except Exception as e:
            seq.append(["EXC:%s" % type(e).__name__])
            break
        await quiesce(it)
        seq.append(ids(it))
    ctx = {k: v for k, v in it.context.items() if not k.startswith("_")}
    await it.stop()
    return seq, ctx, list(st.trace)


def sync_run(b):
    cfg = H.load(b)
    st, script = sync_stub(b)
    logic = st.logic()
    # sync engine: services must be plain callables
    import xstate_statemachine as X
    svcs = {}
    for n in st.svcs:
        def mk(nm):
            def f(interp, ctx, evt):
                st.svc_calls.append(nm)
                v = st.svc.get(nm, {"ok": True})
                if isinstance(v, BaseException):
                    raise v
                return v
            f.__name__ = nm
            return f
        svcs[n] = mk(n)
    logic2 = X.MachineLogic(actions=logic.actions, guards=logic.guards,
                            services=svcs, delays=logic.delays, strict=True)
    m = X.create_machine(json.loads(json.dumps(cfg)), logic=logic2,
                         strict_targets=cfg.get("strictTargets", True))
    it = SyncInterpreter(m)
    it.start()
    seq = [ids(it)]
    for ev, p in script:
        try:
            it.send(ev, **p)
        except Exception as e:
            seq.append(["EXC:%s" % type(e).__name__])
            break
        seq.append(ids(it))
    ctx = {k: v for k, v in it.context.items() if not k.startswith("_")}
    it.stop()
    return seq, ctx, list(st.trace)


def _mk(b):
    async def fn():
        a_seq, a_ctx, a_tr = await async_run(b)
        try:
            s_seq, s_ctx, s_tr = sync_run(b)
        except Exception as e:
            return {"ok": False, "sync_failed": "%s: %s" % (type(e).__name__, str(e)[:250]),
                    "async_seq": a_seq}
        same_states = a_seq == s_seq
        same_ctx = json.dumps(a_ctx, sort_keys=True, default=str) == \
                   json.dumps(s_ctx, sort_keys=True, default=str)
        same_actions = a_tr == s_tr
        return {"ok": same_states and same_ctx and same_actions,
                "states_match": same_states, "context_match": same_ctx,
                "actions_match": same_actions,
                "async_final": a_seq[-1], "sync_final": s_seq[-1],
                "async_seq": a_seq, "sync_seq": s_seq,
                "action_diff": [x for x in a_tr if x not in s_tr][:6]}
    fn.__name__ = "parity_" + b
    return fn


for _b in ("B11", "B12", "B13", "B14", "B15"):
    scenario("PAR-" + _b, "parity", "async vs sync engine, identical script")(_mk(_b))


if __name__ == "__main__":
    sys.exit(run_all("parity"))
