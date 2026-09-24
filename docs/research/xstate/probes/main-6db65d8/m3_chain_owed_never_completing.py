import asyncio,sys
sys.path.insert(0,'src')
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={'id':'p','initial':'off','context':{},'states':{
 'off':{'on':{'ARM':'on'}},
 'on':{'invoke':{'id':'forever','src':'forever'},'on':{'PING':{'actions':['noop']}}}},
 'maxIterations':50}
async def main():
    async def forever(i,c,e): await asyncio.sleep(3600)
    def noop(i,c,e,*a): pass
    i=Interpreter(create_machine(CFG,logic=MachineLogic(services={'forever':forever},actions={'noop':noop})))
    await i.start()
    await i.send('ARM'); await asyncio.sleep(0.1)
    print('after ARM: owed=',i._chain_owed,'depth=',i._raise_depth)
    for _ in range(10):
        await i.send('PING'); await asyncio.sleep(0.01)
    print('after 10 PING: owed=',i._chain_owed,'depth=',i._raise_depth)
    try: await asyncio.wait_for(i.stop(),3)
    except Exception as ex: print('stop failed',type(ex).__name__)
    print('after stop: owed=',i._chain_owed)
asyncio.run(main())
