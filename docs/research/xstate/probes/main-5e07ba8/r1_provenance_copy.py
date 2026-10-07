"""R1: does the engine-private provenance sentinel survive copy/pickle?"""
import copy, pickle, sys
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine.events import system_event, is_system_event, Event

ev = system_event("xstate.init")
print("original      :", is_system_event(ev))
print("copy.copy     :", is_system_event(copy.copy(ev)))
print("copy.deepcopy :", is_system_event(copy.deepcopy(ev)))
try:
    print("pickle roundtr:", is_system_event(pickle.loads(pickle.dumps(ev))))
except Exception as e:
    print("pickle FAILED :", type(e).__name__, e)
print("equality user==system:", Event("xstate.init") == ev)
print("hash equal?   :", end=" ")
try:
    print(hash(Event("xstate.init")) == hash(ev))
except TypeError as e:
    print("unhashable:", e)
