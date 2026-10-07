---
id: DE-L2
title: "Bug: an inline-dict `invoke.src` dies with `TypeError: unhashable type: 'dict'` from inside logic_loader, not a named InvalidConfigError"
labels: [bug, validation, severity/low]
severity: Low
repro_script: repro/DE-L2-repro.py
commit: de2da4e
verified: true
---

## Summary

This is one of the last items on the "make it perfect" list after twelve
rounds of adoption battle-testing — the library is already adopted and this
sits well inside "adopt with constraints", not near a blocker.

`#220` gave the config validator an excellent recursive unknown-key check
with path-named "did you mean" diagnostics. There is one config shape that
never reaches it: an `invoke.src` written as an **inline machine config
dict**. That shape is not supported — which is a perfectly reasonable
design choice — but it fails with a bare `TypeError: unhashable type:
'dict'` raised from deep inside `logic_loader`, under *every* strict
setting, rather than with the `InvalidConfigError` the rest of the config
surface produces.

The ask is small: reject the shape by name at validation time, so the
error says what is wrong and where.

## Environment

- `xstate-statemachine` @ `de2da4e` (main; `__version__` still `0.8.0`,
  `CHANGELOG.md` `[Unreleased]` targets 0.8.1)
- `.venv-main`, CPython 3.13.7, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- cwd `<home>` (neutral — outside any project tree)

## Minimal reproduction

```python
"""DE-L2 repro: an inline-dict `invoke.src` fails with an opaque
`TypeError: unhashable type: 'dict'` from deep inside `logic_loader`,
instead of a named `InvalidConfigError` from the #220 validator.

STANDALONE: stdlib + xstate_statemachine only. Run from cwd <home>.
"""

import sys

sys.path.insert(
    0,
    "<workspace>/_ref/"
    "xstate-statemachine/src",
)
from xstate_statemachine import create_machine, MachineLogic  # noqa: E402

# An inline nested-machine config dict supplied directly as `invoke.src`.
# NOTE: there is no typo anywhere in this config -- it is well-formed.
CLEAN = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "invoke": {
                "id": "kid",
                "src": {
                    "id": "kid",
                    "initial": "k",
                    "states": {"k": {}},
                },
            }
        }
    },
}

# The same shape, with a typo (`entyr` for `entry`) inside the sub-machine.
TYPO = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "invoke": {
                "id": "kid",
                "src": {
                    "id": "kid",
                    "initial": "k",
                    "states": {"k": {"entyr": ["nope"]}},
                },
            }
        }
    },
}

# Control: the identical typo one level up, as an ordinary state config.
CONTROL = {"id": "m2", "initial": "a", "states": {"a": {"entyr": ["nope"]}}}


def attempt(label, cfg, strict):
    try:
        create_machine(cfg, logic=MachineLogic(), strict_config=strict)
        return f"{label:28s} strict={strict!s:5s} -> built OK"
    except Exception as exc:  # noqa: BLE001 -- the point is which type
        return (
            f"{label:28s} strict={strict!s:5s} -> "
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )


lines = [
    attempt("inline dict src, no typo", CLEAN, False),
    attempt("inline dict src, no typo", CLEAN, True),
    attempt("inline dict src, with typo", TYPO, True),
    attempt("control: typo one level up", CONTROL, True),
]
for line in lines:
    print(line)

opaque = "TypeError" in lines[0] and "TypeError" in lines[1]
named_control = "InvalidConfigError" in lines[3]
print()
print("a well-formed inline-dict src fails with TypeError :", opaque)
print("the same typo one level up is named properly       :", named_control)
print()
print("REPRODUCED:", opaque and named_control)
sys.exit(1 if (opaque and named_control) else 0)
```

## Observed behaviour

```
inline dict src, no typo     strict=False -> TypeError: unhashable type: 'dict'
inline dict src, no typo     strict=True  -> TypeError: unhashable type: 'dict'
inline dict src, with typo   strict=True  -> TypeError: unhashable type: 'dict'
control: typo one level up   strict=True  -> InvalidConfigError: Machine 'm2' has unknown config key(s) -- m2.a: 'entyr' (did you mean 'entry'?)...

REPRODUCED: True
```

Exit code 1.

Note the first two lines: the config is **well-formed** — no typo at all —
and it still dies with `TypeError`. So this is not a validation-recursion
gap; the shape is simply unsupported, and says so badly.

## Expected behaviour

An inline-dict `invoke.src` should be rejected at validation time with an
`InvalidConfigError` that names the path and the supported alternatives,
in the same voice as every other config diagnostic. Something like:

```
Machine 'm' -- m.a invoke[kid]: `src` must be a service name (str), a
MachineNode, or a callable returning one; got dict. To invoke a nested
machine, build it with create_machine(...) and register it in
MachineLogic(services={...}).
```

## Root cause analysis

The supported `src` shapes are resolved at spawn time in
`interpreter.py:2501-2508`: a `MachineNode`, or a callable returning one.
A `dict` is neither, so the shape is genuinely unsupported.

The failure happens earlier and lower down. `LogicLoader._extract_logic_from_node`
(`logic_loader.py:229`) does:

```python
for invoke_def in node.invoke:
    if invoke_def.src:
        services.add(invoke_def.src)
```

`services` is a `set`, so `set.add(<dict>)` raises `TypeError: unhashable
type: 'dict'`. The traceback surfaces through `LogicLoader.required_names`
(`logic_loader.py:258`) with no machine id, no state path, and no mention
of `invoke` or `src`.

The `#220` validator never gets a chance to comment: `KNOWN_INVOKE_KEYS`
(`validation.py:332-335`) includes `src`, so the key itself is legal, and
`_collect_unknown_keys` (`validation.py:396-410`) validates the invoke
dict's own keys and its `onDone`/`onError` transitions but does not
type-check `src`'s **value**.

## Impact

Low, and latent for us — no chart in our corpus uses an inline invoked
machine. Two reasons it is still worth a line of code:

1. `TypeError: unhashable type: 'dict'` is genuinely hard to act on. It
   names no machine, no state, and no config key; a reader has to walk the
   `logic_loader` traceback to discover that `invoke.src` is the culprit.
2. An inline nested machine is a natural thing to *try* — it is the shape
   XState's JS API accepts — so this is a plausible first-hour experience
   for a new adopter, and the error gives them nothing to search for.

This is a diagnostics defect, not a functional one. We are explicitly
**not** asking for inline-dict `src` to be supported.

## Proposed fix

Type-check the `src` value in `_collect_unknown_keys`'s invoke loop (or
wherever the invoke block is normalised), before `logic_loader` touches it:

```python
src = inv.get("src")
if src is not None and not isinstance(src, str) and not callable(src):
    out.append(
        f"{ipath}: `src` must be a service name (str), a MachineNode, or "
        f"a callable returning one; got {type(src).__name__}"
    )
```

Emitting through the existing `out` channel means it inherits `#220`'s
strict/warn behaviour and path naming for free.

## Acceptance criteria

- `create_machine(cfg, logic=..., strict_config=True)` with a dict-valued
  `invoke.src` raises `InvalidConfigError`, not `TypeError`, and the
  message names the state path, the invoke id, and the supported `src`
  shapes.
- The same config under `strict_config=False` produces the same named
  diagnostic (as a WARNING, matching `#220`'s strict/warn split) rather
  than a `TypeError`.
- A regression test (e.g. `test_inline_dict_invoke_src_is_named`) pins the
  exception type and asserts the message mentions `src` and the path.
- The existing `#220` fuzz corpus (13 typo cells, 640-case injection
  sweep, 54-chart no-false-positive corpus) is unchanged.

## Verification

- Repro run from cwd `<home>` with the `.venv-main` interpreter:
  **exit 1**, no `ImportError`, output as quoted above.
- The block under "## Minimal reproduction" is byte-identical to
  `repro/DE-L2-repro.py`.
- Root-cause lines confirmed open in current source at `de2da4e`:
  `logic_loader.py:229` (`services.add(invoke_def.src)`),
  `logic_loader.py:258` (`required_names`), `validation.py:332-335`
  (`KNOWN_INVOKE_KEYS` includes `src`), `validation.py:396-410` (invoke
  loop does not inspect `src`'s value), `interpreter.py:2501-2508`
  (supported `src` shapes).
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state
  all --limit 320` searched for `invoke.src`, `validation`, `strict_config`
  — no open issue covers this; `#220` and `#216` are the closest and both
  CLOSED, and neither concerns the `src` *value* type.

## Related

- `#220` — the recursive unknown-key check this sits beside; **noted on
  that thread in an earlier round and promoted to its own issue for
  tracking**.
- `#216` — the root-only predecessor.
- Our adoption audit (#26).
