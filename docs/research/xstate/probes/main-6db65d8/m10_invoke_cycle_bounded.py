import asyncio,sys,time
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
# invoke cycle a -> done -> b -> done -> a, with an optional `after` timer
# in a parallel region. The timer is an engine completion that NEVER owed
# a debt, but _deliver_priority decrements _chain_owed for it anyway.
def cfg(with_timer):
    states={'cyc':{'initial':'a','states':{
        'a':{'invoke':{'id':'s','src':'svc','onDone':'b'}},
        'b':{'invoke':{'id':'s2','src':'svc','onDone':'a'}}}}}
    if with_timer:
        states['tick']={'initial':'t','states':{'t':{'after':{5:'t'}}}}
    return {'id':'p','type':'parallel','context':{},'states':states,'maxIterations':50}
async def run(with_timer,asyncdef):
    laps=[0]
    async def sa(i,c,e): laps[0]+=1; return 1
    def ss(i,c,e): laps[0]+=1; return 1
    i=Interpreter(create_machine(cfg(with_timer),logic=MachineLogic(services={'svc':sa if asyncdef else ss})))
    await i.start()
    t0=time.monotonic()
    while time.monotonic()-t0<2.0 and laps[0]<5000:
        await asyncio.sleep(0.02)
    print(f'timer={with_timer} asyncdef={asyncdef} service_laps={laps[0]} err={type(i.last_error).__name__}',flush=True)
    try: await asyncio.wait_for(i.stop(),2)
    except Exception as ex: print('  stop failed',type(ex).__name__,flush=True)
async def main():
    for ad in (False,True):
        for wt in (False,True): await run(wt,ad)
asyncio.run(main())
