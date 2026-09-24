"""#92: copy.copy(final_logic) is SHALLOW. A MachineLogic SUBCLASS that keeps
other mutable state, or that auto-registers BOUND methods, shares that state
across every machine -- and the copy's bound methods still point at the
ORIGINAL instance."""
import sys, copy
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
CFG={"id":"m","initial":"a","states":{"a":{"entry":["bump"]}}}
class L(MachineLogic):
    def __init__(self):
        self.counter=0
        super().__init__()
    def bump(self, interp, ctx, evt, ad):
        self.counter+=1
l=L()
m1=create_machine(CFG, logic=l); m2=create_machine(CFG, logic=l)
print("m1.logic is m2.logic:", m1.logic is m2.logic, "| both are not caller:", m1.logic is not l)
print("m1.logic.counter is l.counter shared?", m1.logic.counter is l.counter)
f=m1.logic.actions.get("bump")
print("registered 'bump' __self__ is the CALLER instance:", getattr(f,'__self__',None) is l)
