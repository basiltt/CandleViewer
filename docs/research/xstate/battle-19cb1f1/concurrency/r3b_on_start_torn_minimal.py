"""R3b - MINIMAL: `get_persisted_snapshot()` from `on_interpreter_start`
returns a blob claiming status "running" with an EMPTY configuration.

#182 set the in-flight flag for the whole `start()` descent so a snapshot
from an initial entry action is refused. `on_interpreter_start` fires
OUTSIDE that window -- status has already been flipped to "running" but no
state has been entered -- so the blob is accepted and is torn.

Also asks the question that decides severity: does the torn blob RESTORE?
(#143 / #186 read-side guards.)
"""
import asyncio, json
from common2 import (Interpreter, MachineLogic, PluginBase, SyncInterpreter,
                     create_machine, emit, make_service)
from xstate_statemachine.exceptions import SnapshotMidStepError
CFG={"id":"r3b","initial":"a","context":{"n":0},"states":{
 "a":{"entry":["bump"],"invoke":{"src":"s","onDone":{"target":"b"}}},"b":{}}}
def bump(i,c,e,a): c["n"]=c.get("n",0)+1
class P(PluginBase):
    def __init__(self): self.rows=[]
    def on_interpreter_start(self,i):
        try: self.rows.append(("returned", i.get_persisted_snapshot()))
        except SnapshotMidStepError as e: self.rows.append(("refused",str(e)[:60]))
def mk(kind):
    return create_machine(CFG,logic=MachineLogic(actions={"bump":bump},
        services={"s":make_service(kind)}))
async def one(kind,engine):
    p=P()
    if engine=="async":
        i=Interpreter(mk(kind)).use(p); await asyncio.wait_for(i.start(),10)
        live=i.get_persisted_snapshot(); await i.stop()
    else:
        i=SyncInterpreter(mk(kind)).use(p); i.start()
        live=i.get_persisted_snapshot(); i.stop()
    disp,blob=p.rows[0]
    row={"engine":engine,"kind":kind,"disposition":disp,
         "status":blob.get("status") if disp=="returned" else None,
         "state_ids":blob.get("state_ids") if disp=="returned" else None,
         "configuration":blob.get("configuration") if disp=="returned" else None,
         "healthy_state_ids":live.get("state_ids")}
    if disp=="returned":
        try:
            r=Interpreter.from_snapshot(mk(kind),blob) if engine=="async" \
              else SyncInterpreter.from_snapshot(mk(kind),blob)
            row["restore"]="ACCEPTED"
            row["restored_state_ids"]=sorted(getattr(r,'current_state_ids',[]))
            row["restored_status"]=r.status
        except Exception as exc:
            row["restore"]=f"refused:{type(exc).__name__}"
    return row
async def main():
    rows=[await one(k,"async") for k in ("def","async def")]+[await one("def","sync")]
    bad=[r for r in rows if r["disposition"]=="returned" and r["status"]=="running"
         and not r["state_ids"]]
    emit("r3b_on_start_torn_minimal",{"rows":rows,"torn":bad,
         "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
