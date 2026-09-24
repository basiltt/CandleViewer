"""FIFO break: send_threadsafe() (from a worker thread) still goes to the
EXTERNAL inbox; an in-loop send() during the same macrostep now goes to the
INTERNAL queue and jumps ahead of it."""
import sys, asyncio, threading, time
def run(src, label):
    sys.path.insert(0,src)
    for m in list(sys.modules):
        if m.startswith("xstate_statemachine"): del sys.modules[m]
    from xstate_statemachine import create_machine, MachineLogic, Interpreter
    order=[]
    async def slow(i,c,e,a): await asyncio.sleep(0.4)
    def note(i,c,e,a): order.append(e.type)
    CFG={"id":"m","initial":"a","states":{"a":{"on":{
      "SLOW":{"actions":["slow"]},"FROM_THREAD":{"actions":["note"]},"IN_LOOP":{"actions":["note"]}}}}}
    async def main():
        i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow":slow,"note":note})))
        await i.start(); await i.send("SLOW")
        await asyncio.sleep(0.05)
        done=threading.Event()
        def worker():
            i.send_threadsafe("FROM_THREAD"); done.set()
        threading.Thread(target=worker).start()
        await asyncio.to_thread(done.wait)    # FROM_THREAD is definitely queued first
        await asyncio.sleep(0.05)
        await i.send("IN_LOOP")               # sent LATER, from the loop
        await asyncio.sleep(1.2)
        print(f"  {label:8s} order = {order}   (FIFO expects ['FROM_THREAD','IN_LOOP'])")
        await i.stop()
    asyncio.run(main()); sys.path.pop(0)
run("/tmp/lib3c/src","3c527b0")
run("C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src","5e07ba8")
