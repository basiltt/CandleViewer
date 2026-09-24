import asyncio,sys,time
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
class D:
    def __init__(self): self.dropped=[]
    def __getattr__(self,n):
        def f(*a,**k):
            if n=='on_event_dropped': self.dropped.append((getattr(a[1],'type','?'),a[2]))
        return f
CHILD={'id':'kid','initial':'s','context':{'got':0},'states':{'s':{'entry':['slow'],'on':{'POKE':{'actions':['got']}}}}}
PARENT={'id':'par','initial':'up','context':{},'states':{'up':{'invoke':{'id':'kid','src':'kidm'},'on':{'POKE':{'actions':[{'type':'sendTo','params':{'to':'kid','event':'POKE'}}]}}}}}
async def main(nkids=1,slow=1.0,timeout=0.3):
    async def slowentry(i,c,e,*a): await asyncio.sleep(slow)
    def got(i,c,e,*a): c['got']=c.get('got',0)+1
    kid=create_machine(CHILD,logic=MachineLogic(actions={'slow':slowentry,'got':got}))
    d=D()
    i=Interpreter(create_machine(PARENT,logic=MachineLogic(services={'kidm':kid}))).use(d)
    t0=time.monotonic()
    await i.start(children_timeout=timeout)
    el=time.monotonic()-t0
    print(f'start() returned in {el:.3f}s (timeout={timeout}); actors={list(i._actors)}',flush=True)
    await i.send('POKE')   # sendTo while child still starting
    await asyncio.sleep(slow+0.4)
    kidi=next(iter(i._actors.values()),None)
    print('after wait: actors=',list(i._actors),'kid.got=',getattr(kidi,'context',{}).get('got') if kidi else None,flush=True)
    print('drops=',d.dropped,flush=True)
    try: await asyncio.wait_for(i.stop(),3)
    except Exception as ex: print('stop failed',type(ex).__name__)
asyncio.run(main())
