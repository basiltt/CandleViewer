import sys,threading,time
sys.path.insert(0,'src')
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError
CHILD={'id':'kid','initial':'s','context':{'n':0},'states':{'s':{'on':{'SLOW':{'actions':['grind']}}}}}
PAR={'id':'par','initial':'up','context':{},'states':{'up':{'invoke':{'id':'kid','src':'kidm'}}}}
def grind(i,c,e,*a):
    time.sleep(5.0)   # pathological child step on its own pump thread
    c['n']=c.get('n',0)+1
kid=create_machine(CHILD,logic=MachineLogic(actions={'grind':grind}))
p=SyncInterpreter(create_machine(PAR,logic=MachineLogic(services={'kidm':kid})))
p.start()
child=next(iter(p._actors.values()))
print('child pump ident:',child._step_thread_ident)
threading.Thread(target=lambda: child.send('SLOW'),daemon=True).start()
time.sleep(0.3)
t0=time.monotonic()
try:
    p.get_persisted_snapshot()
    print(f'snapshot OK after {time.monotonic()-t0:.3f}s (child still grinding?)')
except SnapshotMidStepError as e:
    print(f'refused after {time.monotonic()-t0:.3f}s child={e.child}')
print('elapsed total %.3f'%(time.monotonic()-t0))
