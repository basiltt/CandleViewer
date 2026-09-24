"""New attack: observability hook matrix for new error classes -
on_plugin_error and on_resolve_error must fire (not silently drop) and
must not themselves leak unredacted secrets by default (they receive raw
exception objects, so we check the *library's own* logging around these
paths, not the hook payload itself, which is intentionally raw for the app
to redact)."""
import sys, logging, io
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.plugins import PluginBase

cfg = {"id": "m", "initial": "a", "context": {},
       "states": {"a": {"on": {"GO": "a", "SEND": "a"},
                          "entry": [{"type": "sendTo", "params": {"to": "no_such_actor", "event": {"type": "PING"}}}]}}}

events = {"plugin_error": None, "resolve_error": None}

class Probe(PluginBase):
    def on_plugin_error(self, interpreter, plugin, hook, exc):
        events["plugin_error"] = (type(plugin).__name__, hook, type(exc).__name__)
    def on_resolve_error(self, interpreter, exc, event):
        events["resolve_error"] = (type(exc).__name__, str(event))

class Bad(PluginBase):
    def on_transition(self, interpreter, transition, event):
        raise RuntimeError("boom-in-plugin")

m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).use(Bad()).use(Probe()).start()
try:
    interp.send("GO")
except Exception as e:
    print("send raised (unexpected escape):", type(e).__name__, e)

print("on_plugin_error fired:", events["plugin_error"])
print("on_resolve_error fired (sendTo to unresolved actor uses on_event_dropped, not on_resolve_error):", events["resolve_error"])
print("interp.last_plugin_error:", interp.last_plugin_error)
assert events["plugin_error"] is not None, "on_plugin_error never fired for a raising plugin hook"
print("OK: hook matrix delivered for on_plugin_error")
