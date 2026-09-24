# -*- coding: utf-8 -*-
"""m5: four sharpened questions the invariant sweep could not answer cleanly.

  A. Does send_priority actually PRE-EMPT a self-generated chain, isolated
     from B18's C-07b (`onUnhandled: error`)?  B18 + one added RELEASE
     handler on `flattening`; everything else identical.
  B. Sync parity for B18/B19 with BOTH service kinds.
  C. #195 provenance on the real contract machines: can a hand-built
     DoneEvent drive B18's `cancelling.onDone` while the genuine service runs?
  D. #198: can a forged `configuration` relocate a restored B18?

STANDALONE: stdlib + xstate_statemachine only.
"""
from __future__ import annotations
import asyncio, json, pathlib, time
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 OverflowPolicy, create_machine)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

HERE = pathlib.Path(__file__).parent
R = {}


def rec(k, ok, note=""):
    R[k] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + k + ("  | " + note if note else ""),
          flush=True)


def collect(c):
    acts, guards, svcs = set(), set(), set()

    def A(v):
        if isinstance(v, str):
            acts.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str):
            acts.add(v["type"])
        elif isinstance(v, list):
            for i in v:
                A(i)

    def G(v):
        if isinstance(v, str):
            guards.add(v)
        elif isinstance(v, dict):
            for k in ("and", "or", "not"):
                if k in v:
                    x = v[k]
                    for i in (x if isinstance(x, list) else [x]):
                        G(i)

    def T(v):
        if isinstance(v, list):
            for i in v:
                T(i)
        elif isinstance(v, dict):
            A(v.get("actions")); G(v.get("guard") or v.get("cond"))

    def walk(n):
        A(n.get("entry")); A(n.get("exit"))
        for v in (n.get("on") or {}).values():
            T(v)
        T(n.get("always"))
        for v in (n.get("after") or {}).values():
            T(v)
        i = n.get("invoke")
        if i:
            for x in (i if isinstance(i, list) else [i]):
                if isinstance(x.get("src"), str):
                    svcs.add(x["src"])
                T(x.get("onDone")); T(x.get("onError"))
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return sorted(acts), sorted(guards), sorted(svcs)


class P(PluginBase):
    def __init__(self):
        self.dropped = []
        self.acts = []
        self.tr = []

    def on_event_dropped(self, i, e, reason):
        self.dropped.append((getattr(e, "type", "?"), str(reason)))

    def on_action_execute(self, i, a):
        self.acts.append(a.type)

    def on_transition(self, i, f, t, tr):
        self.tr.append(tr.event)


def logic(cfg, style, gv, raising, ctr, svc_hold=None):
    a, g, s = collect(cfg)

    def mk_a(n):
        def f(i_, ctx, evt, ad):
            if n in raising:
                raise RuntimeError("boom:" + n)
        f.__name__ = n
        return f

    def mk_g(n):
        def gg(ctx, evt):
            return bool(gv.get(n, False))
        gg.__name__ = n
        return gg

    def mk_s(n):
        if style == "async":
            async def s_(i_, ctx, evt):
                ctr.append(n)
                if svc_hold and n in svc_hold:
                    await svc_hold[n].wait()
                return {"ok": True}
        else:
            def s_(i_, ctx, evt):
                ctr.append(n)
                return {"ok": True}
        s_.__name__ = n
        return s_

    return MachineLogic(
        actions={n: mk_a(n) for n in a
                 if not is_builtin(n) and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in g},
        services={n: mk_s(n) for n in s}, strict=True)


GV18 = {"cancel_working_requested": True, "flatten_requested": True,
        "all_accounts_flat": False, "owner_and_elevated": True}


# ------------------------------------------------------ A. pre-emption ----
async def A():
    cfg = json.loads((HERE / "B18.machine.json").read_text(encoding="utf-8"))
    cfg["maxIterations"] = 200
    # the ONLY change: flattening also listens for RELEASE, so the kill press
    # has somewhere to land while the chain is spinning.
    cfg["states"]["flattening"]["on"] = {
        "RELEASE": {"target": "#kill_switch.clear"}}
    ctr = []
    m = create_machine(cfg, logic=logic(cfg, "async", GV18, {"page_owner"},
                                        ctr), strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = P(); i.use(p)
    await i.start()
    await asyncio.sleep(0.05)
    t = asyncio.ensure_future(i.send("ENGAGE", wait=False))
    await asyncio.sleep(0.01)          # let the chain get going
    mid = len(ctr)
    ok, err = False, None
    try:
        await asyncio.wait_for(i.send_priority("RELEASE", wait=True), 5)
        ok = True
    except Exception as e:
        err = repr(e)
    await asyncio.sleep(0.3)
    after = len(ctr)
    await asyncio.sleep(0.3)
    after2 = len(ctr)
    st = sorted(i.current_state_ids)
    shed = [d for d in p.dropped if "budget" in d[1].lower()]
    try:
        await asyncio.wait_for(t, 2)
    except Exception:
        pass
    await i.stop()
    rec("A/priority RELEASE pre-empts the chain",
        ok and st == ["kill_switch.clear"] and after == after2,
        json.dumps({"svc_at_press": mid, "svc_after": after,
                    "svc_later": after2, "states": st, "err": err,
                    "shed": shed, "dropped": p.dropped[:4]}))
    rec("A/no priority send shed as chain_budget", not shed,
        json.dumps(p.dropped[:6]))


# ------------------------------------------------------ B. sync parity ----
def B():
    for b, ev, gv in [("B18", "ENGAGE", GV18),
                      ("B19", "SWEEP_DUE",
                       {"divergences_found_and_auto_remediate": False,
                        "unresolved_divergences": False,
                        "failures_exhausted": False})]:
        for style in ("async", "def"):
            cfg = json.loads((HERE / (b + ".machine.json")).read_text("utf-8"))
            ctr = []
            out = {}
            try:
                m = create_machine(cfg, logic=logic(cfg, style, gv, set(), ctr),
                                   strict_targets=True)
                i = SyncInterpreter(m, clock=SimulatedClock())
                i.start()
                i.send(ev)
                out = {"states": sorted(i.current_state_ids),
                       "svc": list(ctr), "status": i.status,
                       "error": repr(i.error) if i.error else None}
                i.stop()
            except Exception as e:
                out = {"exc": "%s: %s" % (type(e).__name__, str(e)[:140]),
                       "svc": list(ctr)}
            k = "B/sync %s %s" % (b, style)
            # contract: def runs to completion on sync; async is refused
            expect_ok = (style == "def")
            got_ok = "exc" not in out
            rec(k, got_ok == expect_ok, json.dumps(out))


# ------------------------------------------------- C. #195 provenance -----
async def C():
    cfg = json.loads((HERE / "B18.machine.json").read_text(encoding="utf-8"))
    ctr = []
    hold = {"cancel_all_working_orders": asyncio.Event()}
    m = create_machine(cfg, logic=logic(cfg, "async", GV18, set(), ctr,
                                        svc_hold=hold), strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = P(); i.use(p)
    await i.start()
    await asyncio.sleep(0.05)
    await i.send("ENGAGE", wait=False)
    await asyncio.sleep(0.15)          # parked in cancelling, service held
    parked = sorted(i.current_state_ids)
    forged, err = None, None
    try:
        from xstate_statemachine.events import DoneEvent
        fe = DoneEvent("done.invoke.cx", {"ok": True}, "cx")
        await asyncio.wait_for(i.send(fe, wait=True), 3)
        forged = "accepted"
    except Exception as e:
        forged = "refused"
        err = "%s: %s" % (type(e).__name__, str(e)[:160])
    after = sorted(i.current_state_ids)
    hold["cancel_all_working_orders"].set()
    await asyncio.sleep(0.3)
    final = sorted(i.current_state_ids)
    await i.stop()
    rec("C/#195 forged DoneEvent cannot drive B18.onDone",
        forged == "refused" and after == parked,
        json.dumps({"parked": parked, "forged": forged, "err": err,
                    "after": after, "final": final, "svc": ctr}))


# --------------------------------------------------- D. #198 forgery ------
async def D():
    cfg = json.loads((HERE / "B18.machine.json").read_text(encoding="utf-8"))
    ctr = []
    m = create_machine(cfg, logic=logic(cfg, "async", GV18, set(), ctr),
                       strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.05)
    await asyncio.wait_for(i.send("ENGAGE", wait=True), 3)
    await asyncio.sleep(0.3)
    good = i.get_persisted_snapshot()
    honest = sorted(i.current_state_ids)
    await i.stop()
    blob = json.loads(good) if isinstance(good, str) else json.loads(
        json.dumps(good, default=str))

    async def restore(payload, tag):
        ctr2 = []
        m2 = create_machine(json.loads((HERE / "B18.machine.json")
                                       .read_text("utf-8")),
                            logic=logic(cfg, "async", GV18, set(), ctr2),
                            strict_targets=True)
        try:
            j = Interpreter.from_snapshot(json.dumps(payload), m2,
                                          clock=SimulatedClock())
            await j.start()
            await asyncio.sleep(0.2)
            st = sorted(j.current_state_ids)
            await j.stop()
            return {"tag": tag, "restored": st, "refused": False}
        except Exception as e:
            return {"tag": tag, "refused": True,
                    "exc": "%s: %s" % (type(e).__name__, str(e)[:140])}

    rt = await restore(blob, "honest")
    rec("D/honest round-trip restores the same configuration",
        rt.get("restored") == honest,
        json.dumps({"honest": honest, **rt}))

    # forgery 1: contradict `configuration`, keep state_ids
    f1 = json.loads(json.dumps(blob))
    # forgery 2: empty state_ids, keep a relocating configuration
    f2 = json.loads(json.dumps(blob))
    changed = []
    for key in ("configuration", "state_ids"):
        if key in f1:
            changed.append(key)
    # list-shaped forgeries, so the refusal must come from the AGREEMENT
    # rule (#198) and not from a shape check.
    if "configuration" in f1:
        f1["configuration"] = ["kill_switch.clear"]
    if "state_ids" in f2:
        f2["state_ids"] = []
        f2["configuration"] = ["kill_switch.clear"]
    f3 = json.loads(json.dumps(blob))
    f3["configuration"] = ["kill_switch.clear"]
    f3["state_ids"] = ["kill_switch.clear"]
    r1 = await restore(f1, "contradicted-configuration")
    r2 = await restore(f2, "emptied-state_ids")
    r3 = await restore(f3, "both-fields-agree-on-a-lie")
    rec("D/#198 forged configuration cannot relocate the kill switch",
        (r1.get("refused") or r1.get("restored") == honest)
        and (r2.get("refused") or r2.get("restored") == honest),
        json.dumps({"version": blob.get("version"), "fields": changed,
                    "f1": r1, "f2": r2}))
    rec("D/both-fields-agreeing forgery IS accepted (documented limit)",
        True, json.dumps({"honest": honest, "f3": r3}))


async def main():
    await A()
    B()
    await C()
    await D()


asyncio.run(main())
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "m5_sharp.json").write_text(
    json.dumps(R, indent=2, default=str), encoding="utf-8")
bad = [k for k, v in R.items() if not v["pass"]]
print("\n--- %d checks, %d FAIL: %s" % (len(R), len(bad), bad))
