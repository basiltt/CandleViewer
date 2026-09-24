"""R5-19 repro: get_snapshot() logs the FULL unredacted snapshot at DEBUG
(bypassing LoggingInspector.redact() entirely), and DEFAULT_REDACT_KEYS misses
most financial/session PII even when redact() IS used.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
import io
import logging
import sys

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.plugins import DEFAULT_REDACT_KEYS, redact


def get_snapshot_leak_case():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("xstate_statemachine")
    prev_level = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"api_key": "sk-live-SECRET999", "password": "hunter2"},
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }
    m = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(m).start()
    interp.send("GO")
    interp.get_snapshot()  # logs the raw JSON snapshot at DEBUG, no redaction
    interp.stop()

    text = buf.getvalue()
    lg.removeHandler(h)
    lg.setLevel(prev_level)
    leaked = "sk-live-SECRET999" in text and "hunter2" in text
    return leaked, text


def redact_coverage_case():
    financial_keys = [
        "account_number", "bearer", "cookie", "dob", "email", "iban",
        "mnemonic", "pan", "pin", "pwd", "seed_phrase", "sessionId",
        "signature", "password", "api_key", "token",
    ]
    sample = {k: f"LEAK-{k}" for k in financial_keys}
    redacted = redact(sample)
    missed = [k for k in financial_keys if redacted[k] == f"LEAK-{k}"]
    return missed


def main() -> int:
    leaked, log_text = get_snapshot_leak_case()
    missed = redact_coverage_case()

    print("OBSERVED:")
    print(f"  get_snapshot() DEBUG log leaks secrets : {leaked}")
    if leaked:
        idx = log_text.find("sk-live-SECRET999")
        print(f"  log excerpt: {log_text[max(0, idx - 60): idx + 30]!r}")
    print(f"  DEFAULT_REDACT_KEYS               : {DEFAULT_REDACT_KEYS}")
    print(f"  financial/session keys NOT redacted: {missed}")

    print("EXPECTED:")
    print("  get_snapshot() never emits unredacted context at DEBUG, and")
    print("  DEFAULT_REDACT_KEYS covers realistic financial/session PII")
    print("  (iban, account_number, pan, signature, pwd, sessionId, ...)")

    fail = leaked or len(missed) >= 5
    if fail:
        print("RESULT: FAIL - unredacted secret leak and/or redaction coverage gap")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
