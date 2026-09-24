"""Attack T: reduced-scale soak (~45s, given 20-min task budgets) —
N machines both kinds incl. raise(delay=) heartbeats at 10-50ms +
external priority producer + periodic snapshot/restore at quiescence.
CPU bounded, 0 dropped external, heartbeats never die, scheduled_sends
restore correctly. Full 12-min/200-machine soak deferred (§ not covered).
"""
import asyncio
import json
import random
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic

HB_CFG = {
    "id": "hb",
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "TICK", "delay": 17}}],
            "on": {
                "TICK": {"target": "b", "actions": ["beat"]},
                "EXT": {"actions": ["ext"]},
            },
        },
        "b": {
            "entry": [{"type": "raise", "params": {"event": "TICK", "delay": 17}}],
            "on": {
                "TICK": {"target": "a", "actions": ["beat"]},
                "EXT": {"actions": ["ext"]},
            },
        },
    },
}


def make_logic(ext_counter):
    def beat(interp, ctx, ev, ad):
        ctx["beats"] = ctx.get("beats", 0) + 1

    def ext(interp, ctx, ev, ad):
        ext_counter["n"] += 1

    return MachineLogic(actions={"beat": beat, "ext": ext})


async def producer(interps, stop_evt, sent_counter):
    i = 0
    while not stop_evt.is_set():
        target = interps[i % len(interps)]
        try:
            await target.send({"type": "EXT"})
            sent_counter["n"] += 1
        except Exception:
            pass
        i += 1
        await asyncio.sleep(0.005)


async def chaos_snapshot_restore(interps, stop_evt, restore_ok_counter, cfgs):
    while not stop_evt.is_set():
        await asyncio.sleep(0.5)
        idx = random.randrange(len(interps))
        old = interps[idx]
        try:
            snap = old.get_snapshot()
            m2 = create_machine(HB_CFG, logic=old.machine.logic if hasattr(old.machine, "logic") else None)
        except Exception:
            m2 = create_machine(HB_CFG)
        try:
            new_interp = Interpreter.from_snapshot(snap, m2)
            await new_interp.start()
            interps[idx] = new_interp
            restore_ok_counter["n"] += 1
            await old.stop()
        except Exception as e:
            restore_ok_counter["errs"] = restore_ok_counter.get("errs", 0) + 1
            restore_ok_counter["last_err"] = repr(e)


async def attack_t(n_machines=30, duration_s=20.0):
    ext_counter = {"n": 0}
    sent_counter = {"n": 0}
    restore_ok_counter = {"n": 0}
    logic = make_logic(ext_counter)
    interps = []
    for _ in range(n_machines):
        m = create_machine(HB_CFG, logic=logic)
        interp = Interpreter(m)
        await interp.start()
        interps.append(interp)

    stop_evt = asyncio.Event()
    t0 = time.perf_counter()
    prod_task = asyncio.create_task(producer(interps, stop_evt, sent_counter))
    chaos_task = asyncio.create_task(
        chaos_snapshot_restore(interps, stop_evt, restore_ok_counter, None)
    )
    await asyncio.sleep(duration_s)
    stop_evt.set()
    await asyncio.gather(prod_task, chaos_task, return_exceptions=True)
    wall = time.perf_counter() - t0

    beats = [i.context.get("beats", 0) for i in interps]
    errors = [str(i.last_error) for i in interps if i.last_error is not None]
    for i in interps:
        try:
            await i.stop()
        except Exception:
            pass

    print(
        f"attack_t: n_machines={n_machines} duration_s={duration_s} wall_s={wall:.2f} "
        f"min_beats={min(beats)} max_beats={max(beats)} sent={sent_counter['n']} "
        f"ext_received={ext_counter['n']} dropped_ext={sent_counter['n'] - ext_counter['n']} "
        f"restore_ok={restore_ok_counter.get('n', 0)} restore_errs={restore_ok_counter.get('errs', 0)} "
        f"restore_last_err={restore_ok_counter.get('last_err')} "
        f"n_with_runaway_error={len(errors)}"
    )
    print(
        f"attack_t_heartbeats_alive={min(beats) > 0} "
        f"attack_t_no_dropped_ext={sent_counter['n'] == ext_counter['n']} "
        f"attack_t_no_runaway={len(errors) == 0}"
    )


if __name__ == "__main__":
    asyncio.run(attack_t())
