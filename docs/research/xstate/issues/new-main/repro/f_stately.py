from xstate_statemachine import create_machine, MachineLogic
def a1(i,c,e,ad): pass
def a2(i,c,e,ad): pass
# Two DISTINCT Stately-ish names that normalise to the same key
cfg={"id":"m","initial":"s","states":{"s":{"entry":["inline:m.a#entry[0]"]}}}
m=create_machine(cfg, logic=MachineLogic(actions={"inline_m_a_entry_0":a1}))
print("stately alias ok ->", m.logic.actions["inline:m.a#entry[0]"].__name__)
# collision: 'fetch-data' and 'fetch.data' are different config names
cfg2={"id":"m2","initial":"s","states":{"s":{"entry":["fetch-data","fetch.data"]}}}
m2=create_machine(cfg2, logic=MachineLogic(actions={"fetchData":a1}))
print("both bound:", {k:v.__name__ for k,v in m2.logic.actions.items()})
