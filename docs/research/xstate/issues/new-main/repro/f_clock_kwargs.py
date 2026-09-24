import time
from xstate_statemachine import create_machine, SyncInterpreter
class KwargsClock:
    """0.7/0.8-era clock that forwards **kwargs to an old backend."""
    def __init__(self): self.items=[]
    def now(self): return time.monotonic()
    def set_timeout(self, fn, delay_sec, **kwargs):
        # a real wrapper often forwards to a legacy scheduler:
        owner=kwargs.get("owner")
        assert set(kwargs) <= {"owner"}, f"unexpected kwargs: {sorted(kwargs)}"
        self.items.append((self.now()+delay_sec, fn, owner)); return len(self.items)-1
    def clear_timeout(self, h): pass
    def pump(self, owner=None):
        n=self.now(); fired=0
        for i,(t,fn,o) in list(enumerate(self.items)):
            if t<=n and fn: self.items[i]=(t,None,o); fn(); fired+=1
        return fired
cfg={"id":"m","initial":"a","states":{"a":{"after":{10:{"target":"b"}}},"b":{"type":"final"}}}
c=KwargsClock()
i=SyncInterpreter(create_machine(cfg), clock=c).start()
print("scheduled items:", len(c.items))
time.sleep(0.05); i.tick()
print("state:", i.current_state_ids)
