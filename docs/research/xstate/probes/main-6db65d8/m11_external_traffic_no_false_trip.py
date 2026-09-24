import asyncio,sys,time
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
class D:
    def __init__(self): self.dropped=[]
    def __getattr__(self,n):
        def f(*a,**k):
            if n=='on_event_dropped': self.dropped.append(a[2] if len(a)>2 else '?')
        return f
# independent external traffic, each event arms an async service with latency
CFG={'id':'p','initial':'idle','context':{'done':0},'states':{
 'idle':{'on':{'GO':'work'}},
 'work':{'invoke':{'id':'s','src':'svc','onDone':{'target':'idle','actions':['count']}},'on':{'GO':'work2'}},
 'work2':{'invoke':{'id':'s','src':'svc','onDone':{'target':'idle','actions':['count']}},'on':{'GO':'work'}}},
 'maxIterations':50}
async def run(asyncdef,latency):
    async def sa(i,c,e): await asyncio.sleep(latency); return 1
    def ss(i,c,e):
        time.sleep(latency); return 1
    def count(i,c,e,*a): c['done']=c.get('done',0)+1
    d=D()
    i=Interpreter(create_machine(CFG,logic=MachineLogic(services={'svc':sa if asyncdef else ss},actions={'count':count}))).use(d)
    await i.start()
    for n in range(300):
        await i.send('GO')
        await asyncio.sleep(0.002)
    await asyncio.sleep(1.0)
    print(f'asyncdef={asyncdef} lat={latency} completions={i.context.get("done")} drops={len(d.dropped)} kinds={set(d.dropped)} err={type(i.last_error).__name__}',flush=True)
    try: await asyncio.wait_for(i.stop(),2)
    except Exception as ex: print('  stop failed',type(ex).__name__,flush=True)
async def main():
    for ad in (True,False): await run(ad,0.02)
asyncio.run(main())
