import logging, copy, threading, collections
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"s1","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"s2","onDone":{"target":"#m.a"}}}}}}}
SINGLE_COMPOUND = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"s1","onDone":{"target":"#m.a"}},"states":{"a":{}}}}}
# variant: inner onDone targets INNER's own parent but outer has no invoke
INNER_REENTER = {"id":"m","initial":"a","states":{"a":{"initial":"a","states":{
  "a":{"invoke":{"id":"i2","src":"s2","onDone":{"target":"#m.a.a"}}}}}}}

def run(name,cfg,secs=3):
    c=collections.Counter()
    lg=MachineLogic(services={"s1":lambda i,x,e:(c.update(['s1']),{"ok":1})[1],
                              "s2":lambda i,x,e:(c.update(['s2']),{"ok":1})[1]})
    it=SyncInterpreter(create_machine(copy.deepcopy(cfg),logic=lg))
    th=threading.Thread(target=lambda: it.start(),daemon=True);th.start();th.join(secs)
    print(f"  {name:<18} alive={th.is_alive()} counts={dict(c)}")
run("nested",NESTED)
run("single_compound",SINGLE_COMPOUND)
run("inner_self_reenter",INNER_REENTER)
