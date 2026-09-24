# FUZZ — fuzzing & property-based battle test of `xstate-statemachine`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`5e07ba8842345a73ef8f830f0281de16370a7c74`** (the merge of PR #101,
`fix/round3-ride-alongs`). `CHANGELOG.md` `[Unreleased] — targeting 0.8.1`.
**`__version__` still reports `0.8.0`; this build is identified by commit.**

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **hypothesis:** 6.168.0.
**Interpreter for every command below:**
`_ref/xstate-statemachine/.venv-main/Scripts/python`, with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ (fuzzing & property tests). Scripts live under
`docs/research/xstate/battle-5e07ba8/fuzz/`. No library source was modified.
No `git` command was run in the adopting project's repository. GitHub was
read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced.

---

## 0. Bottom line

**Nine defects, all reproducing on `5e07ba8`, one of them a Blocker.**

- **D-fuzz-1 (Blocker).** A statechart with a parallel region whose `always`
  re-enters a sibling region's invoking state makes **`SyncInterpreter.start()`
  never return**. It is not slow — it is non-terminating: the inbox grows
  without bound (22 426 events in 6 s, ~150 000 and 97 MB RSS in 20 s, still
  climbing), the caller's thread is blocked with no timeout and no way to
  interrupt, and `maxIterations` does not bound it at its default of 1 000.
  The config is accepted by `create_machine()` without a warning. **8.9 % of
  the 6 666 well-formed configs F1 generated hit this.** For an
  order-management system this is a process-kill at start-up on a
  configuration that passes every build-time check the library has.
- **D-fuzz-9 (High) is the same family's other outcome.** When the budget
  *does* trip, the machine is left with an **active leaf whose ancestors are
  inactive** — a configuration that is not a tree — while reporting
  `status="running"`, `last_transition_ok=True`, `last_error=None`. Saving
  it and restoring it yields a *different* configuration, silently. There is
  no value of `maxIterations` that makes these configs behave: too high and
  the process hangs, low enough to trip and the state is corrupt.
- **Three untyped-error classes across the three public entry points.**
  `send()` (D-fuzz-4, D-fuzz-5), `from_snapshot()` (D-fuzz-6) and
  `create_machine()` (D-fuzz-8) all raise bare `TypeError` /
  `AttributeError` / `KeyError` / `RecursionError` on hostile input. The
  library documents `except XStateMachineError` as the way to catch its
  failures; every one of these escapes that handler. **1 750 of F3's 20 000
  snapshot cases** ended in an untyped Python error from library internals.
  `from_snapshot` is the worst of the three because a snapshot comes back
  from Redis/disk/a queue and is untrusted by construction — which is the
  stated premise of #45.
- **`from_snapshot()` loads garbage silently (D-fuzz-7, High).** A blob whose
  `configuration` is empty, or whose `status` is `5` / `None` /
  `["running"]` / `{"s": 1}`, or whose `context` is the integer `42`,
  restores with **no error at all** and yields a "running" machine that
  processes events against an empty configuration — **581 illegal
  configurations and 77 undocumented `status` values** across F3. This is
  the direct negation of the brief's requirement that `from_snapshot`
  "never load garbage silently".
- **An `always` targeting the machine root empties the configuration
  (D-fuzz-2, High)** on **both** engines, leaving `status == "running"`,
  `value == {}` and a snapshot with `state_ids: []` — a machine that is
  alive, accepts events, and can never transition again. **14.8 % of F1's
  valid configs** started into this state.
- **Sync/async parity gap on a non-running machine (D-fuzz-3, Medium).**
  `send()` to a stopped or done `SyncInterpreter` returns normally and fires
  **no hook at all**; the async engine fires
  `on_event_dropped(reason="not_running")`. The event is lost and the sync
  caller has no way to learn it.
- **What held up.** Build-time target validation is sound: every one of the
  1 197 dangling-target mutations, 801 unguarded-`always` self-loops and 725
  duplicate-custom-id configs was rejected with a typed error, 100 % of the
  time. A clean snapshot round-tripped stably in 18 520 of 18 568 cases.
  `strict` rejected every engine-shaped forgery we sent. §4 and §6 say
  exactly what else was covered and what was not.

---

## 1. Method

### 1.1 Shape of the three fuzzers

| Fuzzer | File | What it generates | Oracle |
|---|---|---|---|
| **F1** machine definitions | `f1_machine_config.py` | statecharts (nesting ≤ 4, parallel, history, `always`, `after`, `invoke`, guards, all policy combinations) — valid by construction, plus 9 mutation families that corrupt them | `create_machine` raises only `ALLOWED_BUILD_ERRORS`; a valid config builds AND starts; an invalid target is never accepted |
| **F2** event sequences | `f2_events.py` | random event sequences over a hostile alphabet (known, unknown, engine-shaped, malformed, huge, non-`str`, `None`, unicode, raw objects) under `strict` ∈ {T,F} and every `onUnhandled` / `actionErrorPolicy` / `guardErrorPolicy` | B1 no unexpected exception type; B2 configuration stays legal; B3 no accepted event without a hook; B4/B5 `status` and `last_error` stay coherent |
| **F3** snapshots | `f3_snapshot.py` | a real snapshot taken from a running machine, then corrupted 18 ways (4 text-level: char flip/delete/truncate/junk-insert; 14 structural: field drops, type swaps, version bump, hash & id tampering, junk into `configuration`/`state_ids`/`pending_events`/`deferred`/`history`/`actors`/`context`) | C1 `from_snapshot` raises only `ALLOWED_RESTORE_ERRORS`; C2 never loads garbage silently; C3 a clean snapshot round-trips stably |

Generation is `hypothesis` strategies assembled by pure functions
(`gen_config.py`), so hypothesis's shrinker reduces nesting depth, child
count and mutation count automatically; the hand shrinkers below took over
where the oracle was a hang rather than an exception.

### 1.2 The oracles, stated precisely

The contract sets come from the library's own docstrings and CHANGELOG, not
from our preference:

```python
ALLOWED_BUILD_ERRORS   = (InvalidConfigError, ImplementationMissingError,
                          StateNotFoundError, NotSupportedError)
ALLOWED_SEND_ERRORS    = (UnknownEventError, InvalidEventPayloadError,
                          QueueOverflowError, InterpreterStoppedError,
                          UnhandledEventError, TransitionFailedError,
                          WrongThreadError, StateNotFoundError,
                          RunawayChainError)
ALLOWED_RESTORE_ERRORS = (InvalidConfigError, SnapshotVersionError,
                          SnapshotDriftError, StateNotFoundError,
                          RestoredError, NotSupportedError,
                          ImplementationMissingError)
```

Every one of these is an `XStateMachineError` subclass, which is what
`from_snapshot`'s own docstring tells callers to catch ("Leaking
`json.JSONDecodeError` meant `except XStateMachineError` … silently missed
it", `base_interpreter.py:1163`). Anything outside the set is a defect by
the library's own stated standard.

The **configuration legality** predicate (B2/C2) is:

* on a `running` machine the active set is non-empty;
* every active node's parent is active;
* a `compound` node has **exactly one** active child;
* a `parallel` node has **all** its regions active;
* at least one active node is an atomic leaf.

### 1.3 The anti-hang instrument (`spin_oracle.py`)

D-fuzz-1 surfaced on the 29th generated config and wedged the first run
outright: `start()` does not return, and the inbox grows until memory does.
A wall-clock timeout is unusable as a fuzzing oracle (6 s × 20 000 cases),
so the harness installs a **budgeted `_select_transitions`**: a counter in
our own process that raises a sentinel after `N` selections. A healthy
machine settles in 1–3 selections; a defective one is unbounded, so the
budget is decisive at 20 000 and costs microseconds.

This is a monkey-patch **in the fuzzer's process only**; it never touches
library source on disk. It is what makes both the 20 000-case runs and the
delta-debugging shrinker (`shrink_spin.py`, seconds instead of hours)
tractable. It is also, separately, evidence for D-fuzz-1: the instrument
exists because the defect made an ordinary timeout oracle unaffordable.

### 1.4 Exact commands

```bash
cd docs/research/xstate/battle-5e07ba8/fuzz
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# the three fuzzers, 20 000 generated cases each
$PY -u f1_machine_config.py --cases 20000   # -> out/f1_machine_config.json
$PY -u f2_events.py         --cases 20000   # -> out/f2_events.json
$PY -u f3_snapshot.py       --cases 20000   # -> out/f3_snapshot.json

# minimisation of the non-termination defect
$PY -u shrink_spin.py hang30.json           # -> min_spin.json
$PY -u shrink_hang.py hang30.json --budget 6 # subprocess/timeout variant

# every filed defect, as a standalone hand-checked repro
$PY -u repros.py                            # exit code = defects reproducing
```

`repros.py` is the artefact to re-run against any future build: it imports
nothing from the fuzzers and prints OBSERVED / EXPECTED / verdict per
defect.

---

## 2. Results

### 2.1 Coverage actually achieved

Full counters are in `out/*.json`. The headline numbers:

**F1 — machine definitions, 20 000 cases** (6 666 valid, 13 334 mutated):

| outcome | count | reading |
|---|---|---|
| valid config built | 6 666 / 6 666 | **100 %** — the generator never produced a config the library wrongly rejected |
| …and started cleanly | 6 076 | |
| …**started but never settled** | **590 (8.9 % of valid configs)** | D-fuzz-1 |
| …**started into an empty configuration** | **988 (14.8 %)** | D-fuzz-2 |
| `dangle_target` mutation → typed reject | 1 197 / 1 197 | **100 %** — #29/#30 target validation is sound |
| `cycle_always` → typed reject | 801 / 801 | **100 %** |
| `dup_custom_id` → typed reject | 725 / 725 | **100 %** |
| `self_parent` (aliased cycle) → **`RecursionError`** | **613** | D-fuzz-8 |
| mutated configs that started and never settled | 314 | D-fuzz-1, via corrupted configs |

Two counters in the raw JSON are **harness artefacts, not findings**, and
are excluded above: the 35 `dangle_target.accepted` cases carry
`desc: "noop"` — the generated config contained no `target` key for the
mutation to corrupt, so nothing was mutated. The 653
`unknown_logic.accepted` cases are the behaviour discussed in §4 (accepted
at build, typed `ImplementationMissingError` at run time), deliberately not
filed.

**F3 — snapshots, 20 000 cases.** 65 distinct defect classes, aggregated by
outcome:

| outcome | count | reading |
|---|---|---|
| clean round-trip stable | 18 520 | C3 holds on the overwhelming majority |
| corruption → typed reject | 10 317 | the envelope works |
| corruption → **untyped Python error** | **1 750** | D-fuzz-6 |
| corruption → accepted | 6 453 | |
| …of which **restored an illegal configuration** | **581** | D-fuzz-7 |
| …of which **restored a non-documented `status`** | **77** | D-fuzz-7 (types seen: `str`, `int`, `float`, `list`, `dict`, `NoneType`) |
| **clean round-trip NOT stable — `configuration`** | **40** | **D-fuzz-9** (new) |
| clean round-trip not stable — `pending_events` | 8 | `ErrorEvent.error` becomes `RestoredError`; documented in `events.py:288-290`, not a defect |

The 1 750 untyped restore errors land in six distinct library sites:
`events.py:314/315/317` (`restore_event`), `base_interpreter.py:1195/1202/
1210/1233/1236/1248/1251/1260/1262/1285` (`from_snapshot`),
`models.py:1600` (`get_state_by_id`), and `persistence.py:138`
(`check_version` — `int(snapshot.get("version"))` on a non-numeric value
raises `TypeError`/`ValueError` *inside the version guard itself*).

**F2 — event sequences, 20 000 cases** (46 defect classes; ~62 000 individual
sends, 80 % sync / 20 % async):

| outcome | count | reading |
|---|---|---|
| `send()` accepted | 42 787 | |
| `send()` → typed error (`UnknownEventError`, schema, …) | 6 073 | the guardrails fire |
| `send()` → **untyped Python error** | **1 988** | D-fuzz-4, D-fuzz-5 |
| **accepted but NO hook fired** | **11 019** | D-fuzz-3 |
| **configuration illegal after the send** | **6 296** | D-fuzz-2 (5 899 at the root) + D-fuzz-9 (see below) |
| `send()` never settled | 129 | D-fuzz-1, reached through event traffic |
| `start()` never settled (setup) | 1 253 | D-fuzz-1 |

The illegal-configuration bucket decomposes usefully. 5 899 are "compound
`m` has 0 active children" — D-fuzz-2's root-`always` signature. The
remaining ~400 are **not** that shape and are independent confirmation of
D-fuzz-9 from a completely different fuzzer:

* **48 hits of "active node *X* whose parent *Y* is inactive"** — the orphan
  invariant violation, at seven different depths (`m.a.a`, `m.a.b`, `m.b.a`,
  `m.a.c`, `m.a.a.a`, `m.b.c`, `m.b.b.a.a`). F3 found this via round-trip
  drift; F2 found it by inspecting the live machine after an ordinary
  `send()`.
* **29 hits of "parallel *X* partially active"** (`m.a`, `m.a.a`, `m.b.c`,
  `m.b.b`) — a `parallel` node with some but not all regions active, the
  second corruption shape D-fuzz-9 describes.
* ~330 hits of "compound *X* has 0 active children" at nodes **other than
  the root**, i.e. the same emptying as D-fuzz-2 occurring mid-tree.

None of these were accompanied by an error: every one was observed after a
`send()` that returned normally.

Several fuzzers independently rediscover the same defect (D-fuzz-2 is found
by both F1's start-up check and F2's per-event configuration check); the
attribution below names where each was first minimised.

| Fuzzer | Cases | First minimised here |
|---|---|---|
| F1 machine definitions | 20 000 | D-fuzz-1, D-fuzz-2, D-fuzz-8 |
| F2 event sequences | 20 000 | D-fuzz-3, D-fuzz-4, D-fuzz-5 |
| F3 snapshots | 20 000 | D-fuzz-6, D-fuzz-7, D-fuzz-9 |

### 2.2 The repro suite

```
$ python repros.py
==== 9/9 defects reproduce on this build ====
  D-fuzz-1: REPRODUCED      D-fuzz-6: REPRODUCED
  D-fuzz-2: REPRODUCED      D-fuzz-7: REPRODUCED
  D-fuzz-3: REPRODUCED      D-fuzz-8: REPRODUCED
  D-fuzz-4: REPRODUCED      D-fuzz-9: REPRODUCED
  D-fuzz-5: REPRODUCED
```

---

## 3. Defects

Severity: **Blocker** = cannot ship an order system on it; **High** = silent
data/state loss or an untyped failure on an untrusted boundary; **Medium** =
observability or parity gap with a workaround; **Low** = cosmetic.

### D-fuzz-1 — `start()` never terminates; the inbox grows without bound — **Blocker**

**Minimal repro** (`repros.py::d1`):

```python
cfg = {
    "id": "m",
    "type": "parallel",
    "states": {
        "A": {"initial": "a1", "states": {
            "a1": {"invoke": {"id": "inv", "src": "svc_ok",
                              "onDone": "#m.A.a1"}}}},
        "B": {"initial": "b1", "states": {
            "b1": {"always": "#m.A.a1"}}},
    },
}
SyncInterpreter(create_machine(cfg, logic=LOGIC)).start()   # never returns
```

`svc_ok` is a one-line synchronous service returning `{"ok": 1}`.
`create_machine()` accepts this config with no error and no warning.

**Observed.**

| horizon | `start()` returned | inbox length | RSS |
|---|---|---|---|
| 4 s | no | 36 050 | 57.7 MB |
| 8 s | no | 65 699 | 68.0 MB |
| 12 s | no | 92 845 | 77.4 MB |
| 16 s | no | 119 982 | 86.8 MB |
| 20 s | no | 149 014 | 96.8 MB |

Instrumentation over 90 s showed `_select_transitions` still climbing past
274 000 calls with the active configuration oscillating between 3 and 6
nodes. Event census during the spin: 2 998 transient (`""`) events to 3
`done.invoke.inv` — the machine is re-settling transients forever.

**Mechanism.** Region B's `always` re-enters `m.A.a1`, which exits and
re-enters the invoking state, which **re-arms the invoke**; the sync service
runs inline and queues a fresh `done.invoke.inv`; its `onDone` re-enters
`m.A.a1` again. `_invoke_service` was observed being called 501 times inside
a **single** `_process_transient_transitions` pass. The two guards that
should stop this both miss:

* `sync_interpreter.py:813-824` — the microstep limit inside
  `_process_transient_transitions` bounds *one* settling pass, but each pass
  legitimately re-arms the invoke, so the outer drain loop restarts settling
  with a fresh count. `_process_transient_transitions` was re-entered from
  `_process_event_queue` (line 755) unboundedly with an unchanging
  configuration.
* `sync_interpreter.py:678-690` — the per-chain `generated`/`tripped` budget
  is **reset by design** whenever "a macrostep generates nothing"
  (`sync_interpreter.py:770-776`). Here every macrostep *does* generate
  something, but the chain also keeps completing, so `#94`'s "completions
  are never discarded" rule spares the very event that re-arms the cycle.

The two 0.8.1 fixes meet on this shape and neither is authoritative:
#94 says a completion must always be delivered, and the chain reset says a
producing step earns fresh budget — together they are a permission to spin.

**`maxIterations` does not rescue it** at any usable value:

| `maxIterations` | `start()` returned within 45 s |
|---|---|
| 10 | yes (0.5 s) |
| 20 | yes (3.6 s) |
| 50 | **no** |
| 100 | **no** |
| 200 | **no** |
| 400 | **no** (50 846 events queued at the 45 s mark) |
| **1000 (default)** | **no** |

At `maxIterations: 20` the run does finish, but only by discarding 8 799
events via `on_event_dropped(reason="chain_budget")` — the budget is being
spent on the engine's own completions, not on a user runaway.

**Async engine:** `Interpreter.start()` on the *same* config returns
normally with `['m.A.a1', 'm.B.b1']`. This is a **sync-only** defect and
therefore also an **engine-parity** defect: the two engines disagree about
whether this machine can start at all.

**Root cause (file:line).**
`src/xstate_statemachine/sync_interpreter.py:796-845`
(`_process_transient_transitions` — bounds one settling pass, not the
re-entry) together with `src/xstate_statemachine/sync_interpreter.py:770-776`
(the per-chain reset that clears `generated`/`tripped` on any producing
step) and `:658-670` (`is_completion` sparing the re-arming `done.invoke`).
Build-time validation does not catch the shape:
`src/xstate_statemachine/validation.py:132-151` (`_is_dead_always_loop`)
only recognises an `always` whose target **is its own source**
(`target is t.source`); a cross-region `always` that re-enters a *different*
region's invoking state is invisible to it.

**Impact for an order system.** A statechart with an orthogonal
"supervisor" region that nudges an order region back into its
`invoke: placeOrder` state — a completely ordinary supervision idiom — will
hang the process on `start()`, before any order is placed, with no
exception, no log line at default level, no timeout, and unbounded memory
growth. It is undetectable by every check the library offers at build time.

---

### D-fuzz-2 — an `always` targeting the machine root empties the configuration — **High**

**Minimal repro** (`repros.py::d2`):

```python
cfg = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}
i = SyncInterpreter(create_machine(cfg, logic=LOGIC)); i.start()
```

**Observed.**

```
sync   states=[]  status='running'  value={}   matches('a')=False
async  states=[]  status='running'
snapshot: state_ids=[]  configuration=['m']
send('ANY') -> returns None, last_transition_ok=True, states still []
```

**Expected.** A non-empty atomic configuration (re-entering the root should
re-resolve `initial`), or a typed build/runtime error.

The machine reports itself healthy — `status == "running"`,
`last_transition_ok == True`, no `last_error`, `has_dormant_invocations ==
False` — while holding **no state at all**. Every subsequent event is
accepted and does nothing. A snapshot of it persists `state_ids: []`, so the
damage survives a restart.

This is **not** the same shape as `#30`'s dead-`always` check: the target is
the machine root, not the transition's own source, so
`_is_dead_always_loop` (`validation.py:132`) does not fire, and
`resolve_strict` resolves `#m` happily.

Both engines agree, so there is no parity escape hatch. `on`- and
`after`-targeted root transitions do **not** have this problem (they leave
`['m.a']` intact) — it is specific to `always`.

**Impact.** "Running, zero states, silently ignores everything" is exactly
the class of failure the adoption standard names. Nothing in the library's
observability surface reports it.

---

### D-fuzz-3 — `send()` to a stopped/done `SyncInterpreter` is silent; the async engine is observable — **Medium**

**Minimal repro** (`repros.py::d3`):

```python
i = SyncInterpreter(create_machine(cfg, logic=LOGIC)); i.start(); i.stop()
i.send("GO")     # returns None
```

**Observed.**

| engine | machine | `send()` | `on_event_received` | `on_unhandled_event` | `on_event_dropped` |
|---|---|---|---|---|---|
| sync | stopped | returns `None` | — | — | — |
| sync | done (final state) | returns `None` | — | — | — |
| async | stopped | returns | — | — | `('GO', 'not_running')` |
| async | done | returns | — | — | `('GO', 'not_running')` |

**Expected.** Parity: both engines observe the drop, or both raise
`InterpreterStoppedError` (which the library exports for exactly this).

A sync caller that sends into a machine which reached a final state — a
normal race in any workflow — gets no return value, no exception, and no
hook. The event is gone and there is no way to discover it. The async engine
already does the right thing, so this is a one-sided gap, not a design
choice.

Note this is distinct from, and narrower than, the `onUnhandled` policies:
none of `"ignore"` / `"defer"` / `"error"` changes the sync behaviour above
— all three are silent, because the event never reaches the policy.

**Scale.** F2 recorded **11 019 accepted-with-no-hook sends** across 20 000
cases. The overwhelming majority are this defect: the generated machine
reached a `final` state (so `status` became `done`) partway through its
event sequence, and every remaining send vanished without a trace. In an
order system, "the workflow finished and we kept sending it events that went
nowhere" is a reconciliation bug that only shows up in the ledger.

---

### D-fuzz-4 — a dict event with a non-`str` `type` raises a bare Python error — **High**

**Minimal repro** (`repros.py::d4`):

```python
i.send({"type": None})   # AttributeError: 'NoneType' object has no attribute 'startswith'
i.send({"type": 123})    # AttributeError: 'int' object has no attribute 'startswith'
```

**Observed.**

| `strict` | event | result |
|---|---|---|
| `False` | `{"type": None}` | `AttributeError` — `base_interpreter.py:3691` (`_collect_eligible_transitions`) |
| `False` | `{"type": 123}` | `AttributeError` — same site |
| `True` | `{"type": None}` | `TypeError: 'NoneType' object is not iterable` — `exceptions.py:353` (`UnknownEventError.__init__` → `difflib.get_close_matches`) |
| `True` | `{"type": 123}` | `TypeError` — same site |

**Expected.** `InvalidEventPayloadError` (or any `XStateMachineError`) on
every path.

**Root cause.** `_prepare_event` (`base_interpreter.py:1616-1619`) does
`event_type = data.pop("type", "UnnamedEvent")` and constructs
`Event(type=event_type, ...)` **without checking that the value is a
string**. The non-`str` then reaches `event.type.startswith(...)` at
`base_interpreter.py:3691`, or — under `strict` — reaches the error
constructor itself, so the *error path* is what crashes.

Note the second case is especially bad: the machine correctly decided to
reject the event, and then the rejection machinery raised the wrong
exception type. A caller with `except UnknownEventError` around `send()`
will not catch it.

A dict event is the wire-shaped form an order system receives from a queue
or an HTTP body; `{"type": null}` is a one-character JSON bug away.

---

### D-fuzz-5 — non-event objects raise a bare `TypeError` from `send()` — **Medium**

**Minimal repro** (`repros.py::d5`): `i.send(x)` for
`x ∈ {None, 123, b"B", ["GO"], object()}` →
`TypeError: Unsupported event type passed to send(): <class '…'>` for all
five.

**Root cause.** `base_interpreter.py:1634-1637` — the final `else` of
`_prepare_event` raises a built-in `TypeError`, and its own docstring
declares `Raises: TypeError`.

**Expected.** A typed `XStateMachineError` subclass
(`InvalidEventPayloadError` is the natural fit). The message is good; the
exception class is not catchable by the library's documented catch-all.

This is deliberate per the docstring, so it is filed as Medium rather than
High — but it is inconsistent with the 0.8.1 direction of travel
(`from_snapshot` stopped leaking `json.JSONDecodeError` for precisely this
reason) and it means no single `except` clause covers `send()`.

Related and unfixed: `send({"no_type_key": 1})` is accepted and silently
becomes the event `"UnnamedEvent"` (`base_interpreter.py:1618`), which under
`strict` then fails with `UnknownEventError: Event 'UnnamedEvent' is not
declared` — a confusing diagnosis of a malformed payload.

---

### D-fuzz-6 — `from_snapshot()` raises bare `KeyError`/`AttributeError`/`TypeError` on a corrupted blob — **High**

**Minimal repro** (`repros.py::d6`) — take a real snapshot, corrupt one
field, restore:

| corruption | result |
|---|---|
| `pending_events=[{}]` | `KeyError: 'type'` — `events.py:315` (`restore_event`) |
| `pending_events=[null]` | `AttributeError: 'NoneType' object has no attribute 'get'` — `events.py:314` |
| `pending_events=["GO"]` | `AttributeError: 'str' object has no attribute 'get'` — `events.py:314` |
| `deferred=[{}]` | `KeyError: 'type'` — `events.py:315` |
| `deferred=[null]` | `AttributeError` — `events.py:314` |
| `history={"m": null}` | `TypeError: 'NoneType' object is not iterable` — `base_interpreter.py:1251` |
| `configuration=5` | `TypeError: 'int' object is not iterable` — `base_interpreter.py:1233` |
| `state_ids=[["m.a"]]` | `AttributeError: 'list' object has no attribute 'split'` |
| `actors={"a": null}` | `AttributeError: 'NoneType' object has no attribute 'get'` |

**Expected.** Every one of these is `SnapshotDriftError` or
`InvalidConfigError`.

**Root cause.** `events.py:305-335` (`restore_event`) indexes
`record["type"]` and calls `record.get(...)` with no shape check, and
`base_interpreter.py:1227-1256` (`from_snapshot`) iterates
`snapshot["configuration"]` and `history` values without validating their
types. The envelope checks that *do* run first
(`persistence.check_version`, `check_identity`) only look at `version`,
`machine_id` and `machine_hash` — they say nothing about the payload's
internal shape, so a blob that passes the hash check can still be structurally
malformed (and one whose hash was never written, i.e. a v0/v1 payload, skips
the check entirely by design).

The v1 path is affected identically (`version: 1` with
`pending_events: [{}]` → `KeyError`), so this is not confined to the new v2
layout.

**Why this is High and not Medium.** The whole justification for #45's
envelope and for wrapping `json.JSONDecodeError` is that a snapshot is
untrusted input off a wire. A partially-written Redis value or a truncated
disk write produces exactly these shapes, and the operator's
`except XStateMachineError` does not catch them — the process dies with a
`KeyError` from library internals instead of a diagnosable drift error.

---

### D-fuzz-7 — `from_snapshot()` loads garbage silently — **High**

**Minimal repro** (`repros.py::d7`):

| corruption | restored to |
|---|---|
| `configuration=[]`, `state_ids=[]` | `status='running'`, `states=[]`, no error |
| `configuration=["m"]` (root only) | `status='running'`, `states=[]`, no error |
| `status="zzz"` | `status='zzz'` (an undocumented 5th value) |
| `status=5` | `status=5` (`int`) |
| `status=["running"]` | `status=['running']` (`list` — not even hashable) |
| `context=42` | `context=42`, and a subsequent `send("GO")` transitions normally against a non-mapping context |

**Expected.** `SnapshotDriftError` or `InvalidConfigError` for each.

The empty-configuration cases are the dangerous ones: the restored
interpreter reports `status == "running"` and
`has_dormant_invocations == False` — the two signals #44 added *specifically*
so a health check can tell a restored machine's liveness — yet the machine
holds no state and silently no-ops every event forever. A health check
written exactly as the library documents will pass on a corpse.

`status` is assigned verbatim at `base_interpreter.py:1216`
(`interpreter.status = snapshot["status"]`) with no membership test, so an
attacker-or-bug-supplied value of any Python type lands on the attribute
and propagates into every consumer that switches on `status`.

---

### D-fuzz-8 — a self-referential config is a `RecursionError`, not a typed error — **Low**

**Minimal repro** (`repros.py::d9`, filed as D-fuzz-8):

```python
a = {"initial": "x", "states": {}}
a["states"]["x"] = a                       # the dict contains itself
create_machine({"id": "m", "initial": "a", "states": {"a": a}}, logic=LOGIC)
# RecursionError: maximum recursion depth exceeded
```

**Root cause.** `models.py:244` — `StateNode.__init__` recurses into
`config["states"]` with no cycle detection and no depth cap.
`get_persisted_snapshot` has exactly this guard for actor cycles
(`base_interpreter.py:973-977`, "unbounded recursion would blow the stack
instead of failing cleanly") — the same reasoning applies here and is not
applied.

**Expected.** `InvalidConfigError` naming the cyclic state.

Filed **Low**: reaching it requires building the config in Python with an
aliased dict, which JSON cannot express, so a config loaded from a file is
safe. It is included because deeply-nested-but-acyclic configs (200–1 000
levels) are also accepted and then blow the stack at various later points,
and because the library already treats "recursion instead of a clean
failure" as a bug elsewhere.

---

### D-fuzz-9 — a runaway-chain trip leaves the live machine structurally corrupt — **High**

Found by F3's C3 round-trip check, which flagged 40 cases where an
**unmutated** snapshot did not survive save → restore → save. The drift was
the symptom; the cause is worse.

**Minimal repro** (`repros.py::d10`):

```python
cfg = {
    "id": "m", "initial": "b", "maxIterations": 1,
    "always": {"target": "#m.b", "guard": "g_true"},
    "states": {"b": {"type": "parallel", "states": {
        "a": {"initial": "a", "always": {"target": "#m", "guard": "g_true"},
              "states": {"a": {}}},
        "b": {"initial": "a",
              "invoke": {"id": "v", "src": "svc_ok",
                         "onDone": "#m.b", "onError": "#m.b"},
              "states": {"a": {}}},
    }}},
}
i = SyncInterpreter(create_machine(cfg, logic=LOGIC)); i.start()
```

**Observed.**

```
live active configuration = ['m', 'm.b.b.a']
ORPHANS                   = ['m.b.b.a']     # parents m.b and m.b.b are NOT active
value                     = {}              # the hierarchical view sees nothing
status                    = 'running'
last_transition_ok        = True            # reports success
last_error                = None            # reports no error
save1 configuration       = ['m', 'm.b.b.a']
save2 configuration       = ['m', 'm.b', 'm.b.b', 'm.b.b.a']   # ← rewritten
```

**Expected.** No orphan active node; a budget trip reported through
`last_error` (`RunawayChainError`) and `last_transition_ok=False`, which
the CHANGELOG states as a 0.8.1 guarantee for #77 criterion 6; and a stable
round-trip.

**Three distinct problems in one case.**

1. **The configuration is not a tree.** `m.b.b.a` is active while both its
   parents are inactive. This violates the most basic SCXML invariant and is
   the state on which every subsequent transition-domain computation
   (`_compute_states_to_exit`, `_find_transition_domain`) is based.
2. **The machine reports healthy.** `status == "running"`,
   `last_transition_ok is True`, `last_error is None`. The microstep
   abort at `sync_interpreter.py:815-824` only logs — unlike the *event*
   budget path at `:716-733`, which correctly sets `last_transition_ok`
   and mints a `RunawayChainError`. The transient-settling budget has no
   such reporting, so a trip there is invisible to every observer. Note
   `value` is `{}` — the same "alive but holding nothing" signature as
   D-fuzz-2, arrived at by a different route.
3. **Restore silently disagrees with save.** `from_snapshot`
   (`base_interpreter.py:1229-1234`) walks each restored id up to the root
   adding ancestors, so it *repairs* the corrupt configuration into a legal
   one. That is defensible in isolation, but it means the restored machine
   is **not** the machine that was saved, with no warning: `m.b.a` and
   `m.b.a.a` (the other parallel region) are still missing, so the restored
   machine has a `parallel` node with one of two regions active — a
   different illegal state from the one persisted.

**Root cause (file:line).**
`src/xstate_statemachine/sync_interpreter.py:812-824` — the transient
microstep limit `break`s out of settling mid-way, leaving whatever partial
exit/entry the aborted macrostep had performed, with no rollback and no
error reporting. Contrast `:716-733`, where the event-chain budget does set
`last_transition_ok = False` and `_last_action_error = RunawayChainError`.
The ancestor repair at `src/xstate_statemachine/base_interpreter.py:1229-1234`
masks the result at restore time.

**Reachability.** The repro uses `maxIterations: 1` to make the trip
deterministic and small. The 40 F3 hits were at the **default** budget of
1 000: the fuzzer's generated machines reached the same state through longer
chains. **F2 confirms it independently on the live machine** — 48 orphan
active nodes and 29 partially-active parallel states observed after an
ordinary `send()` that returned normally (§2.1). D-fuzz-1's configs are the
same family — a cross-region `always` plus an `invoke` — so the two defects
are the two possible outcomes of that shape: either the budget is too high
and the machine hangs (D-fuzz-1), or it trips and the machine is left
corrupt and silent (D-fuzz-9). There is no setting of `maxIterations` that
gives a correct result for these configs.

**Impact.** A machine in this state is worse than one that crashed. It
passes every health check the library offers, its `value` says it is
nowhere, it persists a configuration that cannot be reproduced, and the
restore path quietly substitutes a different one. For an order system that
is an order whose recorded state and actual state diverge, with no signal at
either end.

---

## 4. Not filed — checked and found sound

Recording these matters as much as the defects; a clean track must say what
it looked at and did not find.

* **`create_machine` target validation (#29/#30) is solid.** Across F1's
  20 000 cases every `dangle_target` mutation was rejected with
  `InvalidConfigError` carrying a `did you mean` suggestion —
  **1 197 / 1 197**. `cycle_always` (unguarded `always` self-loop) was
  rejected **801 / 801**, `dup_custom_id` **725 / 725**. Every one of the
  6 666 well-formed configs the generator produced was accepted, so there
  are no false positives either. The gap found (D-fuzz-1, D-fuzz-2) is in
  *which shapes* the check models, not in whether it runs.
* **Text-level snapshot corruption is handled well.** Character flips,
  deletions, truncation and junk insertion into the JSON produce
  `InvalidConfigError("Snapshot is not valid JSON")` in the large majority
  of cases — the `json.JSONDecodeError` wrapper works. Version bumps
  (`version: 3/99`) raise `SnapshotVersionError`; a tampered `machine_id`
  raises `SnapshotDriftError`. The envelope does its job; the payload
  interior (D-fuzz-6/7) is where it stops. One caveat: `check_version`
  itself (`persistence.py:138`) does `int(snapshot.get("version", 0))`
  without a type guard, so a non-numeric `version` raises `TypeError` /
  `ValueError` from inside the guard — counted under D-fuzz-6.
* **Clean snapshot round-trip is stable** in 18 520 of 18 568 cases that
  reached the check: `configuration`, `state_ids`, `context`, `deferred`,
  `pending_events` and `history` came back byte-identical. The v2 layout's
  `kind` discriminator round-trips `DoneEvent` / `ErrorEvent` / `AfterEvent`
  / system `Event` as the CHANGELOG claims (#86/#87). The 40 `configuration`
  exceptions are D-fuzz-9; the 8 `pending_events` exceptions are **not a
  defect** — an `ErrorEvent`'s exception cannot survive JSON and comes back
  as a `RestoredError` stand-in, which `events.py:288-290` documents
  explicitly.
* **`strict` mode rejects by provenance, not name.** Every engine-shaped
  user event we sent — `done.invoke.NEVER`, `done.state.NOPE`,
  `error.platform.NOPE`, `after.9999999`, `xstate.whatever`,
  `___xstate_forged` — was refused with `UnknownEventError` under `strict`,
  and `done.review` (a legitimate business name that merely *looks* engine-
  shaped) was treated as ordinary user traffic. #79/#98 hold up under
  adversarial naming.
* **Huge payloads are not a problem.** 50 KB string payloads transited
  `send()` on both engines with no error and no measurable pathology.
* **Unicode event names** (`GØ`, `事件`, `💥`, and a name containing a NUL
  byte) behaved as ordinary undeclared names: accepted non-strict, refused
  with `UnknownEventError` under `strict`. No encoding crash.
* **`last_error` / `last_transition_ok` stayed coherent.** Invariant B5 —
  "`last_transition_ok is False` implies `last_error is not None`" — was
  never violated across F2's ~62 000 sends. The additive 0.8.1 API does what
  it says *when it fires*; D-fuzz-9 is the separate complaint that the
  transient-settling path never fires it at all.
* **`status` never took an undocumented value from event traffic.**
  Invariant B4 was never violated in F2 — only a corrupted *snapshot* can
  put a non-documented value there (D-fuzz-7).
* **`{"type": "GO", "payload": "not-a-dict"}`** is accepted and transitions
  correctly; the string lands under `payload["payload"]`. Surprising, but
  not lossy and not a crash — noted, not filed.
* **An unimplemented action name** is accepted by `create_machine()` with no
  build-time check, but fails at run time with a typed
  `ImplementationMissingError` on both the entry and the transition path.
  Loud, typed and catchable, so not filed — though a build-time check would
  match the treatment `raise` targets already get (#51).

---

## 5. Constraints we would need

If the adopting project proceeds on this build, these are the constraints
the FUZZ track's findings impose. They are stated as testable rules.

* **CV-F01 (from D-fuzz-1) — forbid a cross-region `always` that targets a
  state carrying an `invoke`.** No statechart in the catalogue may contain
  an `always` transition whose target lies in a different parallel region
  from its source AND whose target (or any state entered on the path to it)
  declares an `invoke`. This must be a lint over the B1–B20 JSON, run in
  CI, because the library's build-time validation does not model the shape.
  Without the lint, a single such edit hangs the process at start-up.
* **CV-F02 (from D-fuzz-1) — never call `SyncInterpreter.start()` on the
  main thread without a watchdog.** Until the microstep budget bounds
  re-entry, `start()` has no timeout and cannot be interrupted. If the sync
  engine is used at all, it must be started on a worker thread with a join
  deadline and a hard process-level alarm.
* **CV-F03 (from D-fuzz-2) — forbid any transition targeting the machine
  root (`#<machineId>`) from an `always`.** Lintable statically over the
  catalogue. The `on`/`after` forms are safe; only `always` empties the
  configuration.
* **CV-F04 (from D-fuzz-4/5/6) — wrap every library entry point.** `send`,
  `send_events`, `send_threadsafe` and `from_snapshot` must be called only
  through an in-house shim that catches `Exception`, not
  `XStateMachineError`, and re-raises as the project's own typed error.
  `except XStateMachineError` is **not** sufficient on this build; the
  library's own docstrings promise a coverage that the code does not
  deliver.
* **CV-F05 (from D-fuzz-6/7) — validate a snapshot before handing it to
  `from_snapshot`.** The shim must, at minimum, assert that
  `configuration` is a non-empty list of strings, `state_ids` is a list of
  strings, `status` is one of the four documented values, `context` is a
  mapping, and every record in `pending_events`/`deferred` is a dict with a
  string `type`. `from_snapshot` will neither reject these nor survive them
  reliably.
* **CV-F06 (from D-fuzz-7) — do not use `status` or
  `has_dormant_invocations` as the liveness signal after a restore.** Both
  report healthy on a restored machine with an empty configuration. The
  post-restore health check must assert a non-empty atomic configuration
  directly (`interp.current_state_ids != set()` plus the parent/child
  legality predicate in §1.2).
* **CV-F07 (from D-fuzz-3) — never fire-and-forget on the sync engine.**
  A sync `send()` to a stopped or done machine is silent. Every sync send in
  an order path must check `interp.status` immediately before the call and
  treat any non-`running` value as a failed delivery, since no hook and no
  return value will tell it.
* **CV-F08 (from D-fuzz-9) — assert configuration legality after every
  macrostep, not just after a restore.** The transient-settling budget can
  trip and leave an active leaf with inactive ancestors while reporting
  success. The shim must run the §1.2 predicate (parent-active, exactly-one
  compound child, all-parallel-regions) after each `send()` in an order
  path and treat a violation as a hard failure, because `status`,
  `last_transition_ok` and `last_error` will all say the step succeeded.
* **CV-F09 (from D-fuzz-9) — never trust a restore to reproduce a save.**
  `from_snapshot` repairs a corrupt configuration by adding ancestors, so
  the restored machine can differ from the saved one with no warning. The
  shim must compare `configuration` before and after a round-trip and
  refuse the restore on any difference, rather than assuming fidelity.

---

## 6. What this track covered — and what it did not

**Covered.** Machine-definition generation at nesting depth ≤ 4 with
parallel, compound, final and history nodes; `always`, `after` (numeric and
named delays), `invoke` with `onDone`/`onError`, guarded and unguarded
transitions, internal/external transitions, entry/exit action lists; all
three `actionErrorPolicy` values, all three `guardErrorPolicy` values, all
three `onUnhandled` values, and `maxIterations` variation. Nine mutation
families against those configs. Event sequences up to 8 events over a
9-class hostile alphabet under both `strict` settings on both engines.
Eighteen snapshot mutation families, text-level and structural, with and
without `verify_machine_hash`. Minimisation of every filed defect to a
standalone repro.

**Not covered — stated plainly.**

* **Concurrency.** No multi-threaded fuzzing: `send_threadsafe` was
  exercised for its typed-error behaviour but not raced. Cross-thread
  interleavings are the CONCURRENCY track's ground and nothing here should
  be read as clearing them.
* **Actor hierarchies.** Child actors were generated only as `invoke`d
  callables, never as `MachineNode` children, so `spawn`, `sendParent`,
  `sendTo`, `stopChild` and the systemId registry are untested by this
  track. The `actors` field of a snapshot was mutated, but only ever on a
  snapshot that had no live children — the recursive restore path is
  therefore largely unexercised.
* **Timers under a simulated clock.** `after` transitions were generated,
  but `SimulatedClock` was not driven; every run used the real clock and
  short delays. Timer starvation, cancellation on rollback and the #50/#76
  lane selection were not fuzzed.
* **`event_schemas`.** No schema was registered on any generated machine, so
  `InvalidEventPayloadError`'s schema arm is untested here (its
  non-schema arm is covered via D-fuzz-4's expectation).
* **The async engine got 20 % of the F2 budget**, not parity with sync,
  because each async trial costs an event-loop round trip. Async-only
  defects are correspondingly less likely to have been found. It did
  participate in the findings it shares — 510 of the untyped `send()`
  errors and 9 of the non-settling sends are async — so it is exercised, not
  ignored; but the async engine's clean result in D-fuzz-1 should be read as
  "async does not have *this* defect", not "async is fine".
* **Persistence across library versions.** Only v0/v1/v2 payloads produced
  by *this* build were restored; no genuine 0.7.x snapshot was replayed.
* **Performance.** No throughput or latency claim is made or tested; the
  BENCH track owns that. The memory figures in D-fuzz-1 are evidence of
  non-termination, not a performance measurement.
* **The `pythonic` API, the CLI and `logic_modules`/`logic_providers`
  discovery** were not fuzzed; every machine here was built from JSON with
  an explicit `MachineLogic`.

**One methodological caveat.** The anti-hang budget (§1.3) replaces
"`start()`/`send()` hangs" with "exceeds 20 000 transition selections". A
machine that legitimately needs more than 20 000 selections to settle would
be misreported as non-terminating. We checked the converse on every filed
case: `min_spin.json` and `repro_d1.json` were each also run to a wall-clock
timeout without the instrument and confirmed to be genuinely unbounded
(90 s and 20 s respectively, with the inbox still growing linearly).

---

## 7. Artefacts

| Path | What |
|---|---|
| `fuzz/common.py` | oracles (`ALLOWED_*_ERRORS`), defect recorder with minimal-case retention |
| `fuzz/gen_config.py` | hypothesis statechart generator + the 9 mutation families + the logic vocabulary |
| `fuzz/spin_oracle.py` | the budgeted `_select_transitions` instrument (§1.3) |
| `fuzz/f1_machine_config.py` | F1, machine-definition fuzzer |
| `fuzz/f2_events.py` | F2, event-sequence fuzzer |
| `fuzz/f3_snapshot.py` | F3, snapshot fuzzer |
| `fuzz/shrink_spin.py` | delta-debugging shrinker using the budget oracle (fast) |
| `fuzz/shrink_hang.py` | delta-debugging shrinker using a subprocess timeout (independent, slow — used to cross-check the budget oracle) |
| `fuzz/repros.py` | **the deliverable** — all 8 defects as standalone hand-checked repros; exit code = number still reproducing |
| `fuzz/hang30.json` | the raw generated config that first exposed D-fuzz-1 |
| `fuzz/min_spin.json` | its minimised form |
| `fuzz/repro_d1.json` | the hand-written minimal D-fuzz-1 config |
| `fuzz/out/*.json` | full per-fuzzer counters and every recorded defect class |
| `fuzz/out/*.log` | raw run output |
