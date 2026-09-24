# -*- coding: utf-8 -*-
"""Standalone repro: #142/#143 legality is checked against `state_ids`, while
`configuration` -- the other copy of the same fact in the same snapshot -- is
accepted with any contents.

cec108b (unreleased 0.8.1). Library only.

`get_persisted_snapshot()` writes BOTH keys:
    state_ids     : ['m.a']                 (leaves only)
    configuration : ['m', 'm.a']            (ancestors + leaves)

The round-5 fix ("exactly one active leaf per region, mirrored on the read
side") rejects a snapshot whose legality fails -- but only via `state_ids`:

    both keys emptied      -> SnapshotCorruptError   (correct)
    both keys set to ['m'] -> SnapshotCorruptError   (correct)
    `configuration` alone emptied/garbled, `state_ids` intact -> ACCEPTED

A tamperer or a lossy round-trip that touches one key and not the other gets a
live interpreter back. The two keys are never cross-validated, so the snapshot
carries an internal contradiction the library has already promised to detect.
"""
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "context": {},
       "states": {"a": {"on": {"GO": {"target": "#m.b"}}}, "b": {}}}


async def main():
    m = create_machine(CFG, logic=MachineLogic())
    it = Interpreter(m)
    await it.start()
    await it.send("GO", wait=True)
    snap = it.get_persisted_snapshot()
    await it.stop()
    print("clean snapshot: state_ids=%s configuration=%s"
          % (snap["state_ids"], snap["configuration"]))

    for name, mut in [
        ("both emptied", lambda s: (s.update(state_ids=[], configuration=[]))),
        ("both non-leaf", lambda s: (s.update(state_ids=["m"], configuration=["m"]))),
        ("configuration emptied only", lambda s: s.update(configuration=[])),
        ("configuration garbled only", lambda s: s.update(configuration=["m.NOPE"])),
        ("configuration not a list", lambda s: s.update(configuration="m.b")),
    ]:
        d = json.loads(json.dumps(snap))
        mut(d)
        try:
            i2 = Interpreter.from_snapshot(json.dumps(d), m,
                                           verify_machine_hash=False)
            print("%-28s -> ACCEPTED  state=%s status=%s"
                  % (name, sorted(i2.current_state_ids), i2.status))
        except Exception as exc:
            print("%-28s -> %s" % (name, type(exc).__name__))


asyncio.run(main())
