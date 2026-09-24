import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CHILD={"id":"c","actionErrorPolicy":"fail","initial":"go","states":{"go":{"entry":["boom"]}}}
def boom(i,c,e,a): raise RuntimeError("child exploded")
ch=SyncInterpreter(create_machine(CHILD, logic=MachineLogic(actions={"boom":boom})))
try: ch.start()
except Exception as e: print("child.start raised:", type(e).__name__, e)
print("child status:", ch.status, "| error:", ch.error)
