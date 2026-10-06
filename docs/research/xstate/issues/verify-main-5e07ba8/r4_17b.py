import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import asyncio,sys,threading,logging,json
sys.path.insert(0,str(_XS / 'src'))
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter,MachineLogic,create_machine
from xstate_statemachine.models import OverflowPolicy
from xstate_statemachine.exceptions import QueueOverflowError
CFG={"id":"t","initial":"s","context":{"n":0},"states":{"s":{"on":{"PING":{"actions":["slow"]}}}}}
async def main():
    async def slow(i,c,e,a):
        c["n"]+=1; await asyncio.sleep(0.02)
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"slow":slow})),max_queue_size=3,overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    res={"overflow_raised_on_calling_thread":0,"ok":0,"other":0}
    lk=threading.Lock()
    def prod():
        for _ in range(40):
            try:
                i.send_threadsafe("PING").result(timeout=5)
                with lk: res["ok"]+=1
            except QueueOverflowError:
                with lk: res["overflow_raised_on_calling_thread"]+=1
            except Exception as e:
                with lk: res["other"]+=1
    ts=[threading.Thread(target=prod) for _ in range(8)]
    for t in ts: t.start()
    while any(t.is_alive() for t in ts): await asyncio.sleep(0.01)
    print(json.dumps(res))
    await i.stop(drain=False)
asyncio.run(main())
