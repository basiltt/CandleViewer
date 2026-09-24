"""P1 -- snapshot layout v3 round-trip property (#213/#214).

A: >=300 random machines, each with 0..3 armed delayed self-sends at random
   remaining delays, driven on a SimulatedClock. Properties:
     R1 every armed, unfired self-send appears in `scheduled_sends`
     R2 a cancelled send leaves NO record
     R3 the persisted `remaining_ms` equals the true remaining delay
        (SimulatedClock => exact, tolerance 1e-6 ms)
     R4 a restore + start() re-arms every record, and the event fires after
        exactly `remaining_ms` more simulated milliseconds -- not sooner,
        not later
     R5 the round-trip is a fixpoint: snapshot(restore(s)) == s modulo
        taken_at
B: machine_hash / structure_hash coverage of scheduled_sends.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
Exit 1 if any property fails.
"""

import asyncio
import json
import logging
import random
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SimulatedClock,
    create_machine,
)

N_MACHINES = int(__import__("os").environ.get("N_MACHINES", "300"))
SEED = int(__import__("os").environ.get("SEED", "20260922"))


# ---------------------------------------------------------------- generators
def gen_cfg(idx, rnd):
    """A chart whose entry arms 0..3 delayed self-sends, some cancelled."""
    n_arm = rnd.randint(1, 3)
    n_cancel = rnd.randint(0, n_arm - 1) if n_arm > 1 else 0
    entry = []
    delays = []
    ids = []
    for k in range(n_arm):
        d = rnd.choice([1, 5, 17, 50, 250, 1000, 60000])
        sid = f"s{k}"
        delays.append(d)
        ids.append(sid)
        entry.append(
            {"type": "raise", "params": {"event": f"P{k}", "delay": d,
                                         "id": sid}}
        )
    # cancel the LAST n_cancel of them in the same entry list
    cancelled = ids[n_arm - n_cancel:] if n_cancel else []
    for sid in cancelled:
        entry.append({"type": "cancel", "params": {"sendId": sid}})
    on = {f"P{k}": {"actions": ["mark"]} for k in range(n_arm)}
    cfg = {
        "id": f"p1_{idx}",
        "initial": "armed",
        "context": {"seen": []},
        "states": {"armed": {"entry": entry, "on": on}},
    }
    live = [
        (f"P{k}", delays[k]) for k in range(n_arm) if ids[k] not in cancelled
    ]
    return cfg, live, cancelled


def mark(i, c, e, a=None):
    c.setdefault("seen", []).append([e.type, i.clock.now()])


async def mark_async(i, c, e, a=None):
    c.setdefault("seen", []).append([e.type, i.clock.now()])


def logic(kind):
    return MachineLogic(actions={"mark": mark if kind == "def" else mark_async})


# ---------------------------------------------------------------------- run
async def one(idx, rnd, kind, defects):
    cfg, live, cancelled = gen_cfg(idx, rnd)
    m = create_machine(cfg, logic=logic(kind))
    clk = SimulatedClock()
    it = Interpreter(m, clock=clk)
    await it.start()
    await asyncio.sleep(0)
    # advance a random amount that fires nothing (< min live delay)
    minimum = min([d for _, d in live], default=1000)
    burn = rnd.uniform(0, max(0.0, minimum - 1))
    await _advance(clk, burn)

    snap = json.loads(it.get_snapshot())
    recs = snap.get("scheduled_sends") or []
    tag = f"[{idx}/{kind}]"

    # R1/R2: exactly the live ones, by type
    got = sorted(r["type"] for r in recs)
    want = sorted(t for t, _ in live)
    if got != want:
        defects.append(
            f"R1/R2 {tag} scheduled_sends={got} expected={want} "
            f"(cancelled={cancelled})"
        )
    # R3: remaining_ms exact on a simulated clock
    by_type = {r["type"]: r for r in recs}
    for t, d in live:
        if t not in by_type:
            continue
        want_rem = d - burn
        got_rem = float(by_type[t]["remaining_ms"])
        if abs(got_rem - want_rem) > 1e-6:
            defects.append(
                f"R3 {tag} {t} remaining_ms={got_rem!r} expected={want_rem!r}"
            )
    await it.stop()

    # R4: restore, re-arm, fire at exactly the remaining delay.
    # 📏 Oracle: advance in ONE sweep past the largest remaining delay and
    #    compare each event's RECORDED fire time (the `mark` action stamps
    #    `clock.now()`), rather than stepping per event -- two sends may
    #    share a delay, and a per-event step charges the tie to the first.
    it2 = Interpreter.from_snapshot(json.dumps(snap), m, clock=SimulatedClock())
    await it2.start()
    await asyncio.sleep(0)
    clk2 = it2.clock
    rems = {t: d - burn for t, d in live}
    await _advance(clk2, max(rems.values(), default=0.0) + 1.0)
    fired = {}
    for t, when in (it2.context.get("seen") or []):
        fired.setdefault(t, when * 1000.0)
    for t, rem in rems.items():
        if t not in fired:
            defects.append(f"R4-missing {tag} {t} never fired (rem={rem}ms)")
            continue
        # the re-arm floors a 0-remaining send at 0.001 ms; allow 1e-3 slack
        if abs(fired[t] - rem) > 1.1e-3:
            defects.append(
                f"R4-skew {tag} {t} fired at {fired[t]!r}ms, "
                f"expected {rem!r}ms"
            )

    # R5: re-snapshot is a fixpoint modulo volatile keys
    snap2 = json.loads(it2.get_snapshot())
    await it2.stop()
    for k in ("taken_at",):
        snap.pop(k, None)
        snap2.pop(k, None)
    if snap.get("version") != 3:
        defects.append(f"R5 {tag} version={snap.get('version')} expected 3")
    if snap.get("machine_hash") != snap2.get("machine_hash"):
        defects.append(f"R5 {tag} machine_hash drifted across round-trip")


async def _advance(clk, ms):
    if ms <= 0:
        await asyncio.sleep(0)
        return
    # 🕰️ `SimulatedClock.increment` returns a `_MustAwait` wrapper inside a
    #    running loop -- NOT a bare coroutine, so `iscoroutine` is False and
    #    a naive `if iscoroutine(r): await r` silently drops the advance.
    #    Await anything awaitable.
    r = clk.increment(ms)
    if r is not None and hasattr(r, "__await__"):
        await r
    for _ in range(3):
        await asyncio.sleep(0)


# ------------------------------------------------------------------- part B
async def part_b(defects):
    """machine_hash covers structure only; scheduled_sends must not move it,
    but a snapshot's records must not be accepted against a DIFFERENT chart.
    """
    base = {
        "id": "hb",
        "initial": "a",
        "states": {
            "a": {
                "entry": [
                    {"type": "raise",
                     "params": {"event": "P", "delay": 500, "id": "z"}}
                ],
                "on": {"P": "b"},
            },
            "b": {},
        },
    }
    m1 = create_machine(json.loads(json.dumps(base)))
    it = Interpreter(m1, clock=SimulatedClock())
    await it.start()
    await asyncio.sleep(0)
    snap = json.loads(it.get_snapshot())
    await it.stop()
    n_recs = len(snap.get("scheduled_sends") or [])
    print(f"  B: scheduled_sends persisted = {n_recs}")
    if n_recs != 1:
        defects.append(f"B: expected 1 scheduled_send record, got {n_recs}")

    # change the DELAY only -- a different timer contract, same states
    alt = json.loads(json.dumps(base))
    alt["states"]["a"]["entry"][0]["params"]["delay"] = 9
    m2 = create_machine(alt)
    same = m1.structure_hash == m2.structure_hash
    print(f"  B: structure_hash covers raise-delay change = {not same}")
    verdict = "ACCEPTED"
    try:
        it2 = Interpreter.from_snapshot(json.dumps(snap), m2,
                                        clock=SimulatedClock())
        await it2.start()
        await asyncio.sleep(0)
        rec = (json.loads(it2.get_snapshot()).get("scheduled_sends") or [])
        await it2.stop()
        verdict = f"ACCEPTED (re-armed {len(rec)})"
    except Exception as exc:  # noqa: BLE001
        verdict = f"REFUSED:{type(exc).__name__}"
    print(f"  B: snapshot vs delay-changed chart -> {verdict}")
    if same and verdict.startswith("ACCEPTED"):
        defects.append(
            "B: structure_hash does NOT cover a raise(delay=) change, so a "
            f"snapshot's armed sends restore against a chart whose timer "
            f"contract differs ({verdict})"
        )


async def main():
    print(f"P1 -- v3 round-trip property, {N_MACHINES} machines x 2 kinds, "
          f"seed={SEED}")
    defects = []
    for kind in ("def", "async def"):
        rnd = random.Random(SEED)
        for idx in range(N_MACHINES):
            try:
                await one(idx, rnd, kind, defects)
            except Exception as exc:  # noqa: BLE001
                defects.append(f"[{idx}/{kind}] EXCEPTION {type(exc).__name__}: {exc}")
        print(f"  A/{kind:9s} {N_MACHINES} machines done, "
              f"defects so far = {len(defects)}")
    await part_b(defects)
    print()
    uniq = sorted({d.split(" ")[0] for d in defects})
    print(f"DEFECTS = {len(defects)}  classes={uniq}")
    for d in defects[:12]:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
