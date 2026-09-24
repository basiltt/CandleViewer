"""R13 -- 5-WAY receipt matrix and the engine-completion FORGERY surface.

S1  guard-crash / denied / deferred / unhandled-ignored / onUnhandled="error"
    kill (#189), on BOTH engines, with BOTH service kinds where a service is
    involved.  `(denied, error, deferred)` must discriminate all five.

X1  FORGE the engine-completion marker from user code.  #179/#180 make chain
    accounting depend on a privileged "this is an engine completion" flag.  If
    user code can set it, it buys unbounded self-generated work and a
    permanent DoS. Four vectors:
      (a) an Event SUBCLASS whose type mimics `done.invoke.<id>`
      (b) dataclasses.replace() on a DoneEvent captured from a real completion
      (c) send(..., internal=True)
      (d) sendTo() of a captured DoneEvent
    PASS = the chain budget still trips (RunawayChainError / chain_budget
    drops); FAIL = unbounded laps with no trip.
"""
import asyncio, copy, dataclasses, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    Event,
    DoneEvent,
    PluginBase,
    create_machine,
)

# ------------------------------------------------------------------- S1
S1CFG = {
    "id": "s",
    "initial": "a",
    "guardErrorPolicy": "raise",
    "states": {
        "a": {
            "on": {
                "CRASH": {"target": "a", "guard": "boom"},
                "DENY": {"target": "a", "guard": "no"},
                "OK": {"target": "a"},
            }
        }
    },
}


def s1_logic(async_svc):
    def boom(c, e):
        raise ValueError("guard exploded")

    if async_svc:

        async def svc(i, c, e):
            return {"ok": 1}

    else:

        def svc(i, c, e):
            return {"ok": 1}

    return MachineLogic(
        guards={"boom": boom, "no": lambda c, e: False},
        services={"svc": svc},
    )


def describe(r, exc):
    if exc is not None:
        return f"RAISED:{type(exc).__name__}"
    return (
        f"denied={getattr(r, 'denied', '?')} "
        f"error={type(getattr(r, 'error', None)).__name__ if getattr(r, 'error', None) else None} "
        f"deferred={getattr(r, 'deferred', '?')} "
        f"ok={getattr(r, 'ok', '?')}"
    )


async def s1(async_svc):
    kind = "asyncdef" if async_svc else "plaindef"
    for unhandled in ("ignore", "defer", "error"):
        cfg = copy.deepcopy(S1CFG)
        cfg["onUnhandled"] = unhandled
        # --- sync
        row = []
        for ev in ("CRASH", "DENY", "NOPE", "OK"):
            it = SyncInterpreter(
                create_machine(copy.deepcopy(cfg), logic=s1_logic(False))
            )
            it.start()
            exc = None
            r = None
            try:
                # 🧾 SyncInterpreter returns a Receipt only with wait=True;
                #    without it the call returns None and every field below
                #    reads '?', which is a harness artefact, not a contract.
                r = it.send(ev, wait=True)
            except Exception as e:
                exc = e
            row.append(f"{ev}=({describe(r, exc)})")
            try:
                it.stop()
            except Exception:
                pass
        print(f"   sync  onUnhandled={unhandled:<7} {' | '.join(row)}")
        # --- async
        row = []
        for ev in ("CRASH", "DENY", "NOPE", "OK"):
            it = Interpreter(
                create_machine(copy.deepcopy(cfg), logic=s1_logic(async_svc))
            )
            await asyncio.wait_for(it.start(), 8)
            exc = None
            r = None
            try:
                r = await asyncio.wait_for(it.send(ev, wait=True), 5)
            except Exception as e:
                exc = e
            row.append(f"{ev}=({describe(r, exc)})")
            try:
                await asyncio.wait_for(it.stop(), 5)
            except Exception:
                pass
        print(f"   async onUnhandled={unhandled:<7} svc={kind} {' | '.join(row)}")


# ------------------------------------------------------------------- X1
class Drops(PluginBase):
    def __init__(self):
        self.d = {}

    def on_event_dropped(self, interp, event, reason=None, **kw):
        self.d[str(reason)] = self.d.get(str(reason), 0) + 1


CAP = {"ev": None}


class FakeDone(Event):
    """An Event subclass masquerading as an engine completion."""


async def x1_vector(name, make_event, async_svc, laps=400):
    """A self-feeding chain built ENTIRELY out of forged completions: the
    handler for `done.invoke.cap` re-sends the forged event on the priority
    lane. If the forgery is accepted as an engine completion it is charged and
    the budget trips; if it is charged as a self-raise it also trips. Only a
    forgery that buys FREE work runs to `laps` with no trip at all."""
    n = {"i": 0}

    async def loop_action(i, c, e, a):
        if n["i"] >= laps:
            return
        n["i"] += 1
        ev = make_event(i)
        if ev is None:
            return
        try:
            i.send(ev, priority=True)
        except Exception:
            pass

    async def svc(i, c, e):
        return {"ok": 1}

    def psvc(i, c, e):
        return {"ok": 1}

    cfg = {
        "id": "x",
        "initial": "a",
        "maxIterations": 20,
        "states": {
            "a": {
                "entry": ["loop"],
                "invoke": {"id": "cap", "src": "svc"},
                "on": {
                    # the forged completion re-arms the chain
                    "done.invoke.cap": {
                        "target": "a",
                        "internal": False,
                        "actions": ["loop"],
                    }
                },
            }
        },
    }
    dr = Drops()
    it = Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"loop": loop_action},
                services={"svc": svc if async_svc else psvc},
            ),
        )
    )
    it.use(dr)
    try:
        await asyncio.wait_for(it.start(), 8)
    except asyncio.TimeoutError:
        print(f"   {name:<34} START_TIMEOUT")
        return
    await asyncio.sleep(0.8)
    err = type(it.last_error).__name__ if it.last_error else None
    laps_run = n["i"]
    tripped = err == "RunawayChainError" or dr.d.get("chain_budget", 0) > 0
    # A forgery is only dangerous if it ran a LONG chain with no trip at all.
    free = (not tripped) and laps_run > 50
    print(
        f"   {name:<34} svc={'asyncdef' if async_svc else 'plaindef'} "
        f"chain_laps={laps_run} last_error={err} drops={dr.d} "
        f"=> {'FAIL (forgery bought free work)' if free else 'PASS'}"
    )
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:
        pass


async def x1():
    print("\nX1 forge the engine-completion marker")
    # capture a genuine DoneEvent to replace/replay
    cap = {}

    async def svc(i, c, e):
        return {"ok": 1}

    def on_done(i, c, e, a):
        cap["ev"] = e

    capcfg = {
        "id": "c",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "id": "inv",
                    "src": "svc",
                    "onDone": {"target": "b", "actions": ["grab"]},
                }
            },
            "b": {},
        },
    }
    itc = Interpreter(
        create_machine(
            capcfg,
            logic=MachineLogic(actions={"grab": on_done}, services={"svc": svc}),
        )
    )
    await asyncio.wait_for(itc.start(), 8)
    await asyncio.sleep(0.2)
    await itc.stop()
    real = cap.get("ev")
    print(
        f"   captured real completion: {type(real).__name__} "
        f"type={getattr(real, 'type', None)!r} "
        f"fields={[f.name for f in dataclasses.fields(real)] if dataclasses.is_dataclass(real) else 'not-a-dataclass'}"
    )
    flags = {
        f.name: getattr(real, f.name)
        for f in (dataclasses.fields(real) if dataclasses.is_dataclass(real) else [])
        if f.name not in ("payload", "data")
    }
    print(f"   its non-payload fields: {flags}")

    vectors = {
        "(a) Event subclass 'done.invoke.cap'": lambda i: FakeDone(
            type="done.invoke.cap"
        ),
        "(b) dataclasses.replace(DoneEvent)": (
            (lambda i: dataclasses.replace(real, type="done.invoke.cap"))
            if dataclasses.is_dataclass(real)
            else (lambda i: None)
        ),
        "(c) plain Event 'done.invoke.cap'": lambda i: Event(
            type="done.invoke.cap"
        ),
        "(d) replay the captured DoneEvent": lambda i: real,
    }
    for async_svc in (False, True):
        for name, mk in vectors.items():
            try:
                await x1_vector(name, mk, async_svc)
            except Exception as e:
                print(f"   {name:<34} harness:{type(e).__name__}: {e}")


async def main():
    print("S1 5-way receipt matrix (CRASH / DENY / unhandled NOPE / OK)")
    for a in (False, True):
        await s1(a)
    await x1()


asyncio.run(main())
