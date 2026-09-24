---
r5: R5-19
title: "Bug: get_snapshot() logs unredacted context at DEBUG, and DEFAULT_REDACT_KEYS misses most financial/session PII"
labels: [bug, severity/medium, area/persistence]
severity: Medium
repro_script: repro/R5-19_redaction-gaps.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

Two independent gaps in the redaction contract introduced/left open around
`#126`. First, `Interpreter.get_snapshot()` logs the full JSON snapshot
verbatim via `logger.debug(...)`, entirely bypassing
`LoggingInspector.redact()` — so any app that turns on DEBUG logging (a
routine staging/production-debugging action) writes every secret in
`context` to logs regardless of whether `LoggingInspector` is even
attached. Second, even where `redact()` *is* used, `DEFAULT_REDACT_KEYS`
misses 13 of 16 realistic financial/session key names (`iban`,
`account_number`, `pan`, `signature`, `pwd`, `sessionId`, `bearer`,
`cookie`, `dob`, `email`, `mnemonic`, `pin`, `seed_phrase`). The `redact()`
mechanism itself is well built — pure, recursive, case-insensitive
substring match, documented opt-out via `redact_keys=()` — the defaults and
the unguarded second call site are the problem.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`,
  so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
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
```

## Observed behaviour

```
OBSERVED:
  get_snapshot() DEBUG log leaks secrets : True
  log excerpt: '5241,\n  "status": "running",\n  "context": {\n    "api_key": "sk-live-SECRET999",\n    "passw'
  DEFAULT_REDACT_KEYS               : ('password', 'passwd', 'secret', 'token', 'api_key', 'apikey', 'authorization', 'auth', 'credential', 'private_key', 'ssn', 'card', 'cvv')
  financial/session keys NOT redacted: ['account_number', 'bearer', 'cookie', 'dob', 'email', 'iban', 'mnemonic', 'pan', 'pin', 'pwd', 'seed_phrase', 'sessionId', 'signature']
EXPECTED:
  get_snapshot() never emits unredacted context at DEBUG, and
  DEFAULT_REDACT_KEYS covers realistic financial/session PII
  (iban, account_number, pan, signature, pwd, sessionId, ...)
RESULT: FAIL - unredacted secret leak and/or redaction coverage gap
```

## Expected behaviour

`#126`'s own stated rationale for `LoggingInspector.redact()`, per the
in-repo docstring: "a debugging plugin attached 'just for a minute' is
exactly how credentials end up in a log aggregator." That rationale applies
identically to `get_snapshot()`'s own DEBUG log — a call site the library
controls directly, with no plugin involved at all — and the library's own
defaults should cover the sensitive-key vocabulary of the financial/session
domain it advertises persistence for (`stately.ai/docs/persistence`
documents `getPersistedSnapshot()` as safe to log/store for ops visibility,
which presumes it does not leak secrets when DEBUG logging is on).

## Root cause analysis

- `base_interpreter.py:1010-1029` — `get_snapshot()` calls
  `self.get_persisted_snapshot()`, serializes it with
  `json.dumps(snapshot, indent=2, default=str)`, and logs the **entire**
  `json_snapshot` string via `logger.debug(...)` (`:1026-1028`) with no
  call to `redact()` and no `LoggingInspector` involvement — this call site
  is independent of whether any plugin is attached.
- `plugins.py:454-468` — `DEFAULT_REDACT_KEYS` is a 13-entry tuple
  (`password, passwd, secret, token, api_key, apikey, authorization, auth,
  credential, private_key, ssn, card, cvv`) matched by case-insensitive
  substring in `redact()` (`:471-486`). Substring matching means `card`
  catches `card_number` but not `pan` (the ISO 8583 term for the same
  data), and `token`/`auth` do not catch `bearer`, `cookie`, or `sessionId`
  — common session-identifier key names.
- Secondary, latent (not independently reproduced live in this repro):
  `plugins.py`'s `LoggingInspector` calls `_safe()` (which wraps `redact()`)
  at exactly two sites — `on_event_received` for `Event` payloads and
  `_log_ctx` — so a `DoneEvent.data` or `ErrorEvent.error` logged elsewhere
  bypasses redaction by construction.

## Impact

General: any operator who enables DEBUG logging temporarily — the single
most common way secrets end up in a log aggregator, per the library's own
stated threat model for `#126` — gets every context secret written in
clear via `get_snapshot()`, independent of `LoggingInspector`. Separately,
even careful adopters who *do* attach `LoggingInspector` and rely on
`DEFAULT_REDACT_KEYS` leak the majority of realistic financial/session key
names.

Concrete order-management scenario: an OMS persists account/session state
via `get_snapshot()` for audit/replay, and briefly raises the log level to
DEBUG while chasing a production incident — bank account numbers
(`account_number`), IBANs (`iban`), payment card numbers under the PAN
alias (`pan`), and session identifiers (`sessionId`) all land in the log
aggregator in clear, both via the unguarded `get_snapshot()` log line and
via `LoggingInspector`'s default key list.

## Proposed fix

1. Route `get_snapshot()`'s DEBUG log line through `redact()` on the
   snapshot's `context` before serializing it for the log message (leave
   the returned string itself unredacted and unchanged — only the log
   line changes), so the log-visible secret set is opt-in via
   `redact_keys` the same way `LoggingInspector` already is.
2. Expand `DEFAULT_REDACT_KEYS` to include the missed financial/session
   terms identified above: `pwd`, `pan`, `iban`, `account_number`,
   `signature`, `bearer`, `cookie`, `sessionId`, `dob`, `email`, `mnemonic`,
   `seed_phrase`, `pin`.
3. Extend `_safe()` coverage in `LoggingInspector` to the `DoneEvent.data`
   / `ErrorEvent.error` branches so the secondary latent gap does not
   become live under future logging changes.

Compatibility: additive default-list expansion changes what gets redacted
by default (strictly more redaction, no new leaks) — call out in the
changelog since it changes visible log output for existing adopters who
rely on the current defaults.

## Acceptance criteria

- [ ] `repro/R5-19_redaction-gaps.py` exits `0`.
- [ ] `tests/test_persistence.py::test_get_snapshot_debug_log_is_redacted`
- [ ] `tests/test_plugins.py::test_default_redact_keys_covers_financial_pii`
      — parametrized over the missed-key list above, 0 failures.
- [ ] `tests/test_plugins.py::test_done_event_data_redacted_in_logs`
- [ ] `tests/test_plugins.py::test_error_event_error_redacted_in_logs`
- [ ] Changelog entry noting the expanded default redaction list and the
      new `get_snapshot()` log redaction.

## Related

- Register source: R5-19, evidence
  `security/repro_D_security_1_snapshot_log_leak.py`, `32-r5-diff-review.md`
  **J-7**.
- `#126` (LoggingInspector.redact() itself, whose rationale and mechanism
  this issue extends rather than contradicts).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased 0.8.1)
- Re-ran `repro/R5-19_redaction-gaps.py` fresh: exit 1.
- Root-cause file:line citations checked against `src/xstate_statemachine`
  at this commit; all confirmed exact.
- Duplicates check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "<keyword>"` run for this finding's keywords; no
  round-4 issue (#102-#138, all CLOSED) covers this exact gap — #126 shipped LoggingInspector.redact() itself but did not cover get_snapshot()'s independent DEBUG log line or expand DEFAULT_REDACT_KEYS to the financial/session key set identified here.
