import sys
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
import xstate_statemachine as x
from xstate_statemachine.events import Event, is_system_event
print("system_event exported? ", hasattr(x, "system_event"), "in __all__:", "system_event" in getattr(x,"__all__",[]))
print("is_system_event export?", hasattr(x, "is_system_event"), "in __all__:", "is_system_event" in getattr(x,"__all__",[]))
print("Receipt exported?      ", "Receipt" in getattr(x,"__all__",[]))
print("RunawayChainError      ", "RunawayChainError" in getattr(x,"__all__",[]))
# Forge attempt 1: module attribute
from xstate_statemachine import events as E
ev = Event("PAY_OUT")
object.__setattr__(ev, "_provenance", E._ENGINE_MARK)
print("forged via module attr :", is_system_event(ev))
# Forge attempt 2: no private names at all -- steal from a public mint
try:
    from xstate_statemachine.events import system_event
    donor = system_event("xstate.init")
    ev2 = Event("PAY_OUT")
    object.__setattr__(ev2, "_provenance", donor._provenance)
    print("forged via public mint :", is_system_event(ev2))
except Exception as e:
    print("mint unavailable:", e)
