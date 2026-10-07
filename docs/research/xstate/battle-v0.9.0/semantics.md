# Battle track: SEMANTICS @ `v0.9.0`

**Library:** `_ref/xstate-statemachine` @ tag **`v0.9.0` = `91bd979`**;
`main` = `e3a1f22` is **2 commits ahead** — `git diff v0.9.0..HEAD --stat`
is exactly `.github/workflows/publish.yml | 15 +++-`, i.e. **CI
publish-smoke-test only, no library source**. The claim is verified.
`xstate_statemachine.__version__` reports **`0.9.0`**. The package is **not
yet on PyPI** (`pip download` fails) — everything here runs against the local
clone's `.venv-main`.

**Scope:** round-13 re-verification of the semantics track's carried defects,
a full re-run of the prior semantics suite on **both action kinds**, plus new
attacks aimed at this release's fixes — **#225** (self-send provenance by
task identity), **#226** (chain latch in the v3 envelope), **#227** (`strict`
+ schemas on restored `scheduled_sends`), **#230** (`from_snapshot(plugins=)`),
**#231** (inline-dict `invoke.src` → named `InvalidConfigError`), **#232**
(`RuntimeWarning` on a dropped `wait=True` receipt) and **#233** (sync
priority lane on restore).

**New scripts** (standalone — stdlib + `xstate_statemachine` only, every
helper inlined, run from neutral cwd `<home>`):

| Script | Attacks |
|---|---|
| `battle-v0.9.0/semantics/a_identity.py` | `A1`–`A6` — #225 task-identity matrix, worker-outlives-action, hand-out idiom, in-step refusal, #232 warning matrix, `-W error` surfacing |
| `battle-v0.9.0/semantics/b_persist.py` | `B1`–`B5` — #226 latch round-trip across 5 restarts, #227 300-case both-lane property, #230 exactly-once, #233 sync priority, trust-boundary forgery |
| `battle-v0.9.0/semantics/c_conc_fuzz.py` | `C1`–`C4` — 200-machine spawn concurrency, 100 concurrent hand-outs, #231 config fuzz, determinism incl. latch + round-trip |
| `battle-v0.9.0/semantics/k_soak.py` | soak — 200 machines, both kinds, heartbeats + spawned workers + external priority + chaos v3 restore with `plugins=` |

Prior-suite output under `semantics/prior/`, machine-readable new results
under `semantics/results/`.

**Suite baseline (shared run):** `suite-v0.9.0.log` — **3,577 passed, 13
skipped**, total coverage **92.86 %** (gate 90 %), 597 s. Complete, green.

---

## 1. Prior-defect table (round 12 → round 13)

| Prior | Title | R12 status | **R13 status @ `v0.9.0`** | Evidence |
|---|---|---|---|---|
| **D11-semantics-2** | #214's `on_invalid_event` on restore fires **zero** times; the hook is unreachable by construction | Low, STILL-PRESENT | **FIXED (#230)** | `from_snapshot` now takes `plugins=`. `B3`: a plugin passed via `plugins=` sees `UnknownEventError:NOPE` **at restore time** (before `start()`), and `UnknownEventError:GHOST` when the `scheduled_sends` lane is admitted at `start()` — **exactly once each**, never twice. The pre-#230 route (`.use()` after restore) still misses the `pending_events` refusal, which is the whole point of the new parameter. The round-11 repro `d11_sem_2_restore_invalid_hook.py` still exits 1 — **SUPERSEDED**: its assertion is `on_invalid_event_calls == 0` via the `.use()`-after-restore route, which is now the *unsupported* route; it already records `from_snapshot_has_plugins_kwarg: true` |
| **D11-semantics-1 / R12-02** | `"version": 2` in the payload mints a trusted engine event (forged `after` fires a 24 h timer) | High → **REFUTED** at round 12 (R12-02: a plain v3 verbatim write reaches the identical outcome; the trust boundary, not `upcast`, is load-bearing) | **UNCHANGED, stays refuted** | `p_persistence::P3` re-run at `v0.9.0` is byte-identical (`REPRODUCED: true` for the mechanism), and `repro/d11_sem_1_v2_upcast_mints_after.py` exits 1 as before. #225–#235 do not touch `persistence.py`'s upcast. **Not re-counted** — R12-02's refutation stands: `minimum_version=3` is hygiene, not a security control |
| **D11-semantics-4** | `raise(delay=)` heartbeat leaks one timer handle per beat | FIXED (#218) | **STILL FIXED** | `w_handles_cancel` **3/3 PASS** re-run; the new soak measures `handles_max_per_machine = 1` over 200 machines, and `repro/d11_sem_4_timer_handle_leak.py` exits **0** |
| **D11-semantics-3** | nested unknown config keys silently dropped | FIXED (#220) | **STILL FIXED** | `n_persist_keys` **5/5 PASS**; `repro/d11_sem_3_nested_keys_silent.py` exits 1 only for the documented *default (warn)* disposition, the harness artefact recorded at round 12 |
| **D10-semantics-1 / R9-01** | An engine completion / `after` event re-typed by `_replace` | High, STILL-PRESENT | **FIXED (#235)** | `s_semantics_sec` **4/4 PASS** (it pins current behaviour), and the CHANGELOG's #235 is the direct fix: `_replace()` on an engine-minted event now returns a plain `DoneEvent` / `ErrorEvent` / `AfterEvent` with `is_system_event(...) == False`. The forge-by-`_replace` route no longer produces a trusted event. Carried rule "construct a fresh user `Event`" becomes advisory rather than load-bearing |

### 1b. Prior-suite whole-run at `v0.9.0`

| Script | Result | Note |
|---|---|---|
| `battle-c78ce99/semantics/c_concurrency.py` | **exit 0 — 4/4 PASS** | C1–C4 unchanged (`C1_SECONDS=6`) |
| `battle-c78ce99/semantics/s_semantics_sec.py` | **exit 0 — 4/4 PASS** | S1–S4 unchanged |
| `battle-c78ce99/semantics/f_fuzz.py` | **exit 0 — PASS, 320 runs, 0 hangs** | reduced to 120 configs (see §4); oracle separation still perfect (`always`/`raise0`/`mixed`/`invoke` trip; `raise_delay`/`after` stay periodic) |
| `battle-c78ce99/semantics/p_persistence.py` | **exit 1 — 1/3 PASS** | `P3` fails identically (refuted R12-02); `P4` fails only on the `invalid_hook: []` cell — **SUPERSEDED by #230**, see below |
| `battle-de2da4e/semantics/r_reentrant_latch.py` | **exit 0 — 7/7 PASS** | #219 + #222 matrix intact under #225's rewrite |
| `battle-de2da4e/semantics/n_persist_keys.py` | **exit 0 — 5/5 PASS** | #220/#221 intact |
| `battle-de2da4e/semantics/w_handles_cancel.py` | **exit 0 — 3/3 PASS** | #218 intact at scale (`W1_SECONDS=6`) |
| `battle-de2da4e/semantics/t_determinism.py` | **exit 0 — 2/2 PASS** | determinism intact |
| `repro/d11_sem_212_heartbeat.py` | exit **0** | #212's rule still holds |
| `repro/d11_sem_4_timer_handle_leak.py` | exit **0**, `REPRODUCED: false` | #218 confirmed |

**No regression.** Every round-12 check that passed still passes.

### 1c. SUPERSEDED scripts and assertions

Two prior assertions are superseded by this release and are **rewritten
here rather than counted as failures**:

1. **`p_persistence::P4`, cell `invalid_hook: []`** — asserts that a restored
   strict-refused event reaches no plugin. That was true only because the
   plugin could not be registered early enough. **#230 changes the supported
   route**; the rewritten assertion lives in `B3`, and it passes: the hook
   fires, exactly once, for both lanes. `P4`'s other three cells (state,
   `last_error`, `seen`) are unchanged and correct.
2. **`repro/d11_sem_2_restore_invalid_hook.py`** — same reason, same
   rewrite. Its own output already reports
   `from_snapshot_has_plugins_kwarg: true`.

**No prior script relied on `ContextVar` inheritance**, and none ran under
`-W error`, so **nothing in the carried suite is superseded by #225 or
#232**. Both are covered positively by `A1`–`A6`. `r_reentrant_latch`'s
`R2`/`R5` (the `ensure_future` hatch, 100 concurrent) would have been the
scripts at risk; both still pass unmodified, which is itself evidence #225
preserved the documented hatch.

---

## 2. New attacks

### 2a. #225 — self-send provenance by task identity (`a_identity.py`, 6/6 PASS)

The observable that distinguishes the two verdicts is the #219 guard: an
**in-step** `send(..., wait=True)` is refused (`ReentrantWaitError`), an
**external** one resolves to a `Receipt`. That is the only place the two
provenances diverge visibly, so the matrix is keyed on it.

| Shape | Expected | **Result** |
|---|---|---|
| action → `send` directly | in-step, refused | **`INTERNAL(refused)`** ✔ |
| action → `await helper(i)` → `send` (**same task**) | in-step, refused | **`INTERNAL(refused)`** ✔ — the nesting-depth counter follows the awaited call |
| action → `ensure_future(worker)` → `send` (**worker outlives the action**) | external, resolves | **`EXTERNAL(resolved)`** ✔ — **this is the #225 headline**, and the round-11 hang is gone |
| action → task → task → `send` (**two hops**) | external, resolves | **`EXTERNAL(resolved)`** ✔ — the identity does not leak down a chain of spawns |
| `after`-fired handler's action → `send` | in-step, refused | **`INTERNAL(refused)`** ✔ — the guard is not specific to the initial descent |
| child action → **peer** interpreter `send` | external, resolves | **`EXTERNAL(resolved)`** ✔, peer reaches `p.b`; the guard keys on the *owning* interpreter only |
| `def` **service** (executor thread) → `send` | — | **`WrongThreadError`** — *documented*, not a defect: `send()` is loop-affine and `send_threadsafe()` is the documented route (README §API, `exceptions.py:412`). The `invoke` still completed (`ds.d`) |

| ID | Attack | Result |
|---|---|---|
| `A2` | **#225 at volume**: 200 machines (100 `def` + 100 `async def`), each spawning a worker from its entry action that sleeps past the action's end and then plain-`send()`s, with the loop otherwise idle | **PASS — 100/100 and 100/100 advanced.** Round 11's shape (the worker's event parked in the internal queue until a macrostep that never came) does not reproduce on either kind |
| `A3` | The documented hand-out `ensure_future(i.send("P", wait=True))`, **with and without** the spawning action awaiting afterwards | **PASS** — `OK:Receipt` in both cells, machine reaches `a.b`. The regression #225 names (the hatch flipping to a refusal when the action yields again) is fixed |
| `A4` | The **genuine** in-step await, both engines | **PASS** — `ReentrantWaitError` on the async engine *and* the sync engine. The fix did not widen the hole |
| `C1` | 200 machines × spawned workers **plus 4,000 concurrent external sends**, polled to convergence | **PASS** — 200/200 advanced, `chain_trips = 0`, 0 errored. **No internal-queue starvation** under mixed traffic |
| `C2` | **100 concurrent** hand-outs while every spawning action keeps awaiting | **PASS** — **100/100 `Receipt`**, **zero** `ReentrantWaitError`, 100/100 machines advanced. No false trip under concurrency |

### 2b. #232 — the never-awaited receipt warning (`A5`, `A6`)

| Use of the receipt in a `def` action | **RuntimeWarnings observed** |
|---|---|
| **dropped** (`r = i.send("P", wait=True)`, then out of scope) | **1** — `RuntimeWarning: send('P', wait=True) on 'a' was called from inside an action and its receipt was never awaited (#232). A plain `def` action cannot await, so it received this awaitable, not a Receipt. Send without wait=True, or hand the awaitable out (asyncio.ensure_future(...)) to be awaited elsewhere.` |
| `asyncio.ensure_future(r)` | **0** ✔ |
| `r.add_done_callback(...)` | **0** ✔ |
| `await r` (from a spawned task) | **0** ✔ |

The message names the machine, the event, **why** it happened and **two**
remedies. It is emitted from `_PendingReceipt.__del__`
(`interpreter.py:1204`), i.e. at finalisation, the same discipline CPython
uses for a never-awaited coroutine.

**`A6` — where does it surface under `-W error` inside asyncio?**
Nowhere that can hurt. With `warnings.simplefilter("error", RuntimeWarning)`
active across `start()` and a forced `gc.collect()`:

- **nothing** is raised to the caller of `start()` (`raised_to_caller: []`);
- the asyncio **loop exception handler** receives nothing
  (`loop_exception_handler: []`);
- the machine is **intact** — `status = running`, final `['a.b']`, i.e. the
  event the dropped receipt belonged to still transitioned.

The warning is raised inside `__del__`, where CPython converts any escaping
exception into an *"Exception ignored in:"* traceback on `stderr` rather than
propagating it. That is visible on the console (captured verbatim in
`results/a_identity.json`) but **cannot** fail a step, poison the loop, or be
caught by `-W error` machinery in the ordinary sense. **Worth recording for
adoption:** a service running `-W error` will see stderr noise from this path
and **not** a test failure — so a CI job that greps stderr will flag it, and
one that relies on `-W error` alone will not.

### 2c. #226 — the chain latch in the v3 envelope (`B1`, PASS)

The snapshot now carries both keys:
`chain_trips: 1`, `last_chain_error: "Machine 'ch' exceeded 6 chained
self-generated events in one macrostep and discarded 1 of them. An action
raises or sends the event that triggers it; break the cycle or raise
'maxIterations'."`

| Property | **Result** |
|---|---|
| `chain_trips` across **5 successive restore → re-persist → restore** hops, restored into a *same-shape but non-chaining* chart so no new trip is minted | **1, 1, 1, 1, 1** — monotonic, never reset, never double-counted |
| Latch **type** after each hop | **`RestoredError`** at all 5 hops — the `error` precedent, exactly as the CHANGELOG says |
| Latch **message** across hops | **byte-stable** (1 distinct value over 5 hops) and **intact** — the live `RunawayChainError` text survives verbatim |
| `clear_chain_error()` on a **restored** latch | latch → `None`, `chain_trips` **still 1** — it still clears only the latch |
| **Legacy blob** (a v3 envelope with both keys absent) | upcasts to **`0` / `None`**, no exception — additive as promised |
| A **new** trip after a restore | `chain_trips = 2` = previous + 1 — the counter continues rather than restarting |

This closes the round-12 "gap, not defect" note (`R7`): trip history now
crosses a snapshot, so the wrapper no longer has to scrape it before
`stop()`.

### 2d. #227 — `strict` on **both** restore lanes (`B2`, 300-case property)

300 random cases, each restoring a `strict: True` machine with 0–3
`pending_events` and 0–3 `scheduled_sends` records drawn from a mix of
**declared** (`KNOWN`, `TICK`) and **undeclared** (`NOPE`, `GHOST`, `XX`)
types, then starting it and letting it settle:

| Checked | **Result over 300 cases** |
|---|---|
| Refusals reported via `on_invalid_event`, count **exactly** matching the undeclared records across both lanes | **438 / 438 exact**, 0 mismatches |
| Declared `scheduled_sends` actually armed | **205 armed**, all fired |
| No undeclared type ever reaches a transition | **0 leaks** |
| Machine **consistent** afterwards — starts, advances, `status ∈ {running, done}` | **300/300** |
| No **armed residue**: `_armed_self_sends` and `_restored_self_sends` both empty after settling | **300/300** |
| Restore never **aborts** (the pre-#227 `InvalidEventPayloadError` escape) | **0 raises** |

**`bad_n = 0`.** The two lanes now agree about the same record, which is the
whole content of #227, verified at a volume the fix's own tests do not reach.

### 2e. #230 — `from_snapshot(plugins=)` exactly once (`B3`, PASS)

| Route | At restore (before `start()`) | After `start()` |
|---|---|---|
| **`plugins=[obs]`** | `['UnknownEventError:NOPE']` — the `pending_events` refusal | `['UnknownEventError:NOPE', 'UnknownEventError:GHOST']` — the `scheduled_sends` refusal joins it |
| `.use(obs)` **after** restore (the pre-#230 route) | `[]` — **misses** the pending refusal | `['UnknownEventError:GHOST']` |

**Exactly once, never twice**: 1 call at restore, 2 total after start, with
no duplicate for either lane. The `.use()` row is the residue of
D11-semantics-2 and is exactly what the new parameter exists to fix.

### 2f. #233 — sync priority lane on restore (`B4`, PASS)

A blob carrying `[X:inbox, Y:inbox, Z:priority]`:

| Engine | Delivery order |
|---|---|
| async (two lanes) | **`Z, X, Y`** |
| **sync (single queue)** | **`Z, X, Y`** — identical |

The priority record restores at the **head**, FIFO preserved within the
lane. Parity between the engines is exact.

### 2g. #231 — config fuzz, always a named `InvalidConfigError` (`C3`, PASS)

Nine malformed `invoke` shapes; **zero** raw `TypeError` / `KeyError`:

| Shape | Outcome |
|---|---|
| `src` = **inline dict** (the XState-JS shape, #231's headline) | `InvalidConfigError`: *"State 'c.a' invoke 's': 'src' must be a service name (str), got dict. To invoke a nested machine, build it with create_machine(...) and register it under that name in MachineLogic(services={…})"* |
| inline dict **+ `onDone`** | same named error |
| `src` = list / int / `{"machine": …}` / inline dict **inside a list** | same named error, with the actual type named (`list`, `int`, `dict`) |
| `invoke` = `5` (not an object) | `InvalidConfigError`: *"State 'c.a' has an invalid 'invoke' entry of type 'int'. Expected an object/dict (or a list of them)."* |
| `src` = `None` / `src` **absent** | `ImplementationMissingError: Service 'None' referenced by state 'c.a' is not registered.` — a *different* named library error, and the correct one: an absent `src` is a missing implementation, not a malformed type. **Not a defect**; recorded so the asymmetry is not re-found |

Every shape names the **state** and the **invoke id**.

### 2h. Determinism incl. the latch and a round-trip (`C4`, PASS)

50 runs × `{async, sync}` × `{def, async def}` of a chain-budget chart.
The signature covers the hook trace, `chain_trips`, the live latch type, the
final configuration **and** `chain_trips` / latch type / latch **message**
after a v3 snapshot round-trip:

| Lane | Distinct signatures over 50 runs |
|---|---|
| `async` / `def` | **1** |
| `async` / `async def` | **1** |
| `sync` / `def` | **1** |

Identical trace in all three lanes:
`D:LOOP:chain_budget → C:RunawayChainError`, `chain_trips = 1`, latch
`RunawayChainError`, final `d.b` — and the same after restore. The new v3
latch fields are **as deterministic as the rest of the trace**.

### 2i. Security — forging the new v3 fields, and `strict` bypass (`B5`)

**Framing probe, filed only if a boundary is crossed. It is not.**

| Attempt | Observed | Verdict |
|---|---|---|
| Forge `chain_trips: 999999` and `last_chain_error: "TOTALLY FORGED"` in a v3 blob | Both are accepted verbatim: `chain_trips = 999999`, latch `RestoredError("TOTALLY FORGED")` | **Inside the documented trust boundary.** `from_snapshot`'s own docstring (#205) states the payload is TRUSTED INPUT and `machine_hash` is a fingerprint, not a MAC. The forged values are **observability only** — they do not gate any transition |
| Does a forged latch change control flow / make the machine fatal? | `status = running`, `send("T")` still transitions, final `ch.b` | **No.** Nothing in the engine reads the latch to decide anything; it is a read-only report |
| `strict` bypass via `scheduled_sends`: an **undeclared** record | **Refused** — `UnknownEventError:NOPE`, no transition, final `st.a` | Closed by #227 |
| …with `"engine": true` set on the record (claim engine provenance) | **Refused** — `UnknownEventError:NOPE` | Closed |
| …shaped as a completion (`done.invoke.ghost`) | **Refused** — `UnknownEventError:done.invoke.ghost` | Closed |
| …declaring `"version": 2` (the D11-semantics-1 upcast route), restored with `minimum_version=0` | **Refused** — `UnknownEventError:NOPE` | The **`scheduled_sends` lane is closed even at v2**, unlike the `pending_events` lane's carried R12-02 finding |

That last row is a genuine, previously-unmeasured improvement: **#227's
`_admit_restored` runs on the scheduled lane regardless of the record's
declared version**, so the version-selected bypass that R12-02 refuted on
the `pending_events` lane has no analogue here. No new security defect.

---

## 3. Defects

**No new semantics defect was found this round, and the track's two
remaining carried findings are closed.**

Round 13 closes **D11-semantics-2** (by #230) and **D10-semantics-1 /
R9-01** (by #235). **D11-semantics-1** remains refuted as **R12-02**, which
is not a status change.

**No `D13-semantics-n` is filed.** Every attack aimed at #225, #226, #227,
#230, #231, #232 and #233 landed clean, several well above the fixes' own
test volume: a 300-case both-lane restore property, a 7-shape task-identity
matrix, 200 machines × spawned workers × 4,000 external sends, 100
concurrent hand-outs, 9 malformed config shapes, 150 determinism runs with
snapshot round-trip, 5 latch restore hops.

### 3a. Non-defects, recorded so they are not re-found

- **`def` service on the executor → `send()` raises `WrongThreadError`**
  (`A1`). Documented and correct: `send()` is loop-affine;
  `send_threadsafe()` is the supported route (README API table,
  `exceptions.py:412`). The `invoke` still completed normally.
- **`invoke.src` absent or `None` → `ImplementationMissingError`, not
  `InvalidConfigError`** (`C3`). The right error for a missing
  implementation; #231 is about a *malformed type*, which is refused by
  name in all 7 type-error shapes.
- **#232's warning surfaces as CPython's *"Exception ignored in
  `__del__`"* on stderr, not as a raised exception, even under
  `-W error`** (`A6`). Inherent to finalisation-time warnings; the machine
  is undamaged. **Adoption note, not a defect** — a CI gate that relies on
  `-W error` alone will not catch this path.
- **Forged `chain_trips` / `last_chain_error`** (`B5`). Inside the
  documented `from_snapshot` trust boundary, and read-only — same R10-01 /
  R12-02 framing.

---

## 4. Soak (`k_soak.py`, 200 s — reduced, see §5) — **PASS**

200 machines (100 `def` + 100 `async def`), each a `raise(delay=20)`
heartbeat **plus** a worker spawned from every entry action that outlives it
and sends back, under a continuous external **priority** producer, with
chaos v3 snapshot → `from_snapshot(..., plugins=[obs])` every 2 s:

| Metric | R12 @ `de2da4e` (100 s) | **R13 @ `v0.9.0` (200 s)** |
|---|---|---|
| Heartbeats | — | **1,104,961** |
| External sent / received / **dropped** | 196,400 / 196,400 / **0** | 1,095,800 / 1,095,800 / **0** |
| `on_event_dropped` (any reason) | — | **0** |
| `chain_trips` (all 200 machines) | 0 | **0** |
| `handles_max_per_machine` | 1 | **1** |
| Machines alive at the end | 200 / 200 | **200 / 200** |
| Chaos restores | 240 ok | **495 ok, 0 fail**, **463** carried `scheduled_sends` |
| Restore-time `on_invalid_event` via `plugins=` | n/a | **0** (nothing illegitimate was ever carried — the declared heartbeat re-arms, as #227 promises) |
| **RuntimeWarning noise (#232)** | n/a | **0** |
| **RSS growth** | +11.1 MB / 100 s | **+5.3 MB / 200 s** |

**RSS is flat, not slow-linear.** The last eight 2 s samples all read
**38.2 MB** — identical to the digit — while the beat counter keeps climbing;
the +5.3 MB is start-up arena growth that plateaus. Armed handles oscillate
175–194 across 200 machines (≤1 each, transient), never accumulating.

The #225 shape is the one this soak newly stresses: **every** entry action
on **every** machine spawns a worker that outlives it and sends back, for
200 s, on both action kinds — 1.1 M heartbeats with **zero** dropped external
events proves there is no internal-queue starvation and no provenance leak at
scale.

---

## 5. Not covered / reduced, with reasons

| Area | Status |
|---|---|
| **12-minute soak** | **Reduced to 200 s** (up from round 12's 100 s). The 20-minute task bound had to cover a dual-kind prior-suite re-run, a 320-run fuzz, a 300-case both-lane property, a 7-shape identity matrix and 200-machine concurrency. Defensible here because the long-horizon risk is bounded *directly* rather than inferred: `handles_max_per_machine = 1` is measured, and RSS is **identical to the digit across the last 16 s** of sampling while 1.1 M beats elapse. Recommend `SOAK_SECONDS=720` unattended to confirm. |
| **Livelock fuzz at ≥500 configs** | **Reduced to 120 configs / 320 runs.** At 250 the script exceeded the 120 s per-script bound on this host at `v0.9.0` (it timed out at 180 s on the first attempt and was re-run at 120). Shape coverage is unchanged — all six cycle shapes × both kinds × both engines, oracle separation still perfect — only the per-shape sample shrinks. **Below the brief's ≥500; recorded as a shortfall.** |
| **`def`-service `send()` task identity under the executor** | **Attacked, but the question is moot**: the call raises `WrongThreadError` before provenance is consulted (`A1`). The provenance question for `send_threadsafe()` from an executor thread is **not** pinned. **Gap.** |
| **`sendTo` self → `ReentrantWaitError`** | **Still not attacked** (carried gap from round 12). |
| **Settle-budget (as opposed to chain-budget) trips in the v3 latch** | Not constructed. `B1`/`C4` trip the **chain** budget only; whether a settle-only trip persists identically is unverified. **Gap.** |
| **`plugins=` error isolation** | Not attacked: a plugin whose `on_invalid_event` **raises** during `from_snapshot` — does `on_plugin_error` catch it, or does the restore abort? **Gap**, and a real one for #230. |
| **Snapshot forgery of `lane` / `engine` on `pending_events`** | Not re-attacked; carried, and inside the R12-02 trust-boundary framing. |
| **Redaction, receipt semantics, thread-leak / sync-child reaping** | Carried gaps, untouched by #225–#235. |

---

## 6. Verdict

**All seven round-12 fixes this track could reach hold, and both of the
track's open findings are closed.** `v0.9.0` is the first round in which the
semantics track carries **no** open defect.

- **#225 is the right predicate.** The 7-shape matrix separates in-step from
  external exactly where it should: the same-task awaited helper is still
  in-step, while a spawned worker — one hop or two — is ordinary external
  traffic. The round-11 hang does not reproduce on 200 machines across both
  kinds, and 1.1 M heartbeats of spawned-worker traffic drop **zero** events.
  Crucially it did **not** widen: the genuine in-step await is still refused
  on both engines, and the documented hand-out hatch works whether or not the
  action yields afterwards (100/100 concurrent).
- **#226 makes trip history durable.** Monotonic across 5 hops, byte-stable
  `RestoredError` message, `clear_chain_error()` unchanged in scope, legacy
  blobs upcast cleanly, and a new trip continues the count.
- **#227 closes the lane disagreement completely** — 438/438 exact refusals
  over 300 random both-lane cases with zero armed residue and zero aborted
  restores, and the `scheduled_sends` lane refuses even a `version: 2`
  record, which the `pending_events` lane does not.
- **#230 makes the restore-time hook reachable**, exactly once per refusal,
  per lane.
- **#231, #233** are exact: 9/9 malformed shapes named, engine parity on the
  restored priority lane.
- **#232** warns precisely — loud when dropped, silent for all three
  supported shapes — with the caveat that it surfaces on stderr rather than
  as a raised exception.

**Gate impact (this track's input only): PASS, with two constraints
retired and one rewritten.**

- **RETIRE** the wrapper note "`chain_trips` / `last_chain_error` do not
  cross a snapshot; scrape before `stop()`" — #226 persists both, verified
  across 5 hops.
- **RETIRE** the round-9/10 rule "never re-type an engine event with
  `_replace`; construct a fresh user `Event`" as a *load-bearing* constraint —
  #235 demotes `_replace` on an engine event to the public class. Keep it as
  **advisory style guidance** only.
- **REWRITE** "always call `from_snapshot(..., minimum_version=3)`": retain
  the call as **hygiene**, but the R12-02 framing stands — it is **not** a
  security control. A snapshot crossing a trust boundary must be
  authenticated outside the library (HMAC / signed envelope), which the
  library's own docstring now says explicitly.
- **NEW, recommended**: pass `plugins=` to `from_snapshot` in the wrapper's
  restore path — it is the only way to observe a restore-time refusal, and a
  strict machine that silently drops a restored deadline is exactly the
  failure an OMS cannot afford. Note the untested edge in §5 (a plugin that
  raises during restore).
- **RETAINED unchanged**: the `raise(delay=)` retirement from round 12 stays
  retired (`handles_max = 1` over 1.1 M beats), and `strict: True` is now
  genuinely restore-safe on **both** lanes.
