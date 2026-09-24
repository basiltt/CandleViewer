"""R9-02 — STANDALONE repro.

`after` transitions are selected on the PUBLIC exported `AfterEvent` class,
never on the private `_EngineAfter` minted by #195. Two consequences:

  (A) A hand-built `AfterEvent` fires a 60-second timer instantly.
      A plain `Event` of the SAME NAME does not -- so it is the CLASS that is
      privileged, not the `after.*` namespace. (This control refutes the
      "open namespace" explanation.)

  (B) The decisive vector needs no API call at all, and so never meets the
      `send()`-time `strict` check: a forged `pending_events` record with NO
      "engine" flag restores as user traffic (correct per #195) and is then
      handed straight to the inbox by `_enqueue_restored`. With strict=True
      the machine still reaches `m.expired`.

Exits 1 if either vector fires the timer. Exits 0 when both are refused.

stdlib + xstate_statemachine only. Verified against main @ f28719c.
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    AfterEvent,
    Event,
    Interpreter,
    MachineLogic,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "work",
    "states": {
        "work": {"after": {60000: "expired"}, "on": {"GO": "other"}},
        "expired": {},
        "other": {},
    },
}


def build():
    # Fresh definition each time: the loader mutates target strings in place.
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def vector_a(strict):
    """Hand-built AfterEvent vs a plain Event of the same name."""
    results = {}
    for label, ev in (
        ("AfterEvent", AfterEvent("after.60000.m.work")),
        ("Event(same name)", Event("after.60000.m.work")),
        ("bare str", "after.60000.m.work"),
    ):
        i = Interpreter(build())
        i.strict = strict
        await i.start()
        await asyncio.sleep(0.02)
        try:
            await i.send(ev)
        except Exception as e:  # strict may refuse -- that is the good path
            results[label] = "refused:" + type(e).__name__
            await i.stop()
            continue
        await asyncio.sleep(0.05)
        results[label] = sorted(i.current_state_ids)
        await i.stop()
    return results


async def vector_b():
    """Forged pending_events record, no 'engine' flag, via from_snapshot."""
    i = Interpreter(build())
    i.strict = True
    await i.start()
    await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()

    snap = json.loads(snap) if isinstance(snap, str) else snap
    snap.setdefault("pending_events", []).append(
        {"kind": "after", "type": "after.60000.m.work"}
    )
    try:
        j = Interpreter.from_snapshot(json.dumps(snap), build())
    except Exception as e:
        return "restore refused:" + type(e).__name__
    j.strict = True
    await j.start()
    await asyncio.sleep(0.1)
    out = sorted(j.current_state_ids)
    await j.stop()
    return out


async def main():
    a_strict = await vector_a(True)
    a_default = await vector_a(False)
    b = await vector_b()

    print("VECTOR A -- hand-built event, strict=True (send-side check)")
    for k, v in a_strict.items():
        print("  %-18s -> %s" % (k, v))
    print("VECTOR A -- hand-built event, strict=False (THE DEFAULT)")
    for k, v in a_default.items():
        print("  %-18s -> %s" % (k, v))
    print("VECTOR B -- forged snapshot record (no 'engine' flag), strict=True")
    print("  restored states   -> %s" % (b,))

    bad = []
    if a_default.get("AfterEvent") == ["m.expired"]:
        bad.append(
            "A: at the DEFAULT strict=False, a hand-built AfterEvent fired "
            "the 60s timer"
        )
    if b == ["m.expired"]:
        bad.append(
            "B: a forged snapshot record fired the 60s timer EVEN AT "
            "strict=True (never meets the send()-time check)"
        )

    # Discriminator: if a plain Event of the same name also moves the machine,
    # the `after.*` namespace is merely open and the finding is weaker. If it
    # does NOT move while AfterEvent does, the CLASS itself is privileged.
    ctrl = a_default.get("Event(same name)")
    if a_default.get("AfterEvent") == ["m.expired"] and ctrl == ["m.work"]:
        print()
        print(
            "DISCRIMINATOR: plain Event of the same name stayed in %s while "
            "AfterEvent moved to ['m.expired'] -> the CLASS is privileged, "
            "not the namespace." % (ctrl,)
        )

    print()
    if bad:
        for line in bad:
            print("DEFECT:", line)
        print("VERDICT: FAIL (%d/2 vectors fired a 60-second timer)" % len(bad))
        return 1
    print("VERDICT: ok -- both vectors refused")
    return 0


sys.exit(asyncio.run(main()))
