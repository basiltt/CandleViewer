import asyncio,sys,time
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
def kidcfg(n): return {'id':f'kid{n}','initial':'s','context':{},'states':{'s':{'entry':['slow']}}}
def parent(n):
    states={}
    for k in range(n):
        states[f'r{k}']={'initial':'up','states':{'up':{'invoke':{'id':f'kid{k}','src':f'kidm{k}'}}}}
    return {'id':'par','type':'parallel','context':{},'states':states}
async def main(n=4,slow=0.5,timeout=0.6):
    async def slowentry(i,c,e,*a): await asyncio.sleep(slow)
    logic_services={f'kidm{k}':create_machine(kidcfg(k),logic=MachineLogic(actions={'slow':slowentry})) for k in range(n)}
    i=Interpreter(create_machine(parent(n),logic=MachineLogic(services=logic_services)))
    t0=time.monotonic(); await i.start(children_timeout=timeout); el=time.monotonic()-t0
    print(f'{n} children each {slow}s entry, children_timeout={timeout}: start() took {el:.3f}s')
    print('  -> per-child bound would be <=%.1fs total (concurrent); aggregate bound=%.1f'%(slow,timeout))
    try: await asyncio.wait_for(i.stop(),3)
    except Exception as ex: print('stop failed',type(ex).__name__)
asyncio.run(main())
