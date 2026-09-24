import asyncio,sys
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
# a coroutine service that dies with a BaseException: not caught by the
# wrapper's `except Exception`, and the task is not `cancelled()`, so the
# debt registered by _owe_completion is never settled.
CFG={'id':'p','initial':'off','context':{},'states':{
 'off':{'on':{'ARM':'on'}},
 'on':{'invoke':{'id':'s','src':'boom','onError':'off'},'on':{'BACK':'off'}}},
 'maxIterations':50}
async def main():
    async def boom(i,c,e):
        await asyncio.sleep(0)
        raise BaseException('not an Exception')
    i=Interpreter(create_machine(CFG,logic=MachineLogic(services={'boom':boom})))
    await i.start()
    for n in range(5):
        await i.send('ARM'); await asyncio.sleep(0.05)
        await i.send('BACK'); await asyncio.sleep(0.02)
        print(f'lap {n}: owed={i._chain_owed} depth={i._raise_depth} state={i.current_state_ids}',flush=True)
    try: await asyncio.wait_for(i.stop(),3)
    except Exception as ex: print('stop failed',type(ex).__name__)
asyncio.run(main())
