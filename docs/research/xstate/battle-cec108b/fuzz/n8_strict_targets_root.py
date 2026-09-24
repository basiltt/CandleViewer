"""N8 -- #108 rejects a root target at build under the DEFAULT strict_targets=True.
Does strict_targets=False reopen D-fuzz-2 (configuration silently emptied,
machine reports running)?  Both engines."""
import asyncio, copy, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (SyncInterpreter, Interpreter, MachineLogic,
                                 create_machine, XStateMachineError)

CFG = {"id":"m","initial":"a","states":{"a":{"on":{"GO":"#m"}},"b":{}}}
L = lambda: MachineLogic()

print("sync, strict_targets=False:")
m = create_machine(copy.deepcopy(CFG), logic=L(), strict_targets=False)
it = SyncInterpreter(m); it.start()
print("  before GO:", sorted(it.current_state_ids))
it.send("GO")
print(f"  after  GO: states={sorted(it.current_state_ids)} status={it.status} "
      f"last_transition_ok={it.last_transition_ok} "
      f"last_error={type(it.last_error).__name__ if it.last_error else None}")
try:
    s = it.get_persisted_snapshot()
    print(f"  snapshot: configuration={s.get('configuration')} state_ids={s.get('state_ids')} status={s.get('status')}")
    r = SyncInterpreter.from_snapshot(json.dumps(s), create_machine(copy.deepcopy(CFG), logic=L(), strict_targets=False))
    print(f"  restored: states={sorted(r.current_state_ids)} status={r.status}")
except XStateMachineError as e:
    print(f"  snapshot/restore -> typed {type(e).__name__}: {str(e)[:120]}")
except BaseException as e:
    print(f"  snapshot/restore -> UNTYPED {type(e).__name__}: {e}")
it.send("GO")
print(f"  further send accepted; states={sorted(it.current_state_ids)} status={it.status}")

print("async, strict_targets=False:")
async def main():
    i = Interpreter(create_machine(copy.deepcopy(CFG), logic=L(), strict_targets=False))
    await i.start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    print(f"  after GO: states={sorted(i.current_state_ids)} status={i.status} "
          f"last_transition_ok={i.last_transition_ok} "
          f"last_error={type(i.last_error).__name__ if i.last_error else None}")
    await i.stop()
try: asyncio.run(asyncio.wait_for(main(), 30))
except BaseException as e: print("  async:", type(e).__name__, e)
