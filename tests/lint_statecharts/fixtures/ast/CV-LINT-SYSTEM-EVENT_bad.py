"""Fixture for CV-LINT-SYSTEM-EVENT: no system=True and no
is_system_event()."""


def check(ev):
    return is_system_event(ev)  # noqa: F821
