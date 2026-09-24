import types, sys, logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine
mod=types.ModuleType("tm2")
def fetch_data(i,c,e,a): pass
mod.fetch_data=fetch_data
sys.modules["tm2"]=mod
# Config declares TWO distinct actions; only ONE impl exists.
m=create_machine({"id":"m","initial":"a","states":{"a":{"entry":["fetch-data","fetchData"]}}}, logic_modules=["tm2"])
print("both bound to one impl:", {k:v.__name__ for k,v in m.logic.actions.items()})
