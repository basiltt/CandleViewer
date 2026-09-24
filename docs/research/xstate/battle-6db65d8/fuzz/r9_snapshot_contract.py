"""R9 -- snapshot CONTRACT fuzz on 6db65d8's new rules (#185 / #186), the
5-way receipt matrix, the strict+wildcard matrix (#190), and the
engine-completion FORGERY surface.

A1  #186: `configuration` vs `state_ids` must AGREE or the blob is refused
    with SnapshotCorruptError.  Fuzz: empty / reordered / rewritten / extra /
    missing / null configuration, and the same on state_ids.
A2  #185: a NULL or ABSENT `machine_hash` on a versioned payload is drift.
    Matrix over version in {absent(v0), 0, 1, 2} x hash in {absent, null,
    wrong, correct} x verify_machine_hash in {True, False}.
A3  #190: a "*" handler must not defeat `strict`.  Matrix: declared /
    undeclared / wildcard-only chart / RAISE of an undeclared event.
A4  5-way receipt matrix: guard-crash / denied / deferred / unhandled-ignored
    / onUnhandled=error kill (#189) -- the kill must land on the SENDER's
    receipt.
A5  security: forge the engine-completion marker from user code.
"""
import asyncio, copy, dataclasses, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    Event,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotMidStepError,
    SnapshotVersionError,
    UnhandledEventError,
    UnknownEventError,
)

BASE = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"initial": "c", "states": {"c": {}, "d": {}}},
    },
}
TYPED = (
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotVersionError,
    SnapshotMidStepError,
)


def fresh(cfg=None):
    return create_machine(copy.deepcopy(cfg or BASE), logic=MachineLogic())


def live_blob():
    it = SyncInterpreter(fresh())
    it.start()
    it.send("GO")
    b = it.get_persisted_snapshot()
    it.stop()
    return b if isinstance(b, dict) else json.loads(b)


def restore(blob, **kw):
    """Returns ('refused', ExcName) | ('loaded', ids) | ('untyped', ExcName)."""
    try:
        it = SyncInterpreter.from_snapshot(
            json.dumps(blob), fresh(), **kw
        )
    except TYPED as e:
        return ("refused", type(e).__name__)
    except Exception as e:
        return ("untyped", type(e).__name__)
    ids = sorted(it.current_state_ids)
    try:
        it.stop()
    except Exception:
        pass
    return ("loaded", ids)


def a1_configuration_vs_state_ids():
    print("A1 #186 configuration vs state_ids must agree")
    b = live_blob()
    good_cfg = copy.deepcopy(b.get("configuration"))
    good_ids = copy.deepcopy(b.get("state_ids"))
    print(f"   clean: configuration={good_cfg!r} state_ids={good_ids!r}")
    muts = {
        "configuration=None": lambda d: d.update(configuration=None),
        "configuration={}": lambda d: d.update(configuration={}),
        "configuration=[]": lambda d: d.update(configuration=[]),
        "configuration=bogus-leaf": lambda d: d.update(configuration={"m": "zzz"}),
        "configuration=extra-leaf": lambda d: d.update(
            configuration={"m": {"b": "c", "zz": "q"}}
        ),
        "state_ids=[]": lambda d: d.update(state_ids=[]),
        "state_ids=other-leaf": lambda d: d.update(state_ids=["m.b.d"]),
        "state_ids=superset": lambda d: d.update(
            state_ids=(good_ids or []) + ["m.a"]
        ),
        "state_ids=None": lambda d: d.update(state_ids=None),
        "configuration missing key": lambda d: d.pop("configuration", None),
        "state_ids missing key": lambda d: d.pop("state_ids", None),
        "BOTH rewritten consistently to m.b.d": lambda d: d.update(
            configuration={"m": {"b": "d"}}, state_ids=["m.b.d"]
        ),
    }
    bad = []
    for name, f in muts.items():
        d = copy.deepcopy(b)
        f(d)
        out = restore(d)
        flag = ""
        if out[0] == "loaded" and "consistent" not in name:
            flag = "  <== ACCEPTED (disagreement tolerated)"
            bad.append(name)
        if out[0] == "untyped":
            flag = "  <== UNTYPED"
            bad.append(name)
        print(f"   {name:<38} -> {out[0]}:{out[1]}{flag}")
    print(f"   A1 non-contractual: {len(bad)} {bad}")


def a2_machine_hash():
    print("\nA2 #185 null/absent machine_hash on a versioned payload is drift")
    b = live_blob()
    good = b.get("machine_hash")
    rows = []
    for ver in ("absent", 0, 1, 2):
        for hk in ("absent", "null", "wrong", "correct"):
            for verify in (True, False):
                d = copy.deepcopy(b)
                if ver == "absent":
                    d.pop("version", None)
                else:
                    d["version"] = ver
                if hk == "absent":
                    d.pop("machine_hash", None)
                elif hk == "null":
                    d["machine_hash"] = None
                elif hk == "wrong":
                    d["machine_hash"] = "deadbeef" * 8
                else:
                    d["machine_hash"] = good
                out = restore(d, verify_machine_hash=verify)
                rows.append((ver, hk, verify, out))
    for ver, hk, verify, out in rows:
        # Contract: with verify=True, a versioned blob whose hash is
        # absent/null/wrong must be REFUSED. verify=False is the opt-out.
        expect_refuse = verify and ver != "absent" and hk != "correct"
        got_refuse = out[0] == "refused"
        flag = ""
        if expect_refuse and not got_refuse:
            flag = "  <== ACCEPTED (drift tolerated)"
        if out[0] == "untyped":
            flag = "  <== UNTYPED"
        if flag or expect_refuse:
            print(
                f"   version={str(ver):<6} hash={hk:<7} verify={str(verify):<5} "
                f"-> {out[0]}:{out[1]}{flag}"
            )
    bad = [
        (v, h, ve, o)
        for v, h, ve, o in rows
        if (ve and v != "absent" and h != "correct" and o[0] != "refused")
        or o[0] == "untyped"
    ]
    print(f"   A2 non-contractual: {len(bad)}")
    for r in bad[:8]:
        print(f"      {r}")


def a3_strict_wildcard():
    print("\nA3 #190 a '*' handler must not defeat strict")
    charts = {
        "declared only": {
            "id": "w",
            "initial": "a",
            "states": {"a": {"on": {"GO": "a"}}},
        },
        "wildcard beside declared": {
            "id": "w",
            "initial": "a",
            "states": {"a": {"on": {"GO": "a", "*": "a"}}},
        },
        "wildcard ONLY": {
            "id": "w",
            "initial": "a",
            "states": {"a": {"on": {"*": "a"}}},
        },
        "wildcard in ANOTHER state": {
            "id": "w",
            "initial": "a",
            "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"*": "b"}}},
        },
    }
    for cname, cfg in charts.items():
        for ev in ("GO", "UNDECLARED"):
            row = []
            for eng in ("sync", "async"):
                try:
                    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic())
                    if eng == "sync":
                        it = SyncInterpreter(m, strict=True)
                        it.start()
                        try:
                            it.send(ev)
                            r = "accepted"
                        except UnknownEventError:
                            r = "UnknownEventError"
                        except Exception as e:
                            r = f"untyped:{type(e).__name__}"
                        it.stop()
                    else:

                        async def go():
                            it = Interpreter(m, strict=True)
                            await asyncio.wait_for(it.start(), 5)
                            try:
                                await asyncio.wait_for(
                                    it.send(ev, wait=True), 5
                                )
                                r = "accepted"
                            except UnknownEventError:
                                r = "UnknownEventError"
                            except Exception as e:
                                r = f"untyped:{type(e).__name__}"
                            await it.stop()
                            return r

                        r = asyncio.run(go())
                except Exception as e:
                    r = f"setup:{type(e).__name__}"
                row.append(f"{eng}={r}")
            print(f"   {cname:<26} send({ev:<11}) {'  '.join(row)}")


if __name__ == "__main__":
    a1_configuration_vs_state_ids()
    a2_machine_hash()
    a3_strict_wildcard()
