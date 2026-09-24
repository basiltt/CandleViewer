# -*- coding: utf-8 -*-
"""B11-B15 on c78ce99: build + #216 strictConfig + policy plumbing + happy paths.

Run twice: CV_SVC_STYLE=async (pass 1) then CV_SVC_STYLE=def (pass 2).
"""
from __future__ import annotations
import asyncio, copy, json, logging
import cv78 as H
from cv78 import cfg, rec, dump, Stub, build, drive, drive_sync, STYLE
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine import persistence

IDS = ["B11", "B12", "B13", "B14", "B15"]

KNOWN = {
    "id", "initial", "states", "type", "context", "output", "on", "entry",
    "exit", "after", "always", "invoke", "onDone", "history",
    "actionErrorPolicy", "guardErrorPolicy", "onUnhandled", "maxIterations",
    "spawnBlockingTimeout", "strict", "strictTargets", "strictConfig",
    "meta", "description", "tags", "version",
}


def sc(c):
    """Mandatory config: strictConfig: true, in-config form."""
    c = copy.deepcopy(c)
    c["strictConfig"] = True
    return c


# ------------------------------------------------- 1. our-contract audit --
def audit():
    """#216 is a NEW gate: any unknown top-level key in OUR JSON is an
    our-contract defect. Audit statically, then prove it via the library."""
    for b in IDS:
        c = cfg(b)
        bad = sorted(k for k in c if k not in KNOWN and not k.startswith("x-"))
        rec("audit/%s/no-unknown-keys" % b, not bad, repr(bad))


# ----------------------------------------------- 2. build under strict ---
def builds():
    for b in IDS:
        c = sc(cfg(b))
        st = Stub(c)
        # (a) config-level "strictConfig": true
        try:
            create_machine(copy.deepcopy(c), logic=st.logic(),
                           strict_targets=True)
            rec("build/%s/strictConfig-in-config" % b, True)
        except Exception as e:
            rec("build/%s/strictConfig-in-config" % b, False, repr(e)[:160])
        # (b) kwarg strict_config=True on the ORIGINAL (no strictConfig key)
        st2 = Stub(cfg(b))
        try:
            m = create_machine(copy.deepcopy(cfg(b)), logic=st2.logic(),
                               strict_targets=True, strict_config=True)
            rec("build/%s/strict_config-kwarg" % b, True)
        except Exception as e:
            m = None
            rec("build/%s/strict_config-kwarg" % b, False, repr(e)[:160])
        if m is None:
            continue
        # (c) policies actually plumbed through
        ok = (
            str(getattr(m, "action_error_policy", "?")).endswith("rollback")
            or getattr(m, "action_error_policy", None) == "rollback"
        )
        want_unh = cfg(b)["onUnhandled"]
        got_unh = str(getattr(m, "on_unhandled", "?"))
        rec("build/%s/policies" % b,
            ok and want_unh in got_unh
            and getattr(m, "spawn_blocking_timeout_ms", None) == 5000.0,
            "aep=%r unh=%r spawn=%r" % (
                getattr(m, "action_error_policy", None), got_unh,
                getattr(m, "spawn_blocking_timeout_ms", None)))


# ------------------------------------- 3. #216 catches a typo on OUR json --
def typo_gate():
    """Prove the new gate would have caught a misspelled safety policy in
    each of our five contracts -- the regression #216 exists to stop."""
    for b in IDS:
        for bad_key, want_hint in (("actionErrorPolicyy", "actionErrorPolicy"),
                                   ("Strict", "strict"),
                                   ("onUnhandledEvent", "onUnhandled")):
            c = sc(cfg(b))
            c[bad_key] = c.pop(bad_key.rstrip("y") if False else bad_key, True)
            st = Stub(cfg(b))
            try:
                create_machine(copy.deepcopy(c), logic=st.logic(),
                               strict_targets=True)
                rec("gate216/%s/%s" % (b, bad_key), False, "accepted silently")
            except InvalidConfigError as e:
                rec("gate216/%s/%s" % (b, bad_key),
                    bad_key in str(e) and want_hint in str(e),
                    str(e)[:120])
            except Exception as e:
                rec("gate216/%s/%s" % (b, bad_key), False, repr(e)[:120])
        # x- namespace and metadata must still be accepted
        c = sc(cfg(b)); c["x-cv-owner"] = "oms"; c["meta"] = {"cv": 1}
        st = Stub(cfg(b))
        try:
            create_machine(copy.deepcopy(c), logic=st.logic(),
                           strict_targets=True)
            rec("gate216/%s/x-and-meta-allowed" % b, True)
        except Exception as e:
            rec("gate216/%s/x-and-meta-allowed" % b, False, repr(e)[:120])


# ------------------------------------------------------- 4. happy paths --
HAPPY = {
    "B11": (
        [("REASON_ADDED", {"reason": "r1"}), "STREAM_UNHEALTHY",
         "STREAM_HEALTHY", ("REASON_REMOVED", {"reason": "r1"}), "LINGER_DUE"],
        ["recording.stopped"],
    ),
    "B12": (["PREPARE", "PLAY", "PAUSE", "STEP", "DESTROY"],
            ["replay.destroyed"]),
    "B13": (["CONNECT", "SHUTDOWN"], ["ws_conn.closed"]),
    "B14": (["SUBSCRIBE", "SNAPSHOT", "DELTA", "SEQUENCE_GAP"],
            ["book.snapshot_pending"]),
    "B15": ([("MARK_UPDATE", {"px": 1})], ["paper_account.liquidated"]),
}

GUARDS = {
    "B11": {"reasons_remain": False, "all_streams_healthy": True,
            "position_open_for_symbol": False},
    "B12": {"loop_enabled": False},
    "B13": {"connection_budget_exhausted": False, "is_private": False},
    "B14": {},
    "B15": {"mark_crossed_liq_price": True, "below_maintenance_margin": False},
}


async def happy():
    for b in IDS:
        c = sc(cfg(b))
        st = Stub(c, guard_vals=GUARDS[b])
        script, want = HAPPY[b]
        out = await drive(c, st, script, snapshots=True)
        rec("happy/%s/states" % b, out["states"] == want,
            "got=%r notes=%r" % (out["states"], out["notes"][:3]))
        rec("happy/%s/snapshot-v3-every-macrostep" % b, out["snapshot_ok"],
            repr(out["notes"][:2]))
        rec("happy/%s/no-error" % b, out["error"] is None, repr(out["error"]))
        H.RESULTS.setdefault("_trace", {})
        # sync parity
        st2 = Stub(c, guard_vals=GUARDS[b], sync=True)
        so = drive_sync(c, st2, script)
        rec("happy/%s/sync-parity" % b, so["states"] == want,
            "sync=%r" % (so["states"],))


def snapshot_version():
    rec("meta/SNAPSHOT_VERSION==3", persistence.SNAPSHOT_VERSION == 3,
        str(persistence.SNAPSHOT_VERSION))


async def main():
    logging.disable(logging.CRITICAL)
    audit(); builds(); typo_gate(); snapshot_version()
    await happy()
    H.RESULTS.pop("_trace", None)
    dump("h1_build.json")


if __name__ == "__main__":
    asyncio.run(main())
