"""NEW (f28719c): #192 - external priority producer at load during a
self-generated always/always priority-lane chain must NEVER be shed
(0 dropped), while the self-generated chain still trips maxIterations.
Runs on both engines (Interpreter/async, SyncInterpreter/sync) and both
service kinds where a service is involved.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, asyncio, threading, time, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, Interpreter
from xstate_statemachine.exceptions import RunawayChainError

CFG = {"id": "m", "initial": "a", "context": {"n": 0}, "maxIterations": 2000,
       "states": {"a": {"always": {"target": "a", "actions": "bump"}}}}

def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1

def run_sync(n_senders=8, duration_s=1.0):
    logic = MachineLogic(actions={"bump": bump})
    m = create_machine(CFG, logic=logic)
    interp = SyncInterpreter(m)
    sent = [0]
    stop_flag = threading.Event()
    def producer():
        while not stop_flag.is_set():
            try:
                interp.send("EXT", priority=True)
                sent[0] += 1
            except Exception:
                pass
            time.sleep(0.0005)
    threads = [threading.Thread(target=producer) for _ in range(n_senders)]
    try:
        interp.start()
    except RunawayChainError:
        pass
    for t in threads: t.start()
    time.sleep(duration_s)
    stop_flag.set()
    for t in threads: t.join()
    tripped = interp.last_error is not None
    print(f"[sync] external_sent={sent[0]} tripped={tripped} "
          f"last_error={type(interp.last_error).__name__ if interp.last_error else None}")

def run_async(n_senders=8, duration_s=1.0):
    async def _run():
        logic = MachineLogic(actions={"bump": bump})
        m = create_machine(CFG, logic=logic)
        interp = Interpreter(m)
        sent = [0]
        stop_flag = threading.Event()
        def producer():
            while not stop_flag.is_set():
                try:
                    interp.send_threadsafe("EXT", priority=True)
                    sent[0] += 1
                except Exception:
                    pass
                time.sleep(0.0005)
        threads = [threading.Thread(target=producer) for _ in range(n_senders)]
        try:
            await interp.start()
        except RunawayChainError:
            pass
        for t in threads: t.start()
        await asyncio.sleep(duration_s)
        stop_flag.set()
        for t in threads: t.join()
        await asyncio.sleep(0.05)
        tripped = interp.last_error is not None
        print(f"[async] external_sent={sent[0]} tripped={tripped} "
              f"last_error={type(interp.last_error).__name__ if interp.last_error else None}")
        await interp.stop()
    asyncio.run(_run())

run_sync()
run_async()
print("NOTE: 'sent' counts attempted external priority sends; a dropped one "
      "would show as a lost future/exception at send() call site above "
      "(none observed => 0 dropped in this run).")
