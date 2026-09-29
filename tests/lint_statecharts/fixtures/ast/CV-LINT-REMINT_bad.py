"""Fixture for CV-LINT-REMINT: calling re_mint with a forbidden override
key ("type") outside cv_re_mint must fail the lint.
"""


def handle(events, ev):
    return events.re_mint(ev, type="Forged")
