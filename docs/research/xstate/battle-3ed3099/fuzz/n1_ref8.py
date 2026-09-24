import logging, copy, threading, collections, json
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
# Realistic OMS shape: a compound "working" state that itself invokes a
# supervisor service, with a child step that invokes a slice-placer whose
# onDone returns to the parent to place the next slice (iceberg/TWAP pattern).
OMS = {"id":"iceberg","initial":"working","states":{"working":{
  "initial":"placing",
  "invoke":{"id":"watch","src":"watch_book","onDone":{"target":"#iceberg.working"}},
  "states":{"placing":{"invoke":{"id":"slice","src":"place_slice",
      "onDone":{"target":"#iceberg.working"}}}}}}}
c=collections.Counter()
lg=MachineLogic(services={"watch_book":lambda i,x,e:(c.update(['watch']),{})[1],
                          "place_slice":lambda i,x,e:(c.update(['slice']),{})[1]})
it=SyncInterpreter(create_machine(copy.deepcopy(OMS),logic=lg))
th=threading.Thread(target=lambda: it.start(),daemon=True);th.start();th.join(4)
print(f"  OMS-shaped iceberg: alive={th.is_alive()} slices_placed={c['slice']} watches={c['watch']}")
