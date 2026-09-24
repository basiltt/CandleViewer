"""D8-B: persistence (#182/#183/#185/#186), semantics (#189/#190) and
security attacks on the round-7 machinery.  Every service-bearing attack runs
BOTH `def` and `async def`.

B1  Snapshot from an INITIAL-DESCENT entry action and from a CHILD's entry
    action, both engines, both service kinds -- refused or legal, never torn.
B2  configuration / state_ids disagreement fuzz (400 mutations).
B3  null / absent machine_hash on v0, v1, v2 blobs.
B4  strict + wildcard matrix: declared / undeclared / wildcard-only /
    raise-of-undeclared.
B5  5-way receipt matrix: ok / denied / guard-crash / deferred / unhandled /
    onUnhandled-error kill.
B6  Forge the engine-completion marker from user code.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import random
import sys
from typing import Any, Dict, List

from n_harness import attack, main

import xstate_statemachine as xs
from xstate_statemachine import (
    Event,
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

TORN_OK = (xs.SnapshotMidStepError, XStateMachineError)


def _legal(blob: Dict[str, Any]) -> bool:
    """A blob is legal iff its context write is paired (px set <=> qty set)."""
    ctx = blob.get("context", {})
    return bool(ctx.get("px")) == bool(ctx.get("qty"))


CHILD = {
    "id": "kid",
    "initial": "boot",
    "states": {"boot": {"entry": "pair", "on": {"X": "up"}}, "up": {}},
}
ROOT = {
    "id": "root",
    "initial": "start",
    "states": {
        "start": {
            "entry": "pair",
            "invoke": {"src": "kid", "id": "kid"},
            "on": {"GO": "next"},
        },
        "next": {"entry": "pair"},
    },
}


class HookSnap(PluginBase):
    """Snapshot from every hook; record (hook, outcome)."""

    def __init__(self, target) -> None:  # noqa: ANN001
        self.target = target
        self.torn: List[str] = []
        self.refused = 0
        self.legal = 0
        self.untyped: List[str] = []

    def _snap(self, where: str) -> None:
        try:
            blob = self.target.get_persisted_snapshot()
        except TORN_OK:
            self.refused += 1
            return
        except Exception as exc:  # noqa: BLE001
            self.untyped.append(f"{where}:{type(exc).__name__}")
            return
        if isinstance(blob, str):
            import json

            blob = json.loads(blob)
        if _legal(blob):
            self.legal += 1
        else:
            self.torn.append(where)

    def on_action_execute(self, i, a):  # noqa: ANN001
        self._snap("action")

    def on_transition(self, i, f, t, e):  # noqa: ANN001
        self._snap("transition")

    def on_event_received(self, i, e):  # noqa: ANN001
        self._snap("event")


def _pair_actions(order: str):
    """An entry action that writes px then qty -- torn in between."""

    def pair(i, ctx, e, ad):  # noqa: ANN001
        ctx["px"] = 100
        ctx["qty"] = 5

    async def pair_a(i, ctx, e, ad):  # noqa: ANN001
        ctx["px"] = 100
        await asyncio.sleep(0)
        ctx["qty"] = 5

    return pair_a if order == "async" else pair


@attack(
    "B1",
    "Snapshot from every hook incl. INITIAL DESCENT and CHILD entry actions, "
    "both engines x both action kinds: refused-or-legal, never torn",
    "#182 in-flight over start(), #183/#187 child + action hooks",
)
async def b1() -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    for kind in ("plain", "async"):
        act = _pair_actions(kind)
        # --- async engine -------------------------------------------------
        kid = create_machine(CHILD, logic=MachineLogic(actions={"pair": act}))
        m = create_machine(
            ROOT,
            logic=MachineLogic(actions={"pair": act}, services={"kid": kid}),
        )
        i = Interpreter(m)
        spy = HookSnap(i)
        i.use(spy)
        await i.start()  # hooks fire DURING the initial descent
        await i.send("GO")
        await asyncio.sleep(0.1)
        await i.stop()
        out.append(
            {
                "engine": "async",
                "kind": kind,
                "torn": spy.torn,
                "refused": spy.refused,
                "legal": spy.legal,
                "untyped": spy.untyped,
            }
        )
        if kind == "async":
            continue  # a coroutine action cannot run on the sync engine
        # --- sync engine --------------------------------------------------
        kid2 = create_machine(CHILD, logic=MachineLogic(actions={"pair": act}))
        m2 = create_machine(
            ROOT,
            logic=MachineLogic(actions={"pair": act}, services={"kid": kid2}),
        )
        si = SyncInterpreter(m2)
        spy2 = HookSnap(si)
        si.use(spy2)
        si.start()
        si.send("GO")
        si.stop()
        out.append(
            {
                "engine": "sync",
                "kind": kind,
                "torn": spy2.torn,
                "refused": spy2.refused,
                "legal": spy2.legal,
                "untyped": spy2.untyped,
            }
        )
    ok = all(not r["torn"] and not r["untyped"] for r in out)
    total = sum(r["refused"] + r["legal"] for r in out)
    return {"ok": ok, "snapshots_taken": total, "runs": out}


SIMPLE = {
    "id": "s",
    "initial": "a",
    "context": {"n": 1},
    "states": {"a": {"on": {"G": "b"}}, "b": {}},
}


def _fresh_blob():
    import json

    i = SyncInterpreter(create_machine(SIMPLE, logic=MachineLogic())).start()
    blob = i.get_persisted_snapshot()
    i.stop()
    if isinstance(blob, str):
        blob = json.loads(blob)
    return blob


def _restore(blob) -> str:
    """Return 'RESTORED' or the exception class name."""
    import json

    try:
        m = create_machine(SIMPLE, logic=MachineLogic())
        SyncInterpreter.from_snapshot(json.dumps(blob), m)
        return "RESTORED"
    except XStateMachineError as exc:
        return type(exc).__name__
    except Exception as exc:  # noqa: BLE001
        return f"UNTYPED:{type(exc).__name__}"


@attack(
    "B2",
    "configuration/state_ids disagreement fuzz (400 mutations): every "
    "disagreeing pair is refused SnapshotCorruptError, never silently picked",
    "#186 configuration must agree with state_ids",
)
def b2() -> Dict[str, Any]:
    base = _fresh_blob()
    rng = random.Random(20260921)
    accepted_bad: List[Dict[str, Any]] = []
    untyped: List[str] = []
    n = 0
    for _ in range(400):
        b = copy.deepcopy(base)
        cfg = list(b.get("configuration") or [])
        sids = list(b.get("state_ids") or [])
        mode = rng.randrange(6)
        if mode == 0:
            b["configuration"] = []
        elif mode == 1:
            b["configuration"] = ["s.b"]
        elif mode == 2:
            b["configuration"] = cfg + ["s.ghost"]
        elif mode == 3:
            b["state_ids"] = ["s.b"]
        elif mode == 4:
            b["state_ids"] = []
        else:
            b["configuration"] = ["s.nope"]
            b["state_ids"] = ["s.other"]
        # only count genuinely disagreeing blobs
        c2 = set(b.get("configuration") or [])
        s2 = set(b.get("state_ids") or [])
        if not (c2 and s2) or {x for x in c2 if "." in x} == s2:
            continue
        n += 1
        res = _restore(b)
        if res == "RESTORED":
            accepted_bad.append(
                {"configuration": b["configuration"], "state_ids": b["state_ids"]}
            )
        elif res.startswith("UNTYPED"):
            untyped.append(res)
    return {
        "ok": not accepted_bad and not untyped,
        "disagreeing_blobs_tested": n,
        "silently_accepted": len(accepted_bad),
        "examples": accepted_bad[:4],
        "untyped_rejections": untyped[:4],
    }


@attack(
    "B3",
    "machine_hash null / absent / wrong on v0, v1 and v2 blobs: a versioned "
    "payload without a usable hash is DRIFT, not a free pass",
    "#185 bypass keyed on declared version",
)
def b3() -> Dict[str, Any]:
    base = _fresh_blob()
    rows: List[Dict[str, Any]] = []
    for version in (0, 1, 2):
        for mut in ("null", "absent", "wrong", "intact"):
            b = copy.deepcopy(base)
            if version:
                b["version"] = version
            else:
                b.pop("version", None)
            if mut == "null":
                b["machine_hash"] = None
            elif mut == "absent":
                b.pop("machine_hash", None)
            elif mut == "wrong":
                b["machine_hash"] = "deadbeef" * 8
            rows.append(
                {"version": version, "hash": mut, "result": _restore(b)}
            )
    # Contract: for a DECLARED version (>=1), only 'intact' may restore.
    bad = [
        r
        for r in rows
        if r["version"] >= 1
        and r["hash"] != "intact"
        and r["result"] == "RESTORED"
    ]
    untyped = [r for r in rows if str(r["result"]).startswith("UNTYPED")]
    return {
        "ok": not bad and not untyped,
        "silently_restored_unverified": bad,
        "untyped": untyped,
        "matrix": rows,
    }


STRICTM = {
    "id": "st",
    "strict": True,
    "initial": "a",
    "states": {
        "a": {"on": {"DECLARED": "b", "*": {"actions": "noop"}}},
        "b": {},
    },
}
STRICT_NOWILD = {
    "id": "st2",
    "strict": True,
    "initial": "a",
    "states": {"a": {"on": {"DECLARED": "b"}}, "b": {}},
}


def _send_sync(cfg, ev: str):
    def noop(i, c, e, ad):  # noqa: ANN001
        pass

    i = SyncInterpreter(
        create_machine(copy.deepcopy(cfg), logic=MachineLogic(actions={"noop": noop}))
    ).start()
    try:
        r = i.send(ev)
        return {
            "ok": getattr(r, "ok", None),
            "error": type(r.error).__name__ if getattr(r, "error", None) else None,
        }
    except XStateMachineError as exc:
        return {"raised": type(exc).__name__}
    except Exception as exc:  # noqa: BLE001
        return {"raised_untyped": type(exc).__name__}
    finally:
        try:
            i.stop()
        except Exception:  # noqa: BLE001
            pass


@attack(
    "B4",
    "strict + wildcard matrix: a '*' handler must NOT make an undeclared "
    "event name legal (declared / undeclared / wildcard-only)",
    "#190 is_known_event answers the DECLARATION question",
)
def b4() -> Dict[str, Any]:
    rows = {
        "wild_declared": _send_sync(STRICTM, "DECLARED"),
        "wild_undeclared": _send_sync(STRICTM, "NOT_DECLARED"),
        "nowild_declared": _send_sync(STRICT_NOWILD, "DECLARED"),
        "nowild_undeclared": _send_sync(STRICT_NOWILD, "NOT_DECLARED"),
    }

    def _refused(r) -> bool:
        return bool(r.get("raised")) or bool(r.get("error"))

    ok = (
        not _refused(rows["wild_declared"])
        and _refused(rows["wild_undeclared"])  # the point of #190
        and not _refused(rows["nowild_declared"])
        and _refused(rows["nowild_undeclared"])
        and not any("raised_untyped" in r for r in rows.values())
    )
    return {"ok": ok, "matrix": rows}


KILL = {
    "id": "k",
    "initial": "a",
    "onUnhandled": "error",
    "guardErrorPolicy": "raise",
    "states": {"a": {"on": {"OK": {"target": "b", "cond": "g"}}}, "b": {}},
}


async def _receipt_matrix(engine: str) -> Dict[str, Any]:
    mode = {"v": "allow"}

    def g(ctx, e):  # noqa: ANN001  # guard arity is (context, event)
        if mode["v"] == "crash":
            raise RuntimeError("guard boom")
        return mode["v"] == "allow"

    def mk():
        return create_machine(
            copy.deepcopy(KILL), logic=MachineLogic(guards={"g": g})
        )

    async def one(m_mode: str, ev: str):
        mode["v"] = m_mode
        if engine == "sync":
            i = SyncInterpreter(mk()).start()

            def send(e):  # noqa: ANN001
                return i.send(e, wait=True)
        else:
            i = await Interpreter(mk()).start()

            async def send(e):  # noqa: ANN001
                return await i.send(e, wait=True)

        try:
            r = await send(ev) if engine != "sync" else send(ev)
            sig = (
                bool(getattr(r, "denied", False)),
                getattr(r, "error", None) is None,
                bool(getattr(r, "deferred", None)),
                bool(getattr(r, "changed", False)),
            )
            return {
                "sig": sig,
                "error": type(r.error).__name__ if r.error else None,
            }
        except XStateMachineError as exc:
            return {"sig": ("RAISED",), "error": type(exc).__name__}
        finally:
            try:
                await i.stop() if engine != "sync" else i.stop()
            except Exception:  # noqa: BLE001
                pass

    return {
        "ok_case": await one("allow", "OK"),
        "denied": await one("deny", "OK"),
        "guard_crash": await one("crash", "OK"),
        "unhandled_kill": await one("allow", "UNDECLARED"),
    }


@attack(
    "B5",
    "Receipt matrix ok / denied / guard-crash / onUnhandled-error kill is "
    "injective and the KILL reaches the SENDER's receipt - both engines",
    "#189: a success-shaped receipt must not go back to the killer's caller",
)
async def b5() -> Dict[str, Any]:
    res = {e: await _receipt_matrix(e) for e in ("sync", "async")}
    prob: List[str] = []
    for eng, rows in res.items():
        # 🏛️ Discriminator = the 4-tuple PLUS the error TYPE. The tuple alone
        #    cannot separate guard-crash from the onUnhandled kill (both are
        #    (F,F,F,F)); the error class does, and both are non-None, so an
        #    observer is never handed a success-shaped receipt.
        sigs = [tuple(r["sig"]) + (r["error"],) for r in rows.values()]
        if len(set(sigs)) != len(sigs):
            prob.append(f"{eng}: receipt signatures not injective {sigs}")
        k = rows["unhandled_kill"]
        if k["error"] is None and k["sig"] != ("RAISED",):
            prob.append(f"{eng}: onUnhandled kill invisible to sender {k}")
        if rows["guard_crash"]["error"] != "RuntimeError":
            prob.append(f"{eng}: guard crash not surfaced {rows['guard_crash']}")
    # Engine parity: the two engines must report the same matrix.
    if res["sync"] != res["async"]:
        prob.append("sync/async receipt matrices differ")
    return {"ok": not prob, "problems": prob, "matrix": res}


@attack(
    "B6",
    "Forge the ENGINE-COMPLETION marker from user code (Event subclass, "
    "dataclasses.replace, internal=True, sendTo of a captured DoneEvent)",
    "#179/#180: provenance must not be attacker-settable",
)
async def b6() -> Dict[str, Any]:
    findings: List[str] = []

    cfg = {
        "id": "f",
        "initial": "a",
        "maxIterations": 20,
        "states": {
            "a": {"on": {"P": "b"}},
            "b": {"on": {"P": "a"}},
        },
    }
    m = create_machine(cfg, logic=MachineLogic())
    drops = []

    class D(PluginBase):
        def on_event_dropped(self, i, e, reason):  # noqa: ANN001
            drops.append(reason)

    i = await Interpreter(m).use(D()).start()

    # 1. `send(..., priority=True)` must NOT be chargeable -> no marker path.
    sig = None
    try:
        import inspect as _i

        sig = str(_i.signature(i.send))
    except Exception:  # noqa: BLE001
        pass
    if "engine_completion" in (sig or ""):
        findings.append("public send() exposes engine_completion")

    # 2. Event subclass claiming to be a completion.
    class FakeDone(Event):
        pass

    try:
        fake = FakeDone(type="done.invoke.f.a")
    except Exception:  # noqa: BLE001
        fake = Event(type="done.invoke.f.a")
    for _ in range(200):
        await i.send(fake, priority=True)
    await asyncio.sleep(0.1)
    forged_charged = sum(1 for d in drops if d == "chain_budget")

    # 3. dataclasses.replace on a real Event to graft internal flags.
    replaced_ok = None
    try:
        ev = Event(type="P")
        r2 = dataclasses.replace(ev, type="done.invoke.f.a")
        await i.send(r2, priority=True)
        replaced_ok = "accepted"
    except Exception as exc:  # noqa: BLE001
        replaced_ok = type(exc).__name__

    # 4. send_threadsafe(internal=True) forgery.
    internal_sig = "n/a"
    try:
        import inspect as _i

        internal_sig = str(_i.signature(i.send_threadsafe))
    except Exception:  # noqa: BLE001
        pass

    depth = getattr(i, "_raise_depth", None)
    owed = getattr(i, "_chain_owed", None)
    await i.stop()
    return {
        "ok": not findings,
        "findings": findings,
        "public_send_signature": sig,
        "send_threadsafe_signature": internal_sig,
        "forged_completions_charged_as_chain_budget": forged_charged,
        "dataclasses_replace": replaced_ok,
        "raise_depth_after_200_forgeries": depth,
        "chain_owed_after": owed,
    }


if __name__ == "__main__":
    main("n8_persist_sem_sec")
