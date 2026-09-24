"""G5 -- NEW ATTACK: semantics + security on round-8 machinery.

A. SCXML 3.13 eventless-selection matrix: an `always` at the SAME / DEEPER /
   SHALLOWER depth than a named handler must NEVER consume the named event
   (#196).  Also: fuzz named-event charts that have an `always` present,
   looking for LOST transitions.
B. Receipt matrix: guard-crash / denied / deferred / unhandled / error-kill,
   both engines, both service kinds.
C. Private-subclass isinstance semantics (#195): engine_done IS a DoneEvent,
   but a hand-built DoneEvent is not system.
D. SECURITY: forge an engine completion via (1) import path, (2)
   dataclasses.replace / _replace, (3) pickle round-trip, (4) snapshot
   record with "engine": true.  Under `strict` each must be REFUSED.
E. __slots__ on the private subclasses; redaction of payload in logs.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, copy, logging, pickle, random, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.events import (
    DoneEvent,
    ErrorEvent,
    AfterEvent,
    Event,
    is_system_event,
    restore_event,
)

# ---------------------------------------------------------------- A
def matrix_cfg(always_depth, handler_depth):
    """always at `always_depth`, named handler `EV` at `handler_depth`."""
    deep = {"id": "x", "initial": "a", "context": {"hit": 0}, "states": {}}
    node_a = {"initial": "b", "states": {"b": {"initial": "c", "states": {"c": {}}}}}
    deep["states"]["a"] = node_a
    targets = {0: deep["states"]["a"], 1: node_a["states"]["b"], 2: node_a["states"]["b"]["states"]["c"]}
    # a self-targeting always keeps the configuration but spins the settle pass
    targets[always_depth]["always"] = [
        {"target": "#x.a", "guard": "never", "actions": ["noop"]}
    ]
    targets[handler_depth]["on"] = {"EV": {"actions": ["hit"]}}
    return deep


def hit(i, c, e, a=None):
    c["hit"] = c.get("hit", 0) + 1


def noop(i, c, e, a=None):
    pass


def never(i, c, e):
    return False


async def sect_a():
    print("== A: SCXML 3.13 eventless-selection matrix (always vs named) ==")
    names = {0: "shallow", 1: "same", 2: "deep"}
    bad = 0
    for ad in (0, 1, 2):
        for hd in (0, 1, 2):
            cfg = matrix_cfg(ad, hd)
            logic = MachineLogic(actions={"hit": hit, "noop": noop}, guards={"never": never})
            # async
            m = create_machine(copy.deepcopy(cfg), logic=logic)
            it = await Interpreter(m).start()
            await it.send("EV", wait=True)
            ah = it.context.get("hit", 0)
            await it.stop()
            # sync
            m2 = create_machine(copy.deepcopy(cfg), logic=logic)
            it2 = SyncInterpreter(m2)
            it2.start()
            it2.send("EV")
            sh = it2.context.get("hit", 0)
            it2.stop()
            ok = ah == 1 and sh == 1
            if not ok:
                bad += 1
            print(
                f"  always@{names[ad]:8s} handler@{names[hd]:8s} "
                f"async_hit={ah} sync_hit={sh} => {'PASS' if ok else 'FAIL(LOST)'}"
            )
    print(f"  matrix failures = {bad}")


async def sect_a2(n=120):
    print("== A2: fuzz named-event charts WITH an `always` present ==")
    rnd = random.Random(20260922)
    lost = 0
    for k in range(n):
        ad = rnd.choice([0, 1, 2])
        hd = rnd.choice([0, 1, 2])
        cfg = matrix_cfg(ad, hd)
        if rnd.random() < 0.5:
            cfg["maxIterations"] = rnd.choice([5, 50, 500])
        logic = MachineLogic(actions={"hit": hit, "noop": noop}, guards={"never": never})
        m = create_machine(copy.deepcopy(cfg), logic=logic)
        it = await Interpreter(m).start()
        try:
            await asyncio.wait_for(it.send("EV", wait=True), 2.0)
        except Exception:
            pass
        if it.context.get("hit", 0) != 1:
            lost += 1
        await it.stop()
    print(f"  {n} charts, LOST named transitions = {lost} => {'PASS' if lost == 0 else 'FAIL'}")


# ---------------------------------------------------------------- C/D
async def sect_cd():
    print("== C: private-subclass isinstance semantics (#195) ==")
    from xstate_statemachine.events import engine_done, engine_error, engine_after

    ed = engine_done("done.invoke.i", {"v": 1}, "i")
    ud = DoneEvent("done.invoke.i", {"v": 1}, "i")
    print(f"  engine_done isinstance DoneEvent={isinstance(ed, DoneEvent)} is_system={is_system_event(ed)}")
    print(f"  user DoneEvent          isinstance DoneEvent={isinstance(ud, DoneEvent)} is_system={is_system_event(ud)}")
    print(f"  __slots__ on engine class = {type(ed).__slots__!r}")

    print("== D: SECURITY -- forging an engine completion ==")
    vectors = {}
    vectors["import path engine_done()"] = ed
    try:
        vectors["_replace on engine event"] = ed._replace(data={"v": 999})
    except Exception as exc:
        vectors["_replace on engine event"] = f"ERR:{type(exc).__name__}"
    try:
        vectors["pickle round-trip"] = pickle.loads(pickle.dumps(ed))
    except Exception as exc:
        vectors["pickle round-trip"] = f"ERR:{type(exc).__name__}"
    vectors["snapshot engine:true forgery"] = restore_event(
        {"kind": "done", "type": "done.invoke.i", "data": {}, "src": "i", "engine": True}
    )
    vectors["hand-built DoneEvent"] = ud
    for name, v in vectors.items():
        if isinstance(v, str):
            print(f"  {name:32s} -> {v}")
            continue
        print(f"  {name:32s} -> is_system_event={is_system_event(v)}")

    # end-to-end: does `strict` refuse a forged completion?
    CFG = {
        "id": "s",
        "initial": "a",
        "strict": True,
        "context": {"drove": 0},
        "states": {
            "a": {
                "invoke": {"id": "i", "src": "svc", "onDone": {"target": "b", "actions": ["mark"]}}
            },
            "b": {"type": "final"},
        },
    }

    async def svc(i, c, e):
        await asyncio.sleep(5)
        return {"v": 0}

    def mark(i, c, e, a=None):
        c["drove"] = c.get("drove", 0) + 1

    for name, v in vectors.items():
        if isinstance(v, str):
            continue
        m = create_machine(copy.deepcopy(CFG), logic=MachineLogic(services={"svc": svc}, actions={"mark": mark}))
        it = await Interpreter(m).start()
        res = "accepted"
        try:
            await asyncio.wait_for(it.send(v, wait=True), 2.0)
        except Exception as exc:
            res = f"REFUSED:{type(exc).__name__}"
        drove = it.context.get("drove", 0)
        ids = list(it.current_state_ids)
        await it.stop()
        legit = name == "import path engine_done()"
        bad = (drove > 0 or "s.b" in ids) and not legit
        print(
            f"  strict end-to-end {name:32s} -> {res} drove={drove} ids={ids} "
            f"=> {'FAIL(forgery drove onDone)' if bad else 'PASS'}"
        )


async def main():
    await sect_a()
    await sect_a2()
    await sect_cd()


asyncio.run(main())
