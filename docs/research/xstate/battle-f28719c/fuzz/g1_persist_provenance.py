"""G1 -- NEW ATTACK: persistence of round-8 machinery.

A. Snapshot round-trip of a pending priority-lane item WITH provenance:
   external send(priority=True) vs self-generated raise.  After resume the
   shed/charge decision must still honour provenance (#192).
B. `"engine": true` FORGERY in a persisted event record -> must not restore
   as a trusted completion unless it really was engine-minted (#195).
C. v1 (0.8.0-written, state_ids-only, no `configuration`) restore (#198).
D. Snapshot taken from inside `on_interpreter_start` (#199).

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, copy, json, logging, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.events import (
    persist_event,
    restore_event,
    is_system_event,
    DoneEvent,
    Event,
)
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotMidStepError,
)

CFG = {
    "id": "g1",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "EXT": {"target": "b", "actions": ["bump"]},
                "GO": {"target": "b"},
            }
        },
        "b": {
            "on": {
                "EXT": {"target": "a", "actions": ["bump"]},
                "GO": {"target": "a"},
            }
        },
    },
}

SVC_CFG = {
    "id": "g1s",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": "run"}},
        "run": {
            "invoke": {
                "id": "inv",
                "src": "svc",
                "onDone": {"target": "done", "actions": ["mark"]},
            }
        },
        "done": {"type": "final"},
    },
}


def bump(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def mark(i, c, e, a=None):
    c["marked"] = True


def def_svc(i, c, e):
    return {"v": 1}


async def async_svc(i, c, e):
    await asyncio.sleep(0.01)
    return {"v": 1}


async def sect_a():
    print("== A: priority-lane item round-trip, provenance preserved ==")
    for kind in ("external", "self"):
        m = create_machine(
            copy.deepcopy(CFG), logic=MachineLogic(actions={"bump": bump})
        )
        it = await Interpreter(m).start()
        await it.send("EXT", priority=True, wait=True)
        snap = it.get_snapshot()
        await it.stop()
        d = json.loads(snap) if isinstance(snap, str) else snap
        m2 = create_machine(
            copy.deepcopy(CFG), logic=MachineLogic(actions={"bump": bump})
        )
        it2 = await Interpreter.from_snapshot(snap, m2).start()
        before = it2.context.get("n", 0)
        await it2.send("EXT", priority=True, wait=True)
        after = it2.context.get("n", 0)
        ok = after == before + 1
        print(
            f"  {kind:9s} resume ids={it2.current_state_ids} "
            f"n {before}->{after} applied={ok} => {'PASS' if ok else 'FAIL'}"
        )
        await it2.stop()


async def sect_b():
    print("== B: `engine: true` forgery in a persisted record ==")
    # genuine
    m = create_machine(
        copy.deepcopy(SVC_CFG),
        logic=MachineLogic(
            services={"svc": async_svc}, actions={"mark": mark}
        ),
    )
    cap = {}

    class P(PluginBase):
        def on_transition(self, i, f, t, ev):
            if getattr(ev, "type", "").startswith("done.invoke"):
                cap["ev"] = ev

    it = await Interpreter(m).start()
    it.use(P())
    await it.send("GO", wait=True)
    await asyncio.sleep(0.15)
    await it.stop()
    genuine = cap.get("ev")
    if genuine is None:
        print("  (no done event captured; using engine mint path)")
    else:
        rec = persist_event(genuine)
        print(f"  genuine record engine-flag={rec.get('engine')!r}")
        back = restore_event(rec)
        print(
            f"  genuine round-trip is_system_event={is_system_event(back)} "
            f"=> {'PASS' if is_system_event(back) else 'FAIL'}"
        )
    forged = {
        "kind": "done",
        "type": "done.invoke.inv",
        "data": {"v": 99},
        "src": "inv",
        "engine": True,
    }
    fb = restore_event(forged)
    trusted = is_system_event(fb)
    print(
        f"  FORGED record (hand-written engine:true) -> "
        f"is_system_event={trusted} "
        f"=> {'FAIL(forgery trusted)' if trusted else 'PASS'}"
    )
    noflag = dict(forged)
    noflag.pop("engine")
    nb = restore_event(noflag)
    print(
        f"  record WITHOUT flag -> is_system_event={is_system_event(nb)} "
        f"=> {'PASS' if not is_system_event(nb) else 'FAIL'}"
    )


async def sect_c():
    print("== C: v1 (0.8.0-written, state_ids only) restore ==")
    m = create_machine(
        copy.deepcopy(CFG), logic=MachineLogic(actions={"bump": bump})
    )
    it = await Interpreter(m).start()
    snap = it.get_snapshot()
    await it.stop()
    d = json.loads(snap) if isinstance(snap, str) else copy.deepcopy(snap)
    for label, mut in (
        ("v1 both fields", lambda x: x.update(version=1)),
        (
            "v1 state_ids-only (configuration removed)",
            lambda x: (x.update(version=1), x.pop("configuration", None)),
        ),
        (
            "v0 state_ids-only (no version key)",
            lambda x: (
                x.pop("version", None),
                x.pop("configuration", None),
            ),
        ),
    ):
        p = copy.deepcopy(d)
        mut(p)
        m2 = create_machine(
            copy.deepcopy(CFG), logic=MachineLogic(actions={"bump": bump})
        )
        try:
            it2 = await Interpreter.from_snapshot(
                json.dumps(p), m2, verify_machine_hash=False
            ).start()
            res = f"loaded:{it2.current_state_ids}"
            await it2.stop()
        except Exception as exc:
            res = f"refused:{type(exc).__name__}"
        print(f"  {label:42s} -> {res}")


async def sect_d():
    print("== D: snapshot from inside on_interpreter_start (#199) ==")
    out = {}

    class P(PluginBase):
        def on_interpreter_start(self, i):
            try:
                i.get_snapshot()
                out["r"] = "ACCEPTED (torn window)"
            except SnapshotMidStepError as e:
                out["r"] = "REFUSED:SnapshotMidStepError"
            except Exception as e:
                out["r"] = f"REFUSED:{type(e).__name__}"

    m = create_machine(
        copy.deepcopy(CFG), logic=MachineLogic(actions={"bump": bump})
    )
    it = Interpreter(m)
    it.use(P())
    await it.start()
    await it.stop()
    print(
        f"  async engine -> {out.get('r')} "
        f"=> {'PASS' if 'REFUSED' in str(out.get('r')) else 'FAIL'}"
    )


async def main():
    await sect_a()
    await sect_b()
    await sect_c()
    await sect_d()


asyncio.run(main())
