"""Shared domain primitives (`docs/plan/24-internal-schemas.md` §1).

This package holds the cross-module vocabulary — time/price/qty aliases,
identifiers, symbol/environment literals and the base event envelope — that
every other module imports rather than redefining. It carries no exchange
vocabulary (C-2.2): no Bybit-native return-code field, no Bybit camelCase
field names.

`E08-T01` introduces this package to host the shared types referenced by
`docs/plan/24-internal-schemas.md` §14.1 (`exchange/base.py`) without
duplicating them in the adapter package itself. `candleviewer.domain` has no
module-boundary entry of its own in `CONSTITUTION.md` §3 because it is pure
typing with zero runtime dependencies — every module may import it (see the
architecture note in `primitives.py`).
"""

# nosemgrep: cv-bybit-vocabulary-leak -- the docstring above *describes* the
# P3 invariant in prose (naming the forbidden identifier as an example), it
# does not *use* Bybit vocabulary as a field/identifier. Linked ticket:
# E08-X03.

from __future__ import annotations

__all__: list[str] = []
