"""Verify #160 on cec108b: redaction contract (get_snapshot DEBUG leak +
DEFAULT_REDACT_KEYS coverage).

Acceptance criteria (issue #160 + CHANGELOG "#160" bullet):
  A) Interpreter.get_snapshot()'s DEBUG log does NOT emit unredacted
     context, with or without a LoggingInspector attached.
  B) DEFAULT_REDACT_KEYS covers the 16 named financial/session/personal
     keys: iban, account_number, pan, signature, pwd, sessionId, bearer,
     cookie, session, otp, pin, mnemonic, seed_phrase, dob, email, phone,
     passport (case-insensitive substring match per redact()'s contract).
  C) LoggingInspector redacts service results (on_service_done) and
     ErrorEvent / DoneEvent data.
"""
from __future__ import annotations

import io
import logging
import sys

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.plugins import DEFAULT_REDACT_KEYS, redact, LoggingInspector


def criterion_A_get_snapshot_no_leak() -> bool:
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
    interp.get_snapshot()
    interp.stop()

    text = buf.getvalue()
    lg.removeHandler(h)
    lg.setLevel(prev_level)
    leaked = "sk-live-SECRET999" in text or "hunter2" in text
    print(f"  [A] get_snapshot() DEBUG log leaked secrets: {leaked}")
    return not leaked


def criterion_B_key_coverage() -> bool:
    required = [
        "iban", "account_number", "pan", "signature", "pwd", "sessionId",
        "bearer", "cookie", "session", "otp", "pin", "mnemonic",
        "seed_phrase", "dob", "email", "phone", "passport",
    ]
    sample = {k: f"LEAK-{k}" for k in required}
    redacted = redact(sample)
    missed = [k for k in required if redacted[k] != "***"]
    print(f"  [B] DEFAULT_REDACT_KEYS missed: {missed}")
    return not missed


def criterion_C_service_result_redacted() -> bool:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("xstate_statemachine")
    prev_level = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)

    cfg = {
        "id": "m3",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "src": "svc",
                    "onDone": "b",
                }
            },
            "b": {},
        },
    }

    def svc(interpreter, ctx, event):
        return {"password": "hunter2", "ok": True}

    m = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    inspector = LoggingInspector()
    interp = SyncInterpreter(m)
    interp.use(inspector)
    interp.start()
    interp.stop()

    text = buf.getvalue()
    lg.removeHandler(h)
    lg.setLevel(prev_level)
    leaked = "hunter2" in text
    print(f"  [C] service result 'password' leaked via LoggingInspector: {leaked}")
    return not leaked


def main() -> int:
    results = [
        criterion_A_get_snapshot_no_leak(),
        criterion_B_key_coverage(),
        criterion_C_service_result_redacted(),
    ]
    ok = all(results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


sys.exit(main())
