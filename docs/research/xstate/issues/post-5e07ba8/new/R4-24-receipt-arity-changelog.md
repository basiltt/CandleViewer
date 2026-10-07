---
r4: R4-24
title: "Docs: Receipt's new 4th field (deferred) is an undeclared breaking API change in the CHANGELOG"
labels: [documentation, severity/medium, area/events]
severity: Medium
repro_script: repro/R4-24_receipt_arity_break.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Receipt` (`events.py:338-360`) is an exported public `NamedTuple`. 0.8.1
added a fourth field, `deferred`, changing its arity from 3 to 4. Any
caller that destructures a `Receipt` positionally — the natural way to
consume a `NamedTuple`, and the shape 0.8.0 shipped — now raises
`ValueError` at the first call site, and equality checks against a 3-tuple
silently flip to `False`. The CHANGELOG records `Receipt.deferred` under
"Fixed" rather than calling out that it changes the tuple's arity, so
nothing in the release notes tells an upgrading caller their existing
unpacking code will break.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `<workspace>/_ref/xstate-statemachine`

## Current behaviour and why it is insufficient

```python
"""R4-24: `Receipt` (events.py:338-360) is an exported public NamedTuple.
0.8.1 added a 4th field, `deferred`, changing its arity from 3 to 4. Code
written against 0.8.0 that destructures a Receipt by position now raises at
the first call site, and equality against a 3-tuple silently flips to False.
The CHANGELOG files this under "Fixed", not as a breaking change.

EXPECTED: unpacking a Receipt the way 0.8.0 documented it (3 positions)
should either keep working, or the break should be called out as breaking
in the CHANGELOG before the 0.8.1 tag (it currently is not).
OBSERVED: `ValueError: too many values to unpack`.

Exits 1 while the defect is present, 0 once fixed (either the CHANGELOG is
corrected -- see the issue -- or the arity break itself is fixed).
"""
from __future__ import annotations

from xstate_statemachine.events import Receipt

r = Receipt(frozenset(), False, None)

try:
    ids, changed, err = r  # 0.8.0-shaped destructure
    unpack_ok = True
except ValueError as exc:
    unpack_ok = False
    unpack_error = exc

eq_ok = r == (frozenset(), False, None)

print(f"len(Receipt)            : {len(r)}")
print(f"3-tuple unpack succeeds  : {unpack_ok}")
if not unpack_ok:
    print(f"  -> {unpack_error}")
print(f"equality vs 3-tuple      : {eq_ok}")

defect_present = not unpack_ok
print(
    "\nOBSERVED:",
    "3-tuple unpacking of Receipt raises ValueError; equality against a "
    "3-tuple is False"
    if defect_present
    else "3-tuple unpacking and equality still work",
)
print(
    "EXPECTED: 0.8.0-shaped 3-tuple unpacking keeps working, or the "
    "CHANGELOG explicitly documents this as a breaking change"
)
print("RESULT:", "FAIL - defect present" if defect_present else "PASS")

raise SystemExit(1 if defect_present else 0)
```

## Observed behaviour

```
len(Receipt)            : 4
3-tuple unpack succeeds  : False
  -> too many values to unpack (expected 3)
equality vs 3-tuple      : False

OBSERVED: 3-tuple unpacking of Receipt raises ValueError; equality against a 3-tuple is False
EXPECTED: 0.8.0-shaped 3-tuple unpacking keeps working, or the CHANGELOG explicitly documents this as a breaking change
RESULT: FAIL - defect present
```

(exit code 1)

## Proposed API/text

Semantic Versioning (which a pre-1.0 library is not strictly bound by, but
whose spirit `CHANGELOG.md`'s "Fixed"/"Added"/"Breaking" headings already
gesture at) treats a public tuple's arity as part of its API surface.
Adding `deferred` in a way that changes `len(Receipt)` and breaks
positional unpacking is a legitimate change to make pre-1.0 — but it should
be documented as a breaking change with a one-line migration, not filed
under "Fixed" as if existing call sites are unaffected.

Concretely:

1. In `CHANGELOG.md` and `docs/_guide/changelog.md`, move the `Receipt.
   deferred` entry out of "Fixed" and under an explicit "Breaking" (or
   "Changed — breaking") heading for the 0.8.1 entry, with a one-line
   migration note, e.g.:

   > **Breaking:** `Receipt` gained a fourth field, `deferred` (position 4).
   > Code that unpacks a `Receipt` positionally as a 3-tuple
   > (`state_ids, changed, error = receipt`) will raise `ValueError` — add
   > `deferred` to the unpacking (`state_ids, changed, error, deferred =
   > receipt`) or access fields by name instead.

2. `docs/_guide/testing-and-pure-api.md` (wherever it shows `Receipt`
   consumption) should be updated to demonstrate name-based access
   (`receipt.state_ids`, `receipt.changed`, ...) as the recommended pattern
   precisely because this kind of arity change is expected to keep
   happening pre-1.0.

Compatibility: this is a documentation-only fix; it does not require any
source change. (If the maintainers additionally want a mechanical
mitigation, they could consider not exposing `Receipt` as a bare
`NamedTuple` for future fields, but that is a separate, larger design
question and not part of this issue's scope.)

## Impact

**General users:** anyone upgrading from 0.8.0 who destructures `Receipt`
positionally (the natural, no-import-needed way to consume a `NamedTuple`)
hits a hard `ValueError` on their very first `send(..., wait=True)` call
after upgrading, with no CHANGELOG entry pointing at the cause. It fails
loudly rather than silently corrupting data, which is why this is Medium
rather than High — but it is still an unannounced break.

**Order-management scenario:** an order-processing service's receipt-based
audit trail that does `ids, changed, err = await interp.send(cmd,
wait=True)` for logging breaks on upgrade with no changelog signal telling
the operator why; equality-based tests comparing a captured `Receipt`
against a literal 3-tuple fixture silently start failing instead (no
exception, since `NamedTuple.__eq__` against a shorter tuple returns
`False` rather than raising).

## Acceptance criteria

- [ ] `repro/R4-24_receipt_arity_break.py` exits 0 once the CHANGELOG
      correction lands (per the acceptance definition in this issue, this
      repro documents the current arity break; a docs-only fix "resolves"
      the issue by making the break discoverable in the CHANGELOG rather
      than making the script's assertion trivially pass, so acceptance for
      this row is: CHANGELOG updated per "Proposed API/text" above, and the
      repro script's OBSERVED/EXPECTED text is referenced from the
      changelog entry)
- [ ] `CHANGELOG.md` 0.8.1 entry moves `Receipt.deferred` to a "Breaking"
      heading with the one-line migration note
- [ ] `docs/_guide/changelog.md` updated to match
- [ ] `docs/_guide/testing-and-pure-api.md` updated to show name-based
      `Receipt` access as the recommended pattern

## Related

- Register source id: `probes/main-5e07ba8/r41_receipt_arity.py`
- Register notes this as "not re-refuted this pass — stands as filed"

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (venv: `xstate-statemachine/.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-24_receipt_arity_break.py` in a fresh process (60 s cap):
  output matched the Observed block verbatim; exit code `1`.
- Confirmed `Receipt` at `src/xstate_statemachine/events.py:338-360`: a
  `NamedTuple` with `state_ids, changed, error=None, deferred=False` (4
  fields) — as cited.
- Confirmed `CHANGELOG.md` lines 10-17: `Receipt.deferred` (#84) is listed
  under the `### Fixed` heading with no "Breaking"/arity-change callout —
  as cited; no such heading correction has landed.
- No external XState/SCXML claim to fetch for this row (it is a
  library-internal API/changelog issue, not a semantics claim against the
  XState spec).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all --limit
  120 --search "Receipt deferred arity"`: no matching open/closed issue; no
  duplicate found.
- No project name/label leakage found in the file.
