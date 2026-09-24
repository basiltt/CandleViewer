"""#99: SyncInterpreter delivers onError for a failed invoked CHILD MACHINE."""
import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CHILD={"id":"c","actionErrorPolicy":"fail","initial":"go","states":{"go":{"entry":["boom"]}}}
def boom(i,c,e,a): raise RuntimeError("child exploded")
def mkchild(): return create_machine(CHILD, logic=MachineLogic(actions={"boom":boom}))
def case(with_handler):
    on={"onDone":{"target":"ok"}}
    if with_handler: on["onError"]={"target":"failed","actions":["cap"]}
    P={"id":"p","initial":"a","states":{"a":{"invoke":dict(id="k",src="child",**on)},"ok":{},"failed":{}}}
    cap={}
    def capf(i,c,e,a): cap["e"]=e
    i=SyncInterpreter(create_machine(P, logic=MachineLogic(actions={"cap":capf}, services={"child":mkchild()})))
    try:
        i.start()
        import time; time.sleep(0.5); i.tick()
        print(f"  handler={with_handler}: state={set(i.current_state_ids)} status={i.status} evt={type(cap.get('e')).__name__ if cap else None} err={getattr(cap.get('e'),'error',None)}")
    except Exception as ex:
        print(f"  handler={with_handler}: RAISED {type(ex).__name__}: {ex}")
print("SYNC invoked child machine failure:")
case(True); case(False)
