"""(g) Event-loop blocking: max single-callback duration under load.

Our acceptance criterion: a 100 ms heatmap tick must not be starved, so no
single loop callback may exceed 5 ms. This measures the LOOP's own view --
not the interpreter's -- using `loop.slow_callback_duration` in debug mode
plus a `call_later`-based tick that records its own lateness, which is what
the heatmap actually experiences.

Two instruments:

  A. **Tick lateness.** A `call_later(0.1)` chain reschedules itself every
     100 ms and records `actual - expected`. This is the criterion the
     heatmap cares about literally.

  B. **Callback duration.** `asyncio` debug mode logs every callback taking
     longer than `slow_callback_duration`; it is set to 0.005 s so every
     violation of our 5 ms budget is captured, with the callback's repr.

Scenarios (each 3 s of steady load):

  S0  idle control (no interpreters)
  S1  1 machine, saturated in-loop send()
  S2  100 machines, saturated
  S3  1000 machines, saturated
  S4  100 machines + 32 threads on send_threadsafe
  S5  one machine draining a 50,000-event backlog built up before the
      measurement window (the `_next_event` yield-per-inbox-event design
      is what is under test here)
  S6  a synchronous action that takes 20 ms (the control: user code
      blocking the loop must show up, or the instrument is broken)
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import sys
import threading
import time

from common import counter_machine, emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

BUDGET_MS = 5.0
TICK_S = 0.1
_POS = [a for a in sys.argv[1:] if not a.startswith("-")]
WINDOW_S = float(_POS[0]) if _POS else 3.0


class SlowCallbackCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.hits: list[str] = []

    def emit(self, record):  # noqa: A003
        m = record.getMessage()
        if "Executing" in m and "took" in m:
            self.hits.append(m[:160])


class Ticker:
    """A 100 ms heatmap tick that records its own lateness."""

    def __init__(self, loop):
        self.loop = loop
        self.late_ms: list[float] = []
        self._expected = 0.0
        self._h = None
        self._stop = False

    def start(self):
        self._expected = self.loop.time() + TICK_S
        self._h = self.loop.call_at(self._expected, self._fire)

    def _fire(self):
        now = self.loop.time()
        self.late_ms.append((now - self._expected) * 1000)
        if self._stop:
            return
        self._expected += TICK_S
        self._h = self.loop.call_at(self._expected, self._fire)

    def stop(self):
        self._stop = True
        if self._h:
            self._h.cancel()

    def report(self):
        if not self.late_ms:
            return {"ticks": 0}
        s = sorted(self.late_ms)
        return {
            "ticks": len(s),
            "late_ms_p50": round(statistics.median(s), 3),
            "late_ms_p95": round(s[int(len(s) * 0.95)], 3),
            "late_ms_max": round(s[-1], 3),
            "ticks_over_budget": sum(1 for x in s if x > BUDGET_MS),
        }


async def scenario(name: str, setup, load, teardown, cap: SlowCallbackCapture):
    loop = asyncio.get_running_loop()
    print(f"[scenario] {name} ...", file=sys.stderr, flush=True)
    state = await setup() if setup else None
    before = len(cap.hits)

    # Direct loop-turn gap instrument, independent of the debug logger.
    gaps: list[float] = []
    stop = {"v": False}

    async def sampler():
        last = time.perf_counter()
        while not stop["v"]:
            await asyncio.sleep(0)
            now = time.perf_counter()
            gaps.append((now - last) * 1000)
            last = now

    ticker = Ticker(loop)
    ticker.start()
    s = asyncio.create_task(sampler())
    t0 = time.perf_counter()
    events = await load(state, WINDOW_S)
    elapsed = time.perf_counter() - t0
    stop["v"] = True
    await s
    ticker.stop()
    if teardown:
        await teardown(state)
    print(f"[scenario] {name} done in {elapsed:.2f}s", file=sys.stderr, flush=True)

    gs = sorted(gaps)
    return {
        "scenario": name,
        "window_s": round(elapsed, 3),
        "events_processed": events,
        "throughput_ev_s": round(events / elapsed, 1) if elapsed else None,
        "tick_100ms": ticker.report(),
        "loop_turn_gap_ms_p50": round(statistics.median(gs), 4) if gs else None,
        "loop_turn_gap_ms_p999": round(gs[int(len(gs) * 0.999)], 4) if gs else None,
        "loop_turn_gap_ms_max": round(gs[-1], 4) if gs else None,
        "slow_callback_log_hits": len(cap.hits) - before,
        "slow_callback_sample": cap.hits[before : before + 3],
        "budget_ms": BUDGET_MS,
        "producer_batch_per_loop_turn": BATCH,
        "asyncio_debug_mode": asyncio.get_running_loop().get_debug(),
    }


# --------------------------------------------------------------------------
async def _start_n(n: int):
    m = counter_machine()
    interps = [Interpreter(m) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in interps))
    return interps


async def _stop_all(interps):
    for i in interps:
        await i.stop(drain=True, timeout=30)


#: How many sends the producer issues per loop turn. 200 is "saturate";
#: 1 is a well-behaved producer that yields after every send. The two
#: separate ENGINE-caused tick lateness from PRODUCER-caused lateness --
#: a 200-send batch is itself one long callback and would be charged to
#: the engine if not controlled for. Set by `--batch=N`.
BATCH = next(
    (int(a.split("=")[1]) for a in sys.argv if a.startswith("--batch=")), 200
)


async def _saturate(interps, window_s: float) -> int:
    end = time.perf_counter() + window_s
    n = 0
    k = 0
    while time.perf_counter() < end:
        for _ in range(BATCH):
            await interps[k % len(interps)].send("PING")
            k += 1
            n += 1
        await asyncio.sleep(0)
    while any(i.queue_depth for i in interps):
        await asyncio.sleep(0.001)
    return n


async def s0_idle(_state, window_s: float) -> int:
    await asyncio.sleep(window_s)
    return 0


async def s4_load(interps, window_s: float) -> int:
    """32 threads on send_threadsafe, PACED.

    Unpaced, this scenario does not terminate: b2 measures the loop-side
    ingest cost of `send_threadsafe` at ~87 us/event, so 32 free-running
    threads enqueue faster than the single loop can drain, `queue_depth`
    grows without bound and the post-window drain never finishes. That
    unboundedness is itself a finding (see the report, D-concurrency-6);
    here we pace to a rate the loop can absorb so the LATENCY question the
    scenario exists to answer can actually be measured.
    """
    n_threads = 32
    per_thread_rate = 200.0  # ev/s/thread -> 6,400 ev/s aggregate
    delay = 1.0 / per_thread_rate
    end_flag = threading.Event()
    counts = [0] * n_threads

    def producer(tid):
        k = tid
        while not end_flag.is_set():
            interps[k % len(interps)].send_threadsafe("PING")
            counts[tid] += 1
            k += n_threads
            time.sleep(delay)

    ts = [threading.Thread(target=producer, args=(t,)) for t in range(n_threads)]
    for t in ts:
        t.start()
    await asyncio.sleep(window_s)
    end_flag.set()
    for t in ts:
        t.join()
    deadline = time.perf_counter() + 60
    while any(i.queue_depth for i in interps) and time.perf_counter() < deadline:
        await asyncio.sleep(0.005)
    return sum(counts)


async def s5_setup():
    i = Interpreter(counter_machine())
    await i.start()
    return i


async def s5_load(i, _window_s: float) -> int:
    # Build a deep backlog BEFORE the measurement, then time the drain.
    n = 50_000
    for _ in range(n):
        i._put_inbox(i._prepare_event("PING"))  # bypass pacing, fill directly
    while i.queue_depth:
        await asyncio.sleep(0.001)
    return n


async def s6_setup():
    def slow_sync(interp, ctx, e, ad):  # noqa: ANN001
        time.sleep(0.02)  # 20 ms of CPU-bound user code
        ctx["n"] = ctx.get("n", 0) + 1

    cfg = {
        "id": "slow",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["slow_sync"]}}}},
    }
    i = Interpreter(
        create_machine(cfg, logic=MachineLogic(actions={"slow_sync": slow_sync}))
    )
    await i.start()
    return i


async def s6_load(i, window_s: float) -> int:
    end = time.perf_counter() + window_s
    n = 0
    while time.perf_counter() < end:
        await i.send("PING")
        n += 1
        await asyncio.sleep(0)
    while i.queue_depth:
        await asyncio.sleep(0.001)
    return n


SCENARIOS = (
    "s0", "s1", "s2", "s3", "s4", "s5", "s6",
)


async def main():
    _pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    only = _pos[1] if len(_pos) > 1 else None
    # 🔬 asyncio debug mode is a HEAVY instrument: it times every callback and
    #    tracks coroutine origins. Measured cost on this box: the idle control
    #    alone goes from 0/30 to 8/30 ticks over a 5 ms budget, and saturated
    #    throughput drops from ~240k ev/s (a1, no debug) to ~390 ev/s. Running
    #    the latency measurement under it would measure the instrument.
    #    Default OFF; pass `--debug` to collect the callback-attribution
    #    (instrument B) numbers, which are only ever read qualitatively.
    debug = "--debug" in sys.argv
    loop = asyncio.get_running_loop()
    loop.set_debug(debug)
    if debug:
        loop.slow_callback_duration = BUDGET_MS / 1000
    cap = SlowCallbackCapture()
    logging.getLogger("asyncio").addHandler(cap)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)

    specs = {
        "s0": ("s0_idle_control", None, s0_idle, None),
        "s1": ("s1_1_machine_saturated", lambda: _start_n(1), _saturate, _stop_all),
        "s2": ("s2_100_machines_saturated", lambda: _start_n(100), _saturate, _stop_all),
        "s3": ("s3_1000_machines_saturated", lambda: _start_n(1000), _saturate, _stop_all),
        "s4": ("s4_100_machines_plus_32_threads_paced", lambda: _start_n(100), s4_load, _stop_all),
        "s5": ("s5_50k_backlog_drain", s5_setup, s5_load, lambda i: i.stop(drain=True, timeout=120)),
        "s6": ("s6_20ms_sync_action_control", s6_setup, s6_load, lambda i: i.stop(drain=True, timeout=120)),
    }
    keys = [only] if only else list(specs)
    res = []
    for k in keys:
        name, setup, load, teardown = specs[k]
        res.append(await scenario(name, setup, load, teardown, cap))
    suffix = (f"_{only}" if only else "") + ("_debug" if debug else "")
    suffix += f"_batch{BATCH}" if BATCH != 200 else ""
    emit(f"g1_loop_blocking{suffix}", {"budget_ms": BUDGET_MS, "scenarios": res})


if __name__ == "__main__":
    asyncio.run(main())
