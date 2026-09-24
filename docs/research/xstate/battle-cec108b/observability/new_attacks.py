"""
New attacks on cec108b's round-5 observability-relevant fixes.
Reduced parameters per the 20-min wall-clock budget (stated inline).

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks.py
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
    PluginBase,
    QueueOverflowError,
    OverflowPolicy,
    SnapshotCorruptError,
    RootTargetError,
    RunawayChainError,
    TransitionFailedError,
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def on_unhandled_event(self, interpreter, event, active_state_ids, disposition):
        self._rec("on_unhandled_event", disposition=disposition)

    def on_resolve_error(self, interpreter, error, event):
        self._rec("on_resolve_error", error=repr(error))

    def on_guard_error(self, interpreter, guard_name, event, error):
        self._rec("on_guard_error", guard=guard_name)

    def on_plugin_error(self, interpreter, plugin, hook, error):
        self._rec("on_plugin_error", hook=hook, error=repr(error))

    def on_invalid_event(self, interpreter, error, raw_event):
        self._rec("on_invalid_event", error=repr(error))

    def on_snapshot_error(self, interpreter, error):
        self._rec("on_snapshot_error", error=repr(error))

    def on_error(self, interpreter, error):
        self._rec("on_error", error=repr(error))

    def on_transition_failed(self, interpreter, transition, failed_actions):
        self._rec("on_transition_failed", n=len(failed_actions))

    def on_transition(self, interpreter, f, t, tr):
        self._rec("on_transition")

    def on_event_dropped(self, interpreter, event, reason):
        self._rec("on_event_dropped", reason=reason)


# --- A: guard_denied via on_unhandled_event ---------------------------------
def a_guard_denied():
    cfg = {
        "id": "m_denied",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "guard": "never"}}}, "b": {}},
    }
    logic = MachineLogic(guards={"never": lambda ctx, ev: False})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("GO", wait=True)
    dispositions = [kw["disposition"] for name, kw in rec.calls if name == "on_unhandled_event"]
    print(f"A guard_denied: Receipt.denied={getattr(receipt,'denied',None)} disposition={dispositions} "
          f"changed={receipt.changed}")


# --- B: on_error fires exactly once for actionErrorPolicy=fail --------------
def b_fail_stops_once():
    def boom(interp, ctx, ev, action_def=None):
        raise ValueError("action-boom")

    cfg = {
        "id": "m_fail",
        "initial": "a",
        "actionErrorPolicy": "fail",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": "boom"}}}, "b": {}},
    }
    logic = MachineLogic(actions={"boom": boom})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("GO", wait=True)
    on_error_n = sum(1 for n, kw in rec.calls if n == "on_error")
    on_tf_n = sum(1 for n, kw in rec.calls if n == "on_transition_failed")
    on_t_n = sum(1 for n, kw in rec.calls if n == "on_transition")
    print(f"B fail-stop: status={interp.status} config={interp.current_state_ids} "
          f"on_error x{on_error_n} on_transition_failed x{on_tf_n} on_transition x{on_t_n} "
          f"receipt.error={receipt.error!r}")


# --- C: RootTargetError observability under strict_targets=False -----------
def c_root_target_error():
    cfg = {
        "id": "m_root",
        "initial": "a",
        "states": {"a": {"on": {"GO": "#m_root"}}},
    }
    try:
        create_machine(cfg, logic=MachineLogic(), strict_targets=False)
        print("C RootTargetError: NOT RAISED (regression?)")
    except RootTargetError as e:
        print(f"C RootTargetError: raised at build time as expected: {e!r}")
    except Exception as e:
        print(f"C RootTargetError: unexpected {type(e).__name__}: {e!r}")


# --- D: chain_budget / RunawayChainError observability ----------------------
def d_chain_budget_hook():
    # nested invoke onDone re-entering ancestor -- conservative cycle (#144 fix area)
    def child_done(interp, ctx, ev):
        return None

    cfg = {
        "id": "m_chain",
        "initial": "outer",
        "maxIterations": 50,
        "states": {
            "outer": {
                "initial": "inner",
                "states": {
                    "inner": {
                        "invoke": {
                            "src": "quick",
                            "onDone": "#m_chain.outer.hist",
                        }
                    },
                    "hist": {"always": "inner"},
                },
            }
        },
    }
    logic = MachineLogic(services={"quick": child_done})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec)
    t0 = time.time()
    try:
        interp.start()
        dt = time.time() - t0
        print(f"D chain budget: start() returned in {dt:.2f}s, status={interp.status}, "
              f"error={interp.error!r}")
    except RunawayChainError as e:
        dt = time.time() - t0
        print(f"D chain budget: RunawayChainError raised in {dt:.2f}s: {e!r} (bounded, no hang)")
    except Exception as e:
        dt = time.time() - t0
        print(f"D chain budget: {type(e).__name__} in {dt:.2f}s: {e!r}")


# --- E: SnapshotCorruptError typed for torn parallel configuration ----------
def e_torn_parallel_snapshot():
    cfg = {
        "id": "m_par",
        "type": "parallel",
        "states": {
            "r1": {"initial": "a", "states": {"a": {"on": {"GO1": "b"}}, "b": {}}},
            "r2": {"initial": "x", "states": {"x": {"on": {"GO2": "y"}}, "y": {}}},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(machine).start()
    snap = json.loads(json.dumps(interp.get_persisted_snapshot()))
    # tear one region's leaf out of the configuration
    snap["configuration"] = [s for s in snap["configuration"] if not s.endswith(".a")]
    rec_msgs = []
    try:
        SyncInterpreter.from_snapshot(json.dumps(snap), machine)
        print("E torn-parallel restore: NOT REJECTED (regression)")
    except SnapshotCorruptError as e:
        print(f"E torn-parallel restore: SnapshotCorruptError as expected: {e!r}")
    except Exception as e:
        print(f"E torn-parallel restore: unexpected {type(e).__name__}: {e!r}")


# --- F: service_executor under N concurrent plain-def services -------------
def f_service_executor_concurrency(n=40):
    results = {"done": 0, "err": 0}
    lock = threading.Lock()

    def plain_service(interp, ctx, ev):
        time.sleep(0.01)
        return "ok"

    cfg = {
        "id": "m_svc",
        "initial": "a",
        "states": {"a": {"invoke": {"src": "plain_service", "onDone": "b"}}, "b": {"type": "final"}},
    }
    logic = MachineLogic(services={"plain_service": plain_service})
    machines = [create_machine({**cfg, "id": f"m_svc_{i}"}, logic=logic) for i in range(n)]

    async def run_one(m):
        interp = Interpreter(m)
        await interp.start()
        for _ in range(50):
            if interp.status in ("done", "stopped", "error"):
                break
            await asyncio.sleep(0.02)
        return interp.status

    async def main():
        return await asyncio.gather(*(run_one(m) for m in machines))

    statuses = asyncio.run(main())
    done_n = sum(1 for s in statuses if s == "done")
    print(f"F service_executor concurrency: n={n} done={done_n}/{n}")


# --- G: send_threadsafe internal=True forgery -------------------------------
def g_send_threadsafe_forgery():
    call_count = {"n": 0}

    def self_trigger(interp, ctx, ev, action_def=None):
        call_count["n"] += 1
        if call_count["n"] > 10000:
            return
        # forge internal=True from a plain (non-owned) thread to dodge maxIterations charge
        t = threading.Thread(target=lambda: interp.send_threadsafe("X", internal=True))
        t.start()
        t.join(timeout=1)

    cfg = {
        "id": "m_forge",
        "initial": "a",
        "maxIterations": 50,
        "states": {"a": {"on": {"X": {"target": "a", "actions": "self_trigger"}}}},
    }
    logic = MachineLogic(actions={"self_trigger": self_trigger})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)

    async def main():
        await interp.start()
        try:
            await interp.send("X", wait=True)
            print(f"G forgery: no RunawayChainError after {call_count['n']} generations "
                  f"(status={interp.status}) -- possible chain-budget bypass via internal=True")
        except RunawayChainError as e:
            print(f"G forgery: RunawayChainError raised after {call_count['n']} generations: {e!r} "
                  f"(forged internal=True still charged / bounded)")
        finally:
            await interp.stop()

    asyncio.run(main())


# --- H: QueueOverflowError raised at send_threadsafe call site under RAISE --
def h_send_threadsafe_raise(n_threads=16):
    def slow_action(interp, ctx, ev, action_def=None):
        time.sleep(0.005)

    cfg = {"id": "m_h", "initial": "a", "states": {"a": {"on": {"X": {"target": "a", "actions": "slow_action"}}}}}
    machine = create_machine(cfg, logic=MachineLogic(actions={"slow_action": slow_action}))
    interp = Interpreter(machine, max_queue_size=2, overflow_policy=OverflowPolicy.RAISE, service_executor=None)

    errs = []
    oks = []
    lock = threading.Lock()

    def worker(i):
        for j in range(200):
            try:
                interp.send_threadsafe(f"X{i}_{j}")
                with lock:
                    oks.append((i, j))
            except QueueOverflowError:
                with lock:
                    errs.append((i, j))

    async def main():
        await interp.start()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        await interp.stop()

    asyncio.run(main())
    print(f"H send_threadsafe RAISE under {n_threads} threads x200 sends, max_queue_size=2: "
          f"ok={len(oks)} raised={len(errs)} "
          f"(call-site raise observed={'yes' if errs else 'no'})")


if __name__ == "__main__":
    a_guard_denied()
    b_fail_stops_once()
    c_root_target_error()
    d_chain_budget_hook()
    e_torn_parallel_snapshot()
    f_service_executor_concurrency(n=40)
    g_send_threadsafe_forgery()
    h_send_threadsafe_raise(n_threads=16)
    print("DONE")
