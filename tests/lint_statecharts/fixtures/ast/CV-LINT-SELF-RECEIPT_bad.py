"""Fixture for CV-LINT-SELF-RECEIPT: no action may await a wait=True
receipt on its own interpreter.
"""


async def on_entry(ctx, event, interp):
    await interp.send({"type": "PING"}, wait=True)
