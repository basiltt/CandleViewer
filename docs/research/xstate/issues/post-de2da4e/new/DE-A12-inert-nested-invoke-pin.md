---
id: DE-A12
title: "Test: inert pin shapes in tests/test_round9_findings.py (nested_invoke never exits state a)"
labels: [documentation, docs, area/interpreter, severity/low]
severity: Low
repro_script: null
commit: de2da4e
verified: true
---

## Summary

Another item from the "make it perfect" end of a twelve-round list — the
library is adopted and this is a test-quality nit, not a functional
defect: the `nested_invoke` shape in `tests/test_round9_findings.py` has
been inert (limit-independent) since round 9, and we'd like it (and any
sibling pins with the same shape) audited and given a discriminating
assertion, plus a small meta-test that catches the pattern going forward.

## Current state

`tests/test_round9_findings.py` pins `#209`'s lap-parity claim with two
paired shapes: `rollback_ondone` (which genuinely scales with
`maxIterations` and discriminates across limits 1–25) and `nested_invoke`.
The `nested_invoke` shape never exits its initial state `a`, so it fires
**exactly 2 calls at every limit from 1 to 25** — the assertion holds
trivially regardless of what `maxIterations` is set to, and cannot fail no
matter how the library's runaway-chain accounting changes. We (and
apparently the library's own round-10 finding, its own round-10 #209 verification)
have independently converged on the same observation: this is a constant
agreeing with itself, not coverage.

This is the third time in this study a green suite has certified nothing
on a specific cell:

1. a parametrised test whose one arm could not fail (amendment 13),
2. a pin on behaviour the docs contradict (amendment 15),
3. now: a fixture with no dynamic range across the exact parameter it
   claims to sweep (this item, and the general fixture-with-no-range
   pattern noted as amendment 17).

## Evidence

- `20-adoption-gate.md` (round 9/10 era): *"A 'fixed' claim must be tested
  on a shape that can fail. #209's pin sweeps two shapes and the second —
  `nested_invoke` — never exits its initial state, so it fires exactly 2
  calls at every limit 1–25 and can never trip `RunawayChainError`. It
  agrees across all three lanes because a constant agrees with itself."*
- our round-10 verdict note: *"the paired `nested_invoke` shape
  is inert padding in both the verify script and
  `tests/test_round9_findings.py` — it never exits state `a`, so it fires
  exactly 2 calls at every limit and never trips."* Also: *"Give it a
  shape that scales, or drop it."*
- Same document: *"the pin's second shape proves nothing"* (library
  `tests/test_round9_findings.py` `nested_invoke` cell).

## Requested change

1. Give `nested_invoke` in `tests/test_round9_findings.py` a shape that
   actually varies with `maxIterations` (e.g. make the invoked child
   re-invoke itself or re-enter state `a` on a cycle, so call count scales
   with the limit and the test can genuinely trip `RunawayChainError` at
   some limit), or drop the shape if `rollback_ondone` alone is sufficient
   coverage for the claim.
2. Audit other round-N regression pins (`test_round{7,8,10,11}_findings.py`
   and similar) for the same failure mode: an assertion whose value is
   independent of the parameter the test claims to sweep.
3. Add a small meta-test — e.g. a test that runs each livelock/runaway pin
   at two different limits and asserts the observed count actually
   *differs* between them (or that at least one configured limit trips
   the guard) — so a future inert pin fails CI immediately rather than
   silently passing forever.

## Root cause analysis

N/A (test-quality ask, not a runtime code defect). Location:
`tests/test_round9_findings.py`, the `nested_invoke` parametrization
(reported at line ~610 and ~643 by our round-10 diff review of the same
file).

## Impact

No runtime impact — this is purely about the strength of upstream's own
regression coverage. The practical effect on us: when reading upstream's
"verified on both shapes" claims (here, and potentially elsewhere), we now
have to independently check that both shapes *vary*, because a passing
test alone doesn't establish that.

## Proposed fix

See "Requested change" — give `nested_invoke` a limit-scaling shape (or
remove it as redundant), and add the cross-limit meta-test.

## Acceptance criteria

- [ ] `nested_invoke` (or its replacement) fires a call count that
      differs across at least two configured `maxIterations` limits in
      `tests/test_round9_findings.py`.
- [ ] At least one limit in the sweep causes `nested_invoke` to actually
      trip `RunawayChainError` (or the equivalent guard it's pinning).
- [ ] A short audit note (changelog or PR description) confirming other
      round-N pins were checked for the same inert-shape pattern.
- [ ] A new meta-test asserting limit-dependence for the livelock/runaway
      pins it covers (name at maintainer's discretion, e.g.
      `test_livelock_pins_are_limit_dependent`).

## Verification

Reproduced the inertness directly, at `de2da4e`, by extracting both shapes
from `tests/test_round9_findings.py` and running them across the pin's own
limit ladder `(1, 2, 3, 4, 5, 7, 10, 15, 20, 25)`, counting service calls:

| shape | service calls across limits 1→25 | distinct values |
|---|---|---|
| `nested_invoke` | `[2, 2, 2, 2, 2, 2, 2, 2, 2, 2]` | **1** |
| `rollback_ondone` | `[2, 2, 3, 3, 4, 5, 6, 9, 11, 14]` | **8** |

`nested_invoke` fires exactly 2 calls at every limit — the assertion is a
constant agreeing with itself and cannot fail for any value of
`maxIterations`. Its sibling in the same test discriminates across eight
distinct values, which is what the pin is supposed to be doing.

- Test shapes confirmed present in current source: `_rollback` at
  `tests/test_round9_findings.py:779-798`, `_nested` at `800-823`, and the
  driver `test_service_calls_identical_on_all_lanes` at `825+`, which
  iterates `("rollback_ondone", self._rollback), ("nested_invoke",
  self._nested)` over the limit ladder quoted above.
- The inertness has a visible cause in the shape itself: `_nested`'s
  `invoke` `onDone` targets `#m0.a.b` and `#m0.a.a` **inside** state `a`,
  so the machine never exits `a` and the chain never laps.
- Cross-check: `rollback_ondone` emits a `RunawayChainError` settle
  message at every limit while `nested_invoke` emits none, consistent with
  only the former exercising the runaway-chain accounting the pin exists
  to protect.
- Suite state at this commit, for context: **3545 passed, 0 failed, 13
  skipped**, 92.87% coverage. This issue does not report a failing test —
  it reports a passing one that cannot fail.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `nested_invoke`, `lap parity`,
  `test_round9_findings`. `#209` and `#215` are the originating threads and
  both CLOSED; no open issue covers the pin's discriminating power.

## Related

our round-10 finding (our round-10 verdict note); amendments 13/15/17 in our
adoption audit's running commentary (#26); `#209` lap-parity claim.
