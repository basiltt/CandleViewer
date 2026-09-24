"""D5-security-1: get_snapshot() logs the FULL unredacted snapshot at DEBUG.

LoggingInspector redacts (#126), but the interpreter's own get_snapshot()
(base_interpreter.py ~line 1022-948) logs the raw json_snapshot string via
logger.debug(...) with no redaction at all -- so any app/ops team that turns
on DEBUG logging (very common in staging, or briefly in prod to chase a bug)
gets every secret in `context` written to logs verbatim, independent of
whether LoggingInspector is used.
"""
import logging
import io
import sys

sys.path.insert(0, "src")

buf = io.StringIO()
h = logging.StreamHandler(buf)
lg = logging.getLogger("xstate_statemachine")
lg.addHandler(h)
lg.setLevel(logging.DEBUG)

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter

cfg = {
    "id": "m",
    "initial": "a",
    "context": {"api_key": "sk-live-SECRET999", "password": "hunter2"},
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
interp.send("GO")
snap = interp.get_snapshot()

out = buf.getvalue()
leaked = "sk-live-SECRET999" in out or "hunter2" in out
print("SNAPSHOT_STRING_HAS_SECRET:", "sk-live-SECRET999" in snap)
print("DEBUG_LOG_LEAKS_SECRET:", leaked)
if leaked:
    idx = out.find("sk-live-SECRET999")
    print("LOG EXCERPT:", out[max(0, idx - 80): idx + 40])
assert leaked, "expected secret to leak into DEBUG log (no redaction on get_snapshot)"
print("REPRO CONFIRMED: get_snapshot() DEBUG log has no redaction, unlike LoggingInspector")
