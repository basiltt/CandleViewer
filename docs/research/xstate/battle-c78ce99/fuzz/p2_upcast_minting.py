"""P2 -- #214 restore-strict matrix, v2 upcast matrix, and the v2-upcast
minting vector.

#214 upcasts a v2 (0.8.0-era) `done` / `error` / `after` record as
ENGINE-MINTED, because "a v2 writer had exactly ONE minter of those records
-- the engine itself". That reasoning holds for records the LIBRARY wrote.
It does not hold for records an ATTACKER writes, because the version field
is part of the same payload: writing `"version": 2` is as easy as writing
`"engine": true`, and it needs no flag at all.

So #203's gate (only an engine-minted `after` drives an `after`) and #195's
(only an engine-minted `done` drives `onDone`) are both reachable from a
plain v2-shaped blob. This script asks exactly that:

  A  v2 upcast matrix: done / error / after / user records at version 2
     vs version 3, flagged and unflagged -- what drives a transition?
  B  the minting vector: a hand-written `"version": 2` snapshot with a
     `done.invoke.*` / `after.*` record and NO `engine` flag. Must NOT
     drive `onDone` / `after` if the trust boundary means anything.
  C  #214 restore-strict: a restored USER event under `strict: True` is
     refused, reported once via `on_invalid_event`, recorded on
     `last_error`, and dropped -- while engine records are never "unknown".
  D  lane restore ordering: a `lane: "priority"` record restores AHEAD of
     the inbox.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase  # noqa: E402


async def adv(clk, ms):
    r = clk.increment(ms)
    if r is not None and hasattr(r, "__await__"):
        await r
    for _ in range(4):
        await asyncio.sleep(0)


class Catch(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, error, event=None):  # noqa: D102
        self.invalid.append((type(error).__name__,
                             getattr(event, "type", event)))


# --------------------------------------------------------------- A/B charts
CFG_AFTER = {
    "id": "fa",
    "initial": "armed",
    "states": {
        "armed": {"after": {60000: {"target": "expired"}}},
        "expired": {},
    },
}

CFG_DONE = {
    "id": "fd",
    "initial": "working",
    "context": {"fill": None},
    "states": {
        "working": {
            "invoke": {"id": "job", "src": "svc",
                       "onDone": {"target": "filled", "actions": ["take"]}},
        },
        "filled": {},
    },
}


def take(i, c, e, a=None):
    c["fill"] = getattr(e, "data", None)


async def take_async(i, c, e, a=None):
    c["fill"] = getattr(e, "data", None)


def svc_def(i, c, e):
    import time

    time.sleep(30)
    return {"real": True}


async def svc_async(i, c, e):
    await asyncio.sleep(30)
    return {"real": True}


def logic(kind):
    return MachineLogic(
        actions={"take": take if kind == "def" else take_async},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


def base_snapshot(machine, state_ids, *, version, records, context=None):
    """A hand-written snapshot at an arbitrary declared version."""
    return {
        "version": version,
        "machine_id": machine.id,
        "machine_hash": machine.structure_hash,
        "status": "running",
        "state_ids": list(state_ids),
        "configuration": sorted(
            {machine.id} | {s for sid in state_ids
                            for s in _ancestors(sid)}
        ),
        "context": context or {},
        "pending_events": records,
        "deferred": [],
        "scheduled_sends": [],
        "history": {},
        "actors": {},
        "system": {},
        "output": None,
        "error": None,
    }


def _ancestors(state_id):
    parts = state_id.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


# ------------------------------------------------------------------ part A/B
async def vector(machine, kind, state_ids, record, version, *, context=None):
    """Restore a snapshot carrying one record; report whether it drove."""
    snap = base_snapshot(machine, state_ids, version=version,
                         records=[record], context=context)
    try:
        it = Interpreter.from_snapshot(json.dumps(snap), machine,
                                       clock=SimulatedClock())
        await it.start()
        for _ in range(8):
            await asyncio.sleep(0)
        await adv(it.clock, 1.0)
        ids = sorted(it.current_state_ids)
        ctx = dict(it.context)
        await it.stop()
        return ids, ctx, None
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{type(exc).__name__}"


async def part_ab(defects):
    print("A/B -- v2 upcast matrix and the minting vector")
    print("     'DROVE' = the restored record fired the real transition")
    for kind in ("def", "async def"):
        m_after = create_machine(json.loads(json.dumps(CFG_AFTER)),
                                 logic=logic(kind))
        m_done = create_machine(json.loads(json.dumps(CFG_DONE)),
                                logic=logic(kind))
        cases = [
            # (label, machine, state_ids, record, version, drove_pred)
            ("after v3 flagged  ", m_after, ["fa.armed"],
             {"kind": "after", "type": "after.60000.fa.armed",
              "engine": True, "scheduled_for": 0.0, "fired_at": 0.0}, 3),
            ("after v3 UNflagged", m_after, ["fa.armed"],
             {"kind": "after", "type": "after.60000.fa.armed",
              "scheduled_for": 0.0, "fired_at": 0.0}, 3),
            ("after v2 UNflagged", m_after, ["fa.armed"],
             {"kind": "after", "type": "after.60000.fa.armed",
              "scheduled_for": 0.0, "fired_at": 0.0}, 2),
            ("after v1 UNflagged", m_after, ["fa.armed"],
             {"type": "after.60000.fa.armed"}, 1),
            ("done  v3 flagged  ", m_done, ["fd.working"],
             {"kind": "done", "type": "done.invoke.job",
              "engine": True, "data": {"filled": 999999}, "src": "job"}, 3),
            ("done  v3 UNflagged", m_done, ["fd.working"],
             {"kind": "done", "type": "done.invoke.job",
              "data": {"filled": 999999}, "src": "job"}, 3),
            ("done  v2 UNflagged", m_done, ["fd.working"],
             {"kind": "done", "type": "done.invoke.job",
              "data": {"filled": 999999}, "src": "job"}, 2),
            ("done  v1 UNflagged", m_done, ["fd.working"],
             {"type": "done.invoke.job", "data": {"filled": 999999},
              "src": "job"}, 1),
        ]
        for label, m, sids, rec, ver in cases:
            ids, ctx, err = await vector(m, kind, sids, rec, ver)
            if err:
                print(f"  {kind:9s} {label} v{ver}  -> REFUSED:{err}")
                continue
            drove = ids != sids
            mark = "DROVE" if drove else "inert"
            extra = ""
            if ctx and ctx.get("fill"):
                extra = f"  ctx.fill={ctx['fill']}"
            print(f"  {kind:9s} {label} v{ver}  -> {mark}  {ids}{extra}")
            unflagged = rec.get("engine") is not True
            if drove and unflagged and ver >= 2:
                defects.append(
                    f"B/{kind}: a hand-written v{ver} record with NO 'engine' "
                    f"flag drove the real transition ({label.strip()}): "
                    f"{sids} -> {ids}{extra}"
                )
    print()


# -------------------------------------------------------------------- part C
CFG_STRICT = {
    "id": "sc",
    "initial": "a",
    "strict": True,
    "states": {"a": {"on": {"KNOWN": "b"}}, "b": {}},
}


async def part_c(defects):
    print("C -- #214 restore applies `strict` to USER records")
    print("    changelog: 'a refusal is reported (on_invalid_event,")
    print("    last_error) and the event dropped'")
    for kind in ("def", "async def"):
        m = create_machine(json.loads(json.dumps(CFG_STRICT)),
                           logic=logic(kind))

        # C1: refusal alone -- is it recorded at restore time?
        snap1 = base_snapshot(
            m, ["sc.a"], version=3,
            records=[{"kind": "event", "type": "NOPE", "payload": {}}],
        )
        catch1 = Catch()
        it1 = Interpreter.from_snapshot(json.dumps(snap1), m,
                                        clock=SimulatedClock())
        it1.use(catch1)
        at_restore = (type(it1.last_error).__name__ if it1.last_error
                      else None)
        pend = [getattr(e, "type", e) for e in it1.pending_events]
        await it1.start()
        for _ in range(10):
            await asyncio.sleep(0)
        after_start = (type(it1.last_error).__name__ if it1.last_error
                       else None)
        await it1.stop()
        print(f"  {kind:9s} C1 dropped={pend == []} "
              f"last_error@restore={at_restore} "
              f"last_error@start={after_start} hooks={catch1.invalid}")
        if pend != []:
            defects.append(f"C1/{kind}: refused event was NOT dropped: {pend}")
        if at_restore != "UnknownEventError":
            defects.append(
                f"C1/{kind}: last_error at restore = {at_restore}, "
                f"expected UnknownEventError"
            )
        # 🔔 the hook fires INSIDE from_snapshot, before any caller can
        #    attach a plugin -- `use()` is only reachable on the returned
        #    object. So the `on_invalid_event` half of the claim is
        #    unobservable by construction.
        if not catch1.invalid:
            defects.append(
                f"C1/{kind}: on_invalid_event is unobservable for a restore "
                f"refusal -- it fires inside from_snapshot(), which offers "
                f"no way to attach a plugin first (no `plugins=` parameter); "
                f"`use()` only exists on the already-constructed object"
            )

        # C2: does a following legitimate event ERASE the refusal record?
        snap2 = base_snapshot(
            m, ["sc.a"], version=3,
            records=[{"kind": "event", "type": "NOPE", "payload": {}},
                     {"kind": "event", "type": "KNOWN", "payload": {}}],
        )
        it2 = Interpreter.from_snapshot(json.dumps(snap2), m,
                                        clock=SimulatedClock())
        before = type(it2.last_error).__name__ if it2.last_error else None
        await it2.start()
        for _ in range(10):
            await asyncio.sleep(0)
        after = type(it2.last_error).__name__ if it2.last_error else None
        ids = sorted(it2.current_state_ids)
        await it2.stop()
        print(f"  {kind:9s} C2 last_error@restore={before} "
              f"last_error@start={after} ids={ids}")
        if ids != ["sc.b"]:
            defects.append(
                f"C2/{kind}: the KNOWN restored event did not survive the "
                f"refusal of its neighbour (ids={ids})"
            )
        if before == "UnknownEventError" and after is None:
            defects.append(
                f"C2/{kind}: the restore refusal is erased by the very next "
                f"restored event -- `last_error` resets per processed event, "
                f"so a restore that silently dropped traffic is "
                f"indistinguishable from a clean one the moment any other "
                f"pending event runs. Combined with the unreachable hook, "
                f"neither half of the #214 reporting claim survives a "
                f"non-empty inbox"
            )
    print()


# -------------------------------------------------------------------- part D
CFG_LANE = {
    "id": "ln",
    "initial": "a",
    "context": {"order": []},
    "states": {
        "a": {
            "on": {
                "INBOX": {"actions": ["log_in"]},
                "PRIO": {"actions": ["log_pr"]},
            }
        }
    },
}


async def part_d(defects):
    print("D -- lane restore ordering (#214)")

    def log_in(i, c, e, a=None):
        c.setdefault("order", []).append("INBOX")

    def log_pr(i, c, e, a=None):
        c.setdefault("order", []).append("PRIO")

    async def log_in_a(i, c, e, a=None):
        c.setdefault("order", []).append("INBOX")

    async def log_pr_a(i, c, e, a=None):
        c.setdefault("order", []).append("PRIO")

    for kind in ("def", "async def"):
        lg = MachineLogic(actions={
            "log_in": log_in if kind == "def" else log_in_a,
            "log_pr": log_pr if kind == "def" else log_pr_a,
        })
        m = create_machine(json.loads(json.dumps(CFG_LANE)), logic=lg)
        # INBOX is written FIRST; PRIO carries lane=priority and must run first
        snap = base_snapshot(
            m, ["ln.a"], version=3,
            records=[{"kind": "event", "type": "INBOX", "payload": {}},
                     {"kind": "event", "type": "PRIO", "payload": {},
                      "lane": "priority"}],
            context={"order": []},
        )
        it = Interpreter.from_snapshot(json.dumps(snap), m,
                                       clock=SimulatedClock())
        await it.start()
        for _ in range(10):
            await asyncio.sleep(0)
        order = list(it.context.get("order") or [])
        await it.stop()
        print(f"  {kind:9s} order={order}")
        if order != ["PRIO", "INBOX"]:
            defects.append(
                f"D/{kind}: lane ordering not honoured on restore: {order}"
            )
    print()


async def main():
    print("P2 -- #214 restore-strict / v2 upcast / minting vector\n")
    defects = []
    await part_ab(defects)
    await part_c(defects)
    await part_d(defects)
    print(f"DEFECTS = {len(defects)}")
    for d in defects:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
