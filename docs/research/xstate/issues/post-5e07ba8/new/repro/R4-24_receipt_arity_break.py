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
