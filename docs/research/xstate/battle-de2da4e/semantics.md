# Battle track: SEMANTICS @ `de2da4e`

**Library:** `_ref/xstate-statemachine` @ `de2da4e` (unreleased 0.8.1;
`__version__` still reports 0.8.0 — keyed on the commit).
**Scope:** round-12 re-verification of the round-11 semantics defects, a full
re-run of the prior semantics suite on **both action kinds**, plus new attacks
aimed at this round's five fixes — **#218** (timer handle released on
fire/cancel), **#219** (`ReentrantWaitError`), **#220** (recursive unknown-key
check), **#221** (parked `scheduled_sends` re-emitted until `start()`) and
**#222** (sticky chain-trip latch).

**New scripts** (standalone — stdlib + `xstate_statemachine` only, every
helper inlined, run from neutral cwd `C:/Users/basil`):

| Script | Attacks |
|---|---|
| `battle-de2da4e/semantics/r_reentrant_latch.py` | `R1`–`R7` — #219 matrix, escape hatch, cross-interpreter, #222 latch, observability |
| `battle-de2da4e/semantics/n_persist_keys.py` | `N1`–`N5` — #221 chain property, #220 recursive-key fuzzer, false-positive grammar sweep, catalogue sweep, `strict_config` bypass |
| `battle-de2da4e/semantics/w_handles_cancel.py` | `W1`–`W3` — #218 at scale, cancel storm, fire-vs-cancel race |
| `battle-de2da4e/semantics/t_determinism.py` | `T1`–`T2` — determinism incl. `chain_trips`, hook ordering |

Prior-suite output under `semantics/prior/`, machine-readable new results under
`semantics/results/`.

**Suite baseline (shared run):** `suite-de2da4e.log` — **3,545 passed, 13
skipped**, total coverage **92.87 %** (gate 90 %), 752 s. Complete.

---

## 1. Prior-defect table (round 11 → round 12)

| Prior | Title | R11 severity | **R12 status** | Evidence |
|---|---|---|---|---|
| **D11-semantics-4** | A `raise(delay=)` heartbeat leaks one timer handle **per beat**, unboundedly | High | **FIXED (#218)** | The round-11 repro, unmodified, now exits **0**: `raise_delay/plain` and `/async` both report `timer_handles_retained: 0`, `retained_per_beat: 0.0` over ~630 beats. Confirmed at scale by the new `W1`: **200 machines × 10 s = 93,168 beats**, `handles_max_per_machine = 1`, **RSS Δ = 0.00 MB** (was **+753 MB** in the round-11 soak) |
| **D11-semantics-3** | #216 validated only the top level; a misspelled key inside a state was silently dropped, even under `strict_config=True` | Medium | **FIXED (#220)** | The round-11 repro now reports `REPRODUCED: true` **only for the default (warn) disposition**, and `strict_config` refuses both cells with a path-named message (`n.a: 'onn' (did you mean 'on'?)`). See the harness correction below — the "still silent" reading is an artefact, not a residue. New `N2` proves the check reaches **11/11** nesting levels |
| **D11-semantics-1** | `"version": 2` in the payload mints a trusted engine event (forged `after` fires a 24 h timer) | High | **STILL-PRESENT — unchanged** | Prior `p_persistence::P3` re-run at `de2da4e` is byte-identical: `after_v2/plain` and `after_v2/async` both reach `t.fired_after` with `last_error = None`, while the same record at v3 is refused (`UnknownEventError`). #218–#222 do not touch `persistence.py`'s upcast. Not re-counted as a new defect |
| **D11-semantics-2** | #214's `on_invalid_event` on restore fires **zero** times; the hook is unreachable by construction | Low | **STILL-PRESENT — unchanged** | Prior `P4` re-run: `undeclared/plain` and `/async` both show `last_error = UnknownEventError`, event dropped, `invalid_hook: []`. Unchanged; `from_snapshot` still has no `plugins=` parameter |
| **D10-semantics-1 / R9-01** | An engine completion / `after` event re-typed by `_replace` | High | **STILL-PRESENT — unchanged** | `s_semantics_sec::S2` passes as written (it pins the *current* behaviour); the `_replace` route is untouched by this round. Carried |

> ⚠️ **Harness correction, recorded.** The round-11 `strict_config` /
> unknown-key harnesses (`d11_sem_3_*`, and my first draft of `N2`/`N5`)
> captured findings with `warnings.catch_warnings`. The unknown-key report is
> emitted through **`logging`** (`validation.py` → `logger.warning`), not the
> `warnings` module, so a `catch_warnings` harness sees **nothing** and reports
> "not warned" for a key that *was* warned. `N2`/`N5` capture the
> `xstate_statemachine` logger instead (and re-enable logging for the duration,
> since these scripts disable it globally). Any round-11 "silently accepted"
> cell that rested on `catch_warnings` should be re-read as **"not observed by
> that harness"**; the *behavioural* half of D11-semantics-3 (the transition
> genuinely did nothing) was real and is what #220 fixes.

### 1b. Prior-suite whole-run at `de2da4e`

| Script | Result | Note |
|---|---|---|
| `battle-c78ce99/semantics/c_concurrency.py` | **4/4 PASS** (was 4/4) | C1–C4 unchanged |
| `battle-c78ce99/semantics/s_semantics_sec.py` | **4/4 PASS** (was 4/4) | S1–S4 unchanged |
| `battle-c78ce99/semantics/f_fuzz.py` | **PASS — 666 runs, 0 hangs** | reduced from 500 to **250 configs** (see §4); oracle separation still perfect |
| `battle-c78ce99/semantics/p_persistence.py` | **1/3 PASS** (was 1/3) | `P3` / `P4` fail identically — the two carried defects above |
| `repro/d11_sem_212_heartbeat.py` | exit **0** | #212's rule still holds |
| `repro/d11_sem_4_timer_handle_leak.py` | exit **0**, `REPRODUCED: false` | #218 confirmed |
| `repro/d11_sem_3_nested_keys_silent.py` | exit 1, but `strict_config` now **refuses** | #220 confirmed (see correction) |

**No regression.** Every round-11 check that passed still passes.

### 1c. SUPERSEDED scripts (#219)

No prior semantics script awaited `send(..., wait=True)` on its own
interpreter, so **nothing in the carried suite is superseded by #219**. The
new behaviour is covered positively by `R1`–`R5` rather than by rewriting an
old assertion.

---

## 2. New attacks

### 2a. #219 — `ReentrantWaitError` (`r_reentrant_latch.py`, 7/7 PASS)

| ID | Attack | Result |
|---|---|---|
| `R1` | Self-send `wait=True` from an action, both engines × both kinds | **PASS** — `async def` action on the async engine → **`ReentrantWaitError`** with a diagnostic naming the machine and event; `SyncInterpreter` → **`ReentrantWaitError`**. No hang anywhere (5 s watchdog) |
| `R4` | Same, from inside an **`after`-fired** handler's action (engine-minted event, not the start descent) | **PASS** — `ReentrantWaitError` on the async kind; the guard is not specific to the initial descent |
| `R2` | Escape hatch: `asyncio.ensure_future(i.send("P", wait=True))` issued inside an action, awaited **after** the step | **PASS** — resolves to a real `Receipt`, machine reaches `r.b`. The documented hatch works |
| `R5` | **100 concurrent** interpreters all running the `ensure_future` pattern | **PASS** — 100/100 resolve, **0** failures, **1** distinct configuration. The guard does not false-trip under concurrency |
| `R3` | **Cross-interpreter** `wait=True` (a different interpreter, the child→parent / parent→child shape) issued from inside an action | **PASS** — resolves (`cross: OK`), peer reaches `peer.b`. The guard keys on the **owning** interpreter only, exactly as promised |

> 🧪 **A shape the CHANGELOG does not spell out, worth pinning.** On the
> **async engine**, a **`def`** (non-async) action calling
> `i.send("P", wait=True)` gets the *guarded awaitable* handed back and
> **cannot** await it — so it returns normally and the event is still queued
> (`R1` cell `async_engine/plain = RETURNED`, machine reaches `r.b`). That is
> the `R2` escape-hatch shape arrived at by accident, and it is safe: the
> guard fires on **await**, not on call. Recorded so the matrix is not
> misread as an inconsistency.

### 2b. #222 — chain-trip latch and observability (same script)

| ID | Attack | Result |
|---|---|---|
| `R6` | `chain_trips` monotonic; `last_chain_error` **sticky** across a later benign handled event; `clear_chain_error()` clears the latch and **not** the counter; `on_chain_budget_exceeded` **exactly once** per trip — both engines | **PASS** — identical on async and sync: `trips = 1`, latch `RunawayChainError` **after** the benign event (while `last_error` has already reverted to `None` — the documented per-step read), `clear_chain_error()` → latch `None`, `trips` still **1**, hook count **1** |
| `R7` | Does the latch survive a snapshot? (probe) | **Informational, not a defect** — `chain_trips` restores to **0**, latch `None`, and the snapshot carries **no** chain keys. Nothing in the CHANGELOG promises the latch is persisted; `chain_trips` is documented as an interpreter counter. Recorded as a gap for the wrapper (scrape before `stop()`), not filed |
| `T2` | `on_event_dropped` / `on_chain_budget_exceeded` **ordering**, 50 runs × 3 lanes | **PASS** — **1** distinct sequence per lane; **exactly one** `C` hook per trip; the `D` hook (`reason = "chain_budget"`) fires **immediately before** each `C`. Stable across `{async, sync}` × `{def, async def}` |

### 2c. #221 / #220 — persistence chains and the recursive key check (`n_persist_keys.py`, 5/5 PASS)

| ID | Attack | Result |
|---|---|---|
| `N1` | **#221 chain property, 300 cases**: `restore → persist (NO start) → … → restore → start`, 1–4 hops, random delays and elapsed times on a `SimulatedClock` | **PASS — 300/300, 0 bad.** The record survives **every** hop with `remaining_ms` exact to **1e-6 ms** and its `send_id` intact; after the final `start()` it fires **neither** at `remaining − 0.001` **nor** twice, and **no armed record is left** afterwards (exactly-once). This is the property #221 exists to establish, at chain depth the fix's own tests do not reach |
| `N2` | **#220 typo fuzzer at every nesting level** — root, state, nested state, parallel region, `on`, `always`, `after`, `onDone`, `invoke`, `invoke.onDone`, `invoke.onError` | **PASS — 11/11 caught**, warned by default *and* refused under `strict_config`, **with the path named**: `m.r1.y: 'exitt'`, `m.r2.pa: 'invokee'`, `m.r1.y on['GO']: 'tpye'`, `m.r1.y always: 'guardd'`. Did-you-mean hints on 10/11 (`tpye` → no hint; edit distance to `type` is 2 with a transposition, below `difflib`'s cutoff — cosmetic) |
| `N3` | **False-positive sweep**: 200 valid charts generated from the **full** key grammar, with `meta` / `description` / `tags` / `x-*` sprinkled at **12** levels and every legal root policy set, under `strict_config=True` | **PASS — 0 rejections, 0 unknown-key warnings.** The recursion does not over-reach |
| `N4` | Recursive check over **every** catalogue `.machine.json` in the three prior contract sets | **PASS — 54 files, 0 rejections, 0 warnings.** No adoption chart is disturbed by #220 |
| `N5` | **`strict_config` bypass**: `x-`-smuggling a *policy* key at root/state/nested level; **key-case variants** (`MaxIterations`, `Entry`, `ON`, `Strict`, `Invoke`, `AFTER`) | **PASS** — `x-maxIterations: 1` is accepted **and inert** (`max_iterations` stays 30); all **6** case variants are reported as unknown and refused under `strict_config`, 5/6 with a hint to the real key. A payload cannot smuggle policy through either door |

### 2d. #218 at scale, and cancel storms (`w_handles_cancel.py`, 3/3 PASS)

| ID | Attack | Result |
|---|---|---|
| `W1` | **200 heartbeat machines** (100 `def` + 100 `async def`) × **10 s** of `raise(delay=10)` beats | **PASS** — **93,168 beats** (465/machine), `handles_max_per_machine = **1**`, total retained oscillates around 130–197 for 200 machines (i.e. ≤1 each, transient), **200/200 still beating**, **RSS Δ = 0.00 MB**. Contrast round 11: 1 handle **per beat** and +753 MB |
| `W2` | **Cancel storm**: 3,000 arm/cancel cycles on a single send id, both engines | **PASS** — no exception, `handles ≤ 1`, `armed = 0`, `scheduled = 0`, machine still in `cz.a` on **both** engines. No double-release, no accounting drift |
| `W3` | **Fire-vs-cancel race**: cancel a 1 ms send at its due instant, 500 rounds | **PASS** — **497** fires of 500 arms (3 genuinely cancelled in the race window), **0** exceptions, **0** double-fires, `handles = 0`, `armed = 0`, `chain_trips = 0` |

### 2e. Determinism (`t_determinism.py`, 2/2 PASS)

`T1`: **50 identical runs × {async, sync} × {`def`, `async def`}** of a chart
that trips the chain budget — **1 distinct trace** in all three lanes,
including the drop list, `chain_trips = 1` and the latch
(`RunawayChainError`). The sync engine's trace differs from the async one by
the expected leading-descent offset and is itself perfectly stable.

### 2f. Livelock fuzz, re-run

`f_fuzz.py` at 250 configs → **666 runs, 0 hangs, 0 findings**, oracle
separation unchanged (`always` / `raise0` / `mixed` / `invoke` all trip;
`raise_delay` / `after` never trip and stay alive).

### 2g. Soak (`k_soak.py` re-run, 100 s — reduced, see §4)

200 machines (100 `def` + 100 `async def`), 10–50 ms `raise(delay=)`
heartbeats, a continuous external priority producer, and chaos v3
snapshot/restore/re-persist every 2 s:

| Metric | R11 @ `c78ce99` (90 s) | **R12 @ `de2da4e` (100 s)** |
|---|---|---|
| External sent / fired / **dropped** | 787,400 / 787,400 / **0** | 196,400 / 196,400 / **0** |
| Heartbeats still alive | 200 / 200 | **200 / 200** |
| Runaway errors | 0 | **0** |
| Chaos restores | 320/320 ok | **240 / 240 ok**, 137 carried `scheduled_sends` |
| **RSS growth** | **+753 MB** ← the defect | **+11.1 MB** |

The soak's headline finding of round 11 is gone. The residual +11 MB over
100 s at 97.5 % CPU is ordinary allocator/arena drift, not the linear
per-beat growth #218 fixed (which `W1` now measures at **0.00 MB** over
93,168 beats with no external traffic).

---

## 3. Defects

**No new semantics defect was found this round.** Every attack aimed at
#218, #219, #220, #221 and #222 landed clean, several at higher volume than
the fixes' own tests: 300 chain-property cases, 11/11 nesting levels,
54 catalogue charts, 200 machines × 93k beats, 3,000 cancel cycles, 500 race
rounds, 150 determinism runs.

**Carried, not re-counted** (unchanged at `de2da4e`, evidence in §1):

| ID | Severity | One line |
|---|---|---|
| **D11-semantics-1** | High | `"version": 2` in the payload mints a trusted engine event — the same forged `after` record refused at v3 fires a 24 h timer at v2 (`persistence.py:436-447`) |
| **D11-semantics-2** | Low | #214's `on_invalid_event` on restore fires zero times; `from_snapshot` has no `plugins=` (`base_interpreter.py:1822`) |
| **D10-semantics-1 / R9-01** | High | An engine completion / `after` event re-typed by `_replace` |

Two round-11 defects are **closed**: **D11-semantics-4** (High, handle leak)
and **D11-semantics-3** (Medium, nested key check).

### 3a. Non-defects, recorded so they are not re-found

- **`def` action + `wait=True` on the async engine returns instead of
  raising** (§2a note). Correct: the guard fires on `await`, and a `def`
  action cannot await. Not a parity hole — the sync engine, where the same
  `def` action *can* block, does raise.
- **`chain_trips` / `last_chain_error` do not survive a snapshot** (`R7`).
  No documented promise; both are interpreter-lifetime observability, like
  `last_error`. A wrapper that needs trip history across restarts must
  scrape it before `stop()`. **Gap, not defect.**
- **`tpye` → no did-you-mean hint** (`N2`). `difflib`'s default cutoff; the
  key is still reported with its full path and still refused. Cosmetic.

---

## 4. Not covered / reduced, with reasons

| Area | Status |
|---|---|
| **12-minute soak** | **Reduced to 100 s.** The 20-minute task bound had to cover a dual-kind prior-suite re-run, a 666-run fuzz, a 300-case chain property and a 200-machine × 10 s handle measurement. The reduction is defensible *this round* specifically because the long-horizon risk the soak exists to catch — unbounded growth — was independently bounded by `W1`, which measures the handle count **directly** (`handles_max_per_machine = 1`) rather than inferring it from RSS. Recommend `SOAK_SECONDS=720` unattended to confirm the +11 MB/100 s drift is flat rather than slow-linear. |
| **Livelock fuzz at 500 configs** | **Reduced to 250** (666 runs). At 500 the script exceeds the 120 s per-script bound on this host. Shape coverage is unchanged — all six cycle shapes × both kinds × both engines — only the per-shape sample halves (82–112 runs per cell, all unanimous). |
| **`sendTo` self → `ReentrantWaitError`** | **Not attacked.** The matrix covers `send`, cross-interpreter `send`, and the `after`-fired handler. `sendTo` to one's own id routes through the same `send` path, but I did not pin it. **Gap.** |
| **Snapshot forgery of `lane` / `engine`** | **Not re-attacked** (carried gap from round 11). `P3`'s re-run covers the `version`-selected variant, which is the one that reproduces. Per R10-01 framing, a party with full blob control is inside the documented trust boundary; only the *version-selected* bypass is filed, and it is already filed. |
| **`chain_trips` under the settle budget specifically** | Covered only incidentally. `R6`/`T1` trip the **chain** budget; the CHANGELOG says settle-budget trips also fire the hook, and I did not construct a settle-only trip. **Gap.** |
| **Redaction, receipt semantics, thread-leak/sync-child reaping** | Carried gaps, untouched by #218–#222. |

---

## 5. Verdict

**All five round-12 fixes hold, and the two High/Medium findings this track
filed in round 11 are closed.**

- **#218 is exact and scales.** The handle count is now **≤1 per machine**
  under 93,168 beats across 200 machines with **0.00 MB** RSS growth, and the
  soak's +753 MB is gone (+11 MB/100 s). 3,000 cancel cycles and 500
  fire-vs-cancel races produce no double-release on either engine.
- **#219 is well-shaped.** It raises where it must (own interpreter, both
  engines, including from an `after`-fired handler), permits what it promised
  (the `ensure_future` hatch, 100/100 under concurrency), and does **not**
  false-trip across interpreters — the child→parent shape an OMS actually
  uses is unaffected.
- **#220 is complete in both directions**: 11/11 nesting levels caught with
  path-named findings, and **zero** false positives over 200 generated valid
  charts and all 54 catalogue contracts. The `x-` and key-case bypass attempts
  both fail.
- **#221's property holds at chain depth**: 300/300 multi-hop
  restore→persist→restore→start chains preserve the deadline to 1e-6 ms and
  fire exactly once.
- **#222 behaves as a latch should**: sticky across a benign event, counter
  monotonic, `clear_chain_error()` clears only the latch, hook exactly once
  per trip, and the whole thing is deterministic over 150 runs.

**Gate impact (this track's input only): PASS, with one constraint removed
and one retained.**

- **CV constraint "use `after`, not `raise(delay=)`, for long-lived periodic
  work" can be RETIRED.** It existed solely for D11-semantics-4, which is
  fixed and verified at scale.
- **CV constraint "always call `from_snapshot(..., minimum_version=3)`"
  must be RETAINED** — D11-semantics-1 is unchanged and this is its entire
  defence.
- **CV constraint "lint nested config keys in the wrapper's own loader" can
  be RETIRED** — `strict_config=True` now does it, recursively, with no false
  positives on our catalogue.
- The carried round-9/10 rule stands unchanged: **never re-type an engine
  event with `_replace`; construct a fresh user `Event`** (D10-semantics-1).

One new **wrapper note**, not a constraint: `chain_trips` /
`last_chain_error` are interpreter-lifetime and do **not** cross a snapshot,
so a supervisor that restarts machines must read them before `stop()` if trip
history is to be durable.
