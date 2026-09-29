"""Fixture for CV-LINT-HOTPATH: a hot-path module must never import the
statechart package.
"""

from candleviewer.statechart import factory  # noqa: F401  (intentional violation)
