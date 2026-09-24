"""
NEW attacks on f28719c's round-8 machinery (#192-#201) for the OBSERVABILITY
track. Standalone: stdlib + xstate_statemachine only.

Attacks (see report battle-f28719c/observability.md for the full matrix):
  U1: forge "engine": true on a persisted done-record (import-path / dict
      construction), restore, check strict/onDone behavior.
  U2: v0/v1 (state_ids-only, no "kind") snapshot restore -- still works,
      classified as user event if replayed, no crash.
  U3: children_timeout with 50 async def children vs 1 -- bound is per-child
      not aggregate (start() wall time flat in N).
  U4: priority lane sheds by provenance -- external priority sends survive a
      self-generated chain trip (both service kinds).
  U5: action-issued priority send is charged like a raise (trips the chain).
  U6: def-service rollback -- an armed def-service invoke that gets rolled
      back is never submitted (no observable side effect / thread).
  U7: snapshot attempt from on_interpreter_start -- refused both engines.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks_r8.py
"""
import asyncio
import json
import threading
import time

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    RunawayChainError,
    SnapshotMidStepError,
    SnapshotCorruptError,
)
from xstate_statemachine.events import engine_done, restore_event, is_system_event
from xstate_statemachine.plugins import PluginBase


def u1_forge_engine_true():
    # Build a machine whose onDone matters, then forge a persisted "done"
    # record with "engine": true via plain dict construction (no import of
    # private classes) and see if restore_event trusts it.
    forged_trusted = {
        "kind": "done",
        "type": "done.invoke.svc",
        "data": {"x": 1},
        "src": "svc",
        "engine": True,
    }
    forged_untrusted = dict(forged_trusted)
    forged_untrusted.pop("engine")

    ev_trusted = restore_event(forged_trusted)
    ev_untrusted = restore_event(forged_untrusted)
    print(
        f"U1 forge engine:true via plain dict -> "
        f"is_system_event(trusted)={is_system_event(ev_trusted)} "
        f"is_system_event(untrusted)={is_system_event(ev_untrusted)} "
        f"(expect: True / False -- forging the dict key alone still yields a "
        f"'trusted' engine event; only genuine persist_event() output ever "
        f"legitimately carries it, so this checks the FIELD is honored "
        f"as documented, not that it is unforgeable by a snapshot-writer "
        f"who already has write access to the blob -- #185's stated trust "
        f"boundary)"
    )
    # onDone-driving check: run it through a real machine's strict handling.
    cfg = {
        "id": "u1",
        "initial": "s",
        "states": {"s": {"invoke": {"src": "svc", "onDone": "done"}}, "done": {}},
    }
    logic = MachineLogic(services={"svc": lambda i, c, e: {"never": "call-me"}})
    m = create_machine(cfg, logic=logic)
    interp = SyncInterpreter(m, strict=True)
    interp.start()
    # Feed the forged trusted event directly at the public send() surface,
    # simulating a caller who round-tripped a snapshot with a forged dict.
    r = interp.send(ev_trusted, wait=True)
    print(
        f"U1b forged-trusted done event sent while real 'svc' still pending: "
        f"changed={r.changed} error={r.error!r} state={interp.value} "
        f"(this checks whether the restore path itself is the only mint "
        f"site, not whether send() re-validates identity)"
    )


def u2_v1_restore():
    v1_system = {"type": "___xstate_init___"}
    v1_user = {"type": "after.hours"}
    ev_sys = restore_event(v1_system)
    ev_user = restore_event(v1_user)
    print(
        f"U2 v1 (no 'kind') restore: init-sentinel is_system={is_system_event(ev_sys)} "
        f"'after.hours'-named is_system={is_system_event(ev_user)} "
        f"(expect True/False per #162 -- name-sniffing only for the one "
        f"engine sentinel shape, everything else defaults to user traffic)"
    )
    try:
        restore_event({"type": ""})
        print("U2b empty type: NO ERROR (unexpected)")
    except SnapshotCorruptError as e:
        print(f"U2b empty type -> SnapshotCorruptError (expected): {e}")
    try:
        restore_event("not-a-dict")
        print("U2c non-dict record: NO ERROR (unexpected)")
    except SnapshotCorruptError as e:
        print(f"U2c non-dict record -> SnapshotCorruptError (expected): {e}")


async def u3_children_timeout_scaling():
    def mk(n, d):
        regions = {
            f"r{k}": {
                "initial": "s",
                "states": {"s": {"invoke": {"id": f"k{k}", "src": "kidm"}}},
            }
            for k in range(n)
        }
        child = {"id": "kid", "initial": "w", "states": {"w": {"entry": ["slow"]}}}

        async def slow(i, c, e, a):
            await asyncio.sleep(d)

        return create_machine(
            {"id": "par", "type": "parallel", "states": regions},
            logic=MachineLogic(
                services={
                    "kidm": create_machine(
                        child, logic=MachineLogic(actions={"slow": slow})
                    )
                }
            ),
        )

    out = []
    for n in (1, 50):
        t0 = time.monotonic()
        interp = await Interpreter(mk(n, 0.3)).start(children_timeout=0.1)
        out.append(time.monotonic() - t0)
        await interp.stop()
    print(
        f"U3 children_timeout=0.1s bound, D=0.3s child sleep, N=1 vs N=50 async "
        f"children: start()_wall_time={[round(x,3) for x in out]} "
        f"(expect: both ~0.1s, flat in N -- per-child bound, not aggregate; "
        f"spread={round(max(out)-min(out),3)}s)"
    )


async def u4_priority_shed_by_provenance():
    # A self-generated 'always' chain trips maxIterations; concurrently fire
    # priority=True external sends. All external priority sends must survive
    # (be delivered), only self-generated chain items get shed.
    cfg = {
        "id": "u4",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {
                "always": [{"target": "a", "actions": ["bump"], "cond": "spin"}],
                "on": {"PING": {"actions": ["count_ping"]}},
            }
        },
        "maxIterations": 30,
    }
    pings_received = {"n": 0}

    def bump(i, c, e, a):
        c["n"] = c.get("n", 0) + 1

    def spin(c, e):
        return True

    def count_ping(i, c, e, a):
        pings_received["n"] += 1

    logic = MachineLogic(
        actions={"bump": bump, "count_ping": count_ping}, guards={"spin": spin}
    )
    m = create_machine(cfg, logic=logic)
    interp = Interpreter(m)
    await interp.start()
    n_pings = 60
    for _ in range(n_pings):
        interp.send("PING", priority=True)
    await asyncio.sleep(0.3)
    await interp.stop()
    print(
        f"U4 priority-shed-by-provenance: n_pings_sent={n_pings} "
        f"n_pings_delivered(count_ping fired)={pings_received['n']} "
        f"last_error={interp.last_error!r} "
        f"(expect: RunawayChainError from the self-generated 'always' chain, "
        f"AND all {n_pings} external priority PINGs still delivered -- 0 shed)"
    )


def u5_action_priority_send_charged():
    # An action-issued priority=True send counts toward the chain budget
    # (charged like a raise), per #192's stated fix.
    cfg = {
        "id": "u5",
        "initial": "a",
        "states": {"a": {"on": {"SPIN": {"target": "a", "actions": ["loop"]}}}},
        "maxIterations": 20,
    }
    n = {"c": 0}

    def loop(i, c, e, a):
        n["c"] += 1
        i.send("SPIN", priority=True)

    logic = MachineLogic(actions={"loop": loop})
    m = create_machine(cfg, logic=logic)
    interp = SyncInterpreter(m)
    interp.start()
    interp.send("SPIN", priority=True)
    interp.start()
    print(
        f"U5 action-issued priority send charged: last_error={interp.last_error!r} "
        f"n_loop_calls={n['c']} (expect RunawayChainError, n_loop_calls bounded "
        f"near max_iterations, NOT unbounded)"
    )


async def u6_def_service_rollback():
    # An entry action raises after the invoke is armed; actionErrorPolicy
    # "rollback" must unwind the arming so the def service is never
    # submitted (#193). Uses the async engine (Interpreter), matching the
    # library's own pinned repro shape for this issue.
    called = {"n": 0}

    def svc(i, c, e):
        called["n"] += 1
        return 1

    def boom(*a):
        raise RuntimeError("boom")

    cfg = {
        "id": "u6",
        "initial": "idle",
        "actionErrorPolicy": "rollback",
        "states": {
            "idle": {"on": {"GO": "busy"}},
            "busy": {
                "entry": ["boom"],
                "invoke": {"id": "w", "src": "svc", "onDone": "done"},
            },
            "done": {},
        },
    }

    logic = MachineLogic(services={"svc": svc}, actions={"boom": boom})
    m = create_machine(cfg, logic=logic)

    interp = await Interpreter(m).start()
    await interp.send("GO", wait=True)
    await asyncio.sleep(0.1)
    v = interp.value
    await interp.stop()
    print(
        f"U6 def-service armed-then-rolled-back (async engine, entry raises, "
        f"actionErrorPolicy=rollback): final_state={v} "
        f"svc_called_count={called['n']} "
        f"(expect: state=idle, svc_called_count=0 -- never submitted)"
    )


async def u7_snapshot_from_on_interpreter_start():
    result = {}

    class Snapper(PluginBase):
        def on_interpreter_start(self, interp):
            try:
                interp.get_persisted_snapshot()
                result["ok"] = True
            except SnapshotMidStepError as e:
                result["err"] = repr(e)

    cfg = {"id": "u7", "initial": "s", "states": {"s": {}}}
    m = create_machine(cfg, logic=MachineLogic())
    interp = Interpreter(m).use(Snapper())
    await interp.start()
    await interp.stop()
    print(
        f"U7 snapshot from on_interpreter_start (async engine): "
        f"result={result} (expect: SnapshotMidStepError, not a torn blob)"
    )

    result2 = {}

    class Snapper2(PluginBase):
        def on_interpreter_start(self, interp):
            try:
                interp.get_persisted_snapshot()
                result2["ok"] = True
            except SnapshotMidStepError as e:
                result2["err"] = repr(e)

    m2 = create_machine(cfg, logic=MachineLogic())
    interp2 = SyncInterpreter(m2).use(Snapper2())
    interp2.start()
    interp2.stop()
    print(
        f"U7' snapshot from on_interpreter_start (sync engine): "
        f"result={result2} (expect: SnapshotMidStepError)"
    )


async def main():
    u1_forge_engine_true()
    u2_v1_restore()
    await u3_children_timeout_scaling()
    await u4_priority_shed_by_provenance()
    u5_action_priority_send_charged()
    await u6_def_service_rollback()
    await u7_snapshot_from_on_interpreter_start()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
