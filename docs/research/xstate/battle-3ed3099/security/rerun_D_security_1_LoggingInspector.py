"""Re-run D-security-1 (5e07ba8): LoggingInspector secret leak.
CHANGELOG claims #126 fixed this: LoggingInspector now redacts by default.
Verify: sensitive keys ARE redacted; redact_keys=() opts back into raw logging
(documented escape hatch, not a defect)."""
import logging, io, sys
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.plugins import LoggingInspector

def run(redact_keys=None):
    buf = io.StringIO()
    lg = logging.getLogger("xstate_statemachine")
    for h in list(lg.handlers):
        lg.removeHandler(h)
    lg.addHandler(logging.StreamHandler(buf))
    lg.setLevel(logging.INFO)
    cfg = {"id": "m", "initial": "a", "context": {"api_key": "sk-live-SECRET"},
           "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    m = create_machine(cfg, logic=MachineLogic())
    kwargs = {} if redact_keys is None else {"redact_keys": redact_keys}
    interp = SyncInterpreter(m).use(LoggingInspector(**kwargs)).start()
    interp.send("GO")
    return buf.getvalue()

default_out = run()
print("DEFAULT redacts (no secret in log):", "sk-live-SECRET" not in default_out)
assert "sk-live-SECRET" not in default_out

opt_out = run(redact_keys=())
print("redact_keys=() is explicit opt-out (secret visible):", "sk-live-SECRET" in opt_out)
assert "sk-live-SECRET" in opt_out

print("VERDICT: D-security-1 FIXED for LoggingInspector by default (#126); explicit opt-out preserved.")
