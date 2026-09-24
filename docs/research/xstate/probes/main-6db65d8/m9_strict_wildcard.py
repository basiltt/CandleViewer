import asyncio,sys
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import UnknownEventError
CFG={'id':'p','initial':'a','context':{},'states':{'a':{'on':{'GO':'a','*':{'actions':['log_it']}}}}}
def mk(): return create_machine(CFG,logic=MachineLogic(actions={'log_it':lambda *a: None}))
s=SyncInterpreter(mk(),strict=True); s.start()
for ev in ('GO','TYPO','*'):
    try:
        s.send(ev); print(f'sync strict send({ev!r}) -> accepted, state={s.current_state_ids}')
    except UnknownEventError as e: print(f'sync strict send({ev!r}) -> UnknownEventError')
s2=SyncInterpreter(mk()); s2.start()
for ev in ('TYPO',):
    r=s2.send(ev); print(f'sync non-strict send({ev!r}) -> ok (wildcard dispatch preserved)')
