# -*- coding: utf-8 -*-
"""R7-06 -- `machine_hash` set to `None` or removed silently disables
`from_snapshot()` drift verification on a `version >= 1` payload.

`persistence.py:276-277`:

    snap_hash = snapshot.get("machine_hash")
    if verify_hash and snap_hash is not None:

The `None` branch exists for genuinely unversioned v0 payloads, but it is
keyed on the FIELD's presence/value rather than on the snapshot's DECLARED
`version`. So nulling or deleting one key downgrades a v2 snapshot to
unchecked even with `verify_machine_hash=True` -- the payload still says
`version: 2` while the only defence against restoring into a drifted
machine is gone.

`docs/_guide/snapshots.md:252` scopes unconditional acceptance to payloads
with NO `version` key at all, which is not what the code tests.

This is a correctness defect on a key-loss precondition (a JSON round-trip
that drops nulls, a column default, a schema migration), not a tampering
issue: the hash is a fingerprint, not a MAC.

Derived from battle-221ce7c/persistence/q2_readside_gaps.py.
Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == a versioned payload with a null/absent hash was accepted
into a structurally different machine.
"""
import copy
import json
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import SyncInterpreter, create_machine  # noqa: E402
from xstate_statemachine.exceptions import XStateMachineError  # noqa: E402

# Machine A: the snapshot is taken here.
A = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}
# Machine B: structurally DIFFERENT, same id -> structure_hash must differ.
B = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "c"}}, "c": {"on": {"X": "a"}}},
}


def snap():
    it = SyncInterpreter(create_machine(copy.deepcopy(A)))
    it.start()
    blob = it.get_persisted_snapshot()
    it.stop()
    return blob


def attempt(label, blob, cfg):
    """Restore `blob` into `cfg` with drift verification explicitly ON."""
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(blob),
            create_machine(copy.deepcopy(cfg)),
            verify_machine_hash=True,
        )
        states = sorted(n.id for n in r._active_state_nodes)
        print("  %-42s ACCEPTED  states=%s" % (label, states))
        return True
    except XStateMachineError as exc:
        print("  %-42s %s" % (label, type(exc).__name__))
        return False


def main():
    base = snap()
    print("snapshot version      = %r" % (base.get("version"),))
    print("snapshot machine_hash = %r" % (base.get("machine_hash"),))
    print()
    print("Restoring into structurally DIFFERENT machine B, "
          "verify_machine_hash=True:")

    honest = copy.deepcopy(base)
    ok_control_same = attempt("honest hash vs machine A (control)", honest, A)
    ok_wrong = attempt("honest hash vs machine B", honest, B)

    nulled = copy.deepcopy(base)
    nulled["machine_hash"] = None
    ok_null = attempt("machine_hash=None vs machine B", nulled, B)

    removed = copy.deepcopy(base)
    removed.pop("machine_hash", None)
    ok_absent = attempt("machine_hash key REMOVED vs machine B", removed, B)

    print()
    controls_ok = ok_control_same and not ok_wrong
    if controls_ok and (ok_null or ok_absent):
        print("REPRODUCED: the honest hash is correctly REFUSED against "
              "machine B, but the same version=%r payload with machine_hash "
              "null=%s / absent=%s was ACCEPTED."
              % (base.get("version"), ok_null, ok_absent))
        print("EXPECTED  : a payload declaring version >= 1 whose "
              "machine_hash is missing or null is refused under "
              "verify_machine_hash=True -- gate the v0 bypass on "
              "snapshot.get('version', 0) >= 1, not on the field.")
        return 1
    print("NOT reproduced (control_same=%s wrong=%s null=%s absent=%s)."
          % (ok_control_same, ok_wrong, ok_null, ok_absent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
