# Round 13 — diff review `de2da4e..e3a1f22` (v0.9.0)

**Scope** 41 files, ~1.6k lines. `__version__ = "0.9.0"`. Tag `v0.9.0` = `91bd979`;
`main` = `e3a1f22`.

## 0. Baseline facts (verified, not taken on trust)

| Claim | Verdict |
|---|---|
| `main` is 2 commits ahead of `v0.9.0`, CI-only | **CONFIRMED.** `git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml \| 15 +-` and nothing else. Commits `c133875` (publish smoke test) + merge `e3a1f22`. No `src/`, no `tests/`, no `pyproject.toml`. |
| Suite green | **CONFIRMED.** `3577 passed, 13 skipped, 15 warnings in 597.15s`; coverage **92.86%** (floor 90). Zero `xfail`, zero `xpass`. |
| Not on PyPI | Unchanged — `pip download xstate-statemachine==0.9.0` still fails; the wheel exists only as a CI artefact. Every finding below is against the source tree. |
| BENCH-6 | **PASS**, see §3. |

Source changes are confined to 8 modules: `events.py`, `exceptions.py`,
`models.py`, `persistence.py`, `base_interpreter.py`, `interpreter.py`,
`sync_interpreter.py`, `resolver.py`/`validation.py` (comment-only).

---

## 1. Findings

### S-1 — `drain_pending()` on the async engine silently drops the entire priority lane
**Severity: HIGH (data loss on the documented shutdown path). Pre-existing, but #233 makes it a NEW cross-engine divergence.**

`Interpreter.drain_pending()` (interpreter.py:1715) is documented as
*"Remove and return **every** accepted-but-unprocessed event. Intended for
shutdown paths that must persist accepted work durably before the process
exits."* Its body reads `self._event_queue` only. The async engine has **two**
queues; `_priority_queue` (interpreter.py:374) is never touched. The snapshot
path disagrees: `_snapshot_pending_events` (interpreter.py:1675) returns
`[ev for ev, _ in self._priority_queue] + inbox`.

So the two durability paths return different sets, and the one whose docstring
promises completeness is the lossy one.

```
async snapshot view : ['P1', 'P2', 'I1', 'I2']
async drain_pending : ['I1', 'I2']
LOST BY ASYNC DRAIN : ['P1', 'P2']
sync  drain_pending : ['P1', 'P2', 'I1', 'I2']
```
Repro: `probes/v0.9.0/p8_drain_priority.py`.

Why this is a **round-13** finding and not an old one: #233 just made
`SyncInterpreter._enqueue_restored` honour the priority lane, and
`SyncInterpreter.drain_pending` reads its single queue, so the sync engine now
drains all four events. Before #233 both engines were wrong in the same
direction. The fix to one engine's *restore* ordering has turned a symmetric
bug into an **engine-dependent** one — exactly the parity class #233 exists to
close. A caller who does `drain_pending()` → persist → exit loses every fired
timer and every service completion waiting in the lane on async, and loses
nothing on sync.

Affects: priority events are not an edge case — `send_priority()` is public
(interpreter.py:1051), and `_deliver_priority` is where *fired `after` timers
and invoke completions* land (interpreter.py:2498). The lost events are
precisely the engine-minted, chain-charged ones.

Suggested fix: drain `_priority_queue` first, then the inbox — the same order
`_snapshot_pending_events` uses.

---

### S-2 — Changelog/docs retarget `0.8.1 → 0.9.0` was a blind substitution over *historical* prose
**Severity: MEDIUM (documentation correctness; misleads on-disk-format migration).**

The 0.8.1→0.9.0 retarget (item 9) sed-replaced the string everywhere, including
sentences that describe **what a past release did**. The results are now false
statements about history:

- `events.py:57` — *"Since 0.9.0 (#79) system status is decided by provenance"*. #79 shipped in 0.8.1. A reader on 0.8.1 is told the behaviour is not yet present.
- `events.py:192` — *"before 0.9.0 failures rode in a `DoneEvent`"*. They did not; that changed in 0.8.1.
- `events.py:380` — *"an escalate event or init sentinel persisted by 0.9.0"* — the whole point of that sentence is the **older** writer.
- `events.py:407` — *"See the 0.8.1 changelog migration note"* → now points at a 0.9.0 note that does not describe that migration.
- `persistence.py:41` — **layout table**: *"2 — 0.9.0: every `pending_events`/`deferred` record carries a `kind`"*. Layout **v2 was 0.8.1**; 0.9.0 is **v3**. Two lines below, v3 is also attributed to a release. This table is the normative description of the on-disk format and it now claims two different layout versions for one release.
- `persistence.py:164`, `base_interpreter.py:580`, `base_interpreter.py:1797` — *"every 0.9.0 writer records `version`/`machine_hash`"*, *"the 0.9.0 `sync=` kwarg"*. These are arguments for why `minimum_version=1` is safe **because older writers already did it**; rewriting the version to the current one destroys the argument.
- `docs/_guide/snapshots.md:253` — *"Since layout **v2** (0.9.0)"* in the same bullet as *"Since layout **v3** (#214)"*.

Nothing executable is wrong. But an operator deciding whether a stored blob
needs upcasting, or whether `minimum_version=1` is safe for their archive, is
reading these exact sentences.

---

### S-3 — `last_chain_error` changes type across a snapshot round-trip, and the new type is not in the `RunawayChainError` hierarchy
**Severity: MEDIUM (documented, but a silent `except` narrowing for supervisors — the feature's only consumer).**

`chain_trips` / `last_chain_error` now persist (#226). On restore the error
comes back as `RestoredError`:

```
trips= 1 latched= RunawayChainError      # live
...
type(r.last_chain_error).__name__  -> RestoredError
isinstance(r.last_chain_error, RestoredError)     -> True
RestoredError.__mro__[1]                          -> XStateMachineError
```
Repro: `probes/v0.9.0/p5_chain_latch.py`.

`RestoredError` subclasses `XStateMachineError` directly (exceptions.py:212),
**not** `RunawayChainError`. A supervisor written against #222 —
`if isinstance(i.last_chain_error, RunawayChainError): page()` — is correct
against a live machine and **silently false** against a restored one. The
latch exists *specifically* so a supervisor can see discarded work, and a
restart is the event a supervisor most often reacts to (the changelog says so
in as many words). So the one moment the feature was added for is the one
moment the type check fails.

This is the `error` field's precedent, is documented (`snapshots.md:133`, `:252`),
and JSON cannot carry a type — so it is a **defensible design choice, not a
defect** (R10-01 pattern). Raised as an API-shape observation: making
`RestoredError` also inherit `RunawayChainError` is impossible (it is generic),
but a `RestoredChainError(RestoredError, RunawayChainError)` for this one field
would make the documented supervisor idiom hold across a restart. Flagging
because the doc bullet tells readers the latch "crosses a restart" *before* it
tells them the type changes.

---

### S-4 — `chain_trips` is restored verbatim from the blob with no bound and no hash coverage of the field
**Severity: LOW (trust-boundary; snapshot is already a trusted input).**

`interpreter.chain_trips = int(snapshot.get("chain_trips") or 0)`
(base_interpreter.py:1993). Probe p5 forged `chain_trips: 999` /
`last_chain_error: "FORGED"` into an otherwise valid blob **without touching
`machine_hash`**, and both were accepted:

```
hash-covers-new-fields: True -> accepted forged: 999 RestoredError FORGED
```

The `machine_hash` is a hash of the **machine definition**, not of the payload
(that is its documented job — drift detection), so it neither covers nor is
invalidated by these fields. Consistent with every other restored field
(`context`, `configuration`), so this is the **documented trust boundary**, not
a new hole. Recorded only because the new fields feed a *supervisor alerting*
path: a corrupt or replayed blob can now manufacture a "work was discarded"
alert, or (worse) suppress one by restoring `0`. No fix recommended; worth one
sentence in `snapshots.md` next to the existing trust-boundary note.

Also note `clear_chain_error()` clears the message but **not** the counter
(`after clear: None trips= 999`) — correct and documented (monotonic), just
confirming it survived the change.

---

### S-5 — `_rearm_restored_self_sends()` return value changed meaning; no caller reads it
**Severity: LOW (silent semantic change to a private-but-returned value).**

Was `return len(records)` (records *processed*); now `return armed` (records
*accepted*). The docstring was updated ("Returns how many were ARMED"). Verified:

```
armed= 1 (2 records, 1 refused)
last_error= UnknownEventError
```
Repro: `probes/v0.9.0/p6_admit_restored.py`.

All three in-tree callers (`interpreter.py:601`, `sync_interpreter.py:323`,
`:345`) discard the value; the only reader is the new test at
`test_round12_findings.py:509`. Partial-restore consistency **is** sound: after a
refusal the machine starts, stays in `m.a`, re-persists only the surviving
record (`re-persist after refusal: 1`), and `status == "running"`. No defect —
logged so the meaning change is on the record if the value is ever surfaced.

---

### S-6 — the `#232` `RuntimeWarning` is emitted from `__del__`, so it is invisible to `-W error` and to `filterwarnings = error` CI
**Severity: LOW (the warning is advisory by construction; worth knowing before relying on it as a gate).**

Concern raised in the brief: under `-W error` the warning becomes an exception
at GC time — *inside which task?* Answer: **inside none**. CPython routes an
exception escaping `__del__` to `sys.unraisablehook` and prints
`Exception ignored in:`. Verified with a real machine, no `catch_warnings`:

```
Exception ignored in: <function ..._PendingReceipt.__del__ ...>
RuntimeWarning: send('B', wait=True) on 'm' was called from inside an action ...
after-gc state= ['m.b']
final state= ['m.c'] status= running
PROCESS-OK   EXIT=0
```
Repro: `probes/v0.9.0/p4_werror_del.py`, `p3_warn_finaliser.py`.

Consequences, all benign but worth stating: (a) the machine is unaffected — the
send still happened, `m.a → m.b → m.c`, `status == "running"`, exit 0; (b) a
project running `-W error` **cannot** turn this into a build failure, so it is a
console diagnostic only, never a gate; (c) it cannot be caught by
`pytest.warns` unless the object is forced to finalise inside the block.

Determinism: **fires reliably on CPython** (refcount drop at action return),
one warning per dropped receipt, no duplicates. **No false positive** on the
store-and-await-later shape — `__getattr__` and `__await__` both set `_used`:

```
drop        warnings= 1
store_later warnings= 0 ; later-await: OK ; state= ['m.b']
```

The `__getattr__` implementation is correct and subtle: it marks `_used`
**before** delegating, so `.add_done_callback` / `.result()` count. Note it also
means *any* attribute touch silences the warning — including a `repr()` from a
debugger or a logging call. Acceptable (matches the "any use counts" contract),
but it makes the warning strictly best-effort.

---

### S-7 — `_replace` demotion is correct but leaves a one-way trapdoor with no re-mint path
**Severity: INFO.**

Verified `probes/v0.9.0/p9_misc.py`:

```
minted system: True
after _replace: DoneEvent system: False
deepcopy system: True  pickle system: True
shim warns: ['DeprecationWarning'] still system: True
```

All four contracts in the changelog hold exactly. The engine's own two
`fired_at` stamps were correctly converted from `_replace` to `_engine_after`
re-mints (`interpreter.py:2890`, `sync_interpreter.py:1578`) — I grepped for
remaining `._replace(` on engine events and the **only** occurrences left are
the three demoting overrides in `events.py` themselves. Complete.

The deprecation shims warn and still mint trusted events, which is the right
call for a one-release bridge (breaking them immediately would be the worse
failure). They are removed in 1.0 per the shim text.

---

### S-8 — `#225` task-identity predicate: nesting, spawning, and the executor lane all verified correct
**Severity: INFO (no defect found; this was the highest-risk item in the brief).**

The brief asked four specific questions. Answers, all from live probes:

1. **Nesting depth** — an action that calls a helper coroutine *on the same
   task* keeps internal provenance; the depth counter in `_run_action`
   (`interpreter.py:2320`) is correct, and `finally` decrements rather than
   clearing, so an inner action's return does not un-mark the outer one.
2. **Spawned task, and task-spawns-task** — both external, at **every** depth:
   ```
   same_task      {'action_internal': True,  'helper_internal': True,  landed m.b}
   spawned_nested {'action_internal': True,  'worker_internal': False,
                   'inner_internal': False,  landed m.b}
   ```
   (`probes/v0.9.0/p1_nesting.py`) — the exact #225 regression, fixed.
3. **`ContextVar` fully removed?** — **No, and deliberately so.**
   `_ACTIVE_ACTION_OWNER` survives for exactly one path: `send_threadsafe` from
   a foreign thread, where `asyncio.current_task()` raises `RuntimeError` and
   there is no task identity to consult (`interpreter.py:2402`). The changelog
   says "the ContextVar is gone", which is **imprecise** — it is gone from the
   loop-thread predicate. The code comment (`interpreter.py:84`) is accurate.
   Minor doc nit, not a defect.
4. **Thread-pool `def` services** — a `def` service runs in `run_in_executor`
   (`interpreter.py:3306`) on a named worker thread. `_issued_from_own_action()`
   returns **`False`** there, so a `send()` from inside a `def` service is
   **external** traffic:
   ```
   {'thread': 'xsm-svc-m_0', 'own_action': False,
    'threadsafe': 'accepted', 'landed': ['m.b']}
   ```
   (`probes/v0.9.0/p2_defservice_thread.py`). This is **correct** — a service is
   not an action, it genuinely runs concurrently with the loop, and charging its
   sends to `maxIterations` would be the #105 bug again. No `RuntimeError`
   escapes: the `try/except RuntimeError` in the predicate handles the
   no-running-loop case on the worker thread. `send_threadsafe` from the service
   is accepted and lands.

---

### S-9 — `#231` inline-dict `invoke.src`: message is good, and the check is wider than advertised
**Severity: INFO.**

The changelog says "inline-dict `invoke.src`". The guard is
`not isinstance(raw_src, str)`, so it also catches `list` and `int`:

```
dict -> State 'm.a' invoke 'child': 'src' must be a service name (str), got dict. To invoke a nested machine, build it with create_machine(...) and register it under that name in MachineLogic(services={...}).
list -> ... got list. ...
int  -> ... got int. ...
```

Message content meets the bar: names the **state id**, the **invoke id**, the
**type received**, and the **supported alternative**. Raised unconditionally
("a hard error whatever `strict_config` says") which matches the non-dict
`invoke` precedent. `InvalidConfigError` was already imported in `models.py:57`.
No finding.

---

### S-10 — `#228` test-quality fix has real teeth (mutation-tested)
**Severity: INFO — this is the item most likely to be a paper fix, so I tried to break it.**

I reverted **only** the shape (`"#m0.a", reenter: True` → `"#m0.a.a"`, i.e.
restored the pre-#228 inert config) and left the new meta-test in place:

```
E   AssertionError: 2 == 2 : nested_invoke: 2 calls at limit 1 and at
    limit 10 -- the pin is inert
1 failed, 1 passed
```

`TestLivelockPinsAreLimitDependent` **does** fail CI if the inert shape returns.
The bound is load-bearing, not decorative. Working tree restored
(`git diff --stat` clean). This is the strongest item in the round.

---

### S-11 — `plugins=` ordering vs `.use()`
**Severity: INFO (no defect).**

`from_snapshot(plugins=...)` registers via the same `use()` in list order
(`base_interpreter.py:1886`), **before** the context layer, before
`pending_events` admission (`:1975`), and before the `chain_trips` restore
(`:1993`). Both hooks fire, in registration order, and a plugin added by
`.use()` afterwards still sees a later `_rearm_restored_self_sends()` refusal
because that runs at `start()`:

```
plugins= saw: [('plugins=', 'UNDECLARED')] | .use() saw: [('.use()', 'UNDECLARED')]
```

The genuinely early case — a `pending_events` refusal, which happens *inside*
`from_snapshot` — is reachable **only** via `plugins=`, which is precisely the
gap #230 closes. Correct. Plugins are wrapped in `_SafePlugin` on both paths, so
a throwing plugin cannot abort a restore.

---

### S-12 — publish smoke test
**Severity: INFO (the fix is right).**

`assert len(x.__all__) == 65` → the new block checks: installed dist version
`== x.__version__` (via `importlib.metadata` — catches a tag/metadata mismatch,
a genuinely useful new check), **every** `__all__` name resolves via `hasattr`
(catches a name exported but not defined — what a pinned count can never
catch), `len(__all__) >= 65` as a never-shrinks ratchet, plus explicit imports
of the 0.8.0 and 0.9.0 surfaces. The old pin failed the 0.9.0 release at 81
names for no defect; the replacement is strictly stronger and cannot rot the
same way. It does **not** import from a *clean* environment check beyond the
wheel install, and it does not assert `__all__` is sorted/deduped — minor, not
worth a finding.

---

## 2. Items checked, nothing found

- **Deleted / weakened tests:** none. `test_round9_findings.py` is the only
  existing test file touched; the change **strengthens** it (S-10) and adds a
  meta-test. `git diff --stat` shows `+59/-…` with no test deletions elsewhere.
  Zero `xfail`/`skipif` added. 13 skips are pre-existing platform skips.
- **Semver:** `0.8.x → 0.9.0` is a minor bump. Three changes are arguably
  breaking for someone: (a) the `engine_*` → `_engine_*` rename — mitigated by
  working `DeprecationWarning` shims that still mint trusted events (verified,
  S-7); (b) `_replace` demotion — behaviour change on a private class only
  reachable if you already hold an engine event, and the old behaviour was the
  vulnerability; (c) the v3 envelope gains two fields — **additive**, old blobs
  upcast to `0`/`None` (verified: `upcast defaults: 0 None`). None of these is a
  public-API break, so **minor is defensible**. The ContextVar removal is
  internal. The `RuntimeWarning` (S-6) cannot fail a build (S-6b), so it cannot
  break a consumer either.
- **`_admit_restored` on both lanes:** `pending_events` and `scheduled_sends`
  now share one admission function; `InvalidEventPayloadError` is caught
  alongside `UnknownEventError` on both, so a schema refusal no longer aborts
  the whole restore. Partial-restore state is consistent (S-5).
- **Sync priority restore (`#233`):** ordering is correct —
  `sync drained: ['P1','P2','I1','I2']` from input order `I1,P1,I2,P2`: FIFO
  within the priority lane, ahead of the inbox. `_restored_priority_count` is a
  new slot, initialised in `__init__`. (The async comparison exposed S-1, which
  is a `drain_pending` defect, not a `_enqueue_restored` one.)

## 3. BENCH-6 — their `benchmarks/production_characteristics.py --quick`, §2

Loaded timer lateness at 500 busy machines, 5 consecutive runs. Bar: **≤100 ms**.

| run | 0 | 10 | 100 | **500 busy** |
|---|---|---|---|---|
| 1 | +0.2 | +1.5 | +11.4 | **+78.2** |
| 2 | +0.1 | +1.5 | +14.9 | **+64.3** |
| 3 | +0.2 | +1.7 | +12.2 | **+81.0** |
| 4 | +0.1 | +1.2 | +13.6 | **+77.1** |
| 5 | +0.1 | +2.6 | +13.6 | **+77.6** |

**Distribution @500:** min +64.3, median **+77.6**, max +81.0, spread 16.7 ms.
**PASS — 5/5 under the bar, with ~19% headroom at the worst reading.**

Round-12 readings on the same host with the same tool were
+89.6 / +94 / +113 / +110 / +111 (2 of 5 **over** the bar). v0.9.0 is a clear
improvement: the max drops from +113 to +81 and the spread tightens from ~23 ms
to ~17 ms. I did not isolate the cause; removing the per-action `ContextVar`
set/reset from the action hot path (#225) is the plausible candidate, since §2
loads the machine with exactly that work.

## 4. Verdict

The round-12 fixes are real. The two I most expected to be cosmetic — #228
(test quality) and #225 (task identity) — both survived direct attempts to
break them: the meta-test fails on the reverted shape, and the task-identity
predicate is correct at every nesting depth and on the executor lane.

**One finding worth acting on before adoption: S-1**, async
`drain_pending()` losing the priority lane. It is pre-existing, but #233 turned
it into an engine-dependent divergence on a path documented to persist
*everything*, and the events it loses are fired timers and invoke completions.
S-2 (the blind changelog substitution) should be corrected because it
misstates the on-disk layout table. Everything else is INFO or a documented
trust boundary.

---

### Probes

All standalone (stdlib + `xstate_statemachine`, inline helpers, neutral cwd
`<home>`), under `docs/research/xstate/probes/v0.9.0/`:

| file | covers |
|---|---|
| `p1_nesting.py` | S-8 — task-identity nesting / spawned / nested-spawn |
| `p2_defservice_thread.py` | S-8 — `def` service executor-thread provenance |
| `p3_warn_finaliser.py` | S-6 — `#232` determinism + no false positive |
| `p4_werror_del.py` | S-6 — `-W error` at finaliser; machine survives |
| `p5_chain_latch.py` | S-3, S-4 — latch persistence, type, upcast, forgery |
| `p6_admit_restored.py` | S-5, S-11 — armed count, partial restore, plugin order |
| `p7_sync_priority.py` | §2 — sync vs async restore lane order |
| `p8_drain_priority.py` | **S-1** — async `drain_pending` priority-lane loss |
| `p9_misc.py` | S-7, S-9 — `_replace` demotion, shims, `src` message |
