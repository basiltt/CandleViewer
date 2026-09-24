"""S-probe 6: #227/#230 — scheduled_sends admission, armed-count semantics,
partial-restore consistency, plugins= vs .use() ordering."""
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.plugins import PluginBase

CFG = {"id": "m", "strict": True, "initial": "a", "states": {
    "a": {"entry": [{"type": "xstate.raise",
                     "params": {"event": "TICK", "delay": 5000}}],
          "on": {"TICK": "b"}}, "b": {}}}

class Spy(PluginBase):
    def __init__(s, n): s.n = n; s.seen = []
    def on_invalid_event(s, i, err, ev=None):
        s.seen.append((s.n, getattr(ev, "type", ev)))

async def main():
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m); await i.start(); await asyncio.sleep(0.05)
    snap = i.get_persisted_snapshot(); await i.stop()
    print("scheduled_sends:", [(r["type"], r.get("remaining_ms")) for r in snap["scheduled_sends"]])

    # Inject one undeclared + one declared record. Order: bad first.
    bad = dict(snap["scheduled_sends"][0]); bad["type"] = "UNDECLARED"; bad["remaining_ms"] = 10
    snap2 = json.loads(json.dumps(snap))
    snap2["scheduled_sends"] = [bad, dict(snap["scheduled_sends"][0])]

    a, b = Spy("plugins="), Spy(".use()")
    r = Interpreter.from_snapshot(json.dumps(snap2), m, plugins=[a])
    r.use(b)
    armed = r._rearm_restored_self_sends()
    print("armed=", armed, "(2 records, 1 refused)")
    print("last_error=", type(r.last_error).__name__ if r.last_error else None)
    print("plugins= saw:", a.seen, "| .use() saw:", b.seen)
    await r.start(); await asyncio.sleep(0.05)
    print("re-persist after refusal:", len(r.get_persisted_snapshot()["scheduled_sends"]))
    print("status=", r.status, "state=", sorted(r.current_state_ids))
    await r.stop()

asyncio.run(asyncio.wait_for(main(), 25))
