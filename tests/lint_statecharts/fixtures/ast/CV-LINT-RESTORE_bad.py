"""Fixture for CV-LINT-RESTORE: from_snapshot must appear only in
persistence.py, always with minimum_version=3 and plugins=.
"""


def restore(machine, blob):
    return Interpreter.from_snapshot(machine, blob)  # noqa: F821
