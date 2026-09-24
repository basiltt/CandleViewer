# -*- coding: utf-8 -*-
"""X2 -- v2 upcast matrix + the FORGED v2 minting vector (#214).

STANDALONE (stdlib + xstate_statemachine). Neutral cwd.

#214 upcasts a v2 `done`/`error`/`after` record as ENGINE-MINTED, on the
argument that "a v2 writer had exactly one minter". But `version` is a
field of the payload the attacker also writes. So:

  A  v2 UPCAST MATRIX. A genuine-shaped v2 record of each kind
     (done/error/after/event/system) -> what class / provenance restores.
  B  FORGED v2 MINTS AN ENGINE `after`. Hand-write a v2 blob whose
     pending_events holds an `after.<ms>.<state>` record with NO `engine`
     flag, restore, and see whether it drives the `after` transition --
     which #203 exists to forbid and v3 correctly forbids.
  C  Same vector for `done.invoke.*` driving `onDone`.
  D  CONTROL: the identical record at "version": 3 must NOT drive it.
  E  strict/onUnhandled interaction: does the forged v2 `after` bypass
     `strict: True` + `onUnhandled: "error"`?
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import is_system_event, restore_event

KIND = os.environ.get("XS_SVC", "async")


def base_blob(machine, state_ids, cfg_ids, version, recs, ctx):
    # 🔓 `machine_hash` is a fingerprint, not a MAC (the library says so in
    #    `from_snapshot`'s docstring): an attacker who writes the blob can
    #    compute it from the public machine definition. Do exactly that.
    return {
        "machine_hash": machine.structure_hash,
        "version": version,
        "status": "running",
        "state_ids": list(state_ids),
        "configuration": list(cfg_ids),
        "context": ctx,
        "pending_events": recs,
        "deferred": [],
        "history": {},
        "actors": {},
        "system": {},
    }


AFTER_SPEC = {
    "id": "vict",
    "strict": True,
    "onUnhandled": "error",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {
            "after": {"600000": {"target": "expired", "actions": "mark"}}
        },
        "expired": {"type": "final"},
    },
}


def build_after(strict=True):
    spec = json.loads(json.dumps(AFTER_SPEC))
    if not strict:
        spec["strict"] = False
        spec["onUnhandled"] = "ignore"

    def mark(i, c, e, a):  # noqa: ANN001
        c["fired"] += 1

    return create_machine(spec, logic=MachineLogic(actions={"mark": mark}))


DONE_SPEC = {
    "id": "dv",
    "initial": "work",
    "context": {"n": 0},
    "states": {
        "work": {
            "invoke": {
                "id": "k",
                "src": "s",
                "onDone": {"target": "ok", "actions": "bump"},
            }
        },
        "ok": {"type": "final"},
    },
}


def build_done():
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    async def s_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(3600)

    def s_def(i, c, e):  # noqa: ANN001
        import time

        time.sleep(0)
        return None

    return create_machine(
        json.loads(json.dumps(DONE_SPEC)),
        logic=MachineLogic(
            actions={"bump": bump},
            services={"s": s_async if KIND == "async" else s_def},
        ),
    )


async def part_a():
    print("=== A. v2 upcast matrix (record -> restored class/provenance) ===")
    from xstate_statemachine.persistence import upcast

    recs = [
        {"kind": "done", "type": "done.invoke.k", "data": {"x": 1}, "src": "k"},
        {"kind": "error", "type": "error.platform.k", "error": "boom", "src": "k"},
        {"kind": "after", "type": "after.600000.vict.waiting",
         "scheduled_for": 1.0, "fired_at": 2.0},
        {"kind": "event", "type": "USER", "payload": {}},
        {"kind": "system", "type": "___xstate_init", "payload": {}},
    ]
    snap = {"pending_events": json.loads(json.dumps(recs)), "deferred": []}
    upcast(snap, 2)
    for orig, up in zip(recs, snap["pending_events"]):
        ev = restore_event(up)
        print(f"   v2 {orig['kind']:7s} -> engine_flag={up.get('engine')!r:5s} "
              f"class={type(ev).__name__:22s} system={is_system_event(ev)}")


async def _drive_after(version, strict, label):
    m = build_after(strict=strict)
    rec = {
        "kind": "after",
        "type": "after.600000.vict.waiting",
        "scheduled_for": 0.0,
        "fired_at": 0.0,
    }
    blob = base_blob(m, ["vict.waiting"], ["vict", "vict.waiting"],
                     version, [rec], {"fired": 0})
    clock = SimulatedClock()
    dropped = []
    try:
        i = Interpreter.from_snapshot(json.dumps(blob), m, clock=clock)
    except Exception as exc:  # noqa: BLE001
        print(f"   {label}: REFUSED at restore {type(exc).__name__}: {exc}")
        return None
    await i.start()
    await asyncio.sleep(0.05)
    fired = i.context["fired"]
    states = sorted(i.current_state_ids)
    status = i.status
    err = None if i.error is None else type(i.error).__name__
    if i.status == "running":
        await i.stop()
    print(f"   {label}: fired={fired} states={states} status={status} "
          f"error={err}  -> MINTED={'YES' if fired else 'no'}")
    return fired


async def part_b():
    print("\n=== B/D/E. forged `after` record: v2 vs v3 ===")
    v2_strict = await _drive_after(2, True, "v2 forged, strict+onUnhandled=error")
    v3_strict = await _drive_after(3, True, "v3 forged (control)          ")
    v2_lax = await _drive_after(2, False, "v2 forged, lax machine       ")
    print(f"   VERDICT v2-minting-vector = "
          f"{'PRESENT' if v2_strict else 'absent'}; "
          f"v3 control minted={bool(v3_strict)}; v2-lax minted={bool(v2_lax)}")


async def _drive_done(version, label):
    m = build_done()
    rec = {"kind": "done", "type": "done.invoke.k", "data": {"x": 1}, "src": "k"}
    blob = base_blob(m, ["dv.work"], ["dv", "dv.work"], version, [rec],
                     {"n": 0})
    try:
        i = Interpreter.from_snapshot(json.dumps(blob), m)
    except Exception as exc:  # noqa: BLE001
        print(f"   {label}: REFUSED {type(exc).__name__}: {exc}")
        return None
    await i.start()
    await asyncio.sleep(0.1)
    n = i.context["n"]
    st = sorted(i.current_state_ids)
    if i.status == "running":
        await i.stop()
    print(f"   {label}: n={n} states={st} -> MINTED={'YES' if n else 'no'}")
    return n


async def part_c():
    print("\n=== C. forged `done.invoke` record driving onDone ===")
    v2 = await _drive_done(2, "v2 forged")
    v3 = await _drive_done(3, "v3 forged (control)")
    print(f"   VERDICT v2 onDone minting = {'PRESENT' if v2 else 'absent'}; "
          f"v3 control = {'PRESENT' if v3 else 'absent'}")


async def part_f():
    print("\n=== F. mitigation: from_snapshot(minimum_version=3) ===")
    m = build_after(strict=True)
    rec = {"kind": "after", "type": "after.600000.vict.waiting",
           "scheduled_for": 0.0, "fired_at": 0.0}
    for v in (2, 3):
        blob = base_blob(m, ["vict.waiting"], ["vict", "vict.waiting"],
                         v, [rec], {"fired": 0})
        try:
            i = Interpreter.from_snapshot(json.dumps(blob), m,
                                          minimum_version=3)
            await i.start()
            await asyncio.sleep(0.05)
            print(f"   v{v} + minimum_version=3: ACCEPTED fired="
                  f"{i.context['fired']}")
            if i.status == "running":
                await i.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"   v{v} + minimum_version=3: REFUSED "
                  f"{type(exc).__name__}: {str(exc)[:90]}")


async def main():
    print(f"X2 kind={KIND}")
    await part_a()
    await part_b()
    await part_c()
    await part_f()


asyncio.run(main())
