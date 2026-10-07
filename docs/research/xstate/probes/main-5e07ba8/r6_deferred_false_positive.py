"""Deterministic: a HANDLED event reports deferred=True because
`_deferred_this_step` keeps id()s of dead objects (fire-and-forget defers)."""
import sys
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":{"target":"a"}}}}}
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic())); i.start()
i.send("NOPE")                                   # deferred, no receipt -> id leaks
stale = set(i._deferred_this_step)
print("stale ids held:", len(stale))
hits=0; trials=4000
for _ in range(trials):
    r = i.send("GO", wait=True)                  # ALWAYS handled (self-transition)
    if r.deferred:
        hits+=1
print(f"handled 'GO' wrongly reported deferred=True: {hits}/{trials}")
print("VERDICT:", "DEFECT REPRODUCED" if hits else "not hit this run (id reuse is timing-dependent)")
print("residual stale ids:", len(i._deferred_this_step))
i.stop()
