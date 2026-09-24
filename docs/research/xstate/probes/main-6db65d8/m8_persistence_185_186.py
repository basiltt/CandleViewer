import sys,json
sys.path.insert(0,'src')
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
CFG={'id':'p','type':'parallel','context':{'n':1},'states':{
 'r1':{'initial':'a','states':{'a':{'on':{'X':'b'}},'b':{}}},
 'r2':{'initial':'c','states':{'c':{}}}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic()));s.start();s.send('X')
blob=s.get_persisted_snapshot()
d=blob if isinstance(blob,dict) else json.loads(blob)
print('version',d.get('version'),'hash?',('machine_hash' in d))
print('state_ids',d['state_ids']); print('configuration',d.get('configuration'))
r=SyncInterpreter.from_snapshot(json.dumps(d),create_machine(CFG,logic=MachineLogic()))
print('roundtrip ok ->',r.current_state_ids)
# #185: strip hash
d2=dict(d); d2['machine_hash']=None
try:
    SyncInterpreter.from_snapshot(json.dumps(d2),create_machine(CFG,logic=MachineLogic())); print('null hash: ACCEPTED (bad)')
except Exception as e: print('null hash refused:',type(e).__name__)
# #186: drop configuration key entirely (older writer)
d3=dict(d); d3.pop('configuration',None)
try:
    r3=SyncInterpreter.from_snapshot(json.dumps(d3),create_machine(CFG,logic=MachineLogic())); print('no configuration key: accepted ->',r3.current_state_ids)
except Exception as e: print('no configuration key refused:',type(e).__name__,e)
