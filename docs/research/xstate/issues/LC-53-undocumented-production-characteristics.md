---
lc: LC-53
title: "Docs: three production-critical characteristics are undocumented — timer starvation, the `SyncInterpreter` threading model, and the global throughput budget"
labels: [documentation, severity/high, area/docs, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-53_undocumented-production-characteristics.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

Three facts determine whether a deployment of this library succeeds or fails in production, and none of them appears anywhere in `docs/_guide/`. (1) **Timer starvation**: `after` deadlines are ordinary coroutines competing with event processing on the shared loop, so a 10 ms timer fires ~2,250 ms late once 500 busy interpreters exist. (2) **The `SyncInterpreter` threading model**: `after` timers run on background `threading.Thread`s that mutate context with no lock, while `send()` executes the macrostep on the calling thread — so a "sync, single-threaded" interpreter is in fact concurrently mutated. (3) **The global throughput budget**: all interpreters share one asyncio loop on one OS thread, so aggregate throughput is roughly constant (~18–21k ev/s) regardless of machine count — adding machines divides capacity rather than adding it.

None of these is necessarily a bug — (1) and (3) follow from a single-threaded asyncio design, and (2) is a deliberate trade-off. But a reader sizing a system from the current documentation will get all three wrong in the same direction: optimistic. The docs should state each plainly, with the measured numbers.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (CPython, GIL enabled)
- OS: Windows 11 (x64)
- Install method: `pip install -e .` into a dedicated venv
- Benchmarks (`bench_b2_scaling.py`, `bench_c_timers.py`, `bench_f_sync_vs_async.py`) run with `tracemalloc` off

## Minimal reproduction

This is a documentation gap, so the repro asserts on the shipped guide sources: for each topic it scans the pages a reader would actually consult and looks for any mention.

```python
"""LC-53 repro: three production-critical characteristics are undocumented.

Measured in this study but absent from `docs/_guide/`:

1. **Timer starvation** -- `after` deadlines are ordinary coroutines on the
   shared event loop; at 500 busy interpreters a 10 ms timer fires ~2,250 ms
   late (`bench_c_timers.py`).
2. **`SyncInterpreter` threading model** -- `after` timers run on background
   `threading.Thread`s that mutate context with no lock, while `send()` runs
   the macrostep on the calling thread (`bench_f`).
3. **Global throughput budget** -- one asyncio loop, one thread: 18,152 ev/s
   aggregate at N=1,000 interpreters, i.e. 18.2 ev/s each (`bench_b2`).

This scans the guide pages a reader would consult for each topic.
Exits 1 if any topic is undocumented.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

# Locate the shipped guide: env override, else walk up from CWD looking for a
# checkout of the library, else assume we are running inside one.
def _find_guide() -> pathlib.Path:
    env = os.environ.get("XSM_REPO")
    if env:
        return pathlib.Path(env) / "docs" / "_guide"
    here = pathlib.Path.cwd().resolve()
    for base in (here, *here.parents):
        cand = base / "docs" / "_guide"
        if (cand / "interpreters.md").is_file():
            return cand
    return here / "docs" / "_guide"


GUIDE = _find_guide()

TOPICS = {
    "timer starvation / delayed-transition accuracy under load": (
        ["delayed-transitions.md", "interpreters.md", "faq.md"],
        [r"starv", r"timer (drift|accuracy|precision)", r"fires? late", r"under load"],
    ),
    "SyncInterpreter threading model (after timers on unlocked background threads)": (
        ["interpreters.md", "delayed-transitions.md"],
        [r"threading\.timer", r"background thread", r"worker thread", r"thread-safe"],
    ),
    "global throughput budget (one loop, one thread, shared ev/s)": (
        ["interpreters.md", "faq.md", "services.md"],
        [r"ev/s", r"events per second", r"throughput", r"global budget"],
    ),
}


def main() -> int:
    if not GUIDE.is_dir():
        print("OBSERVED  guide directory not found:", GUIDE)
        print("HINT      set XSM_REPO=/path/to/xstate-statemachine")
        return 1
    print(f"OBSERVED  scanning docs/_guide/ ({len(list(GUIDE.glob('*.md')))} pages present)")

    undocumented = []
    for topic, (pages, patterns) in TOPICS.items():
        corpus = "\n".join(
            (GUIDE / p).read_text(encoding="utf-8", errors="replace")
            for p in pages
            if (GUIDE / p).is_file()
        ).lower()
        hits = [p for p in patterns if re.search(p, corpus)]
        print(f"OBSERVED  {topic!r}\n            pages={pages} matched={hits or 'NONE'}")
        if not hits:
            undocumented.append(topic)

    print("OBSERVED  undocumented topics:", undocumented)
    print(
        "EXPECTED  all three production characteristics documented, with the "
        "measured numbers (+2,250 ms timer error @500 machines; SyncInterpreter "
        "threading contract; ~18k ev/s global budget)"
    )
    ok = not undocumented
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED  scanning docs/_guide/ (26 pages present)
OBSERVED  'timer starvation / delayed-transition accuracy under load'
            pages=['delayed-transitions.md', 'interpreters.md', 'faq.md'] matched=NONE
OBSERVED  'SyncInterpreter threading model (after timers on unlocked background threads)'
            pages=['interpreters.md', 'delayed-transitions.md'] matched=NONE
OBSERVED  'global throughput budget (one loop, one thread, shared ev/s)'
            pages=['interpreters.md', 'faq.md', 'services.md'] matched=NONE
OBSERVED  undocumented topics: ['timer starvation / delayed-transition accuracy under load', 'SyncInterpreter threading model (after timers on unlocked background threads)', 'global throughput budget (one loop, one thread, shared ev/s)']
EXPECTED  all three production characteristics documented, with the measured numbers (+2,250 ms timer error @500 machines; SyncInterpreter threading contract; ~18k ev/s global budget)
RESULT: FAIL
```

Zero mentions across the pages a reader would consult. What the docs *do* say, and why it misleads:

- `docs/_guide/interpreters.md:737` — a comparison table row reading `| Thread safety | Single-threaded (asyncio) | Single-threaded |`. For `SyncInterpreter` that is not accurate: its `after` timers run on `threading.Thread`s (`sync_interpreter.py:1257-1327`).
- `docs/_guide/interpreters.md:402` — *"The `SyncInterpreter` processes events immediately and synchronously within the `send()` call — there is no background queue."* True for `send()`, but it omits that timers arrive from outside that call.
- `docs/_guide/interpreters.md:396-400` — the async queue section mentions *"Timer-based `after` transitions are scheduled as background tasks"* without saying those tasks share the same loop as event processing and are therefore starvable.
- `docs/_guide/faq.md:467-469` — *"Event processing: microseconds per transition"* and *"No background threads or event loops (unless using `Interpreter` with `after`)"*. The per-transition microsecond figure invites multiplying by machine count, which is exactly the wrong mental model; and the background-threads caveat names the async interpreter while the sync one is the one that actually spawns threads.

## Expected behaviour

There is no XState/SCXML *semantic* rule being violated here — the ask is documentation parity with how the reference implementation describes its own execution model. XState documents the relevant contracts explicitly and this library should do the same:

- <https://stately.ai/docs/delayed-transitions> documents the delayed-transition *lifecycle* as part of the public contract (*"Delayed transition timers are canceled when the state is exited."*) and lists a **simulated clock** under its Testing section, i.e. the reference implementation treats timer scheduling as a substitutable, documented concern rather than an unspecified detail. (That page is itself thin on the clock API — the point being borrowed here is only that timing is treated as a documented contract. See the separate clock-injection request for the missing feature; this issue asks only that the *current* behaviour be described.)
- <https://stately.ai/docs/actors> describes the actor execution model, snapshot emission and subscription semantics as part of the public contract, so users can reason about ordering and observation points.

Neither of those is a promise about throughput or timer accuracy — XState makes no such promise either. The expectation here is weaker and entirely self-directed: that *this* library describe *its* execution model, because its model has consequences (a shared loop, a shared throughput budget, timer threads on the "sync" engine) that a reader cannot infer from the current docs and will otherwise get wrong.

Concretely, the expectation is a *Production characteristics* page stating each of the three behaviours, with the measured numbers and the scaling guidance that follows.

## Root cause analysis

This is a docs gap, so "root cause" is the code the docs fail to describe.

**1. Timer starvation** — `src/xstate_statemachine/base_interpreter.py` schedules `after` deadlines as `asyncio` tasks via the task manager (`src/xstate_statemachine/task_manager.py`), and those tasks are queued on the *same* event loop that drains every interpreter's event queue. `asyncio.sleep(d)` guarantees only "not before `d`"; when the loop is saturated, the callback waits behind all ready work. Measured (`bench_c_timers.py`): idle error +6 to +16 ms (Windows' ~15.6 ms timer granularity is the floor); 100 busy interpreters → ~+500 ms; **500 busy interpreters → +2,250 ms for a 10 ms timer**, and roughly the *same absolute* error for 100 ms and 1 s timers — the signature of loop starvation rather than proportional drift. A separate standalone probe independently measured 5 ms `after` delays drifting ~10.9 ms p50 on an otherwise **idle** loop.

**2. `SyncInterpreter` threading model** — `src/xstate_statemachine/sync_interpreter.py:134-135` declares `_after_threads: Dict[str, threading.Thread]` and `_after_events: Dict[str, threading.Event]`. The `after` timers themselves are created in `_after_timer` at `:1257-1327`: `:1272` creates the per-timer cancellation `threading.Event`, and `:1323-1327` constructs and starts a daemon `threading.Thread` named `after-<key>` whose body waits out the delay and then calls `self.send(event)` from that background thread (`:1305`). (Two further thread spawns exist nearby and are easy to conflate: `:1087` is the delayed-`send`/`raise` built-in action, and `:1185` is the actor runner.) Those timer threads call back into the interpreter and mutate `context` with **no lock**, concurrently with whatever the calling thread is doing inside `send()`. `bench_f_sync_vs_async.py` observes a `SyncInterpreter` advancing state with no event pump at all — i.e. from the timer thread. The user-visible contract "sync means single-threaded" is therefore false whenever `after` is used.

(Minor, worth fixing while in the area: the docstring at `sync_interpreter.py:909-911` says delayed sends are *"backed by `threading.Timer` rather than asyncio tasks, matching how this engine already implements `after`"*. Neither path uses `threading.Timer` — both use a bare `threading.Thread` around a `cancel_event.wait(timeout=…)`.)

**3. Global throughput budget** — every `Interpreter` owns an `asyncio.Queue` and a `_run_event_loop` task, but all such tasks run on one loop on one OS thread under the GIL. Concurrency is interleaving, not parallelism. Measured (`bench_b2_scaling.py`): N=1 → 21,231 ev/s; N=10 → 20,305; N=100 → 20,063; N=500 → 19,323; N=1,000 → **18,152 aggregate, i.e. 18.2 ev/s per machine**. Aggregate throughput is flat-to-decaying in N. The correct scaling unit is the **process**, not the machine.

## Impact

**General users.** All three gaps push a reader's sizing in the optimistic direction, and the failure shows up only under production load:

- A user builds a 250 ms refill loop or a 2 s stop-loss deadline on `after`, validates it on an idle laptop where error is ~10 ms, and ships it. Under load the deadline slips by seconds. Nothing warned them.
- A user picks `SyncInterpreter` *specifically because* the docs say single-threaded, puts a mutable object in `context`, adds an `after` timer, and now has an unsynchronised data race in code they chose for its simplicity. The comparison table at `interpreters.md:737` actively told them this was safe.
- A user benchmarks one machine at ~21k ev/s, needs 200k ev/s, and provisions 10 machines in one process expecting linear scaling. They get ~20k, and discover at integration time that the fix is a re-architecture into multiple processes.

**CandleViewer trading OMS.** Every one of our timing-sensitive behaviours rides on `after`: 250 ms order refills, TWAP order slicing, a 200 ms price-chase re-quote, a **2–3 s stop-loss deadline**, a 10 s heartbeat pong, and a 5 s stall watchdog. A +2,250 ms timer error at our target of ~500 concurrent order machines means a stop-loss that should fire at 2 s fires at 4.25 s — in a fast market that is the difference between a bounded loss and an unbounded one, and the watchdog meant to catch the stall is starved by the same loop. The throughput budget caps all of those behaviours collectively and makes in-process handling of raw market-tick streams impossible, forcing a pre-filter that drops ≥99 % of ticks before they reach a machine. Because none of this is documented, we had to discover all of it by building a benchmark suite — roughly two weeks of work that a paragraph in the guide would have replaced, and we can only trust our numbers on our own hardware since there is no published baseline to compare against.

## Proposed fix

Add `docs/_guide/production-characteristics.md` (linked from `interpreters.md`, `delayed-transitions.md` and `faq.md`), covering the three topics with the measured numbers and explicit guidance. Suggested outline:

**§1 Concurrency is interleaving, not parallelism.** State plainly: all interpreters in a process share one asyncio event loop on one OS thread. Include the measured table (N=1 → 21,231 ev/s … N=1,000 → 18,152 aggregate / 18.2 each), note the numbers are hardware-specific and give the benchmark so readers can reproduce on their own hardware. Guidance: **scale by process, not by machine count**; size against the aggregate figure; keep actions non-blocking (any synchronous CPU or I/O in an action stalls every machine in the process, not just its own).

**§2 `after` timers are best-effort, and starve under load.** State that `after` guarantees "not before", never "at". Give the measured error curve (idle +6–16 ms; 100 busy → ~+500 ms; 500 busy → +2,250 ms) and note the error is roughly constant in absolute terms across delay sizes, so short deadlines degrade worst in relative terms. Note the OS floor (~15.6 ms on Windows). Guidance: do not use `after` for deadlines where lateness is a correctness problem — own those in an external monotonic scheduler and `send()` into the machine; cross-reference the clock-injection request for testability.

**§3 The `SyncInterpreter` threading contract.** Correct `interpreters.md:737`: `SyncInterpreter` is single-threaded **for event processing only**. If the machine uses `after`, timers run on background threads that re-enter the interpreter and mutate `context` without a lock. Say explicitly what is and is not safe: safe to `send()` from the owning thread; **not** safe to assume `context` is unobserved between `send()` calls; not safe to share a `SyncInterpreter` across threads. Recommend either avoiding `after` on `SyncInterpreter` or guarding context access.

Also fix the two directly misleading statements in place:

- `docs/_guide/interpreters.md:737` — change the `SyncInterpreter` thread-safety cell from `Single-threaded` to `Single-threaded event processing; `after` timers run on background threads (see Production characteristics)`.
- `docs/_guide/faq.md:467-469` — qualify *"microseconds per transition"* with "per transition on an unloaded loop; aggregate throughput across all machines in a process is a fixed budget — see Production characteristics", and correct the background-threads bullet, which currently attributes threads to `Interpreter` when it is `SyncInterpreter` that spawns them.

This is documentation only — no API change, no backwards-compatibility concern, no migration.

## Acceptance criteria

- [ ] `docs/_guide/production-characteristics.md` exists with the three sections above, each carrying the measured numbers and the hardware/Python version they were measured on.
- [ ] The page is linked from the nav and from `interpreters.md`, `delayed-transitions.md` and `faq.md`.
- [ ] `delayed-transitions.md` states that `after` is "not before", not "at", and links to §2.
- [ ] `interpreters.md:737` thread-safety row corrected for `SyncInterpreter`.
- [ ] `faq.md:467-469` corrected: per-transition cost qualified, background-threads bullet attributed to the right interpreter.
- [ ] `repro/LC-53_undocumented-production-characteristics.py` exits 0.
- [ ] Tests added:
  - `tests/test_docs_site.py::test_production_characteristics_page_exists`
  - `tests/test_docs_site.py::test_production_characteristics_covers_all_three_topics` (keyword assertions mirroring the repro)
  - `tests/test_docs_site.py::test_sync_interpreter_thread_safety_row_mentions_timer_threads`
- [ ] A reproducible benchmark script ships under `benchmarks/` (or is linked) so readers can measure the three numbers on their own hardware.

## Related

Companion findings from the same review (filed separately):

- `after` timers degrade catastrophically under event-loop load — the behaviour behind §2; this issue asks for documentation, that one for a fix.
- `SyncInterpreter` unlocked cross-thread context mutation — the bug behind §3.
- Throughput is a fixed global budget — the measurement behind §1, filed as docs-only for the same reason.
- No clock injection / virtual time — the testability half of the timer story, referenced from §2.
- Docs disagree on whether `status` can be `'error'`; stale comparison table and untested docs build — grouped docs work, and a docs-build CI job would also protect the new page.
- Unbounded event queue with no backpressure — a downstream consequence of §1.

## Verification

Independently verified on **2026-09-15**.

- Repro `repro/LC-53_undocumented-production-characteristics.py` run in a fresh process against the local clone at commit `42612cf`: **exit code 1**, output matches the Observed section verbatim — all three topics match zero keywords across the guide pages a reader would consult.
- Python 3.13.7 (CPython), Windows 11 x64, `pip install -e .` into `.venv-cv`.
- The repro was **made portable** during verification: it previously hardcoded an absolute path to the author's clone, so it would have failed for anyone else with "guide directory not found". It now resolves the guide via `$XSM_REPO`, else by walking up from the CWD for a `docs/_guide/interpreters.md`. Confirmed exit 1 both ways (with `XSM_REPO` set, and run from inside the library checkout). A missing `import re` introduced by that edit was also fixed.
- Docs citations checked against the shipped guide: `interpreters.md:737` is the `| Thread safety | Single-threaded (asyncio) | Single-threaded |` row; `:400` is the "scheduled as background tasks" bullet; `:402` is the "no background queue" sentence; `faq.md:467` and `:469` are the per-transition and background-threads bullets. All verbatim.
- Code citations **corrected**: the `after` timer threads are created in `_after_timer` at `sync_interpreter.py:1257-1327` (cancel `Event` at `:1272`, `threading.Thread` constructed and started at `:1323-1327`, `self.send(event)` called from the timer thread at `:1305`). The original draft cited `:1047`/`:1087`/`:1185`, which are the delayed-`send` built-in action and the actor runner — different thread spawns. Also noted: the docstring at `:909-911` claims `threading.Timer`, but neither path uses it.
- The XState claim was **corrected**: the draft quoted the delayed-transitions page as saying *"you can provide a custom clock"*. That wording does not appear — the page's Testing section is a stub reading only "Simulated clock". The Expected section was rewritten around what the page actually says (the timer-cancellation lifecycle contract) and now states plainly that XState makes no throughput or timer-accuracy promise either, so the ask is self-directed documentation of *this* library's model rather than parity.
- Not a duplicate: the only issue on `basiltt/xstate-statemachine` is #17 (closed, unrelated).
