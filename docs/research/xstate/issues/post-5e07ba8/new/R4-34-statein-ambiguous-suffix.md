---
r4: R4-34
title: "Bug: stateIn resolves an ambiguous bare state name by suffix match instead of rejecting it"
labels: [bug, severity/low, area/validation]
severity: Low
repro_script: repro/R4-34_statein_ambiguous_suffix.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

The built-in `stateIn` guard accepts a bare (non-fully-qualified) state name
and resolves it by checking every active state node for `node.id == target`
**or** `node.id.endswith("." + target)`. When two leaf states in different
branches of a parallel machine share the same bare name (e.g. two states
both named `work`), a bare `stateIn: "work"` silently matches whichever one
happens to be active, rather than being rejected as ambiguous. The
fully-qualified and relative spellings both behave correctly; only the bare
spelling is unsound. Low severity: it only manifests with duplicate bare
leaf names, and is fully avoidable by mandating fully-qualified ids -- it is
filed because the library already enforces an ambiguity check for actor
targets and does not apply the same discipline here.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine


def run(target, label):
    CFG = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "right",
                        "states": {
                            "left": {"initial": "work", "states": {"work": {}}},
                            "right": {"initial": "work", "states": {"work": {}}},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {"type": "stateIn", "params": {"state": target}},
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    s.send("E")
    ids = sorted(s.current_state_ids)
    s.stop()
    fired = "m.p.B.b2" in ids
    print(f"{label:46} target={target!r:24} fired={fired}")
    return fired


def main() -> int:
    run("#m.p.A.left.work", "fully-qualified inactive branch (want False)")
    run("#m.p.A.right.work", "fully-qualified active branch (want True)")
    run("left.work", "relative path of the INACTIVE branch (want False)")
    run("right.work", "relative path of the ACTIVE branch (want True)")

    print(
        "\nEXPECTED: a bare, ambiguous state name ('work', matching both "
        "m.p.A.left.work and m.p.A.right.work) is REJECTED (at build time or "
        "at guard-evaluation time), not silently resolved to whichever branch "
        "happens to be active."
    )
    try:
        fired = run("work", "ambiguous bare leaf name (2 states named work)")
        print(
            "OBSERVED: no exception raised; 'stateIn' silently resolved the "
            f"ambiguous name (fired={fired})."
        )
        ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"OBSERVED: raised {type(exc).__name__}: {exc}")
        ok = True
    print("RESULT:", "PASS" if ok else "FAIL (ambiguous bare name resolved silently, not rejected)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
fully-qualified inactive branch (want False)   target='#m.p.A.left.work'       fired=False
fully-qualified active branch (want True)      target='#m.p.A.right.work'      fired=True
relative path of the INACTIVE branch (want False) target='left.work'              fired=False
relative path of the ACTIVE branch (want True) target='right.work'             fired=True

EXPECTED: a bare, ambiguous state name ('work', matching both m.p.A.left.work and m.p.A.right.work) is REJECTED (at build time or at guard-evaluation time), not silently resolved to whichever branch happens to be active.
ambiguous bare leaf name (2 states named work) target='work'                   fired=True
OBSERVED: no exception raised; 'stateIn' silently resolved the ambiguous name (fired=True).
RESULT: FAIL (ambiguous bare name resolved silently, not rejected)
```

The fully-qualified and relative spellings all behave correctly (`fired`
matches the intended active/inactive branch). The bare, ambiguous spelling
`"work"` does not raise; it silently resolves `fired=True` because the
active branch (`m.p.A.right.work`) happens to be iterated and matched first
-- had the *inactive* branch been active instead, the same config would
silently resolve to `False`, with no code-visible difference between the two
outcomes.

## Expected behaviour

XState v5's `stateIn`
(https://stately.ai/docs/guards#in-state-guards) is documented against fully
qualified state value paths; an implementation accepting bare names as a
convenience should reject, not guess, when a bare name is ambiguous within
the machine's state chart -- the same principle the library already applies
elsewhere: actor-target resolution (`sendTo`/`invoke` id lookups) raises on
an ambiguous match rather than picking one silently. `stateIn` should hold
itself to the same bar it already sets for actor targets.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:4186-4220`, `_is_state_in`:

```python
normalised = target[1:] if target.startswith("#") else target
for node in self._active_state_nodes:
    if node.id == normalised or node.id.endswith("." + normalised):
        return True
return False
```

The `endswith("." + normalised)` branch is a deliberate convenience for
relative/bare names, but it is applied uniformly with no ambiguity check:
the loop returns `True` on the *first* active node whose id ends with the
bare name, with no check for whether a second, different active node also
matches. Because `_active_state_nodes` iteration order is whatever the
active configuration happens to produce, which of two same-named leaves
"wins" is an implementation accident, not a documented resolution rule.

## Impact

**General users.** Any machine with duplicate bare leaf/branch names inside
different parallel regions (a common pattern -- e.g. two independently
tracked sub-processes that both have a `"work"`/`"idle"`/`"done"` phase) has
a `stateIn` guard using the shorter, more natural bare spelling silently
producing whichever answer the currently-active branch happens to give,
with zero indication in logs or exceptions that the name was ambiguous.
Because both spellings are ordinarily "valid" (the guard fires sometimes,
correctly, by coincidence), the bug is very hard to notice in testing and
resurfaces only when the two branches' activity states diverge from what the
test suite happened to exercise.

**Concrete order-management scenario.** An order-management machine with
independent parallel regions for `execution` and `risk-check`, each having a
`"pending"` sub-state, uses `stateIn: "pending"` in a guard intended to mean
"the risk-check region is still pending." If the execution region also has a
state named `"pending"` and happens to be active when the guard evaluates,
the guard can silently resolve against the wrong region's state, gating a
transition on the wrong condition with no error anywhere.

## Proposed fix

**Design.** Reject an ambiguous bare name at build/validation time, using
the actor-target ambiguity error the library already has as a precedent.

1. At machine-build time (where other guard/target validation already
   happens), for every `stateIn` guard using a bare (non-`#`-prefixed,
   non-dotted, or dotted-but-not-fully-qualified) name, walk the compiled
   state chart and count how many state node ids end with
   `"." + target"` (or equal `target`); if more than one, raise the same
   class of ambiguity error used for actor targets, naming the guard's
   containing state and the colliding node ids.
2. If build-time detection is impractical for guards using dynamic/callable
   `params`, perform the same check at guard-evaluation time in
   `_is_state_in` and raise instead of returning on the first match.
3. Document that `stateIn` requires either a fully-qualified id or a
   sufficiently-qualifying relative suffix to be unambiguous.

**Compatibility.** Behavior change only for configs that are already
relying (knowingly or not) on the ambiguous resolution; such configs are, by
definition, non-deterministic today and should be flagged.

**Alternatives considered.**
1. *Leave as documentation-only ("always use fully-qualified ids").*
   Rejected: the library validates other classes of ambiguity already; a
   silent wrong-answer guard is a worse failure mode than a loud build-time
   error for the rare colliding case.

## Acceptance criteria

- [ ] An ambiguous bare `stateIn` target raises a clear, named error (build
      time preferred; evaluation time acceptable) rather than silently
      resolving.
- [ ] Fully-qualified and unambiguous relative spellings continue to work
      unchanged.
- [ ] `repro/R4-34_statein_ambiguous_suffix.py` exits `0`.
- [ ] `tests/test_state_in_guard.py::test_ambiguous_bare_name_rejected`
- [ ] `tests/test_state_in_guard.py::test_fully_qualified_and_relative_unaffected`

## Related

- Register row `R4-34` (filed Low, stands as filed).
- Evidence: `battle-5e07ba8/semantics/repro/d2b.py`.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-34_statein_ambiguous_suffix.py` in a fresh process: exit code
  `1`, output matches the Observed section verbatim (fully-qualified and
  relative spellings resolve correctly; the ambiguous bare name `"work"`
  silently resolves `fired=True` with no exception raised).
- Root cause confirmed: `base_interpreter.py`'s `_is_state_in` loop --
  `if node.id == normalised or node.id.endswith("." + normalised): return
  True` -- returns on the first match with no check for a second,
  differently-active node also matching.
- XState v5 `stateIn` semantics confirmed against
  https://stately.ai/docs/guards: `stateIn` is documented and exemplified
  only with fully-qualified ids (`stateIn('#state1')`) or state-value objects
  (`stateIn({ form: 'submitting' })`); no bare-suffix convenience is
  documented, consistent with the issue's framing that the bare-name
  shortcut is this library's own addition and should be held to the same
  ambiguity-rejection bar as its other id-resolution paths.
- No duplicate found on `gh issue list --search "stateIn ambiguous"` (no
  results). Issue **#34** ("over-forgiving target resolution silently binds
  an unrelated state in another region") is a related but distinct defect
  in *target* resolution (transition targets), not the `stateIn` *guard*;
  no overlap in code path or repro.
- Self-contained; no project-name/label leak.
