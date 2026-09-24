"""
Isolated repro for D5-observability-1: SyncInterpreter.start() with
restart_timers=True never attaches the SimulatedClock settle hook, so a
re-armed 'after' timer fires internally but is never drained until some
other call (send()/tick()) happens to run. Kept separate from
new_attacks.py so it can be re-run standalone.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python d5_repro_sync_timer_settle.py
"""
import json
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

cfg = {"id": "m_timer", "initial": "a", "states": {"a": {"after": {1000: "b"}}, "b": {}}}
machine = create_machine(cfg, logic=MachineLogic())
clock = SimulatedClock()
interp = SyncInterpreter(machine, clock=clock).start()
snap = json.dumps(interp.get_persisted_snapshot())

new_clock = SimulatedClock()
restored = SyncInterpreter.from_snapshot(snap, machine, clock=new_clock, restart_timers=True)
restored.start()
print("settlers attached to restored clock (expect 1):", len(new_clock._settlers))
new_clock.increment(1001)  # advance well past the 1000ms deadline
print("state after increment(1001) with NO other call (expect 'm_timer.b', BUG if still 'a'):",
      restored.current_state_ids)
restored.tick()  # manual workaround
print("state after a manual .tick() (workaround):", restored.current_state_ids)
