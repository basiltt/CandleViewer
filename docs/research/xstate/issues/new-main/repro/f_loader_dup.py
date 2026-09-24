import types, sys
from xstate_statemachine import create_machine
mod=types.ModuleType("dupmod")
def fetch_data(i,c,e,a): return "SNAKE"
def fetchData(i,c,e,a): return "CAMEL"
mod.fetch_data=fetch_data; mod.fetchData=fetchData
sys.modules["dupmod"]=mod
m=create_machine({"id":"m","initial":"a","states":{"a":{"entry":["FETCH_DATA"]}}}, logic_modules=["dupmod"])
print("bound to:", m.logic.actions["FETCH_DATA"].__name__)
