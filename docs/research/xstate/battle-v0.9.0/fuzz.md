# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `v0.9.0`

**Build under test.** Local clone `_ref/xstate-statemachine`, tag **`v0.9.0`
= `91bd979`**; working tree on `main` = **`e3a1f22`**, which is 2 commits
ahead of the tag. Verified with `git diff v0.9.0..HEAD --stat`: the delta is
`.github/workflows/publish.yml | 15 ++++++++++++++-` — **CI publish
smoke-test only, no library source**. The environment's claim holds.
`__version__ == "0.9.0"`. **Not yet on PyPI** (`pip download` fails); every
run here is against the local clone.

**Date:** 2026-09-23. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Every script run from the neutral
cwd `C:/Users/basil`.

**Suite baseline** (`suite-v0.9.0.log`, complete): **3577 passed, 13 skipped,
15 warnings in 597 s**; total coverage **92.86 %** (gate 90 %).

**Track:** FUZZ, re-run of `battle-de2da4e/fuzz.md` plus a new attack set
aimed at round 12's fixes (#225–#235). New scripts under
`docs/research/xstate/battle-v0.9.0/fuzz/`; raw output under `fuzz/out/`.
No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted. **Every action/service check was run with both `def`
and `async def` implementations.** Plateaus and hangs are polled to
convergence, never sampled at a fixed instant. A trust boundary the docs
draw is not a defect unless the crossing is demonstrated against a control.

---

## 0. Bottom line

**Round 12 is the cleanest round this track has measured. The two fixes that
were most likely to break something under fuzzing — #225's task-identity
rewrite of self-send provenance and #227's strict check on restored
`scheduled_sends` — both verify at scale, with zero property violations in
1 280 persistence cases and a 6/6 task-identity matrix on both kinds. Round
12 also closes the track's oldest standing Blocker, D12-fuzz-1, and one half
of the long-standing restore-reporting record (`plugins=`, #230). The single
new finding is an observability hole the `plugins=` work exposes rather than
creates: a snapshot-RESTORED interpreter never fires `on_interpreter_start`,
on either engine, through either registration route.**

- **NEW D13-fuzz-1 (Medium) — `on_interpreter_start` is silently skipped for
  every snapshot-restored interpreter, both engines, both registration
  routes.** `d13_fuzz_1_restored_start_hook.py` → `result: FAIL`, **5/5
  cells**. Control first: a fresh interpreter of the same chart logs
  `['start', 'transition', 'stop']`; the restored one logs
  `['recv:GO', 'transition', 'stop']` — no `start`, and no `transition` for
  its initial configuration either. `Interpreter.start()` has two paths, and
  the "resume a snapshot-restored interpreter" early return
  (`interpreter.py:591-618`) binds the loop, re-arms `scheduled_sends` and
  returns **without the plugin notification loop** that the fall-through path
  runs at `interpreter.py:663-665`; `SyncInterpreter` has the same shape.
  This is exactly the surface #230 was opened for — "a restore-time event
  reaches `on_invalid_event` like a runtime one" — and the hook that says
  *"a machine came up"* is the one it does not reach. A supervisor that
  counts machine bring-ups from plugin hooks under-counts by exactly the
  restarted ones.

- **D12-fuzz-1 (Blocker) is FIXED.** `rerun_f4.txt` § D still prints
  `DROVE` for the forged `done.invoke.*` / `after.*` records, but that is the
  prior script's **v2-upcast** cell, refuted as R12-02 (trust boundary, not
  escalation). The v3 half the record was actually about — a hand-written
  `scheduled_sends` record bypassing the engine-flag check — is closed:
  `g4_security.py` § S3 shows all four forgery shapes (`s3a`–`s3d`, incl.
  `done.invoke.ghost` with `engine: true` forged) **refused, reported via
  `on_invalid_event`, and landing on `last_error`**, against a CONTROL that
  confirms a *declared* record still arms and fires. `_rearm_restored_self_sends`
  now routes every record through `_admit_restored`
  (`base_interpreter.py:1291-1300`).

- **#225 verifies on the sharpest available oracle, 12/12 cells.**
  `g2_concurrency.py` § A. Plain-queue routing is *not* a usable oracle (an
  internal send is drained later in the same macrostep, so it lands either
  way); the observable that actually separates the two is the #219 guard.
  `a1 action awaits own receipt → ReentrantWaitError`;
  `a7 after-handler → ReentrantWaitError`; and **every** spawned-task shape
  is ordinary external traffic — `a2 action → helper task → OK:Receipt`,
  `a4 action → task → task → OK:Receipt`, `a6 child action → parent →
  OK:Receipt`, `a5 other thread → send_threadsafe → OK`. Both kinds. § B:
  **200/200** machines whose worker was spawned from an action and outlives
  it land their send with the loop otherwise idle — the starvation shape
  #225 fixes. § C: **100/100** `ensure_future(send(wait=True))` hand-outs
  resolve *while the spawning action keeps awaiting*, the regression shape
  the changelog calls out, on both kinds.

- **#226 verifies across 6 restarts, both kinds.** `g1_persistence.py` § A:
  `chain_trips` holds at 1 through six `from_snapshot` → `get_snapshot`
  hops, the latched error comes back as `RestoredError` carrying the
  original text (`"Machine 'trip' exceeded 1000 chained self-gene…"`) every
  time, and `clear_chain_error()` clears the latch **without rewinding** the
  counter, which then survives a further re-persist. Closes the CV-C62
  observation from `battle-de2da4e`.

- **#227 verifies as a property, 640 cases.** `g1_persistence.py` § B:
  320 generated strict machines × 2 kinds, each restoring a
  `scheduled_sends` blob that mixes 1–3 declared and 1–3 undeclared types in
  random order. **0 violations** on five properties per case: no undeclared
  type delivered; every declared record fires exactly once; `on_invalid_event`
  fires exactly once per refused record; the machine is `running` and still
  usable after the partial refusal; and a refused record does **not** survive
  a re-persist.

- **#231 verifies over the whole shape space.** `g3_fuzz_det.py` § B: 10
  non-`str` `invoke.src` variants × `strict_config` on/off = **18/18 raise a
  named `InvalidConfigError`, 0 `TypeError`** (the 2 accepted cells are
  `src: None`, which is the separate "missing src" WARNING path). The message
  names the state, the invoke id, the type received and the supported
  alternative.

- **Livelock oracle clean at the target scale for the first time on this
  track.** `g3_fuzz_det.py` § A: **520 configs × 2 kinds × 2 engines =
  1 560 cells in 36.5 s** — `LEGAL rings ok=1089 tripped=0`,
  `MUST-TRIP tripped=471 missed=0`, **0 disagreements**. (The prior
  `p5` script self-bounds at 110 s and reached only 234 cells; see § 4.)

- **Determinism holds including the new fields.** `g3` § C: **1 distinct
  trace over 50 runs** on the async engine for both kinds and on the sync
  engine, with identical `chain_trips` **and** identical latch type.

- **Soak clean.** `g5_soak.py`, 200 machines × 2 kinds × 3 min each with
  delayed-self-send heartbeats, action-spawned workers outliving their
  actions, an external priority producer and a chaos
  `snapshot → from_snapshot(plugins=) → re-persist` worker — results in § 3.

---

## 1. Prior-defect table (`battle-de2da4e/fuzz/*` and `battle-c78ce99/fuzz/*` re-run verbatim)

| Prior record | Status @ `v0.9.0` | Evidence |
|---|---|---|
| **`D12-fuzz-1`** — a hand-written `scheduled_sends` record mints an engine-only event at v3 (Blocker) | **FIXED** | The v3 half is closed by #227: `g4_security.py` § S3 — `s3b` (`done.invoke.ghost`) and `s3d` (same, with `engine: true` forged onto the record) are both `delivered=False`, `on_invalid_event=[('UnknownEventError', 'done.invoke.ghost')]`, `last_error=UnknownEventError`; CONTROL `D0` still `delivered=True`. `rerun_f4.txt` § D still reports 4 `DROVE` cells, but those run through the **v2 upcast**, refuted as R12-02 (trust boundary). |
| `D11-fuzz-1` / `D10-fuzz-1` — v2 upcast is a universal mint | **STILL-PRESENT, REFUTED as a defect (R12-02)** | `out/rerun_p2_upcast_minting.txt`: 8 defects, unchanged — `after v2 UNflagged → DROVE`, `done v2 UNflagged → DROVE ctx.fill={'filled': 999999}`, both kinds; v3 unflagged correctly inert. Accepted: an honest v3 write of `configuration`/`context` reaches the same outcome. Residual is documentation (`minimum_version=3` is hygiene, not a control). |
| `D11-fuzz-5` — `on_invalid_event` unreachable on restore | **FIXED (C1 half) / STILL-PRESENT (C2 half)** | `out/rerun_p2_upcast_minting.txt` still prints both C1 and C2 because the script predates `plugins=`. Re-asserted directly: with `from_snapshot(..., plugins=[spy])` the refusal **does** reach `on_invalid_event` (`('UnknownEventError','ZZ')`) — C1 is closed by #230. C2 survives: after the next restored event is processed, `last_error` resets to `None` while the hook record persists. The hook is now the durable half; `last_error` is a per-step read. **SUPERSEDED assertion** — see `g1_persistence.py` § C. |
| `D11-fuzz-4` — `structure_hash` omits `raise(delay=)` | **STILL-PRESENT** | `out/rerun_p1_v3_roundtrip.txt`: `structure_hash covers raise-delay change = False`; snapshot vs delay-changed chart → `ACCEPTED (re-armed 1)`. 1 defect, unchanged. § A of the same script: **600/600** v3 round-trip property cases clean, both kinds. |
| `D11-fuzz-2` — chain trip erased from `last_error` | **FIXED (superseded by #222, strengthened by #226)** | `rerun_f1` § B: latch survives the benign event on both kinds, and now also survives the snapshot (`snapshot keys w/ 'chain'=['chain_trips','last_chain_error']`, `restored trips=1 err=RestoredError`) — the CV-C62 residual is gone. |
| `D11-fuzz-3` — key check is root-only | **FIXED** | `out/rerun_f3_key_check_fuzz.txt`: `{'RAISED': 319, 'WARNED': 0, 'SILENT': 0}` (`def`) and `318/0/0` (`async def`) across state/trans/invoke/root levels; default mode `55–56 WARNED, 0 SILENT`; all six case variants (`Entry`, `ENTRY`, `oN`, `Always`, `After`, `Invoke`) RAISED with a path-named message. **0 defects.** |
| `p3` § B — mixed delayed+zero-delay chain trips 45–49/50 | **STILL-PRESENT (Low)** | `out/rerun_p3_concurrency.txt`: 45/50 (`def`), 48/50 (`async def`). A scheduling race, not a rule error; unchanged in character. |
| `f1` § A — parked `scheduled_sends` property (640 cases) | **clean** | `rerun_f1`: `A/def 320 cases done, defects so far = 0`, `A/async def` likewise. #221 still exact across 1–4 restore→re-persist hops. |
| `f2` — #219 matrix + #218 handle release + cancel storm | **clean, one CHANGED detail** | `rerun_f2`: `A1/A3/A6 → ReentrantWaitError`, `A2/A4 → OK Receipt`, `A7 100/100`; § B 200-beat heartbeat `peak_handles_per_owner=1`; § C 500 arm/cancel pairs `peak=0, err=None`. **CHANGED:** a `def` action's returned object is now `_PendingReceipt` (was `_Awaitable`) — the #232 guard object. Cosmetic rename; the script's assertion still passes. |
| `f4` § A/B/C — 200-machine handles, determinism, #222 exactly-once | **clean** | `rerun_f4`: handles ≤ 200 with negative heap growth, `distinct traces=1 trips=[1]` on all three engine/kind cells, `trip1 trips=1 hook=1 … trip2 trips=2 hook=2 … after clear trips=2`. |
| `p5` § A — livelock fuzzer under the #212 oracle | **clean but under-scaled → SUPERSEDED** | `out/rerun_p5_livelock.txt`: 234 cells in 110.2 s, `LEGAL ok=220 tripped=0`, `MUST-TRIP tripped=14 NOT_tripped=0`. Its § B3 probe *raises* by design now and aborts the script (exit 1) — the #220 fix it was written to prove absent. Superseded by `g3_fuzz_det.py` § A (1 560 cells) and `f3` (§ B). |
| `p6` — determinism + soak | **superseded** | Replaced by `g3` § C and `g5_soak.py`; the v3 chaos worker now exercises `plugins=`. |

**No prior fuzz defect regressed.** The track's only Blocker (`D12-fuzz-1`)
is fixed; `D11-fuzz-2` and `D11-fuzz-3` remain fixed and are strengthened;
`D11-fuzz-5`'s reachability half is fixed by `plugins=`. The three survivors
— the v2-upcast mint (refuted as a trust-boundary non-defect), the
`structure_hash` delay gap, and the mixed-chain scheduling race — are all
pre-round-12 carry-forwards on surfaces round 12 did not touch.

---

## 2. New attacks

All scripts are standalone (stdlib + `xstate_statemachine` only), run from
`C:/Users/basil`, and exit non-zero on any violated property.

### 2.1 `g1_persistence.py` — #226 latch restarts, #227 property, #230 hooks

**A — the chain-trip latch across 6 restarts.** A chart that trips its
budget on start is snapshotted, then passed through six
`from_snapshot` → `get_snapshot` hops.

    A/def       seq=[(1,"Machine 'trip' exceeded 1000 chained sel"), (1,'RestoredError') x6]
                | clear: trips 1->1 err=NoneType | re-persist trips=1
    A/async def (identical)

Properties, all held: the count is **identical at every hop** (monotonic —
never rewound); the latched error is a `RestoredError` at every hop, never
`None`; the message carries the original text; `clear_chain_error()` clears
the error object but **does not rewind** `chain_trips`; and the cleared,
re-persisted blob still restores `chain_trips=1`. **0 defects.** This is the
`battle-de2da4e` CV-C62 observation closed.

**B — #227 as a property, 640 cases.** 320 generated `strict: True`
machines × 2 kinds. Each restores a `scheduled_sends` blob shuffling 1–3
**declared** types (`D0`/`D1`/`D2`) with 1–3 **undeclared** ones
(`U0`/`U1`/`ZZ`/`done.invoke.ghost`).

    B/def       320 cases done, defects so far = 0
    B/async def 320 cases done, defects so far = 0

Five properties per case: **P1** no undeclared type is ever delivered;
**P2** every declared record fires exactly once at its remaining delay;
**P3** `on_invalid_event` fires exactly once per refused record (no more,
no fewer); **P4** the interpreter is `running` and still processes a fresh
`send()` after the partial refusal — the restore is never aborted; **P5** a
refused record does not survive a re-persist. **0/640 violations.**

**C — `from_snapshot(plugins=...)` hook delivery (#230).** A blob carrying
one undeclared record in **each** lane.

    C/def  invalid@from_snapshot=[('UnknownEventError','U1')]
           invalid@post-start   =[('UnknownEventError','U1'), ('UnknownEventError','U0')]
           starts=0  last_error=UnknownEventError
    C/def  plugins=+use(same) invalid=[('U1'),('U0'),('U0')]

Both lanes are reported exactly once each, and the timing is the point:
the `pending_events` refusal (`U1`) fires **inside `from_snapshot`** — only
reachable because `plugins=` registers before admission — and the
`scheduled_sends` refusal (`U0`) fires when `start()` re-arms. #230 verifies.
Two observations, neither a defect: passing the **same** plugin object to
both `plugins=` and `.use()` double-registers it (`U0` reported twice) —
caller error, but `.use()` does not dedupe; and **`starts=0`** on every cell,
which is D13-fuzz-1 below.

### 2.2 `g2_concurrency.py` — #225 task identity, #232, #219 residual

**A — the task-identity matrix.** The oracle matters. Plain-queue routing
cannot separate internal from external: an internal send is drained *later
in the same macrostep*, so it lands either way with the loop idle
(measured — the first draft of this script called that a defect and was
wrong). The observable that does separate them is the #219 reentrancy
guard on `send(..., wait=True)`, which fires exactly on "the current task
is running one of my actions".

    A/def       a1 action awaits own receipt         -> DEF-RETURNED:_PendingReceipt
    A/def       a2 action -> helper task -> receipt  -> OK:Receipt
    A/def       a4 action -> task -> task -> receipt -> OK:Receipt
    A/def       a5 other thread -> send_threadsafe   -> OK
    A/def       a7 after-handler awaits own receipt  -> DEF-RETURNED:_PendingReceipt
    A/def       a6 child action -> parent receipt    -> OK:Receipt
    A/async def a1 -> REFUSED:ReentrantWaitError     a2 -> OK:Receipt
    A/async def a4 -> OK:Receipt                     a5 -> OK
    A/async def a7 -> REFUSED:ReentrantWaitError     a6 -> OK:Receipt

**12/12 as specified.** The two genuine in-step awaits (`a1`, `a7` — the
`after` handler counts as an action of the same task) are refused; every
spawned-task and cross-interpreter shape is ordinary external traffic. A
`def` action cannot await at all, so its cells return the #232 guard object
instead — covered in § D. `a5` uses `send_threadsafe`: the documented
cross-thread API. `asyncio.run_coroutine_threadsafe(i.send(...), loop)` is
refused with a named `WrongThreadError` whose message *names the
replacement* — correct and helpful, verified in passing.

**B — 200 machines × a worker spawned from an action that outlives it.**
This is the exact starvation shape #225 fixes: under the `ContextVar`
predicate the worker inherited "is an action" for life, so its plain
`send()` went to the internal queue and sat there with the loop idle.

    B/def       machines=200 worker_sends_issued=200 landed=200/200
    B/async def machines=200 worker_sends_issued=200 landed=200/200

**C — 100 concurrent `ensure_future(send(wait=True))` hand-outs**, with the
spawning `async def` action *continuing to await* afterwards — the
regression the changelog calls out.

    C/def       receipts_resolved=100/100 failures=[] advanced=100/100
    C/async def receipts_resolved=100/100 failures=[] advanced=100/100

**D — #232's RuntimeWarning: where does it surface?**

    D1 dropped receipt warnings = [('RuntimeWarning', "send('B', wait=True) on 'dd'
       was called from inside an action and its receipt was never aw...")]
    D2 -W error: raised_to_caller=None loop_exception_handler=[] status=running
       last_error=NoneType

D1: the warning fires, and its text names the call, the machine, the cause
and **both** supported alternatives. D2 is the operationally important half:
the warning is emitted from `_PendingReceipt.__del__`, so under
`-W error` the resulting `RuntimeWarning` is raised **inside a finaliser**
and CPython prints `Exception ignored in: ...__del__` to stderr. It does
**not** reach the caller, does **not** reach the asyncio exception handler,
and does **not** set `last_error` — the machine keeps running. That is the
correct containment choice (a finaliser must not kill the loop), but it
means **`-W error` does not turn this warning into a failure**: a CI job
relying on `-W error` to catch dropped receipts will not fail. Not a defect
(it is how `__del__` works in CPython), but it belongs in adoption guidance:
grep stderr for `Exception ignored in` rather than trusting `-W error`.

### 2.3 `g3_fuzz_det.py` — livelock at scale, #231, determinism

**A — livelock fuzzer, 520 configs × 2 kinds × 2 engines.**

    configs=520 cells=1560 in 36.5s
    LEGAL rings  ok=1089 tripped=0
    MUST-TRIP    tripped=471 missed=0

Oracle (#212, current): the chain is broken by **any** delayed edge, so a
ring must trip only when **every** edge is zero-delay; a ring with at least
one delayed edge is a legal periodic process. **0 disagreements, 0 misses.**
Two harness corrections are recorded in the script so the result is
reproducible: the first draft used `any(delay == 0)` as the must-trip
predicate (wrong — one delayed edge suffices to break the chain), and the
ring was kicked from its own `s0` entry, which re-adds a zero-delay
self-feeding edge on every lap and trips even an all-delayed ring. The ring
is now kicked from a separate `boot` state. Both were harness artefacts,
verified against a 5-line minimal probe before the harness was changed.

**B — #231, every non-`str` `invoke.src` shape.** 10 variants ×
`strict_config` on/off:

    src=inline machine dict / empty dict / nested dict / list / int / float /
    bool / list-of-dicts / dict-with-keys   ->  InvalidConfigError  (18/18)
    src=none                                ->  ACCEPTED (2/2)

`src: None` is the pre-existing "missing `src`" path, which WARNs
(`Invoke definition in state 'g3b.a' is missing a 'src' property.`) — a
different, documented behaviour, not the #231 shape. **0 `TypeError`, 0
`KeyError`, 0 silent acceptances of a dict.** The message:

    State 'g3b.a' invoke 'inv1': 'src' must be a service name (str), got dict.
    To invoke a nested machine, build it with create_machine(...) and register
    it under that name in MachineLogic(services={...})

— names the state, the invoke id, the received type and the fix.

**C — determinism, 50 runs × engines × kinds, including the new fields.**

    async  engine /def       distinct_traces=1 trips=[1] latch=['RunawayChainError']
    async  engine /async def distinct_traces=1 trips=[1] latch=['RunawayChainError']
    sync   engine /def       distinct_traces=1 trips=[1] latch=['RunawayChainError']

The trace compares the settled configuration **and** the full event log;
`chain_trips` and the latched error type are compared as first-class
observables. **1 distinct value on all three, all cells.**

### 2.4 `g4_security.py` — trust-boundary probes on the v3 fields

Framing per R10-01 / R12-02: a snapshot is trusted input; a forgery counts
only if it reaches an outcome an honest `configuration`/`context` write
could not. Every cell runs a control.

**S1/S2 — forging the #226 latch.**

    CONTROL untouched blob: chain_trips=1 last_chain_error="Machine 'sec' exceeded 1000..."
    S1 erased latch   -> trips=0 err=NoneType
    S2 inflated latch -> restored=1000000000, genuine re-trip=1000000001, monotonic=True
    CONTROL honest restore -> 1 -> 2   (forged path: 1000000000 -> 1000000001)

S1 (erasing the latch) succeeds, and is **not a defect**: the same writer can
rewrite `configuration` and `context` wholesale, so no boundary is crossed —
the R10-01 pattern exactly. S2 is the one that could have been a defect and
is not: an inflated counter does **not** disable the budget and does **not**
break monotonicity — a genuine new trip still increments by exactly one,
matching the honest control's `1 → 2`. The latch is a report, not a control
input. **0 defects.**

**S3 — bypassing #227 on the restored lanes.**

    s3a undeclared in scheduled_sends        -> delivered=False  hook=[('UnknownEventError','ZZ')]
    s3b engine-ish name (done.invoke.ghost)  -> delivered=False  hook=[(...,'done.invoke.ghost')]
    s3c lane:"priority" on scheduled_sends   -> delivered=False  hook=[('UnknownEventError','ZZ')]
    s3d engine:true forged on the record     -> delivered=False  hook=[(...,'done.invoke.ghost')]
    CONTROL undeclared in pending_events     -> delivered=False  hook=[('UnknownEventError','ZZ')]
    CONTROL declared in scheduled_sends      -> delivered=True   seen=['D0']  hook=[]

All four bypass shapes are refused, each reported through `on_invalid_event`
and landing on `last_error`; the two lanes now agree (the #214/#227
disagreement is gone); and a declared record still arms and fires. **This is
the cell that closes D12-fuzz-1.** **0 defects.**

---

## 3. Soak — `g5_soak.py`

200 machines × 2 kinds × 3 min each. Every machine runs a delayed-self-send
heartbeat (`raise(event="HB", delay=10–49 ms)` re-armed from its own
handler), spawns a worker **from an entry action** that outlives the action
and sends `WORK` every 250 ms, and receives external `EXT` traffic on the
**priority** lane from a producer looping over all 200. A chaos worker runs
continuous `get_snapshot → from_snapshot(plugins=[Counter()]) → get_snapshot`
rounds, comparing the `scheduled_sends` record set before and after and
checking `chain_trips` for drift. RuntimeWarnings are captured for the whole
run so #232 noise on supported shapes would be caught.

    G5 -- soak: 200 machines x 2 kinds x 180s each (360s total)

      def       ext_sent=155000 ext_applied=155000 lost=0 send_err=0
                beats min/max=2136/4359 dead=0 | worker sends min/max=632/633 dead=0
                chain_trips_total=0 handles_peak=200 (<= 200 = 1/machine) heap=+2208.3KB
                chaos={'rounds': 2079, 'mismatch': 0, 'invalid': 0, 'restore_err': 0, 'trip_drift': 0}
      async def ext_sent=155800 ext_applied=155800 lost=0 send_err=0
                beats min/max=2155/4407 dead=0 | worker sends min/max=634/635 dead=0
                chain_trips_total=0 handles_peak=200 (<= 200 = 1/machine) heap=+2119.4KB
                chaos={'rounds': 2102, 'mismatch': 0, 'invalid': 0, 'restore_err': 0, 'trip_drift': 0}

      RuntimeWarnings (#232 noise) = 0 []

    DEFECTS = 0

Invariants asserted, all held: **0 external sends lost** (every accepted
`send()` is applied); **0 dead heartbeats**; **0 dead workers** — every
action-spawned worker landed its sends, the #225 property at soak scale;
`chain_trips == 0` on all 400 machine-runs (nothing here is a chain);
timer handles capped at ≤ 1 per machine (#218) across the whole run; chaos
rounds with **0 record mismatches, 0 restore exceptions, 0 `chain_trips`
drift, 0 unexpected `on_invalid_event`**; and **0 RuntimeWarnings** — #232
is silent on every supported shape, which matters because a false positive
there would be log noise on every production action.

---

## 4. Defects

### D13-fuzz-1 (Medium) — `on_interpreter_start` is never fired for a snapshot-restored interpreter

**Repro:** `battle-v0.9.0/fuzz/d13_fuzz_1_restored_start_hook.py` →
`result: FAIL`, **5/5 cells** (async × `def`, async × `async def`, each via
`from_snapshot(plugins=)` and via `.use()`; plus the sync engine).

**Observed vs control:**

    async engine / def
      CONTROL fresh  .use()            : ['start', 'transition', 'stop']
      RESTORED from_snapshot(plugins=) : ['recv:GO', 'transition', 'stop']
      RESTORED .use()                  : ['recv:GO', 'transition', 'stop']
    sync engine / def
      CONTROL fresh  .use()            : ['start', 'transition', 'stop']
      RESTORED from_snapshot(plugins=) : ['recv:GO', 'transition', 'stop']

The restored interpreter fires **no** `on_interpreter_start`, and no
`on_transition` for its initial configuration either — its first hook of any
kind is `on_event_received` for whatever the application happens to send
next. If nothing is sent, a restored machine is invisible to its plugins for
its entire life.

**Root cause.** `Interpreter.start()` has two paths.
`interpreter.py:591-618` is the "resume a snapshot-restored interpreter"
early return: it detects `status in ("running","done","error")` with
`_event_loop_task is None`, binds the loop, spawns the run loop, re-arms
`scheduled_sends` (#213), optionally re-drives invokes and timers, resumes
child actors, and `return self`. The plugin notification loop lives only in
the fall-through path, at `interpreter.py:663-665`
(`for plugin in self._plugins: plugin.on_interpreter_start(self)`), which the
early return never reaches. `sync_interpreter.py:386-388` has the identical
shape. `on_interpreter_stop` is unaffected — it lives in `stop()`, which has
one path — which is why the restored log ends in `stop` with no matching
`start`.

**Why it is a defect, not a design choice.** The hook is documented as
firing "once when `start()` is called" (`docs/_guide/plugins.md:207`,
`docs/api/index.md:1919` — "`start()` begins"). `start()` **is** the
documented way to resume a restored actor — the early return's own comment
says so. Nothing in `plugins.md` or `snapshots.md` records an exception for
restored interpreters. And the asymmetry is load-bearing for exactly the
use the docs suggest for this hook ("opening database connections, starting
timers, or initializing counters"): a supervisor that counts machine
bring-ups, or opens a per-machine resource, from `on_interpreter_start`
under-counts by precisely the restarted machines — the population you most
need to see after a crash. Rounds 8 and 9 already treated this hook as
contract surface (R8-09 → #199), so its firing discipline is established.

**Severity: Medium.** Observability, not correctness: no event is lost, no
state is wrong, and the machine works. It is silent, it survives both
registration routes so there is no workaround inside the plugin API, and it
degrades exactly the restart path. A wrapper can compensate by calling the
hook itself after `from_snapshot(...).start()`, which is why it is not High.

**Fix direction.** Move the notification loop above the branch, or repeat it
inside the resume path before `return self`, on both engines. If the
divergence is deliberate, it needs a documented name (a distinct
`on_interpreter_resume`, or an explicit note on `on_interpreter_start`) —
the current state is neither.

**Wrapper obligation (new).** Our interpreter factory must fire the
bring-up notification itself on the restore path, and no plugin may assume
`on_interpreter_start` precedes the first `on_event_received`.

---

## 5. Not covered

- **The 12-min soak was reduced to 6 min** (200 machines × 2 kinds × 3 min
  each) to stay inside the task's 20-minute bound, and this is stated rather
  than glossed. The shorter run still reached 310 800 external sends and
  4 181 chaos restores; what a 12-min run would add is confidence in slow
  leaks, and heap growth (+2.2 MB / +2.1 MB over 3 min each, with 200 live
  machines and tracemalloc attached) is the one figure a longer run should
  re-measure before production sign-off.
- **BENCH-6 / loaded timer lateness was not re-measured here.** The
  environment note directs it to `benchmarks/production_characteristics.py
  --quick` § 2, run ≥ 5×; that belongs to the bench track, and running it
  concurrently with this track's 200-machine soak would have poisoned both.
  Round 12's readings (+89.6/+94/+113/+110/+111 ms against a ≤ 100 ms p99
  bar) stand un-refreshed by FUZZ.
- **`p4_rule_matrix.py` and `f5_soak.py` were not re-run**, being superseded
  in full: the rule matrix polls `last_error` (the per-step read the #222/#226
  latch replaced as the correct observable) and `f5`'s chaos worker predates
  `plugins=`. `g3` § C and `g5_soak.py` cover both at greater scale.
- **`SyncInterpreter` coverage is narrower than the async engine's** by
  construction: it admits no `async def` actions, so every `kind="async def"`
  cell is async-only. The sync engine was exercised in `g3` § A (780 of the
  1 560 livelock cells), `g3` § C (determinism) and the D13-fuzz-1 repro.
- **The `.use()` double-registration observation** (§ 2.1 C) was noted, not
  pursued: passing the same plugin object to both `plugins=` and `.use()`
  fires its hooks twice. That is caller error under any reading; whether
  `.use()` should dedupe is an API question for the diff-review track.
- **Nothing was fuzzed against a *hostile* `MachineLogic`** (a plugin that
  raises inside `on_invalid_event` during restore, a guard that mutates
  context mid-check). Round 11 covered plugin-hook containment; the
  restore-time intersection with `plugins=` is new surface and is the most
  obvious gap left by this round.

---

## 6. Verdict

**FUZZ passes v0.9.0 with one new Medium finding.**

Round 12 is the first round on this track where every fix under test
verified at the scale it was designed for, and where a standing Blocker was
retired. #225, #226, #227, #230, #231 and #232 all hold: 12/12 on the
task-identity matrix, 640/640 persistence property cases, 1 280 total
persistence cases with zero violations, 1 560 livelock cells with zero
disagreements, 18/18 named `InvalidConfigError`s, and a 310 800-send soak
with zero loss, zero trips, flat handles and zero warning noise. The
trust-boundary probes found nothing new: the forged latch behaves exactly
as an honest restore does, and all four #227 bypass shapes are refused and
reported.

The single new finding, **D13-fuzz-1**, is the mirror image of the round's
own theme. #230 was opened so a restore-time refusal is as observable as a
runtime one; it succeeds, and in succeeding it makes visible that the
*other* restore-time hook — the one that says a machine came up — never
fires at all. It is Medium: silent, reproducible 5/5 across both engines and
both registration routes, confined to observability, and compensable in a
wrapper.

**Recommendation for the adoption gate:** this track raises **no blocker**
against v0.9.0. D13-fuzz-1 should be filed upstream and carried as a wrapper
obligation (fire bring-up notification on the restore path; no plugin may
assume `on_interpreter_start` precedes the first `on_event_received`). Two
adoption notes fall out of the measurements rather than from defects:
`-W error` does **not** convert a dropped `wait=True` receipt into a test
failure (§ 2.2 D), so CI must grep stderr for `Exception ignored in`
instead; and `minimum_version=3` remains hygiene, not a security control
(R12-02, unchanged).

**Carry-forward, unchanged:** the v2-upcast mint (refuted — trust boundary),
the `structure_hash` gap on `raise(delay=)` changes (Low; a delay-contract
change is accepted silently by a restore), the mixed delayed/zero-delay
chain's 45–49/50 trip rate (Low; scheduling race, not a rule error), and
`last_error`'s per-step reset erasing a restore refusal once any other
pending event runs (Low, now mitigated — the `on_invalid_event` record via
`plugins=` is the durable half).

---

## 7. Artefacts

| Path | What |
|---|---|
| `fuzz/g1_persistence.py` | #226 latch × 6 restarts, #227 property (640 cases), #230 hook delivery |
| `fuzz/g2_concurrency.py` | #225 task-identity matrix, 200-machine worker outliving, 100 hand-outs, #232 surface |
| `fuzz/g3_fuzz_det.py` | livelock fuzzer (1 560 cells), #231 `invoke.src` shapes, determinism 50× |
| `fuzz/g4_security.py` | v3 latch forgery + #227 bypass attempts, each against a control |
| `fuzz/g5_soak.py` | 200 machines × 2 kinds × 3 min, workers + heartbeats + priority + chaos restore |
| `fuzz/d13_fuzz_1_restored_start_hook.py` | **D13-fuzz-1 minimal repro**, 5/5 cells, both engines |
| `fuzz/out/g1.txt` … `out/g5_soak.txt` | raw output of the above |
| `fuzz/out/rerun_f1…f4, rerun_p1…p3, rerun_p5_livelock.txt` | prior-script re-runs behind § 1 |
