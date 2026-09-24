"""Verify #216 on main@c78ce99: unknown top-level config keys.
Standalone: stdlib + xstate_statemachine only. cwd-independent.
Exit 0 = all criteria met. Exit 1 = any criterion fails.
"""
import logging
from io import StringIO
from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError

fails = []

def base(extra):
    cfg = {"id": "m", "initial": "a", "states": {"a": {}}}
    cfg.update(extra)
    return cfg

def warns_with_hint(extra_key, expect_hint):
    buf = StringIO()
    h = logging.StreamHandler(buf)
    logger = logging.getLogger("xstate_statemachine.validation")
    logger.addHandler(h)
    logger.setLevel(logging.WARNING)
    try:
        create_machine(base({extra_key: True}))
    finally:
        logger.removeHandler(h)
    out = buf.getvalue()
    ok = "unknown top-level key" in out.lower() or "unknown" in out.lower()
    ok = ok and (expect_hint.lower() in out.lower())
    return ok, out

MISSPELLINGS = {
    "actionErrorPolicyy": "actionErrorPolicy",
    "Strict": "strict",
    "maxIteration": "maxIterations",
    "onUnhandledEvent": "onUnhandled",
}

for bad, hint in MISSPELLINGS.items():
    ok, out = warns_with_hint(bad, hint)
    if not ok:
        fails.append(f"WARN+hint missing for {bad}: {out!r}")

# strict_config=True raises
try:
    create_machine(base({"Strict": True}), strict_config=True)
    fails.append("strict_config=True did not raise for 'Strict'")
except InvalidConfigError:
    pass
except Exception as e:
    fails.append(f"strict_config=True raised wrong type: {type(e)}")

# config-level strictConfig: true raises
try:
    create_machine(base({"Strict": True, "strictConfig": True}))
    fails.append("config-level strictConfig:true did not raise")
except InvalidConfigError:
    pass
except Exception as e:
    fails.append(f"config-level strictConfig raised wrong type: {type(e)}")

# reserved keys always accepted (no strict_config)
try:
    create_machine(base({"x-foo": 1, "meta": {}, "description": "d",
                          "tags": ["a"], "version": 1}))
except Exception as e:
    fails.append(f"reserved keys rejected: {e}")

# reserved keys accepted even under strict_config=True
try:
    create_machine(base({"x-foo": 1, "meta": {}, "description": "d",
                          "tags": ["a"], "version": 1}), strict_config=True)
except Exception as e:
    fails.append(f"reserved keys rejected under strict_config: {e}")

# control: bad VALUE for known key still raises regardless
try:
    create_machine(base({"actionErrorPolicy": "not-a-policy"}))
    fails.append("control: bad value for known key was NOT refused")
except InvalidConfigError:
    pass

if fails:
    print("FAIL:")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("PASS: all #216 criteria verified on main@c78ce99")
raise SystemExit(0)
