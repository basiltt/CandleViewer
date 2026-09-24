"""m3 — replay F2's saved B2-illegal-configuration repro verbatim.

Loads out/b2_repro.json (engine, strict, config, script) and re-runs it,
printing the configuration legality after each event. Confirms whether the
illegal (zero-active-child compound) configuration is deterministic, and
whether the machine keeps accepting events / snapshots in that state.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
    XStateMachineError,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.join(HERE, "out", "b2_repro.json")


def _act(i, c, e, a):
    c.setdefault("log", []).append("x")


def _svc_ok(i, c, e):
    return {"ok": 1}


def _svc_fail(i, c, e):
    raise RuntimeError("svc boom")


def logic():
    return MachineLogic(
        actions={f"act_{k}": _act for k in "abc"},
        guards={"guard_true": lambda c, e: True,
                "guard_false": lambda c, e: False,
                "guard_ctx": lambda c, e: bool(c.get("n", 0) % 2)},
        services={"svc_ok": _svc_ok, "svc_fail": _svc_fail},
    )


def legality(interp) -> str:
    active = set(interp._active_state_nodes)
    problems = []
    stack = [interp.machine]
    while stack:
        n = stack.pop()
        kids = getattr(n, "states", None)
        if not kids:
            continue
        ak = [c for c in kids.values() if c in active]
        if getattr(n, "type", "") == "parallel":
            if len(ak) != len(kids):
                problems.append(f"parallel {n.id}: {len(ak)}/{len(kids)}")
        else:
            if len(ak) != 1:
                problems.append(f"compound {n.id}: {len(ak)} active kids")
        stack.extend(ak)
    return "; ".join(problems) or "LEGAL"


EVENTS = ["GO", "PING", "PONG", "NEXT", "X", "BACK", "DONE_IT"]


async def run_async(cfg, events):
    """Replay on the ASYNC engine, which is what the fuzzer recorded."""
    m = create_machine(copy.deepcopy(cfg), logic=logic())
    it = Interpreter(m)
    await asyncio.wait_for(it.start(), timeout=10)
    print(f"  [async] after start: {legality(it)} "
          f"states={sorted(it.current_state_ids)}")
    bad = None
    for ev in events:
        name = ev if isinstance(ev, str) else ev.get("type")
        try:
            await asyncio.wait_for(it.send(name), timeout=10)
        except XStateMachineError as exc:
            print(f"  [async] {str(name):10s} typed {type(exc).__name__}")
            continue
        except Exception as exc:
            print(f"  [async] {str(name):10s} UNTYPED {type(exc).__name__}")
            continue
        leg = legality(it)
        print(f"  [async] {str(name):10s} {leg:46s} "
              f"states={sorted(it.current_state_ids)} status={it.status}")
        if leg != "LEGAL" and bad is None:
            bad = name
            try:
                s = it.get_persisted_snapshot()
                out = f"snapshot PRODUCED state_ids={s.get('state_ids')}"
                try:
                    Interpreter.from_snapshot(
                        s, create_machine(copy.deepcopy(cfg), logic=logic()))
                    out += " restore=ACCEPTED"
                except XStateMachineError as e2:
                    out += f" restore={type(e2).__name__}"
            except XStateMachineError as e2:
                out = f"snapshot refused {type(e2).__name__}"
            except Exception as e2:
                out = f"snapshot UNTYPED {type(e2).__name__}"
            print(f"    >>> [async] torn at {name}: {out}")
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass
    print("  [async] first illegal event:", bad)


def main():
    if not os.path.exists(REPRO):
        print("no repro file:", REPRO)
        return 2
    rep = json.load(open(REPRO, encoding="utf-8"))
    cfg = rep["config"]
    print("engine(recorded)=", rep.get("engine"), "strict=", rep.get("strict"))
    m = create_machine(copy.deepcopy(cfg), logic=logic())
    it = SyncInterpreter(m)
    it.start()
    print(f"  after start: {legality(it)}  states={sorted(it.current_state_ids)}")
    first_bad = None
    for ev in EVENTS:
        try:
            it.send(ev)
        except XStateMachineError as exc:
            print(f"  {ev:8s} typed {type(exc).__name__}")
            continue
        except Exception as exc:
            print(f"  {ev:8s} UNTYPED {type(exc).__name__}: {exc}")
            continue
        leg = legality(it)
        print(f"  {ev:8s} {leg:48s} states={sorted(it.current_state_ids)} "
              f"status={it.status} ok={getattr(it,'last_transition_ok',None)}")
        if leg != "LEGAL" and first_bad is None:
            first_bad = ev
            # does the library let us persist the torn configuration?
            try:
                s = it.get_persisted_snapshot()
                out = f"snapshot PRODUCED state_ids={s.get('state_ids')}"
                try:
                    SyncInterpreter.from_snapshot(
                        s, create_machine(copy.deepcopy(cfg), logic=logic()))
                    out += " restore=ACCEPTED"
                except XStateMachineError as exc2:
                    out += f" restore={type(exc2).__name__}"
            except XStateMachineError as exc2:
                out = f"snapshot refused {type(exc2).__name__}"
            except Exception as exc2:
                out = f"snapshot UNTYPED {type(exc2).__name__}"
            print(f"    >>> torn at {ev}: {out}")
    print("first illegal event (sync):", first_bad)
    recorded = rep.get("events") or EVENTS
    print("recorded event script:", [e if isinstance(e, str) else e for e in recorded][:20])
    asyncio.run(run_async(cfg, recorded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
