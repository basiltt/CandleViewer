"""New round-10 attacks, part 1: persistence v3 round-trip + delayed
self-send ping-pong CPU-bounded concurrency + #216 config-key fuzz.
Standalone: stdlib + xstate_statemachine only. Run from neutral cwd.
"""
import asyncio
import json
import random
import time

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    InvalidConfigError,
    MachineLogic,
)

# ---------------------------------------------------------------------
# Attack P: v3 snapshot round-trip incl. armed delayed self-sends
# ---------------------------------------------------------------------
PING_CFG = {
    "id": "ping",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "GO", "delay": 37}}], "on": {"GO": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "GO", "delay": 41}}], "on": {"GO": "a"}},
    },
}


async def attack_p():
    random.seed(7)
    ok = 0
    total = 60
    for i in range(total):
        m = create_machine(PING_CFG)
        interp = Interpreter(m)
        await interp.start()
        # let it run a random number of steps to arm a delayed self-send
        steps = random.randint(0, 4)
        for _ in range(steps):
            await asyncio.sleep(0.005)
        snap = interp.get_snapshot()
        d = json.loads(snap)
        has_sched = bool(d.get("scheduled_sends"))
        await interp.stop()
        # restore
        m2 = create_machine(PING_CFG)
        try:
            restored = Interpreter.from_snapshot(snap, m2)
        except Exception as e:
            restored = None
            print(f"  restore_failed[{i}]: {e!r}")
        if restored is not None:
            await restored.start()
            await asyncio.sleep(0.08)
            await restored.stop()
            ok += 1
    print(f"attack_p: total={total} restored_ok={ok} sample_has_scheduled_sends_field={has_sched}")


# ---------------------------------------------------------------------
# Attack Q: 1ms raise(delay=) ping-pong x N machines for a few seconds,
# CPU must be bounded by the clock; must NOT raise RunawayChainError.
# ---------------------------------------------------------------------
FAST_PING_CFG = {
    "id": "fastping",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": {"target": "b", "actions": ["bump"]}},
        },
        "b": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": {"target": "a", "actions": ["bump"]}},
        },
    },
}


def make_impls():
    def bump(interp, ctx, ev, ad):
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"bump": bump})


async def attack_q(n_machines=20, duration_s=5.0):
    impls = make_impls()
    interps = []
    errors = []
    for _ in range(n_machines):
        m = create_machine(FAST_PING_CFG, logic=impls)
        interp = Interpreter(m)

        def on_err(i=interp):
            errors.append(str(i.last_error))

        try:
            interp.machine.config  # noop, ensure attr exists
        except Exception:
            pass
        interps.append(interp)
    t0 = time.perf_counter()
    for i in interps:
        await i.start()
    await asyncio.sleep(duration_s)
    cpu_dt = time.perf_counter() - t0
    counts = [i.context.get("n", 0) for i in interps]
    last_errors = [str(i.last_error) for i in interps if i.last_error is not None]
    for i in interps:
        await i.stop()
    print(
        f"attack_q: n_machines={n_machines} duration_s={duration_s} wall_s={cpu_dt:.2f} "
        f"min_count={min(counts)} max_count={max(counts)} n_with_error={len(last_errors)} "
        f"sample_errors={last_errors[:3]}"
    )
    print(f"attack_q_no_runaway={len(last_errors) == 0}")


# ---------------------------------------------------------------------
# Attack R: #216 unknown top-level config-key fuzz (misspellings) +
# strict_config=True must raise InvalidConfigError; nested state-level
# unknown keys are checked separately for behaviour documentation.
# ---------------------------------------------------------------------
def attack_r():
    base = {
        "id": "cfgfuzz",
        "initial": "s",
        "context": {},
        "states": {"s": {"on": {"GO": "s"}}},
    }
    misspellings = ["actionErrorPolicyy", "Strict", "maxIteration", "onUnhandledEvent", "strictConfigg"]
    results = {}
    for key in misspellings:
        cfg = dict(base)
        cfg[key] = True
        # default: WARNING, no raise
        try:
            create_machine(cfg)
            default_raised = False
        except InvalidConfigError:
            default_raised = True
        # strict_config=True -> InvalidConfigError
        try:
            create_machine(cfg, strict_config=True)
            strict_raised = False
        except InvalidConfigError:
            strict_raised = True
        results[key] = {"default_raised": default_raised, "strict_raised": strict_raised}

    # nested state-level unknown key
    nested_cfg = json.loads(json.dumps(base))
    nested_cfg["states"]["s"]["actionErrorPolicyy"] = True
    try:
        create_machine(nested_cfg)
        nested_default_raised = False
    except InvalidConfigError:
        nested_default_raised = True
    try:
        create_machine(nested_cfg, strict_config=True)
        nested_strict_raised = False
    except InvalidConfigError:
        nested_strict_raised = True

    print(f"attack_r top_level={results}")
    print(
        f"attack_r nested_default_raised={nested_default_raised} "
        f"nested_strict_raised={nested_strict_raised}"
    )


async def main():
    await attack_p()
    await attack_q()
    attack_r()


if __name__ == "__main__":
    asyncio.run(main())
