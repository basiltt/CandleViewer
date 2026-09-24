import asyncio,sys
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError
CFG={'id':'p','initial':'a','context':{'n':1},'states':{'a':{'entry':['e']}}}
class P:
    def __init__(s): s.results={}
    def __getattr__(s,n):
        def f(*a,**k):
            if n in ('on_transition','on_interpreter_start','on_action_execute'):
                i=a[0]
                try:
                    i.get_persisted_snapshot(); s.results[n]='ok'
                except SnapshotMidStepError: s.results[n]='REFUSED'
                except Exception as ex: s.results[n]=type(ex).__name__
        return f
async def main():
    p=P()
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={'e':lambda *a:None}))).use(p)
    await i.start()
    print('async engine hook snapshots:',p.results)
    await i.stop()
    p2=P()
    s=SyncInterpreter(create_machine(CFG,logic=MachineLogic(actions={'e':lambda *a:None}))).use(p2)
    s.start()
    print('sync  engine hook snapshots:',p2.results)
asyncio.run(main())
