"""Fixture for CV-LINT-PRIORITY: priority=True must never be set."""


def send_event(gw, ev):
    return gw.send(ev, priority=True)
