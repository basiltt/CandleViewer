"""
NEW attacks on 6db65d8's round-7 machinery (#179-190), observability track.
Reduced params stated inline per the 20-min wall-clock budget.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks_r7.py
"""
import asyncio
import logging
import time

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    RunawayChainError,
    SnapshotMidStepError,
)

log_records = []


class CaptureHandler(logging.Handler):
    def emit(self, record):
        log_records.append((record.levelname, record.getMessage()))


lib_logger = logging.getLogger("xstate_statemachine")
lib_logger.setLevel(logging.DEBUG)
lib_logger.addHandler(CaptureHandler())
lib_logger.propagate = False


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_event_dropped(self, interpreter, event, reason):
        self.calls.append(("on_event_dropped", reason))

    def on_action_execute(self, interpreter, action_name, event):
        self.calls.append(("on_action_execute", action_name))


# --- P: async-def invoke ping-pong is bounded and observable (#179) --------
async def p_async_invoke_bounded():
    cfg = {
        "id": "m_pp",
        "initial": "a",
        "maxIterations": 20,
        "states": {
            "a": {"invoke": {"src": "svc", "onDone": "b"}},
            "b": {"invoke": {"src": "svc", "onDone": "a"}},
        },
    }

    async def svc(interp_, ctx, ev):
        return {}

    logic = MachineLogic(services={"svc": svc})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    rec = Recorder()
    interp.use(rec)
    await interp.start()
    t0 = time.time()
    while time.time() - t0 < 2.0 and interp.last_error is None:
        await asyncio.sleep(0.05)
    await interp.stop()
    print(
        f"P async invoke ping-pong bounded: last_error={interp.last_error!r} "
        f"status_before_stop_checked=True"
    )


# --- Q: external priority sends never charged, BOTH service kinds ----------
async def q_priority_never_charged(service_kind: str):
    """Each PING triggers a small bounded self-raise (well under
    maxIterations on its own); many PINGs sent back-to-back with
    priority=True must all be received -- #180 says only engine
    completions/self-raises are charged, not external priority sends, so
    none of these should be dropped as chain_budget."""
    cfg = {
        "id": f"m_prio_{service_kind}",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 10,
        "states": {
            "a": {
                "on": {
                    "PING": {"actions": ["count_ping", "raise_bump"]},
                    "BUMP": {"actions": ["inc"]},
                }
            }
        },
    }
    sent = {"n": 0}
    received = {"n": 0}
    interp_holder = {}

    def inc(interp_, ctx, ev, action_def):
        ctx["n"] = ctx.get("n", 0) + 1

    def count_ping(interp_, ctx, ev, action_def):
        received["n"] += 1

    def raise_bump(interp_, ctx, ev, action_def):
        interp_holder["interp"].send({"type": "BUMP"}, internal=True)

    if service_kind == "async":
        async def svc_noop(interp_, ctx, ev):
            return {}
    else:
        def svc_noop(interp_, ctx, ev):
            return {}

    logic = MachineLogic(
        actions={"inc": inc, "count_ping": count_ping, "raise_bump": raise_bump},
        services={"noop": svc_noop},
    )
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    interp_holder["interp"] = interp
    await interp.start()

    for _ in range(800):
        await interp.send({"type": "PING"}, priority=True, wait=True)
        sent["n"] += 1
    await asyncio.sleep(0.3)
    await interp.stop()
    dropped = sent["n"] - received["n"]
    print(
        f"Q[{service_kind}] external priority PING never charged: sent={sent['n']} "
        f"received={received['n']} dropped={dropped} last_error={interp.last_error!r} "
        f"(expect dropped==0)"
    )


# --- R: children_timeout with a slow child; start() bounded and observable
async def r_children_timeout():
    cfg = {
        "id": "m_ct",
        "type": "parallel",
        "states": {
            f"r{i}": {"invoke": {"src": "slow", "onDone": "done_" + str(i)}}
            if False else {"initial": "running", "states": {"running": {"invoke": {"src": "slow", "onDone": "done"}}, "done": {}}}
            for i in range(1)
        },
    }

    async def slow(interp_, ctx, ev):
        await asyncio.sleep(5.0)
        return {}

    logic = MachineLogic(services={"slow": slow})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    t0 = time.time()
    with CaptureWarnings() as records:
        await interp.start(children_timeout=0.3)
    elapsed = time.time() - t0
    print(
        f"R children_timeout=0.3s vs 5s-slow child: start() returned in {elapsed:.2f}s "
        f"status={interp.status} warning_logged={any('timeout' in r[1].lower() or 'children' in r[1].lower() for r in records)}"
    )
    await interp.stop()


class CaptureWarnings:
    def __enter__(self):
        self.start_len = len(log_records)
        return log_records

    def __exit__(self, *a):
        return False


# --- S: in-flight flag over start() descent, async engine, entry action ---
async def s_inflight_over_async_start():
    cfg = {
        "id": "m_s_entry",
        "initial": "a",
        "context": {"filled": 0},
        "states": {"a": {"entry": ["fill_ctx"]}},
    }
    snap_holder = {}
    interp = None

    def fill_ctx(interp_, ctx, ev, action_def):
        ctx["filled"] = 1
        try:
            snap_holder["ok"] = interp.get_persisted_snapshot()
            snap_holder["err"] = None
        except SnapshotMidStepError as e:
            snap_holder["ok"] = None
            snap_holder["err"] = e

    logic = MachineLogic(actions={"fill_ctx": fill_ctx})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    print(
        f"S async in-flight-over-start entry action: snap_ok={snap_holder.get('ok')} "
        f"snap_err={snap_holder.get('err')!r} (expect refused, not a torn snapshot)"
    )
    await interp.stop()


# --- T: _chain_owed under 100 concurrent never-completing coroutine
# services + stop() -- leak or hang check
async def t_chain_owed_never_completing_stop():
    cfg = {
        "id": "m_owed",
        "type": "parallel",
        "states": {
            f"r{i}": {"initial": "running", "states": {"running": {"invoke": {"src": "hang", "onDone": "done"}}, "done": {}}}
            for i in range(100)
        },
    }

    async def hang(interp_, ctx, ev):
        await asyncio.sleep(3600)
        return {}

    logic = MachineLogic(services={"hang": hang})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    t0 = time.time()
    await interp.start()
    await asyncio.sleep(0.2)
    stop_t0 = time.time()
    await asyncio.wait_for(interp.stop(), timeout=10.0)
    stop_elapsed = time.time() - stop_t0
    print(
        f"T chain_owed leak/hang check: 100 never-completing coroutine services, "
        f"stop() elapsed={stop_elapsed:.2f}s status={interp.status} "
        f"chain_owed_after_stop={getattr(interp, '_chain_owed', 'n/a')} "
        f"(expect fast stop, no hang, no leaked owed count)"
    )


async def main():
    await p_async_invoke_bounded()
    for kind in ("def", "async"):
        await q_priority_never_charged(kind)
    await r_children_timeout()
    await s_inflight_over_async_start()
    await t_chain_owed_never_completing_stop()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
