"""Fixture for CV-LINT-CORO: registered actions must be `async def`."""


def do_thing(ctx, event):
    return None


actions = {"doThing": do_thing}
