import asyncio,sys,time
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={'id':'p','initial':'a','context':{},'states':{'a':{'on':{'PING':{'target':'b','actions':['bump']}}},'b':{'on':{'PING':{'target':'a','actions':['bump']}}}},'maxIterations':50}
CAP=20000
async def run(asyncdef):
    laps=[0]; t0=time.monotonic()
    def stopnow(i):
        raise SystemExit
    async def ba(i,c,e,*a):
        laps[0]+=1
        if laps[0]<CAP: await i.send('PING',priority=True)
    def bs(i,c,e,*a):
        laps[0]+=1
        if laps[0]<CAP: i.send('PING',priority=True)
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={'bump':ba if asyncdef else bs})))
    await i.start(); await i.send('PING')
    for _ in range(200):
        await asyncio.sleep(0.02)
        if laps[0]>=CAP: break
    print(f'asyncdef={asyncdef} priority=True laps={laps[0]} (cap {CAP}) elapsed={time.monotonic()-t0:.2f}s err={type(i.last_error).__name__}',flush=True)
    try: await asyncio.wait_for(i.stop(),2)
    except Exception as ex: print('  stop failed',type(ex).__name__,flush=True)
async def main():
    for ad in (False,True): await run(ad)
asyncio.run(main())
