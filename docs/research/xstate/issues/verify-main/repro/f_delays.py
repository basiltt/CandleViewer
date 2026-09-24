from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
cfg={"id":"m","initial":"a","states":{"a":{"after":{"MY_DELAY":{"target":"b"}}},"b":{"type":"final"}}}
try:
    m=create_machine(cfg, logic=MachineLogic(delays={"my_delay":10}))
    print("built OK; delay resolved?")
    i=SyncInterpreter(m).start()
    print("state", i.current_state_ids)
except Exception as e:
    print("ERR", type(e).__name__, e)
