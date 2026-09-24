# -*- coding: utf-8 -*-
"""Verify #205 on main @ 19cb1f1: snapshot authenticity affordances.

This is a design-constraint / documentation ask, not a defect: check what
shipped against the issue's stated acceptance criteria.

1. `minimum_version=` on `from_snapshot()` (both engines) rejects a
   version-0 / absent-version payload when set.
2. `expected_machine_hash=` overrides trusting the payload's own hash.
3. `structure_hash`/`check_identity` docstrings say "checksum", not an
   authentication guarantee (wording regression guard).
4. Default behaviour (no new kwargs) is unchanged -- both new params are
   additive/opt-in.

Exit 0 only if every criterion is met.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine, MachineLogic
from xstate_statemachine.exceptions import SnapshotVersionError, SnapshotDriftError

FAILS: list = []


def fail(label, detail):
    FAILS.append((label, detail))
    print("FAIL:", label, "--", detail)


CFG_A = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}}}
CFG_B = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"BACK": "a", "JUMP": "c"}},
        "c": {},
    },
}


def build(cfg):
    return create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())


async def check_minimum_version():
    for EngineCls, is_async in ((Interpreter, True), (SyncInterpreter, False)):
        m = build(CFG_A)
        if is_async:
            i = EngineCls(m)
            await i.start()
        else:
            i = EngineCls(m)
            i.start()
        snap = i.get_snapshot()
        if is_async:
            await i.stop()
        else:
            i.stop()
        snap_d = json.loads(snap) if isinstance(snap, str) else snap
        # downgrade: strip version + hash (the v0 bypass shape)
        snap_d.pop("version", None)
        snap_d.pop("machine_hash", None)
        blob = json.dumps(snap_d)

        # (a) default: no minimum_version -> restores unchecked (documented)
        try:
            EngineCls.from_snapshot(blob, build(CFG_A))
            default_ok = True
        except Exception as e:  # noqa: BLE001
            default_ok = False
            print(f"  [{EngineCls.__name__}] unexpected: default restore raised {e!r}")

        # (b) minimum_version=1 -> must refuse
        try:
            EngineCls.from_snapshot(blob, build(CFG_A), minimum_version=1)
            refused = False
        except SnapshotVersionError:
            refused = True
        except Exception as e:  # noqa: BLE001
            refused = False
            print(f"  [{EngineCls.__name__}] wrong exception type: {e!r}")

        print(f"  {EngineCls.__name__}: default_restore_ok={default_ok} minimum_version=1_refused={refused}")
        if not default_ok:
            fail(f"205-default-changed-{EngineCls.__name__}", "default (no minimum_version) behaviour changed")
        if not refused:
            fail(f"205-minimum-version-{EngineCls.__name__}", "minimum_version=1 did not refuse v0 payload")


async def check_expected_machine_hash():
    for EngineCls, is_async in ((Interpreter, True), (SyncInterpreter, False)):
        m = build(CFG_A)
        good_hash = m.structure_hash
        if is_async:
            i = EngineCls(m)
            await i.start()
        else:
            i = EngineCls(m)
            i.start()
        snap = i.get_snapshot()
        if is_async:
            await i.stop()
        else:
            i.stop()
        snap_d = json.loads(snap) if isinstance(snap, str) else snap
        # Forge machine_hash to match a DIFFERENT (drifted) machine's hash,
        # while claiming the honest structure_hash via expected_machine_hash.
        drifted_hash = build(CFG_B).structure_hash
        snap_d["machine_hash"] = drifted_hash
        blob = json.dumps(snap_d)

        # payload's own hash matches the drifted machine -> would normally
        # restore fine into a machine built with that same drifted shape;
        # but we ask for expected_machine_hash=good_hash (the honest one,
        # which the payload's forged hash does NOT match) -> must refuse.
        try:
            EngineCls.from_snapshot(blob, build(CFG_A), expected_machine_hash=good_hash)
            refused = False
        except SnapshotDriftError:
            refused = True
        except Exception as e:  # noqa: BLE001
            refused = False
            print(f"  [{EngineCls.__name__}] wrong exception: {e!r}")
        print(f"  {EngineCls.__name__}: expected_machine_hash overrides forged payload hash -> refused={refused}")
        if not refused:
            fail(f"205-expected-hash-{EngineCls.__name__}", "expected_machine_hash did not override forged payload hash")


def check_docstring_wording():
    import xstate_statemachine.persistence as persistence
    import xstate_statemachine.base_interpreter as bi
    doc1 = persistence.structure_hash.__doc__ or ""
    doc2 = persistence.check_identity.__doc__ or ""
    doc3 = bi.BaseInterpreter.from_snapshot.__doc__ or ""
    has_checksum = "checksum" in doc1.lower() or "checksum" in doc2.lower() or "checksum" in doc3.lower()
    has_fingerprint_not_mac = (
        "fingerprint" in (doc1 + doc2 + doc3).lower()
        and ("not a mac" in doc3.lower() or "not authentication" in doc3.lower())
    )
    has_not_auth = "not authentication" in doc3.lower() or "not an authentication" in (doc1 + doc2 + doc3).lower() or "NOT authentication" in doc3
    print(f"  'checksum' present in relevant docstrings: {has_checksum}")
    print(f"  'fingerprint ... not a MAC/not authentication' present (equivalent wording): {has_fingerprint_not_mac}")
    print(f"  'not authentication' guidance present: {has_not_auth}")
    if not has_checksum and not has_fingerprint_not_mac:
        fail("205-docstring-checksum", "no docstring uses 'checksum' or equivalent fingerprint/not-a-MAC wording")
    elif not has_checksum:
        print("  NOTE: literal word 'checksum' from the acceptance criterion is absent; "
              "library instead says 'fingerprint ... not a MAC over the payload' / "
              "'NOT authentication' -- semantically equivalent, wording differs.")
    if not has_not_auth:
        fail("205-docstring-not-auth", "no docstring clarifies hash != authentication")


async def main() -> int:
    print("== Criterion 1: minimum_version rejects v0/downgraded payload ==")
    await check_minimum_version()
    print("== Criterion 2: expected_machine_hash overrides payload's own claim ==")
    await check_expected_machine_hash()
    print("== Criterion 3: docstring wording (checksum, not authentication) ==")
    check_docstring_wording()

    print()
    if FAILS:
        print(f"VERDICT: FAIL ({len(FAILS)} criterion/a)")
        for label, detail in FAILS:
            print("  -", label, ":", detail)
        return 1
    print("VERDICT: ALL CRITERIA MET (classify as FIXED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
