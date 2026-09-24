from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
# a: GO->b handled. BACK unhandled in a => deferred. In b, BACK handled.
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":"b"}},"b":{"on":{"BACK":"a"}}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic())); s.start()
bad=0; n=3000
for k in range(n):
    r=s.send("BACK",wait=True)   # in a -> deferred; replayed after GO
    r2=s.send("GO",wait=True)    # handled -> a->b, then deferred BACK replays -> a
    for rr in (r,r2):
        if rr is not None and rr.deferred and rr.changed: bad+=1
print("receipts with deferred=True AND changed=True:",bad,"of",2*n)
print("final ids",s.current_state_ids,"deferred_count",s.deferred_count,
      "stale id-set size",len(getattr(s,'_deferred_this_step',()) or ()))
