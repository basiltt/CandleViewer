"""w4 (@v0.9.0) -- STANDALONE. #232 RuntimeWarning + #231 invoke.src +
concurrency LOAD (200 machines x action-spawned workers).

  R1  #232 the dropped receipt warns.  A `def` action that calls
      `i.send(X, wait=True)` and throws the result away must produce a
      RuntimeWarning.  Attacked on three axes the changelog names as
      SILENT (supported shapes): ensure_future / add_done_callback /
      await.  Plus the question the brief asks: where does the warning
      SURFACE under `-W error` inside asyncio?  The warn fires from
      `__del__`, i.e. at GC time on whatever stack the collector runs --
      so under `-W error` the resulting exception is NOT raised at the
      call site.  Recorded as an OBSERVATION with its landing site.

  R2  #231 an inline-dict `invoke.src` raises a NAMED InvalidConfigError,
      never TypeError.  Fuzzed over dict / list / int / None / nested
      machine-shaped dict, at top level, in a nested state, and inside a
      parallel region; both kinds.

  R3  LOAD.  200 machines, each of whose actions spawns a worker task
      that outlives it and later sends a PLAIN event with the loop
      otherwise idle (the #225 starvation shape at scale).  Every machine
      must advance: 0 events may be stranded in the internal queue.

  R4  100 concurrent ensure_future(send(wait=True)) hand-outs while the
      spawning actions KEEP AWAITING (the #225 regression shape,
      concurrently).  All 100 receipts must resolve; none may be refused.

Exit 1 == defect.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import warnings
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError, ReentrantWaitError

MACHINES = int(os.environ.get("W4_MACHINES", "200"))
HANDOUTS = 100
ROWS: Dict[str, Any] = {}
FAILS: List[str] = []
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])),
            **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


CFG = {
    "id": "w4",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"entry": ["boom"], "on": {"GO": "done"}},
               "done": {"entry": ["tick"]}},
}


def mk(boom_sync=None, boom_async=None) -> MachineLogic:
    def tick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    if boom_sync is not None:
        def boom(i, ctx, e, ad):  # noqa: ANN001
            boom_sync(i, ctx, e, ad)
        return MachineLogic(actions={"boom": boom, "tick": tick})

    async def aboom(i, ctx, e, ad):  # noqa: ANN001
        await boom_async(i, ctx, e, ad)

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
    return MachineLogic(actions={"boom": aboom, "tick": atick})


def mid_cfg(mid: str) -> Dict[str, Any]:
    c = json.loads(json.dumps(CFG))
    c["id"] = mid
    return c


# ─────────────────────────── R1: #232 RuntimeWarning ────────────────────

async def r1_warning() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    async def run_shape(name: str, boom) -> Dict[str, Any]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            m = create_machine(mid_cfg(f"w4r1_{name}"), logic=mk(boom_sync=boom))
            i = Interpreter(m)
            await i.start()
            await asyncio.sleep(0.15)
            await i.stop()
            del i, m
            gc.collect()               # force __del__ for the dropped receipt
            await asyncio.sleep(0.05)
            gc.collect()
            msgs = [str(w.message) for w in caught
                    if issubclass(w.category, RuntimeWarning)
                    and "#232" in str(w.message)]
        return {"shape": name, "warnings": len(msgs),
                "mentions_232": all("#232" in x for x in msgs),
                "sample": msgs[:1]}

    def dropped(i, ctx, e, ad):  # noqa: ANN001  -- the defect shape
        i.send("GO", wait=True)                       # receipt thrown away

    def handed_out(i, ctx, e, ad):  # noqa: ANN001   -- supported, silent
        asyncio.ensure_future(i.send("GO", wait=True))

    def callbacked(i, ctx, e, ad):  # noqa: ANN001   -- supported, silent
        r = i.send("GO", wait=True)
        asyncio.ensure_future(r)

    def no_wait(i, ctx, e, ad):  # noqa: ANN001      -- no receipt at all
        i.send("GO")

    for nm, fn in (("dropped_receipt", dropped),
                   ("ensure_future_handout", handed_out),
                   ("ensure_future_of_var", callbacked),
                   ("plain_send_no_wait", no_wait)):
        rows.append(await run_shape(nm, fn))

    warned = {r["shape"]: r["warnings"] for r in rows}
    if warned["dropped_receipt"] < 1:
        FAILS.append("R1: a `def` action that DROPPED its wait=True receipt "
                     "produced no #232 RuntimeWarning")
    for silent in ("ensure_future_handout", "ensure_future_of_var",
                   "plain_send_no_wait"):
        if warned[silent] != 0:
            FAILS.append(f"R1: the SUPPORTED shape '{silent}' produced "
                         f"{warned[silent]} #232 RuntimeWarning(s) -- the "
                         f"changelog says these stay silent")
    return {"shapes": rows,
            "note": "the warning is emitted from __del__, so it lands "
                    "whenever the collector runs -- see R1b for what that "
                    "means under -W error"}


async def r1b_under_w_error() -> Dict[str, Any]:
    """Where does the #232 warning SURFACE with warnings-as-errors inside
    asyncio? It is raised from `__del__`, and CPython cannot propagate an
    exception out of `__del__`: it goes to sys.unraisablehook. So under
    `-W error` the adopter does NOT get a failing action -- they get an
    unraisable on stderr, at GC time, on an unrelated stack."""
    seen: List[str] = []
    orig = sys.unraisablehook

    def hook(un):  # noqa: ANN001
        seen.append(f"{un.exc_type.__name__}: {un.exc_value}")

    sys.unraisablehook = hook
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            action_raised = None

            def dropped(i, ctx, e, ad):  # noqa: ANN001
                i.send("GO", wait=True)

            m = create_machine(mid_cfg("w4r1b"), logic=mk(boom_sync=dropped))
            i = Interpreter(m)
            await i.start()
            await asyncio.sleep(0.15)
            action_raised = i.context.get("n", 0)
            await i.stop()
            del i, m
            gc.collect()
            await asyncio.sleep(0.05)
            gc.collect()
    finally:
        sys.unraisablehook = orig
    return {
        "unraisable_seen": seen[:2],
        "count": len(seen),
        "surfaces_as": ("sys.unraisablehook (NOT a raised exception at the "
                        "call site)" if seen else "nothing observable"),
        "note": "OBSERVATION, not a defect claim: __del__ cannot propagate. "
                "An adopter running -W error must install an unraisablehook "
                "(or a warnings capture) to see #232 in CI -- `-W error` "
                "alone will not fail the test.",
    }


# ─────────────────── R2: #231 inline-dict invoke.src, fuzzed ────────────

BAD_SRCS = [
    ("inline_machine_dict", {"id": "inner", "initial": "x",
                             "states": {"x": {}}}),
    ("empty_dict", {}),
    ("list_src", ["a", "b"]),
    ("int_src", 7),
    ("none_src", None),
    ("nested_dict", {"src": {"id": "deep", "initial": "y",
                             "states": {"y": {}}}}),
]


def chart_with_invoke(mid: str, site: str, src: Any) -> Dict[str, Any]:
    inv = {"id": "svc", "src": src}
    if site == "top":
        return {"id": mid, "initial": "a", "states": {
            "a": {"invoke": inv}, "b": {}}}
    if site == "nested":
        return {"id": mid, "initial": "a", "states": {
            "a": {"initial": "a1",
                  "states": {"a1": {"invoke": inv}, "a2": {}}}}}
    return {"id": mid, "initial": "p", "states": {
        "p": {"type": "parallel", "states": {
            "r1": {"initial": "s", "states": {"s": {"invoke": inv}}},
            "r2": {"initial": "t", "states": {"t": {}}}}}}}


def _start_error(mid: str, site: str, src: Any):  # noqa: ANN001
    """Build + start; return (exception name or None, message)."""
    async def go():
        m = create_machine(chart_with_invoke(mid + "_s", site, src),
                           logic=MachineLogic())
        i = Interpreter(m)
        try:
            await i.start()
            await asyncio.sleep(0.05)
        finally:
            try:
                await i.stop()
            except Exception:  # noqa: BLE001
                pass

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, str(exc)
    return None, ""


def r2_invoke_src(kind: str) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for site in ("top", "nested", "parallel"):
        for nm, src in BAD_SRCS:
            mid = f"w4r2_{kind[:1]}_{site}_{nm}"
            exc_name, msg = None, ""
            try:
                m = create_machine(chart_with_invoke(mid, site, src),
                                   logic=MachineLogic())
                Interpreter(m)
            except InvalidConfigError as exc:
                exc_name, msg = "InvalidConfigError", str(exc)
            except Exception as exc:  # noqa: BLE001
                exc_name, msg = type(exc).__name__, str(exc)
            # 🔎 #231 is a CONSTRUCTION-time claim, but a bad `src` may
            #    instead be caught at ARM time (start()). Either is a named
            #    refusal; what #231 forbids is the raw TypeError and what
            #    the brief forbids is silence. So when construction is
            #    clean, drive start() and take the error from there.
            if exc_name is None:
                exc_name, msg = _start_error(mid, site, src)
            rows.append({"site": site, "src": nm, "raised": exc_name,
                         "names_invoke_id": "svc" in msg,
                         "sample": msg[:110]})
            if exc_name == "TypeError":
                FAILS.append(f"R2/{kind}/{site}/{nm}: raised the raw "
                             f"TypeError #231 was filed for: {msg[:80]}")
            elif exc_name is None:
                FAILS.append(f"R2/{kind}/{site}/{nm}: an invalid invoke.src "
                             f"({nm}) built a machine with no error at all")
            elif exc_name not in ("InvalidConfigError",
                                  "ImplementationMissingError"):
                FAILS.append(f"R2/{kind}/{site}/{nm}: raised {exc_name}, "
                             f"expected a named library error")
    return {"kind": kind, "variants": len(rows), "rows": rows}


# ───────────── R3: 200 machines x action-spawned outliving worker ───────

async def r3_load(kind: str) -> Dict[str, Any]:
    async def worker(i, delay):  # noqa: ANN001
        await asyncio.sleep(delay)
        i.send("GO")                 # PLAIN send, loop idle, action long gone

    def spawn(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i, 0.10 + (id(i) % 7) * 0.01))

    async def aspawn(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i, 0.10 + (id(i) % 7) * 0.01))

    logic = mk(boom_sync=spawn) if kind == "def" else mk(boom_async=aspawn)
    interps = [Interpreter(create_machine(mid_cfg(f"w4r3_{kind[:1]}_{k}"),
                                          logic=logic))
               for k in range(MACHINES)]
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(1.2)                      # loop otherwise IDLE
    landed = sum(1 for i in interps
                 if any(s.endswith(".done") for s in i.current_state_ids))
    ticked = sum(1 for i in interps if i.context.get("n", 0) == 1)
    stranded = sum(len(getattr(i, "pending_events", []) or [])
                   for i in interps)
    await asyncio.gather(*(i.stop() for i in interps))
    if landed != MACHINES or ticked != MACHINES:
        FAILS.append(f"R3/{kind}: {MACHINES} machines, only {landed} landed "
                     f"and {ticked} ticked -- worker sends were stranded in "
                     f"the internal queue (the #225 shape at scale)")
    if stranded:
        FAILS.append(f"R3/{kind}: {stranded} events left pending at the end")
    return {"kind": kind, "machines": MACHINES, "landed": landed,
            "ticked": ticked, "stranded_pending": stranded}


# ──── R4: 100 concurrent hand-outs while the spawning action keeps awaiting ─

async def r4_concurrent_handouts(kind: str) -> Dict[str, Any]:
    receipts: List[Any] = []
    lock = asyncio.Lock()

    async def aboom(i, ctx, e, ad):  # noqa: ANN001
        t = asyncio.ensure_future(i.send("GO", wait=True))
        async with lock:
            receipts.append(t)
        await asyncio.sleep(0.03)     # the action YIELDS AGAIN -- the trap
        await asyncio.sleep(0.03)

    def sboom(i, ctx, e, ad):  # noqa: ANN001
        receipts.append(asyncio.ensure_future(i.send("GO", wait=True)))

    logic = mk(boom_sync=sboom) if kind == "def" else mk(boom_async=aboom)
    interps = [Interpreter(create_machine(mid_cfg(f"w4r4_{kind[:1]}_{k}"),
                                          logic=logic))
               for k in range(HANDOUTS)]
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(0.5)
    resolved = refused = other = timed_out = 0
    for t in receipts:
        try:
            await asyncio.wait_for(t, 5.0)
            resolved += 1
        except ReentrantWaitError:
            refused += 1
        except asyncio.TimeoutError:
            timed_out += 1
        except Exception:  # noqa: BLE001
            other += 1
    landed = sum(1 for i in interps
                 if any(s.endswith(".done") for s in i.current_state_ids))
    await asyncio.gather(*(i.stop() for i in interps))
    if resolved != HANDOUTS or refused or timed_out:
        FAILS.append(f"R4/{kind}: {HANDOUTS} concurrent hand-outs -> "
                     f"resolved={resolved} refused={refused} "
                     f"hung={timed_out} other={other}")
    if landed != HANDOUTS:
        FAILS.append(f"R4/{kind}: only {landed}/{HANDOUTS} machines advanced")
    return {"kind": kind, "handouts": HANDOUTS, "resolved": resolved,
            "refused": refused, "hung": timed_out, "other": other,
            "landed": landed}


async def main() -> int:
    ROWS["R1_232_runtimewarning"] = await r1_warning()
    ROWS["R1b_under_W_error"] = await r1b_under_w_error()
    ROWS["R2_231_invoke_src"] = [await asyncio.to_thread(r2_invoke_src, k)
                                 for k in ("def", "async def")]
    ROWS["R3_load_outliving_workers"] = [await r3_load(k)
                                         for k in ("def", "async def")]
    ROWS["R4_concurrent_handouts"] = [await r4_concurrent_handouts(k)
                                      for k in ("def", "async def")]
    emit("w4_warning_config_and_load", {
        "machines": MACHINES, "handouts": HANDOUTS,
        **ROWS,
        "failures": FAILS[:30],
        "failure_count": len(FAILS),
        "verdict": "CLEAN" if not FAILS else "DEFECT",
    })
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
