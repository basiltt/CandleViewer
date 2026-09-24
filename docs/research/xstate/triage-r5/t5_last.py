import json
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.plugins import LoggingInspector
R={}
# wildcard "*" vs onUnhandled:defer  (our-contract CD-01/D-1/C-02)
base={"id":"w","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":"b"}},"b":{}}}
for star in (False,True):
    cfg=json.loads(json.dumps(base))
    if star: cfg["states"]["a"]["on"]["*"]={"actions":["defer"]}
    i=SyncInterpreter(create_machine(cfg,logic=MachineLogic(actions={"defer":lambda i,c,e,ad=None:None}))).start()
    i.send("UNKNOWN")
    R[f"star={star}"]={"deferred_count":getattr(i,"deferred_count",None),"ids":sorted(i.current_state_ids)}
# "*" defeats strict
for star in (False,True):
    cfg={"id":"s","initial":"a","strict":True,"states":{"a":{"on":{"GO":"b"}},"b":{}}}
    if star: cfg["states"]["a"]["on"]["*"]={"actions":["defer"]}
    i=SyncInterpreter(create_machine(cfg,logic=MachineLogic(actions={"defer":lambda i,c,e,ad=None:None}))).start()
    try: i.send("NOT_REAL"); R[f"strict_star={star}"]="ACCEPTED"
    except Exception as ex: R[f"strict_star={star}"]=type(ex).__name__
# LoggingInspector default redaction coverage
li=LoggingInspector()
keys=["account_number","bearer","cookie","dob","email","iban","mnemonic","pan","pin","pwd","seed_phrase","sessionId","signature","password","api_key","ssn","card","token"]
red=getattr(li,"redact",None)
if red:
    out=red({k:"SECRET" for k in keys})
    R["unredacted"]=sorted(k for k in keys if out.get(k)=="SECRET")
print(json.dumps(R,indent=1,default=str))
