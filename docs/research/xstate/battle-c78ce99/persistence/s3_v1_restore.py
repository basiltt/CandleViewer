# -*- coding: utf-8 -*-
"""S3 -- v1 (0.8.0-written) payload restore + the #198 both-fields rule.

0.8.0 shipped `SNAPSHOT_VERSION = 1`; its writer already emitted BOTH
`state_ids` and `configuration` (verified by reading `v0.8.0:
base_interpreter.py:948,955`). #198 now says: on a `version >= 1` RUNNING
payload both fields must be present and non-empty, because "every writer
since v1 has" recorded both.

This probe checks the compatibility claim from the other side:

  A. A genuine 0.8.0-SHAPED v1 payload (version 1, `state_ids` +
     `configuration`, no v2 `kind` discriminators on records) restores.
  B. A v1 payload that is `state_ids`-only -- which is what a consumer
     gets if their storage layer drops a null/empty column, or if the
     blob passed through a reader that only kept the documented v0 keys --
     is now REFUSED. Is that a compatibility break for real 0.8.0 data?
     (Answer depends on whether 0.8.0 ever wrote such a blob: a STOPPED
     0.8.0 machine has status != running, so the rule does not bite; a
     running one always had both.)
  C. v1 `pending_events` records with no `kind` and no `engine` flag --
     the 0.8.0 record shape -- restore as USER traffic, never as engine
     completions (the #195 upcast path, `persistence.py:382`).
  D. The mirror of B at v0: `state_ids`-only with no `version` key must
     still be accepted (the documented legacy shape).

STANDALONE.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import is_system_event

FAIL: list[str] = []

SPEC = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


def classify(fn):
    try:
        obj = fn()
        return "ACCEPT", obj
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, str(exc)[:90]


async def honest_blob():
    i = Interpreter(create_machine(SPEC, logic=MachineLogic()))
    await i.start()
    i.send("NOPE")  # one pending record, user traffic
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


def as_v1(blob):
    """Rewrite a v2 blob into the shape 0.8.0's writer produced."""
    b = json.loads(json.dumps(blob))
    b["version"] = 1
    for key in ("pending_events", "deferred"):
        for rec in b.get(key) or []:
            rec.pop("kind", None)
            rec.pop("engine", None)
    return b


async def main() -> None:
    print("=== S3 v1 / 0.8.0 payload restore ===")
    blob = await honest_blob()
    print("live blob: version=%s state_ids=%s configuration=%s"
          % (blob["version"], blob["state_ids"], blob["configuration"]))
    print("pending record shape (v2):", blob["pending_events"])

    cases = {
        "A v1 both fields (0.8.0 shape)": lambda b: b,
        "B v1 state_ids only (configuration dropped)":
            lambda b: (b.pop("configuration", None), b)[1],
        "B' v1 configuration empty":
            lambda b: b.update(configuration=[]) or b,
        "D v0 state_ids only (legacy)":
            lambda b: (b.pop("version", None), b.pop("configuration", None),
                       b.pop("machine_hash", None), b)[-1],
    }
    for name, mut in cases.items():
        b = mut(as_v1(blob))
        kind, det = classify(
            lambda b=b: Interpreter.from_snapshot(
                json.dumps(b), create_machine(SPEC, logic=MachineLogic())
            )
        )
        if kind == "ACCEPT":
            det = "leaves=%s pending=%s" % (
                sorted(det.current_state_ids),
                [type(e).__name__ + ":" + getattr(e, "type", "?")
                 for e in det.pending_events],
            )
            # C: provenance of the v1 record
            for e in det if False else []:
                pass
        print("  %-44s %-22s %s" % (name, kind, det))

    # ---- C: a v1 done.invoke record has no `engine` flag -> user traffic
    print("\n=== C. v1 completion record provenance ===")
    b = as_v1(blob)
    b["pending_events"] = [{"type": "done.invoke.k", "data": {"x": 1},
                            "src": "k"}]
    j = Interpreter.from_snapshot(
        json.dumps(b), create_machine(SPEC, logic=MachineLogic())
    )
    for e in j.pending_events:
        sysf = is_system_event(e)
        print("  restored %-14s %-12s system=%s"
              % (getattr(e, "type", "?"), type(e).__name__, sysf))
        if sysf:
            FAIL.append("C: a v1 (pre-#195) completion record restored as "
                        "an ENGINE completion")
    await j.stop()

    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
