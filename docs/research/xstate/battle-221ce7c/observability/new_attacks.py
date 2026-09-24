"""
New attacks on 221ce7c's round-6 observability-relevant fixes (#157, #166-175).
Reduced parameters per the 20-min wall-clock budget (stated inline per attack).

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks.py
"""
import asyncio
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
    RunawayChainError,
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def on_event_dropped(self, interpreter, event, reason):
        self._rec("on_event_dropped", reason=reason)

    def on_transition(self, interpreter, f, t, tr):
        self._rec("on_transition")

    def on_guard_error(self, interpreter, guard_name, event, error):
        self._rec("on_guard_error", guard=guard_name)

    def on_unhandled_event(self, interpreter, event, active_state_ids, disposition):
        self._rec("on_unhandled_event", disposition=disposition)

    def on_error(self, interpreter, error):
        self._rec("on_error", error=repr(error))


from xstate_statemachine import SnapshotMidStepError


# --- I: queue_full loop-side RAISE refusal is observable (#157) ------------
async def i_queue_full_loop_side():
    """16 producer threads slam send_threadsafe() against a tiny bounded
    inbox while a slow action drains it, under OverflowPolicy.RAISE. Any
    refusal that lands ON THE LOOP (a concurrent producer raced past the
    caller-side qsize() check) must still fire on_event_dropped(reason=
    "queue_full") exactly once per such refusal, and the WARNING log."""
    cfg = {
        "id": "m_qf",
        "initial": "a",
        "states": {
            "a": {
                "on": {"GO": {"actions": "slow"}},
            }
        },
    }

    async def slow(interp_, ctx, ev, action_def):
        await asyncio.sleep(0.003)

    logic = MachineLogic(actions={"slow": slow})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = (
        Interpreter(
            machine,
            max_queue_size=2,
            overflow_policy=OverflowPolicy.RAISE,
        )
        .use(rec)
    )
    await interp.start()

    caller_side_raises = 0
    future_side_errors = 0
    futures = []

    def producer():
        nonlocal caller_side_raises
        for _ in range(40):
            try:
                fut = interp.send_threadsafe("GO")
                futures.append(fut)
            except QueueOverflowError:
                caller_side_raises += 1

    threads = [threading.Thread(target=producer) for _ in range(16)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=25)
    # let the loop drain / settle
    await asyncio.sleep(0.5)

    for fut in futures:
        try:
            fut.result(timeout=0)
        except QueueOverflowError:
            future_side_errors += 1
        except Exception:
            pass

    dropped = [kw for name, kw in rec.calls if name == "on_event_dropped"]
    dropped_qf = [kw for kw in dropped if kw.get("reason") == "queue_full"]
    total_refusals = caller_side_raises + future_side_errors
    print(
        f"I queue_full loop-side: caller_side_raises={caller_side_raises} "
        f"future_side_errors={future_side_errors} "
        f"on_event_dropped(queue_full) fired={len(dropped_qf)} "
        f"total_refusals={total_refusals} elapsed={time.monotonic()-t0:.2f}s "
        f"(exactly-once check: hook_count<=total_refusals? "
        f"{len(dropped_qf) <= total_refusals if total_refusals else 'n/a'})"
    )
    await interp.stop()


# --- J: get_persisted_snapshot() refused from inside entry action (#169) --
def j_entry_window_refusal_root():
    """At the ROOT, in-flight alone must refuse a snapshot taken from
    inside an entry action -- even though the new leaf is already legal
    (the #169 fix: legality alone is not sufficient, in-flight is)."""
    calls = {"snap_ok": None, "snap_err": None}
    holder = {}

    def entry_action(interp_, ctx, ev, action_def):
        try:
            holder["interp"].get_persisted_snapshot()
            calls["snap_ok"] = True
        except SnapshotMidStepError as e:
            calls["snap_err"] = repr(e)

    machine = create_machine(
        {
            "id": "m_entry_snap",
            "initial": "a",
            "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["snap"]}},
        },
        logic=MachineLogic(actions={"snap": entry_action}),
    )
    interp = SyncInterpreter(machine)
    holder["interp"] = interp
    interp.start()
    interp.send("GO", wait=True)
    print(
        f"J entry-window root refusal: snap_ok={calls['snap_ok']} "
        f"snap_err={calls['snap_err']}"
    )


async def j_entry_window_refusal_root_async():
    """Same attack, async engine."""
    calls = {"snap_ok": None, "snap_err": None}
    holder = {}

    async def entry_action(interp_, ctx, ev, action_def):
        try:
            holder["interp"].get_persisted_snapshot()
            calls["snap_ok"] = True
        except SnapshotMidStepError as e:
            calls["snap_err"] = repr(e)

    machine = create_machine(
        {
            "id": "m_entry_snap_a",
            "initial": "a",
            "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["snap"]}},
        },
        logic=MachineLogic(actions={"snap": entry_action}),
    )
    interp = Interpreter(machine)
    holder["interp"] = interp
    await interp.start()
    await interp.send("GO", wait=True)
    print(
        f"J' entry-window root refusal (async): snap_ok={calls['snap_ok']} "
        f"snap_err={calls['snap_err']}"
    )
    await interp.stop()


# --- K: chain-budget trip observable on both engines, same lap count -----
def k_chain_budget_sync():
    """always -> re-enters itself forever (self-transition). Must trip
    RunawayChainError at maxIterations, observable via last_error."""
    cfg = {
        "id": "m_chain_sync",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 25,
        "states": {
            "a": {
                "always": [{"actions": "inc"}],
            }
        },
    }

    def inc(interp_, ctx, ev, action_def):
        ctx["n"] = ctx.get("n", 0) + 1

    machine = create_machine(cfg, logic=MachineLogic(actions={"inc": inc}))
    interp = SyncInterpreter(machine)
    try:
        interp.start()
    except RunawayChainError:
        pass
    print(
        f"K sync chain-budget: status={interp.status} "
        f"last_error={interp.last_error!r} n={interp.context.get('n')}"
    )


async def k_chain_budget_async():
    cfg = {
        "id": "m_chain_async",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 25,
        "states": {"a": {"always": [{"actions": "inc"}]}},
    }

    def inc(interp_, ctx, ev, action_def):
        ctx["n"] = ctx.get("n", 0) + 1

    machine = create_machine(cfg, logic=MachineLogic(actions={"inc": inc}))
    interp = Interpreter(machine)
    await interp.start()
    await asyncio.sleep(0.2)
    print(
        f"K' async chain-budget: status={interp.status} "
        f"last_error={interp.last_error!r} n={interp.context.get('n')}"
    )
    await interp.stop()


# --- L: async chain/settle budget NOT reset by 16 concurrent external ----
#         senders during a self-generated chain (external must not reset
#         the bound; chain must still trip)
async def l_external_senders_dont_reset_chain_budget():
    cfg = {
        "id": "m_ext_chain",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 30,
        "states": {
            "a": {
                "always": [{"actions": "inc"}],
                "on": {"PING": {"actions": "noop"}},
            }
        },
    }

    def inc(interp_, ctx, ev, action_def):
        ctx["n"] = ctx.get("n", 0) + 1

    def noop(interp_, ctx, ev, action_def):
        pass

    machine = create_machine(
        cfg, logic=MachineLogic(actions={"inc": inc, "noop": noop})
    )
    interp = Interpreter(machine)
    await interp.start()

    stop_flag = threading.Event()

    def sender():
        while not stop_flag.is_set():
            try:
                interp.send_threadsafe("PING")
            except Exception:
                pass
            time.sleep(0.001)

    threads = [threading.Thread(target=sender) for _ in range(16)]
    for t in threads:
        t.start()
    await asyncio.sleep(1.0)
    stop_flag.set()
    for t in threads:
        t.join(timeout=5)
    print(
        f"L external-senders-vs-chain-budget: status={interp.status} "
        f"last_error={interp.last_error!r} n={interp.context.get('n')} "
        f"(expect: tripped RunawayChainError despite 16 concurrent external "
        f"PING senders -- external sends must not reset the self-generated "
        f"'always' chain's budget)"
    )
    try:
        await interp.stop()
    except Exception:
        pass


# --- M: service_pool_size=1, 50 plain services, stop() mid-service -------
async def m_pool_size_one_stop_mid_service():
    done = []

    def plain(ctx, ev, interp=None):
        time.sleep(0.02)
        done.append(1)
        return "ok"

    cfg2 = {
        "id": "m_pool1b",
        "initial": "a",
        "states": {
            "a": {
                "invoke": [
                    {"src": f"svc{i}", "onDone": "b"} for i in range(50)
                ]
            },
            "b": {},
        },
    }
    logic2 = MachineLogic(services={f"svc{i}": plain for i in range(50)})
    machine2 = create_machine(cfg2, logic=logic2)
    interp2 = Interpreter(machine2, service_pool_size=1)
    t0 = time.monotonic()
    await interp2.start()
    await asyncio.sleep(0.05)  # let a few services start
    await interp2.stop()
    elapsed = time.monotonic() - t0
    print(
        f"M service_pool_size=1 stop-mid-service: status={interp2.status} "
        f"completed_before_stop={len(done)}/50 elapsed={elapsed:.2f}s "
        f"last_error={interp2.last_error!r} (no hang, no crash expected)"
    )


# --- N: start() ordering -- initial invoke children registered (#171) ----
async def n_start_ordering():
    cfg = {
        "id": "m_start_order",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"id": "kid", "src": "child_machine"},
                "on": {"CANCEL": {"target": "cancelled"}},
            },
            "cancelled": {},
        },
    }
    child_cfg = {"id": "child", "initial": "running", "states": {"running": {}}}
    child_machine = create_machine(child_cfg, logic=MachineLogic())
    logic = MachineLogic(services={"child_machine": child_machine})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    # Immediately probe: is 'kid' registered as a child actor?
    has_kid = "kid" in getattr(interp, "children", {}) or any(
        getattr(a, "id", None) == "kid" for a in getattr(interp, "children", {}).values()
    ) if hasattr(interp, "children") else None
    receipt = await interp.send("CANCEL", wait=True)
    print(
        f"N start()-ordering: status_after_start={interp.status} "
        f"children_attr_present={hasattr(interp, 'children')} "
        f"cancel_receipt_changed={receipt.changed} "
        f"final_state={sorted(interp.current_state_ids)}"
    )
    await interp.stop()


# --- O: done-callback double-fire / in-flight counter balance (#172) -----
async def o_done_callback_balance():
    """Fire many self-issued send_threadsafe() calls right as the loop is
    being stopped, to try to leak (double-decrement or under-decrement)
    the in-flight counter that gates the chain-budget reset."""
    cfg = {
        "id": "m_inflight",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 15,
        "states": {"a": {"on": {"BUMP": {"actions": "inc"}}}},
    }

    interp_holder = {}

    def inc(*args, **kwargs):
        ctx = args[1]
        ctx["n"] = ctx.get("n", 0) + 1
        # self-issue a threadsafe send from inside our own action --
        # exercises the #150/#172 in-flight accounting path.
        try:
            interp_holder["interp"].send_threadsafe("BUMP")
        except Exception:
            pass

    machine = create_machine(cfg, logic=MachineLogic(actions={"inc": inc}))
    interp = Interpreter(machine)
    interp_holder["interp"] = interp
    await interp.start()
    await interp.send("BUMP", wait=True)
    await asyncio.sleep(0.3)
    inflight = getattr(interp, "_threadsafe_self_sends_in_flight", None)
    print(
        f"O done-callback in-flight balance: status={interp.status} "
        f"last_error={interp.last_error!r} n={interp.context.get('n')} "
        f"in_flight_counter={inflight} (expect settles back to 0 and/or "
        f"chain trips cleanly with no leaked accounting)"
    )
    await interp.stop()


def main():
    print("=== I: queue_full loop-side refusal observability ===")
    asyncio.run(i_queue_full_loop_side())
    print("=== J: entry-window snapshot refusal (sync) ===")
    j_entry_window_refusal_root()
    print("=== J': entry-window snapshot refusal (async) ===")
    asyncio.run(j_entry_window_refusal_root_async())
    print("=== K: chain-budget observability (sync) ===")
    k_chain_budget_sync()
    print("=== K': chain-budget observability (async) ===")
    asyncio.run(k_chain_budget_async())
    print("=== L: external senders vs chain budget (async) ===")
    asyncio.run(l_external_senders_dont_reset_chain_budget())
    print("=== M: service_pool_size=1, 50 services, stop() mid-service ===")
    asyncio.run(m_pool_size_one_stop_mid_service())
    print("=== N: start() ordering (#171) ===")
    asyncio.run(n_start_ordering())
    print("=== O: done-callback in-flight balance (#172) ===")
    asyncio.run(o_done_callback_balance())
    print("DONE")


if __name__ == "__main__":
    main()
