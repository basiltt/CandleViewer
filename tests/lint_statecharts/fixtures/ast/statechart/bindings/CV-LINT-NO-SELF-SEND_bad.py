"""Fixture for CV-LINT-NO-SELF-SEND: bindings/ must not call send() on the
interpreter directly.
"""


async def on_entry(ctx, event, interp):
    interp.send({"type": "SELF"})
