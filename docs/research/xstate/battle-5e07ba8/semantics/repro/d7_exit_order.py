"""D-semantics: exit order across parallel regions is depth-major
(all leaves, then all regions) rather than SCXML's reverse document order
(region-major). Checked for STABILITY across PYTHONHASHSEED values, since
`_compute_states_to_exit` returns a Set."""
import logging, os, subprocess, sys, json
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG={"id":"m","initial":"p","states":{
 "p":{"exit":["xp"],"type":"parallel","states":{
   "A":{"exit":["xA"],"initial":"a1","states":{"a1":{"exit":["xa1"],"on":{"E":"#m.X"}}}},
   "B":{"exit":["xB"],"initial":"b1","states":{"b1":{"exit":["xb1"],"on":{"E":"#m.Y"}}}}}},
 "X":{"entry":["eX"]},"Y":{"entry":["eY"]}}}

def once():
    log=[]
    mk=lambda n:(lambda i,c,e,a: log.append(n))
    names=["xp","xA","xa1","xB","xb1","eX","eY"]
    s=SyncInterpreter(create_machine(CFG,logic=MachineLogic(
        actions={n:mk(n) for n in names}))).start()
    log.clear(); s.send("E"); s.stop(); return log

if os.environ.get("CHILD"):
    print(json.dumps(once())); sys.exit()
orders=set()
for seed in ["0","1","42","12345","99999"]:
    env=dict(os.environ, CHILD="1", PYTHONHASHSEED=seed,
             PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    out=subprocess.run([sys.executable,__file__],env=env,
                       capture_output=True,text=True).stdout.strip()
    print(f"PYTHONHASHSEED={seed:6} -> {out}")
    orders.add(out)
print("\nSCXML exitOrder (reverse document order):",
      json.dumps(["xb1","xB","xa1","xA","xp","eX"]))
print("distinct orders observed:", len(orders),
      "->", "DETERMINISTIC" if len(orders)==1 else "NONDETERMINISTIC")
