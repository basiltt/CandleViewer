"""K-8: PR#141 geometry memo — is TransitionDefinition._geometry shared
mutable state across interpreters of the SAME machine object?
Also: does a parallel root whose regions all reach final report done?"""
import asyncio, time
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

# 1. geometry memo shared across interpreters
cfg={"id":"g","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{"on":{"GO":"a"}}}}
m=create_machine(cfg, logic=MachineLogic())
i1=SyncInterpreter(m).start(); i1.send("GO")
t=m.states["a"].on["GO"][0]
print("[1] geometry memo after i1:", t._geometry is not None,
      "->", None if t._geometry is None else (t._geometry[1].id if t._geometry[1] else None))
i2=SyncInterpreter(m).start(); i2.send("GO")
print("    i1 ids:", i1.current_state_ids, "i2 ids:", i2.current_state_ids)

# 2. strict_targets=False live-resolution: memo keyed on id(target) -> id reuse?
print("[2] memo key is id(target_state); StateNodes are held by the machine "
      "tree for its lifetime, so id() reuse needs the node to be GC'd. "
      "Live-resolved targets always resolve within the same tree.")

# 3. parallel all-final -> done?
n=3
pc={"id":"p","type":"parallel","states":{f"r{k}":{"initial":"s","states":{
    "s":{"on":{"GO":"d"}},"d":{"type":"final"}}} for k in range(n)}}
pm=create_machine(pc, logic=MachineLogic())
pi=SyncInterpreter(pm).start()
pi.send("GO")
print("[3] parallel all regions final -> status:", pi.status,
      "ids:", sorted(pi.current_state_ids))
