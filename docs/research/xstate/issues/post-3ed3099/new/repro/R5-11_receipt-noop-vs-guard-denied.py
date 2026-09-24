"""R5-11 repro: a real no-op and a guard-DENIED event are indistinguishable.

Under one `onUnhandled` policy, `send(..., wait=True)` returns a byte-identical
`Receipt(changed=False, error=None, deferred=False)` for (a) an event the state
does not declare and (b) an event it DOES declare whose only guard returned
False -- with identical `status`, `last_transition_ok`, and
`on_unhandled_event` disposition. Two other cases ARE separable and are printed
as controls: `onUnhandled:"error"` flips `status`, `"defer"` sets
`Receipt.deferred`.

Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


class Hook:
    """Records on_unhandled_event without depending on hook arity."""

    def __init__(self):
        self.seen = []

    def __getattr__(self, name):
        def f(*a, **k):
            if name == "on_unhandled_event":
                self.seen.append(a[-1] if len(a) > 2 else None)
        return f


def cfg(policy, guarded):
    on = {"GO": ({"target": "b", "guard": "deny"} if guarded else "b")}
    return {
        "id": "m", "initial": "a",
        "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
        "onUnhandled": policy, "strictTargets": True, "strict": False,
        "spawnBlockingTimeout": 5.0,
        "states": {"a": {"on": on}, "b": {}},
    }

async def probe(policy, guarded, event):
    m = create_machine(cfg(policy, guarded),
                       logic=MachineLogic(guards={"deny": lambda c, e: False}))
    i = Interpreter(m)
    h = Hook()
    i.use(h)
    await i.start()
    r = await i.send(event, wait=True)
    # The hook's event TYPE is deliberately excluded -- the caller already
    # knows which event it sent. Only the DISPOSITION is a signal.
    out = (r.changed, repr(r.error), r.deferred, i.status,
           i.last_transition_ok, h.seen)
    await i.stop()
    return out


async def main() -> int:
    noop = await probe("ignore", False, "NOPE")
    denied = await probe("ignore", True, "GO")
    errored = await probe("error", False, "NOPE")
    deferred = await probe("defer", False, "NOPE")

    def show(label, t):
        print("  %-22s changed=%s error=%s deferred=%s status=%s last_ok=%s "
              "hook=%s" % (label, t[0], t[1], t[2], t[3], t[4], t[5]))

    print("OBSERVED:")
    show("real no-op", noop)
    show("guard-denied", denied)
    show("unhandled (control)", errored)
    show("deferred (control)", deferred)
    print("EXPECTED:")
    print("  a guard-denied event is distinguishable from an event the state")
    print("  never declared -- via the receipt, `last_transition_ok`, or an")
    print("  `on_unhandled_event` disposition such as 'guard_denied'.")
    if noop == denied:
        print("RESULT: FAIL - no-op and guard-denied are identical on every "
              "surface")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
