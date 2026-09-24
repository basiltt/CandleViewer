---
lc: LC-45
title: "Perf: hot path rebuilds transition-candidate lists per event and logs at INFO on every event, guard and state entry/exit"
labels: [performance, severity/medium, area/perf]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-45_hot-path-alloc-and-info-logging.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

Two costs sit on the per-event path shared by both engines. First, nothing about transition selection is precomputed: `_select_transitions` rebuilds a `leaves` list, sorts it, builds a per-leaf `eligible` list and a fresh `guard_cache` dict on **every event**, and `_matching_descriptors` rescans every key of every `on` map on every ancestor walk because there is no descriptor index. On a 3-state OMS machine those helpers account for ~72% of per-event `tottime` under a profiler.

Second, the hot path logs at **INFO**, not DEBUG: guard evaluation logs per guard, and the sync engine logs per event and per state entry and exit. These are unconditional `logger.info(...)` calls with argument tuples. Attaching any INFO handler — which an application doing `logging.basicConfig(level=logging.INFO)` does by default to the root logger — makes the library **3–4× slower** (3.42× measured here, 4.26× in an earlier run), with the handler writing to an in-memory `StringIO` so I/O cost is excluded.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (64-bit, CPython)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-45 repro: the event hot path allocates per event and logs at INFO on
every transition, guard evaluation and state entry/exit.

Two measurable symptoms, both in the shared engine code:

  * `base_interpreter._select_transitions` (`:2562-2599`) rebuilds a `leaves`
    list, sorts it, builds a per-leaf `eligible` list and a fresh `guard_cache`
    dict for EVERY event; `_matching_descriptors` (`:2408-2418`) rescans every
    key of every `on` map on every ancestor walk with no precompiled
    descriptor index; `_is_descendant` (`:2751-2771`) does
    `node.id.startswith(f"{ancestor.id}.")` -- an f-string allocation plus
    O(len(id)) string compare -- inside loops over the active configuration,
    even though `StateNode.depth` is already cached as an int.

  * Guard evaluation logs `logger.info` per guard (`:2927-2931`); the sync
    engine logs `logger.info` per event (`sync_interpreter.py:365`) and per
    state entry/exit (`:643`, `:747`). Those are unconditional calls with
    argument tuples; attaching any INFO handler makes them cost real time.

This script measures (1) allocations per event with `tracemalloc` and
(2) throughput with the `xstate_statemachine` logger disabled vs. enabled at
INFO with a null-ish handler.

Exit code 1 if per-event allocation is non-trivial or INFO logging measurably
slows the hot path.
"""

from __future__ import annotations

import cProfile
import io
import logging
import pstats
import sys
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CONFIG = {
    "id": "oms",
    "initial": "idle",
    "context": {"n": 0, "qty": 0.0},
    "states": {
        "idle": {"on": {"SUBMIT": {"target": "open", "actions": ["tick"]}}},
        "open": {
            "on": {
                "FILL": [
                    {
                        "target": "open",
                        "cond": "is_partial",
                        "actions": ["tick"],
                    },
                    {"target": "closed", "actions": ["tick"]},
                ],
                "AMEND": {"target": "open", "actions": ["tick"]},
            }
        },
        "closed": {"type": "final"},
    },
}


def tick(interpreter, context, event, action_def) -> None:
    context["n"] += 1


def is_partial(context, event) -> bool:
    return True


def build():
    return SyncInterpreter(
        create_machine(
            CONFIG,
            logic=MachineLogic(
                actions={"tick": tick}, guards={"is_partial": is_partial}
            ),
        )
    ).start()


def events(n):
    return [{"type": "SUBMIT"}] + [
        {"type": "FILL" if k % 2 else "AMEND", "qty": 1.0} for k in range(n - 1)
    ]


N = 5_000
EV = events(N)

logging.disable(logging.CRITICAL)

# 1️⃣ Hot-path work per event: how many times the per-event helpers run.
#    (Allocation here is churn, not retention: the temporaries are freed each
#    event, so a tracemalloc high-water mark stays flat. What costs time is
#    that they are rebuilt from scratch every single event.)
it = build()
prof = cProfile.Profile()
prof.enable()
for e in EV:
    it.send(e)
prof.disable()
counts = {}
stats_obj = pstats.Stats(prof)
for (fname, line, func), (cc, nc, tt, ct, _cal) in stats_obj.stats.items():
    if "xstate_statemachine" in fname and func in (
        "_select_transitions",
        "_collect_eligible_transitions",
        "_matching_descriptors",
        "_is_descendant",
        "_evaluate_guard",
    ):
        counts[func] = (nc, tt)
print(f"OBSERVED per-event hot-path helper calls over {N} events:")
for func, (nc, tt) in sorted(counts.items(), key=lambda kv: -kv[1][0]):
    print(
        f"  {func:<32} calls={nc:>7} ({nc / N:.1f}/event)  "
        f"tottime={tt * 1e6 / N:.1f} us/event"
    )

# 2️⃣ INFO logging cost on the hot path.
def run(n):
    it = build()
    evs = EV[:n]
    t0 = time.perf_counter()
    for e in evs:
        it.send(e)
    return (time.perf_counter() - t0) / n * 1e6


run(500)
us_quiet = run(N)

logging.disable(logging.NOTSET)
lg = logging.getLogger("xstate_statemachine")
lg.setLevel(logging.INFO)
lg.addHandler(logging.StreamHandler(io.StringIO()))
run(500)
us_info = run(N)
logging.disable(logging.CRITICAL)

print(f"OBSERVED logging disabled : {us_quiet:.1f} us/event")
print(f"OBSERVED logger at INFO   : {us_info:.1f} us/event")
print(f"OBSERVED slowdown         : {us_info / us_quiet:.2f}x")
print(
    "EXPECTED a precompiled descriptor/transition index instead of rebuilding "
    "candidate lists per event, and no measurable cost from a library whose "
    "hot path logs at DEBUG"
)

ok = us_info / us_quiet < 1.10
sys.exit(0 if ok else 1)
```

## Observed behaviour

```
OBSERVED per-event hot-path helper calls over 5000 events:
  _select_transitions              calls=  10000 (2.0/event)  tottime=8.3 us/event
  _collect_eligible_transitions    calls=  10000 (2.0/event)  tottime=6.9 us/event
  _matching_descriptors            calls=  10000 (2.0/event)  tottime=2.6 us/event
  _is_descendant                   calls=      2 (0.0/event)  tottime=0.0 us/event
OBSERVED logging disabled : 24.8 us/event
OBSERVED logger at INFO   : 84.9 us/event
OBSERVED slowdown         : 3.42x
EXPECTED a precompiled descriptor/transition index instead of rebuilding candidate lists per event, and no measurable cost from a library whose hot path logs at DEBUG
EXIT=1
```

Two notes on how to read this, so the claim is not overstated:

- **Allocation is churn, not retention.** An earlier version of this script measured a `tracemalloc` high-water mark and found only 3 KiB over 5000 events — because the temporaries are freed each event. The cost is not memory growth; it is that the same lists, sorts and dicts are constructed from scratch 5000 times. The profile above measures that directly: ~17.8 µs/event of `tottime` in `_select_transitions` + `_collect_eligible_transitions` + `_matching_descriptors`, against a 24.8 µs/event total. Transition selection *is* the hot path. (These `tottime` figures are gathered under `cProfile`, which inflates per-call cost; treat the *share* of total as the signal, not the absolute microseconds.)
- **`_is_descendant` is not hot on this machine** (2 calls total). The register row cited it from a static read of `base_interpreter.py:2751-2771`; on a flat 3-state machine the loops that call it are not entered. It remains a valid micro-cleanup (§ Proposed fix item 3) but it is not where the time goes, and the register row should be narrowed accordingly.

The INFO figure is the headline: 24.8 → 84.9 µs/event, a **3.4×** slowdown, with the handler writing to `io.StringIO` so no file or console I/O is included. Formatting and `LogRecord` construction alone account for all of it. The exact ratio moves between runs (3.42× and 4.26× were both observed on the same hardware); the magnitude is stable at 3–4×.

## Expected behaviour

There is no XState/SCXML *semantic* rule at stake here — this is a library-engineering expectation, so the citation is to the ecosystem norm rather than a spec clause. Two norms apply:

1. **A library's per-operation hot path logs at DEBUG, not INFO.** Python's own logging HOWTO (https://docs.python.org/3/howto/logging.html) defines INFO as "Confirmation that things are working as expected" and DEBUG as "Detailed information, typically of interest only when diagnosing problems". Per-event, per-guard and per-state-entry traces are diagnostic detail by that definition. The library already gets the *other* half of this right — `logger.py:63-69` installs a `NullHandler` on the `xstate_statemachine` namespace, which is exactly the recommended practice — so the level choice is the only thing out of line.
2. **XState's own interpreter precompiles transition candidates.** `StateNode.transitions` is built once at machine-creation time as a `Map<string, TransitionDefinition[]>` keyed by event descriptor, and `getCandidates(eventName)` is a map lookup (see https://stately.ai/docs/transitions). The per-event work is walking the configuration, not re-deriving the candidate set.

## Root cause analysis

**Transition selection rebuilt per event** — `src/xstate_statemachine/base_interpreter.py:2562-2599`:

```python
leaves = [
    s for s in self._active_state_nodes
    if s.is_atomic or s.is_final or not s.states
]
if not leaves:
    leaves = list(self._active_state_nodes)
selected: List[TransitionDefinition] = []
seen: Set[int] = set()
guard_cache: Dict[int, bool] = {}
for leaf in sorted(leaves, key=lambda s: (-s.depth, s.id)):
    eligible = self._collect_eligible_transitions(leaf, event, guard_cache)
    ...
selected.sort(key=lambda t: -t.source.depth)
```

Per event: one list comprehension over the configuration, one `sorted()` with a tuple key and a Python-level lambda, one fresh `dict`, one fresh `set`, one `eligible` list per leaf, one `max()` with a lambda per leaf, and a final `sort()`. The `guard_cache` in particular is *created and thrown away* every event — it memoises only within a single pass, so for a single-leaf configuration (the common case) it never serves a hit at all and is pure overhead.

**No descriptor index** — `base_interpreter.py:2408-2418`:

```python
partials: List[str] = []
for key in on_map:
    if key == "*" or not key.endswith(".*"):
        continue
    prefix = key[:-2]
    if event_type == prefix or event_type.startswith(prefix + "."):
        partials.append(key)
partials.sort(key=len, reverse=True)
```

Every key of every `on` map is iterated and `.endswith(".*")`-tested on every ancestor walk, on every event — to find wildcard descriptors that, for the overwhelming majority of machines, do not exist. A machine that uses no `.*` descriptor at all still pays the full scan. The set of `.*` keys per `on` map is fixed at machine-construction time and could be computed once.

**INFO on the hot path** — four sites:

- `base_interpreter.py:2927-2931` — `logger.info("🛡️  Evaluating guard '%s': %s", guard.type, ...)`, once per guard evaluation. Note the third argument is `"✅ Passed" if result else "❌ Failed"`, so a conditional expression is evaluated eagerly at the call site regardless of level.
- `sync_interpreter.py:365` — `logger.info("⚙️ Processing event: '%s'", current_event.type)`, once per event.
- `sync_interpreter.py:643` — `logger.info("➡️ Entering state: '%s'", state.id)`, once per state entered.
- `sync_interpreter.py:747` — `logger.info("⬅️ Exiting state: '%s'", state.id)`, once per state exited.

Even when no handler is attached, each call pays `Logger.info` → `isEnabledFor` → cache lookup plus the argument tuple build. When a handler *is* attached — the measured case — each pays `LogRecord.__init__`, `%`-formatting and handler dispatch. On a self-transition in a 3-state machine that is 1 event + 1 guard + 1 exit + 1 entry = 4 INFO records per event.

## Impact

**General users.** The library is presented as suitable for application control flow, and the logging is a good-citizen `NullHandler` setup — so users reasonably assume `logging.basicConfig(level=logging.INFO)` in their app is safe. It is not: it quadruples state-machine cost and floods the log with per-event noise that no operator wants at INFO. The workaround (`logging.getLogger("xstate_statemachine").setLevel(logging.WARNING)`) is undiscoverable until someone profiles.

**CandleViewer (trading OMS).** CandleViewer is the downstream application this research was conducted for: an order-management system that runs a family of order-lifecycle state machines on this library, sharing a throughput budget of roughly 20k events/s across market-data ingestion and order handling. At ~25 µs/event quiet we have ~40k ev/s of headroom — workable. At ~85 µs/event with application-level INFO logging on, that collapses to ~12k ev/s, *under* budget: during a burst of market-data updates the order machines fall behind, and because `SyncInterpreter`'s queue is unbounded (reported separately as LC-41) the backlog grows silently rather than erroring. The failure mode is the worst possible one for an OMS — an order machine still sitting in `submitting` while the exchange has already filled it, with the `FILLED` event queued behind a few thousand price ticks. The trigger is nothing more exotic than a developer turning on INFO logging to debug something unrelated.

## Proposed fix

**1. Demote the four hot-path INFO calls to DEBUG.** `base_interpreter.py:2927`, `sync_interpreter.py:365`, `:643`, `:747`. Keep INFO for lifecycle events that happen O(1) times per interpreter — `start()`, `stop()`, service invocation start/completion, `_fail()`. Backwards compatibility: this is observable behaviour for anyone who parses the library's INFO output, so note it in the CHANGELOG under "Changed"; no API surface moves. While touching `:2927`, also make the `"✅ Passed" if result else "❌ Failed"` argument lazy (pass `result` and let the format string handle it, or guard with `if logger.isEnabledFor(logging.DEBUG)`).

**2. Precompile a per-`StateNode` descriptor index at machine-construction time.** In `models.py`, alongside the existing `on` map, build once:

```python
self._exact: Dict[str, List[TransitionDefinition]]   # "FILL" -> [...]
self._partials: List[Tuple[str, str]]                # ("a.b.*", "a.b") sorted by len desc
self._wildcard: List[TransitionDefinition]           # from "*"
```

`_matching_descriptors` then becomes a dict lookup plus a scan of `_partials` (empty for most machines, so the loop body never executes) plus the `_wildcard` fallback — with the existing `done.`/`error.`/`after.`/`xstate.` exclusion rule preserved verbatim, since that guard is load-bearing (it is what stops a bare `"*"` from swallowing timers and invoke results). No public API changes; the index is private and derived.

**3. Restructure `_select_transitions` to avoid per-event construction.**
- Replace the `leaves` list comprehension + `sorted()` with iteration over a configuration set the interpreter maintains in depth-sorted order, or at minimum sort by the cached int `depth` only (dropping the `s.id` string tiebreak to a secondary pass, since it only matters for ties).
- Hoist `guard_cache` to an interpreter attribute cleared per event (`self._guard_cache.clear()`) rather than allocated, and skip it entirely when `len(leaves) == 1`, where it can never hit.
- Reuse a single `selected` list and `seen` set as interpreter attributes, cleared per event.
- In `_is_descendant` (`base_interpreter.py:2751-2771`), replace `node.id.startswith(f"{ancestor.id}.")` — which allocates an f-string per call — with a `depth`-guarded walk: `if node.depth < ancestor.depth: return False`, then walk `node.parent` up `node.depth - ancestor.depth` times and compare identity. This is a pure micro-optimisation, not a correctness fix. An earlier draft claimed the string-prefix test could produce a false positive for a sibling whose key begins with the ancestor's key plus a dot; that claim was tested during verification and **does not hold** — `models.py` rejects such configs at construction time with `InvalidConfigError: State key 'a.b' in 'r' is ambiguous: its first segment 'a' is also a sibling state…`, and sibling pairs like `ord`/`ord2` are correctly distinguished because the test requires a trailing dot. Priority is low: the profile shows the function is not hot on flat machines.

Item 1 is a one-line-per-site change delivering the 4.3×; items 2 and 3 are the structural work. They can ship separately.

## Acceptance criteria

- [ ] `tests/test_logging_levels.py::test_hot_path_does_not_log_at_info` — drive 100 events through a `SyncInterpreter` with a capturing handler at INFO on `xstate_statemachine`; assert zero records for event processing, guard evaluation and state entry/exit.
- [ ] `tests/test_logging_levels.py::test_lifecycle_still_logs_at_info` — `start()`/`stop()` still produce INFO records.
- [ ] `tests/test_transition_index.py::test_descriptor_index_matches_linear_scan` — property-style test over machines with exact, `a.b.*`, and `*` descriptors: the indexed `_matching_descriptors` returns the identical ordered list as the current implementation.
- [ ] `tests/test_transition_index.py::test_wildcard_does_not_swallow_internal_events` — the `done.`/`error.`/`after.`/`xstate.` exclusion survives the rewrite.
- [ ] `tests/test_base_interpreter.py::test_is_descendant_depth_walk_matches_string_prefix` — the depth-walk rewrite agrees with the current string-prefix implementation across a machine with nested and sibling states (including a `ord`/`ord2` pair), confirming no behaviour change.
- [ ] `tests/test_perf_hot_path.py::test_info_handler_does_not_slow_hot_path` — ratio of per-event cost with an INFO `StringIO` handler to without is < 1.10 (marked `slow`).
- [ ] `repro/LC-45_hot-path-alloc-and-info-logging.py` exits 0.

## Related

- **LC-39** — throughput global budget; this is the largest single lever on it.
- **LC-41** — unbounded queue with no backpressure; the mechanism by which the slowdown here turns into silent unbounded lag rather than an error.
- **LC-44** — the pure API pays all of this per event *plus* its own per-call interpreter construction.
- **LC-38** — `SyncInterpreter` timer threads (relevant to the OMS scenario above).

## Verification

- Date: 2026-09-15
- Python: 3.13.7 (CPython, 64-bit, Windows 11 x64)
- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Repro exit code: **1** (fails today), reproduced in a fresh process
- Corrections applied during verification:
  - Observed block refreshed with the measured run (24.8 → 84.9 µs/event, 3.42×). The draft's 4.26× was not reproduced exactly; both figures are real and the ratio is now reported as a stable 3–4× range rather than a single number.
  - Added a caveat that the per-helper `tottime` figures are gathered under `cProfile` and are therefore inflated in absolute terms — the meaningful signal is their share of the total, which is ~72%.
  - **Retracted the `_is_descendant` "genuine latent bug" claim.** Tested directly: the library rejects the ambiguous-dotted-key configs that would be required to trigger a false positive (`InvalidConfigError` raised from `models.py:705` at construction time), and sibling pairs such as `ord`/`ord2` already evaluate correctly because the prefix test requires a trailing dot. Downgraded to a pure micro-optimisation, and the corresponding acceptance criterion was rewritten from "proves the fix" to "confirms no behaviour change".
  - All cited line numbers re-checked against the source and confirmed accurate: `base_interpreter.py:2408-2418` (descriptor scan), `:2562-2599` (`_select_transitions`), `:2927-2931` (guard INFO log), `:2751-2771` (`_is_descendant`), `sync_interpreter.py:365`, `:643`, `:747` (INFO logs), and `logger.py:63-69` (`NullHandler`).
  - Removed the `candleviewer` label and the trailing internal-doc references (`01-library-core.md`, `04-performance-concurrency.md`, `12-challenge-register.md`); rewrote the CandleViewer impact paragraph to explain itself without the internal "B1–B9" shorthand, and rescaled its numbers to the measured figures.
  - Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns exactly one issue (#17, camelCase/snake_case logic auto-discovery, closed). Not a duplicate.
