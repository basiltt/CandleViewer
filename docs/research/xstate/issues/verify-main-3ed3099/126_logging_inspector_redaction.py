# -*- coding: utf-8 -*-
"""Verify #126 on main@3ed3099: LoggingInspector redacts denylisted keys by
default (context + event payload), nested/list structures, and does not
leak secret values to the logger even without opt-in configuration.
"""
from __future__ import annotations

import io
import logging

from xstate_statemachine import SyncInterpreter, create_machine
from xstate_statemachine.plugins import LoggingInspector, redact


def crit_redact_nested() -> bool:
    out = redact(
        {
            "apiKey": "x",
            "user": {"password": "y", "name": "ok"},
            "l": [{"token": "z"}],
            "authorization": "Bearer abc",
            "secret": "s",
        }
    )
    expected = {
        "apiKey": "***",
        "user": {"password": "***", "name": "ok"},
        "l": [{"token": "***"}],
        "authorization": "***",
        "secret": "***",
    }
    print(f"  redact() output: {out}")
    return out == expected


def crit_no_leak_in_logs() -> bool:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    lg = logging.getLogger("xstate_statemachine")
    prev_level = lg.level
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        i = SyncInterpreter(
            create_machine(
                {
                    "id": "m",
                    "initial": "a",
                    "context": {"api_key": "SECRET-KEY", "token": "TOK-1"},
                    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
                }
            )
        ).use(LoggingInspector())
        i.start()
        i.send("GO", password="hunter2", secret="deep-dark")
    finally:
        lg.removeHandler(h)
        lg.setLevel(prev_level)
        logging.disable(prev_disable)
    text = buf.getvalue()
    leaks = [s for s in ("SECRET-KEY", "TOK-1", "hunter2", "deep-dark") if s in text]
    has_redaction_marker = "***" in text
    print(f"  captured log leaks: {leaks}")
    print(f"  redaction marker present: {has_redaction_marker}")
    return not leaks and has_redaction_marker


def crit_docstring_documents_redaction() -> bool:
    doc = LoggingInspector.__doc__ or ""
    ok = "redact" in doc.lower() and (
        "production" in doc.lower() or "secret" in doc.lower()
    )
    print(f"  LoggingInspector docstring mentions redaction/production warning: {ok}")
    return ok


def main() -> int:
    r1 = crit_redact_nested()
    r2 = crit_no_leak_in_logs()
    r3 = crit_docstring_documents_redaction()
    print(f"crit_redact_nested: {'PASS' if r1 else 'FAIL'}")
    print(f"crit_no_leak_in_logs: {'PASS' if r2 else 'FAIL'}")
    print(f"crit_docstring_documents_redaction: {'PASS' if r3 else 'FAIL'}")
    ok = r1 and r2 and r3
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
