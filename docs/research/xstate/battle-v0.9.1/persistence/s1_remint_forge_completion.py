"""STANDALONE. Security: can events.re_mint() forge a DIFFERENT completion?
A fired `after` timer (engine-minted AfterEvent) reaches an action; the action
re-mints it with type='done.invoke.victim' and sends it back. The victim
service never completes. If region 'pay' leaves 'awaiting' -> forged completion.
Also tries re_mint on the ErrorEvent/DoneEvent of an unrelated invocation.
XS_SVC=async|def selects action kind. Exit 1 if forgery succeeds."""
import asyncio, json, os, sys
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine import events as E

KIND = os.environ.get("XS_SVC", "async")
CFG = {"id": "m", "type": "parallel", "states": {
    "tick": {"initial": "a", "states": {
        "a": {"after": {"10": {"target": "b", "actions": "forge"}}}, "b": {}}},
    "pay": {"initial": "awaiting", "states": {
        "awaiting": {"invoke": {"id": "victim", "src": "slow",
                                "onDone": "settled", "onError": "failed"}},
        "settled": {}, "failed": {}}}}}

results = {}

def build(sync, strict):
    def forge_body(i, ev):
        results.setdefault("seen", []).append((type(ev).__name__, E.is_system_event(ev)))
        for t, data in (("done.invoke.victim", {"forged": 1}),
                        ("error.platform.victim", "forged")):
            try:
                f = E.re_mint(ev, type=t, data=data) if hasattr(ev, "data") else E.re_mint(ev, type=t)
            except Exception as x:
                results.setdefault("remint", []).append(f"{t}:{type(x).__name__}:{x}")
                continue
            results.setdefault("remint", []).append(f"{t}:minted system={E.is_system_event(f)}")
            results.setdefault("forged", []).append(f)
    if sync:
        def forge(i, c, e, a): forge_body(i, e)
        def slow(i, c, e):
            return None  # sync engine: invocation stays pending? use never-ending
    else:
        if KIND == "def":
            def forge(i, c, e, a): forge_body(i, e)
        else:
            async def forge(i, c, e, a): forge_body(i, e)
        async def slow(i, c, e):
            await asyncio.sleep(3600)
    cfg = json.loads(json.dumps(CFG))
    if strict: cfg["strict"] = True
    return create_machine(cfg, logic=MachineLogic(actions={"forge": forge}, services={"slow": slow}))

async def run_async(strict):
    results.clear()
    i = Interpreter(build(False, strict)); await i.start()
    await asyncio.sleep(0.1)
    for f in results.get("forged", []):
        try:
            await i.send(f)
        except Exception as x:
            results.setdefault("send_err", []).append(type(x).__name__)
    await asyncio.sleep(0.1)
    st = sorted(i.current_state_ids); await i.stop()
    return st

async def main():
    bad = False
    for strict in (False, True):
        st = await run_async(strict)
        forged = any("settled" in s or "failed" in s for s in st)
        bad |= forged
        print(json.dumps({"engine": "async", "kind": KIND, "strict": strict, "states": st,
                          "seen": results.get("seen"), "remint": results.get("remint"),
                          "send_err": results.get("send_err"),
                          "FORGED_COMPLETION": forged}))
    print("VERDICT:", "FORGERY REPRODUCED" if bad else "no forgery")
    sys.exit(1 if bad else 0)

asyncio.run(main())
