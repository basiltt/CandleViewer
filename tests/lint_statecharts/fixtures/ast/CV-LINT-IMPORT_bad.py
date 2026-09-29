"""Fixture for CV-LINT-IMPORT: importing the pinned statechart runtime from
a module other than factory.py/persistence.py must fail the lint.
"""

import xstate_statemachine  # noqa: F401  (intentional violation for the fixture)
