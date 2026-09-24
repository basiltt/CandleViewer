# -*- coding: utf-8 -*-
"""STANDALONE refutation harness for R12-13 (C-04): B16 elevation outlives
revocation.  Covers BOTH engines (async Interpreter + SyncInterpreter) and
BOTH action kinds (def / async def), and proves the config-only fix.
stdlib + xstate_statemachine only; runs from any cwd.
"""
from __future__ import annotations
import asyncio, json, copy
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)

KILLS = ("REVOKE", "LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE")

def base_cfg():
    return {
        "id": "session", "type": "parallel",
        "actionErrorPolicy": "rollback", "onUnhandled": "defer",
        "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
        "context": {"revoke_reason": None, "audits": []},
        "states": {
            "auth": {"initial": "pending_mfa", "states": {
                "pending_mfa": {"on": {"MFA_OK": {"target": "#session.auth.active"}}},
                "active": {"on": {k: {"target": "#session.auth.revoked",
                                      "actions": ["set_reason"]} for k in KILLS}},
                "revoked": {"type": "final"}}},
            "elevation": {"initial": "normal", "states": {
                "normal": {"on": {"STEP_UP_OK": {
                    "target": "#session.elevation.elevated",
                    "actions": ["audit_step_up"]}}},
                "elevated": {"on": {
                    "REVOKE": {"target": "#session.elevation.normal"},
                    "STEP_UP_OK": {"target": "#session.elevation.elevated",
                                   "reenter": True,
                                   "actions": ["audit_step_up"]}}}}},
        },
    }

def fixed_cfg():
    """Proposed config-only fix: hoist the four revocation events to the root,
    targeting a final elevation.dead; audit on the re-enter arm."""
    c = base_cfg()
    c["states"]["elevation"]["states"]["dead"] = {"type": "final"}
    c["on"] = {k: {"target": "#session.elevation.dead"} for k in KILLS}
    return c

def logic(async_actions: bool):
    if async_actions:
        async def set_reason(i, c, e, a): c["revoke_reason"] = e.type
        async def audit_step_up(i, c, e, a): c["audits"].append("step_up")
    else:
        def set_reason(i, c, e, a): c["revoke_reason"] = e.type
        def audit_step_up(i, c, e, a): c["audits"].append("step_up")
    return MachineLogic(actions={"set_reason": set_reason,
                                 "audit_step_up": audit_step_up}, strict=True)

async def run_async(cfg, kill, async_actions):
    m = create_machine(copy.deepcopy(cfg), logic=logic(async_actions),
                       strict_targets=True)
    i = Interpreter(m)
    await i.start()
    for ev in ("MFA_OK", "STEP_UP_OK", kill, "STEP_UP_OK"):
        await i.send(ev)
        for _ in range(5):          # poll to convergence
            await asyncio.sleep(0.01)
    st = sorted(i.current_state_ids); ctx = dict(i.context)
    await i.stop()
    return st, ctx

def run_sync(cfg, kill, async_actions):
    if async_actions:
        return None, None           # sync engine takes sync actions only
    m = create_machine(copy.deepcopy(cfg), logic=logic(False),
                       strict_targets=True)
    i = SyncInterpreter(m); i.start()
    for ev in ("MFA_OK", "STEP_UP_OK", kill, "STEP_UP_OK"):
        i.send(ev)
    st = sorted(i.current_state_ids); ctx = dict(i.context)
    i.stop()
    return st, ctx

async def main():
    rows = []
    for label, cfg in (("catalogue", base_cfg()), ("fixed", fixed_cfg())):
        for kind, aa in (("def", False), ("async def", True)):
            for kill in KILLS:
                st, ctx = await run_async(cfg, kill, aa)
                rows.append({"cfg": label, "engine": "async", "kind": kind,
                             "kill": kill, "states": st,
                             "elevated": "session.elevation.elevated" in st,
                             "audits": len(ctx["audits"])})
                st2, ctx2 = run_sync(cfg, kill, aa)
                if st2 is not None:
                    rows.append({"cfg": label, "engine": "sync", "kind": kind,
                                 "kill": kill, "states": st2,
                                 "elevated": "session.elevation.elevated" in st2,
                                 "audits": len(ctx2["audits"])})
    for r in rows:
        print(json.dumps(r))
    bad = [(r["cfg"], r["engine"], r["kind"], r["kill"])
           for r in rows if r["elevated"]]
    print("\nLIVE-ELEVATION-AFTER-REVOCATION:", bad)
    print("catalogue-fails:", sum(1 for b in bad if b[0] == "catalogue"),
          " fixed-fails:", sum(1 for b in bad if b[0] == "fixed"))

asyncio.run(main())
