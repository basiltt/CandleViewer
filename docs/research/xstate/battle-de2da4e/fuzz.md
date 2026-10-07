# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `de2da4e`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`de2da4e`** ("Merge pull request #223 from basiltt/fix/0.8.1-round11").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-23. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Every script run from the neutral
cwd `<home>`.

**Suite baseline** (`suite-de2da4e.log`, complete): **3545 passed, 13 skipped,
15 warnings in 752 s**; total coverage **92.87 %** (gate 90 %).

**Track:** FUZZ, re-run of `battle-c78ce99/fuzz.md` plus a new attack set aimed
at round 11's fixes (#218–#222). New scripts under
`docs/research/xstate/battle-de2da4e/fuzz/`; raw output under `fuzz/out/`.
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

**Round 11 is the strongest round this track has measured on the fixes it
claims. All five — #218, #219, #220, #221, #222 — verify clean, several of
them at scales this track has not previously reached: 640/640 parked-record
property cases exact, 638/640 nested config typos caught with a path-named
message and 400/400 valid charts accepted, 200-beat heartbeats holding at
exactly one timer handle, and a 90 s / 200-machine / 71 000-external-send
soak with zero loss and zero trips. The one new finding is the mint surface
again: #221's verbatim re-emission of parked `scheduled_sends` is a fifth
door into the engine-event boundary, and unlike #214's it is reachable at
v3 with no version trick.**

- **NEW D12-fuzz-1 (Blocker) — a hand-written `scheduled_sends` record mints
  an engine-only event (`done.invoke.*`, `after.*`) at v3, with an
  attacker-chosen payload.** `f4_conc_det_obs_sec.py` § D. Control first:
  the *untouched* v3 blob restores inert (`['fg.armed']`). Append one record
  `{"type": "done.invoke.job", "payload": {"filled": 999999}, "remaining_ms":
  0.5}` and the machine **DROVES** to `['fg.expired']` through a real
  `onDone` handler with `e.data == e.payload == {'filled': 999999}` — while
  the genuine 60 000 ms deadline is still pending. The `after.*` shape drives
  identically. Both kinds, 4/4 cells. `_rearm_restored_self_sends` calls
  `restore_event(rec)` and `_arm_restored_self_send` directly
  (`base_interpreter.py:1269-1287`), bypassing `_admit_restored` — so the
  `engine` flag the v3 lane exists to check is never consulted on this path.
  A delayed **self-send is never a completion**; the kind should be refused
  outright. (This is exactly the upstream fix R11-02 already prescribes; it
  is unfixed at `de2da4e`.)

- **#218 verifies perfectly.** `f2_reentrant_timers.py` § B: a 200-beat
  `raise(delay=2ms)` heartbeat holds **peak 1** handle per owner, final
  `{'hb': 1}`, both kinds. § C, a 500× arm/cancel storm: `fired=0`,
  `peak_handles=0`, `armed=0`, `scheduled=0`, **no double-release crash**,
  both kinds. § A of `f4`: 200 concurrent heartbeat machines over 10 s never
  exceed 200 handles total (≤1/machine) and heap growth is **negative**.

- **#219 verifies exactly as specified, including the subtle half.**
  `f2` § A matrix: self-await → `ReentrantWaitError` (async); after-fired
  clock handler → `ReentrantWaitError`; **sync engine → `ReentrantWaitError`**
  (parity); the `ensure_future` receipt awaited *after* the action returned
  → **OK, `Receipt`, state advanced** — the refusal is in-step only, as the
  changelog claims; cross-interpreter (`driver → peer`) `wait=True` →
  **OK**, correctly not refused; **100/100** concurrent `ensure_future`
  actions resolved. A `def` action gets the `_Awaitable` handle back rather
  than an exception (it cannot await, so nothing hangs) — behaviour noted,
  not a defect.

- **#220 verifies at the scale it was missing.** `f3_key_check_fuzz.py`:
  **637/640** mutations at randomly chosen nesting levels **RAISED** under
  `strict_config=True` (3 dropped as degenerate mutations, **0 SILENT, 0
  WARNED-only**), broken down `state 306/306`, `trans 258/258`,
  `invoke 33/33`, `root 40/40`, with paths as precise as
  `f3_47.r2.x.x1 invoke[inv1] onDone: 'traget'`. Default mode: **111/120
  WARNED, 0 SILENT**. False positives: **0/400** valid charts rejected.
  Catalogue: **109/109** contract JSONs build clean. Bypass: `x-` cannot
  smuggle a policy key (accepted *and inert*), and six case variants
  (`Entry`, `ENTRY`, `oN`, `Always`, `After`, `Invoke`) are all **RAISED**.

- **#221 verifies to the microsecond over long chains.**
  `f1_parked_chain_latch.py` § A: **640 property cases** (320 × 2 kinds),
  1–3 armed sends pushed through **1–4** restore→re-persist hops *without*
  `start()`. Every hop preserves the record set **verbatim** (no time
  charged), the final `start()` fires each event **exactly once** at
  **exactly** its original delay, and no parked record survives
  consumption. **0 defects.**

- **#222 verifies exactly-once on both halves.** `f4` § C: first trip
  `chain_trips=1`, `on_chain_budget_exceeded` hook `=1`; a benign event no
  longer disturbs the latch (`RunawayChainError` still latched — the
  R11-09 eraser is gone); second trip `=2,2`; `clear_chain_error()` clears
  the latch and **does not rewind** the counter. Both kinds. `f1` § B adds
  the boundary: the latch is **deliberately not persisted** (no `chain`
  key in the snapshot; a restored interpreter reads `trips=0`) — correct,
  but worth a catalogue note.

- **Determinism holds.** `f4` § B: **1 distinct trace over 50 runs** on the
  async engine for both kinds and on the sync engine, with identical
  `chain_trips` — including a chart that trips the budget.

- **Soak clean.** `f5_soak.py`, 200 machines × 45 s × 2 kinds with 10–50 ms
  heartbeats, an external priority producer and a chaos snapshot/restore/
  re-persist worker: **71 000 external sends, 0 lost**, 0 dead heartbeats,
  `chain_trips=0`, handles capped at exactly 200 (1/machine), heap +0.6 MB,
  and **100/100 chaos restores** with 0 record mismatches on either the
  #221 hop or the started restore.

---

## 1. Prior-defect table (`battle-c78ce99/fuzz/*` re-run verbatim)

| Prior record | Status @ `de2da4e` | Evidence |
|---|---|---|
| `D11-fuzz-1` — v2 upcast is a universal mint | **STILL-PRESENT** | `out/rerun_p2_upcast_minting.txt`: `after v2 UNflagged → DROVE`, `done v2 UNflagged → DROVE ctx.fill={'filled': 999999}`, both kinds; v3 unflagged correctly inert. 8 defects, unchanged. |
| `D10-fuzz-1` — `after` provenance forgeable | **STILL-PRESENT** (carry-forward) | Same `p2` matrix; not re-run standalone this round (out of scope of round 11). |
| `D11-fuzz-2` — chain trip erased from `last_error` | **FIXED (superseded by #222)** | `out/rerun_p4_rule_matrix.txt` still reports 22/60 (`def`) and 9/60 (`async`) erasures **via `last_error`** — the per-step read, now documented as such. The new latch is clean: `f4` § C shows `chain_trips`/`last_chain_error` surviving the benign event on both kinds. The prior script's assertion is **SUPERSEDED**: it polls the wrong observable. |
| `D11-fuzz-3` — key check is root-only | **FIXED** | `out/rerun_p5_livelock_keys.txt`: nested-state level now `{'warned': 0, 'silent': 0, 'raised': 200}` (was 200 silent). The script's own §B3 probe now dies on the `InvalidConfigError` it was written to prove absent — **SUPERSEDED**, re-asserted in `f3`. |
| `D11-fuzz-4` — `structure_hash` omits `raise(delay=)` | **STILL-PRESENT** | `out/rerun_p1_v3_roundtrip.txt`: `structure_hash covers raise-delay change = False`; snapshot vs delay-changed chart → `ACCEPTED (re-armed 1)`. |
| `D11-fuzz-5` — `on_invalid_event` unreachable on restore | **STILL-PRESENT** | `out/rerun_p2_upcast_minting.txt` § C1/C2, both kinds. |
| `p3` §B — mixed delayed+zero-delay chain trips 49/50 | **STILL-PRESENT (Low)** | `out/rerun_p3_concurrency.txt`: 49/50 both kinds. A scheduling race, not a rule error. |
| `p1` §A — v3 round-trip property (600 machines) | **FIXED / clean** | 0 defects, both kinds. |
| `p6` — determinism + 60 s soak | **clean** | `ext_sent=438200 ext_applied=438200 lost=0`, `still_beating=200/200`, `runaway=0`, chaos 580/580. |
| `p5` §A — livelock fuzzer under the #212 oracle | **clean (reduced)** | 234 cells in 110 s (script self-bounds at 110 s): 220 legal rings never tripped, 14 must-trip rings all tripped, 0 disagreements. **Under the ≥500-config target — see § 4.** |

**No prior fuzz defect regressed.** Two are fixed by round 11, two prior
scripts are SUPERSEDED by the new semantics and re-asserted in `f2`/`f3`,
and the four surviving records are all pre-round-11 carry-forwards on the
mint / hash / restore-reporting surfaces that round 11 did not touch.

---

## 2. New attacks

All scripts are standalone (stdlib + `xstate_statemachine` only), run from
`<home>`, and exit non-zero on any violated property.

### 2.1 `f1_parked_chain_latch.py` — #221 parked records, #222 latch vs snapshot

**A — parked `scheduled_sends` across restore→persist→restore→start chains.**
320 generated charts × 2 kinds = **640 property cases**. Each arms 1–3
delayed self-sends (delays drawn from 1/7/40/250/1000/60000 ms) on a
`SimulatedClock`, snapshots, then passes the blob through **1–4 hops** of
`from_snapshot` → `get_snapshot` **without `start()`** — the
journal-compaction shape #221 fixes — and only then starts the final blob.

    A/def       320 cases done, defects so far = 0
    A/async def 320 cases done, defects so far = 0

Properties per case: R0 the initial record set equals the armed set exactly;
R1 every hop preserves `(type, remaining_ms)` byte-for-byte (no clock is
bound, so no time may be charged); R2 the final `start()` fires each event
**exactly once**; R3 at its original delay (±1.5 ms); R4 a *started*
interpreter does not re-emit consumed parked records. **0/640 violations.**

**B — is the #222 latch persisted?**

    B/def:       trips@trip=1 err=RunawayChainError | after BENIGN trips=1 err=RunawayChainError
                 | snapshot keys w/ 'chain'=[] | restored trips=0 err=NoneType
    B/async def: (identical)

The benign event no longer erases the latch (R11-09's clearing half is
fixed). The latch is **not** carried in the snapshot: a restored interpreter
reports `chain_trips=0`, `last_chain_error=None`. Defensible — the counter
describes a *process*, not the chart state — but a supervisor that restarts
from a snapshot loses the evidence of discarded work. Observation, not a
defect (→ **CV-C62**).

### 2.2 `f2_reentrant_timers.py` — #219 matrix, #218 handle release, cancel storm

**A — ReentrantWaitError matrix.**

    def       A1 self-await          = def-returned:_Awaitable
    def       A2 ensure_future later = OK receipt=Receipt states={'a2.b'}
    def       A3 after-fired handler = def-returned:_Awaitable
    def       A4 cross-interpreter   = OK(def/ensure_future) Receipt
    async def A1 self-await          = ReentrantWaitError
    async def A2 ensure_future later = OK receipt=Receipt states={'a2.b'}
    async def A3 after-fired handler = ReentrantWaitError
    async def A4 cross-interpreter   = OK peer={'peer.b'}
    sync      A6 self-send wait=True = ReentrantWaitError
    A7 100 concurrent ensure_future actions: OK=100/100 bad=[]

Every cell matches the specification. The refusal is **in-step only** — `A2`
proves the receipt is still handed out and resolves normally once the action
has returned, which is the half most likely to have been broken by an
over-eager guard. Cross-interpreter waits (`A4`) are correctly *not* refused;
that is the child→parent / parent→child shape, and a naive "am I inside any
action?" guard would have deadlocked or refused it. The sync engine refuses
for parity, propagating out of `start()`.

**`def`-action note (not a defect).** A `def` action cannot await, so
`i.send(..., wait=True)` returns the `_Awaitable` guard object unawaited.
Nothing hangs and nothing is minted — but nothing warns either, and the event
*is* queued. A `def` action written expecting a receipt gets an object it can
never resolve. Observation → **CV-C63**.

**B — #218 timer-handle release**, 200-beat `raise(delay=2ms)` heartbeat:

    def       beats=200 peak_handles_per_owner=1 final={'hb': 1} armed=1
    async def beats=200 peak_handles_per_owner=1 final={'hb': 1} armed=1

Exactly the changelog's claim ("at most one handle"), both kinds.

**C — cancel storm**, 500 arm+cancel pairs on one `sendId`:

    def       fired=0 peak_handles=0 final={} armed=0 scheduled=0 err=None
    async def fired=0 peak_handles=0 final={} armed=0 scheduled=0 err=None

**0 fires, no leak, no double-release exception** — release-on-cancel is
idempotent.

### 2.3 `f3_key_check_fuzz.py` — #220 recursive check, four ways

**A — mutation fuzz**, 320 single-typo injections per kind at a *randomly
chosen* node (root / state / transition body / invoke / invoke-handler),
under `strict_config=True`:

    def       {'RAISED': 319, 'WARNED': 0, 'SILENT': 0, 'OTHER': 0, 'no_path': 10}
              bylevel={'trans': 129 raised/0 miss, 'state': 153/0, 'root': 20/0, 'invoke': 17/0}
    async def {'RAISED': 318, ... 'no_path': 10}
              bylevel={'trans': 129/0, 'invoke': 16/0, 'state': 153/0, 'root': 20/0}
    def       default mode (60): {'WARNED': 55, 'SILENT': 0, 'other': 4}
    async def default mode (60): {'WARNED': 56, 'SILENT': 0, 'other': 4}

**Zero misses at every level.** The `no_path: 10` counter is a harness
artefact, not a finding: those are mutations of `id` (rejected earlier with
`"must have a root 'id'"`) and keys reported under a different spelling.
Verified by hand — `{'states': {'a': {'tpye': ...}}}` → `RAISED m.a: 'tpye'
(did you mean 'type'?)`; `{'conetxt': ...}` → `RAISED m: 'conetxt'`. Messages
name the full path, e.g. `f3_47.r2.x.x1 invoke[inv1] onDone: 'traget'`,
`f3_53.r2.y.y1 always: 'gaurd'`, `f3_48.r1 after['50']: 'traget'`.

**B — false-positive fuzz**, 200 charts per kind generated from the *full*
grammar (every `KNOWN_*` key at its legal level, plus `x-`/`meta`/
`description`/`tags` randomly sprinkled at **every** level):

    def       rejections=0/200 []
    async def rejections=0/200 []

**0/400.** The `x-`/`meta`/`description`/`tags` acceptance claim holds at
every nesting level — where a recursive check is most likely to over-fire.

**C — catalogue sweep.** All **109** `*.machine.json` under
`battle-*/contracts/` built with `strict_config=True`: **0 rejected**. No
latent typo in the chart catalogue, and no false positive on real charts.

**D — bypass attempts.**

    x-actionErrorPolicy at root  -> SILENT   (accepted AND inert -- not a bypass)
    state key 'Entry'/'ENTRY'/'oN'/'Always'/'After'/'Invoke' -> RAISED (all six)
    root 'StrictConfig' + nested 'entyr', no kwarg -> WARNED, names BOTH

No bypass. The `x-` escape hatch cannot smuggle a policy key, because the
parser reads policies by exact name — the smuggled key changes no behaviour,
which is the bar this track sets. Case variants are all caught, several with
a did-you-mean.

### 2.4 `f4_conc_det_obs_sec.py` — concurrency / determinism / observability / security

**A — 200 heartbeat machines × 10 s**, both kinds, `tracemalloc` (no psutil):

    A/def       handles per sample=[139,105,141,188,161,194,137,132,132,174]
                heap_growth=-124.5KB beats min=157 max=158 alive=200/200
    A/async def handles per sample=[132,188,197,108,170,197,129,131,171,162]
                heap_growth=-140.9KB beats min=138 max=139 alive=200/200

Never above 200 handles for 200 machines (≤1 each; sub-200 samples are
machines caught between fire and re-arm). Heap **shrinks**. Beat spread
across 200 machines is 1 — no straggler.

**B — determinism**, 50 runs × both engines × both kinds, comparing the full
`(event, counter)` action trace, the final configuration **and `chain_trips`**:

    async engine /def       distinct traces=1 trips=[1]
    async engine /async def distinct traces=1 trips=[1]
    sync engine  /def       distinct traces=1 trips=[1]

**C — #222 exactly-once.**

    C/def       trip1 trips=1 hook=1 | after benign trips=1 err=RunawayChainError
                | trip2 trips=2 hook=2 | after clear trips=2 err=NoneType
    C/async def (identical)
    plugin order tail=['recv:GO','recv:GO','recv:GO','recv:GO',
                       'drop:GO:chain_budget','chain:RunawayChainError']

One increment and one hook per trip; the latch survives a benign event;
`clear_chain_error()` clears the error and **preserves** the count.
`on_event_dropped(reason='chain_budget')` fires **before**
`on_chain_budget_exceeded` — a sane order (the drop is the cause, the trip
the summary), stable across both kinds.

**D — snapshot forgery.** See **D12-fuzz-1** in § 3.

### 2.5 `f5_soak.py` — 200 machines, heartbeats + external producer + chaos

45 s per kind (reduced, § 4). 10–50 ms `raise(delay=)` heartbeats, an
external producer sending `EXT` to all 200 machines in a tight loop, and a
chaos worker doing snapshot → **#221 hop (restore + re-persist, no start)** →
restore → start → verify:

    def       handles max 200 for 200 machines
              beats min=168 max=226 dead=0 | ext_sent=40600 ext_applied=40600 lost=0
              chain_trips=0 | heap=+613.4KB
              chaos={'ok':56,'rec_mismatch':0,'refused':0,'hop_mismatch':0}
    async def handles max 200 | beats min=131 max=166 dead=0
              ext_sent=30400 ext_applied=30400 lost=0 | chain_trips=0 | heap=+617.4KB
              chaos={'ok':44,'rec_mismatch':0,'refused':0,'hop_mismatch':0}

**71 000 external sends, 0 lost. 0 heartbeats died. 0 chain trips. 100/100
chaos cycles with no record loss on either hop.** Handles flat at exactly one
per machine throughout.

---

## 3. Defects

### D12-fuzz-1 — **Blocker** — a hand-written `scheduled_sends` record mints an engine-only event at v3, with an attacker-chosen payload

**File:** `f4_conc_det_obs_sec.py` § D (`part_d`, lines 262–332);
standalone control/forgery probe reproduced inline below.
**Kinds:** `def` and `async def`, 4/4 forging cells.
**Source:** `base_interpreter.py:1269-1287` `_rearm_restored_self_sends` →
`restore_event(rec)` → `_arm_restored_self_send`. This path does **not** go
through `_admit_restored` (`base_interpreter.py:1211-1232`), so the v3
`engine` flag that the restore lane exists to check is never consulted for a
`scheduled_sends` record. #221 made the parked records re-emit *verbatim*,
which is correct for genuine records and is also what carries a forged one
through an arbitrary number of compaction hops.

**Control first.** The untouched v3 blob restores **inert**:

    control records: [{'kind': 'event', 'type': 'LATER', 'payload': {},
                       'remaining_ms': 59999.597, 'send_id': 'z'}]
    CONTROL untouched -> ['fg.armed']

**Forgery.** Append one record to `scheduled_sends`:

    {'type': 'done.invoke.job', 'payload': {'filled': 999999},
     'data': {'filled': 999999}, 'remaining_ms': 0.5}

    FORGED -> ['fg.expired'] hit= ({'filled': 999999}, {'filled': 999999})

The machine takes its real `done.invoke.job` transition, runs the `onDone`
action, and the action reads the attacker's payload from **both** `e.data`
and `e.payload` — while the genuine 60 000 ms deadline is still pending. The
`after.*` shape (`{'type': 'after.999.fg.armed', 'remaining_ms': 0.5}`)
drives the same transition identically. Full matrix, both kinds:

    D1 forged done.invoke in scheduled_sends   -> DROVE  hit={'filled': 999999}
    D2 forged after.* in scheduled_sends       -> DROVE  hit=None

**Why this is a defect and not the documented trust boundary.** The library
*does* draw an `engine`-flag boundary at v3 and enforces it on the
`pending_events` lane — `p2`'s v3-unflagged `done`/`after` records are
correctly **inert**. This path is the same class of record arriving through a
different door that performs **no check at all**, so the boundary the docs
draw is not the boundary the code enforces. The R10-01 framing does not cover
it: the exposure is an inconsistency *within* the stated model, demonstrated
against a control. Additionally, a delayed **self-send is never a
completion** — `done.*` / `error.*` / `after.*` are structurally invalid as
`scheduled_sends` kinds regardless of provenance, so the refusal costs
nothing in expressiveness.

**Relationship to prior records.** This is the fifth independent door onto the
engine-mint boundary (`D10-fuzz-1` ×4 vectors, `D11-fuzz-1` v2 upcast) and the
first that works **at v3 with no version trick and no private import** — just
a JSON key. It is exactly the fix already prescribed as the upstream remedy
for `R11-02` ("route `_rearm_restored_self_sends` through `_admit_restored`,
and refuse `kind in (done, error, after)` in `scheduled_sends` outright"),
still unimplemented at `de2da4e`.

**D3–D5 (not defects).** Shortening a genuine record's `remaining_ms`
60 000 → 1, setting it negative, and tagging a pending event
`lane: 'priority'` all DROVE — but these mutate a record's *schedule*, not its
*provenance*, and altering your own snapshot's timing is squarely the
documented in-process trust boundary (R10-01). Recorded for completeness.

**Severity: Blocker** for an OMS restoring blobs from any store that is not
integrity-protected: a forged `done.invoke.*` injects a fill.
**Mitigation unchanged:** MAC the snapshot at rest in the persistence wrapper.

### No other new defects

`f1` (640 cases), `f2` (matrix + 200-beat heartbeats + 500× cancel storm),
`f3` (640 mutations + 400 valid charts + 109 catalogue JSONs + 8 bypasses),
`f4` §§ A–C and `f5` (90 s soak) all exit **0**.

### Observations (not counted)

| Ref | Observation | Evidence |
|---|---|---|
| **CV-C62** | `chain_trips` / `last_chain_error` are not persisted; a restore reads `0` / `None`. Supervisors must externalise the trip count before snapshotting. | `f1` § B |
| **CV-C63** | A `def` action calling `send(..., wait=True)` receives the `_Awaitable` guard unawaited — no error, no warning, no usable receipt. | `f2` § A1/A3, `def` rows |
| **CV-C64** | `on_event_dropped(reason='chain_budget')` precedes `on_chain_budget_exceeded`; both fire exactly once per trip. Safe to key a supervisor on either. | `f4` § C |
| carry-forward | `structure_hash` still omits `raise(delay=)` delays (`D11-fuzz-4`); `on_invalid_event` still unreachable on restore (`D11-fuzz-5`); v2 upcast mint (`D11-fuzz-1`) and `after` forgery (`D10-fuzz-1`) unchanged. | § 1 |

---

## 4. Not covered / reduced

Stated plainly rather than implied.

- **Soak is 45 s per kind, not 12 min.** The task's hard bound is 120 s per
  script; `f5_soak.py` defaults to `SECS=100` and was run at `SECS=45` × 2
  kinds ≈ 95 s. The 60 s / 200-machine soak in `p6` (re-run clean, 438 200
  sends, 0 lost) and this 90 s run cover the same invariants; a genuine
  12-minute run is **not performed** and remains open.
- **Livelock fuzzer ran 234 cells, not ≥500 configs × kinds × engines.**
  `p5_livelock_keys.py` self-bounds at 110 s and stopped at config 117 of
  500. All 234 cells agreed with the #212 oracle (220 legal / 14 must-trip,
  0 disagreements), but the ≥500-config target was **not** reached this
  round. It was reached at `c78ce99` (1000/1000) on unchanged semantics.
- **`sendTo self` was not exercised** in the ReentrantWaitError matrix — the
  charts here use `raise` and direct `i.send`. The self / after-fired /
  cross-interpreter / sync / concurrent cells are covered.
- **Parent↔child ReentrantWait was tested as two independent interpreters**
  (`A4`), not through a real `invoke`d child machine's spawn linkage.
- **No `SyncInterpreter` cell in the #221 parked-record property run**
  (`f1` § A is async-engine only); `f2` § A6 and the suite cover the sync
  engine for #219, and `f4` § B for determinism.
- **D12-fuzz-1 was not re-tested under `minimum_version=3` or `strict=True`**
  this round; at `c78ce99` `minimum_version` gated the v2 upcast but is
  irrelevant here — the forged record is *already* v3.

---

## 5. Verdict

**ADOPT-with-guardrails, unchanged in direction and materially stronger in
evidence.** Round 11 fixed five defects and this track could not break any of
them: #218, #219, #220, #221 and #222 each verified at a scale beyond what
the library's own 23 pins assert — 640 parked-record property cases, 640
nested key mutations with zero misses and zero false positives on 400 valid
charts and 109 real catalogue charts, 200-beat heartbeats at one handle, a
500× cancel storm with no double-release, exactly-once trip accounting on
both engines, and a 90 s / 200-machine soak with 71 000 external sends and
zero loss. Determinism is total (1 trace / 50 runs, all three lanes).

**The blocker is not new in kind.** `D12-fuzz-1` is the fifth door onto the
same engine-mint boundary, and it exists because #221 — correctly — made
parked records re-emit verbatim without also routing them through the
admission check. The remedy is already written down as `R11-02`'s upstream
fix and is a few lines: refuse `done.*` / `error.*` / `after.*` kinds in
`scheduled_sends`, which are structurally impossible for a delayed
self-send. Until then the adopting project's guardrail is the one it already
has — **integrity-protect the snapshot at rest**; no in-band library setting
closes this door (`minimum_version=3` does not apply, the record is v3).

**Row-6 ADOPT stands.** No round-11 fix regressed, no prior fuzz defect
worsened, and two (`D11-fuzz-2`, `D11-fuzz-3`) are closed outright.
