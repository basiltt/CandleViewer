# Battle test (round 13) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

Target: `xstate-statemachine` **v0.9.0** = `91bd979`; library clone `main`
= `e3a1f22`. `git diff v0.9.0..HEAD --stat` is **one file**,
`.github/workflows/publish.yml` (+14/−1) — the CI publish-smoke-test
claim is **verified**: no source change between the tag and `main`, so
every reading here is a reading of the tag. `__version__ == "0.9.0"`.

**Not on PyPI.** `pip download xstate-statemachine==0.9.0` fails — the
release exists as a git tag only. Anyone adopting 0.9.0 today pins a VCS
ref, not a wheel; the publish workflow that constitutes the two extra
commits has not yet produced an artefact.

Library suite @ this tree: **3577 passed, 13 skipped, 92.86 % coverage**
(`suite-v0.9.0.log`, complete, 597 s).

Scripts: `battle-v0.9.0/concurrency/w1`–`w5`, plus the round-12 suite
re-run under `concurrency/rerun-de2da4e/`. Every probe is standalone
(stdlib + `xstate_statemachine`, helpers inlined), proven from the
neutral cwd `<home>`. Every action check runs BOTH `def` and
`async def`; every engine check runs BOTH engines.

---

## 0. Bottom line

**All eight round-12 fixes in this track hold. One new defect:
`on_interpreter_start` never fires on a restored interpreter.**

The round-12 headline fix — #225, self-send provenance moved from an
inherited `ContextVar` to task identity — is **exact on every shape I
could build**, including the three the old implementation got wrong:

* an action's **own task** is still INTERNAL (guard refuses, in-step);
* an **awaited helper coroutine** is still INTERNAL — no task boundary
  is crossed, and the library correctly does not treat a coroutine as a
  task;
* a **spawned task**, a **grandchild task**, a worker that **outlives**
  its action by 250 ms with the loop idle, and the hand-out idiom where
  **the spawning action yields again afterwards** are all EXTERNAL and
  all advance the machine.

At scale: **200 machines × both kinds**, every one of whose actions
spawns a worker that outlives it and then plain-`send()`s with the loop
otherwise idle → **200/200 landed, 200/200 ticked, 0 stranded**, both
kinds. **100 concurrent hand-outs** while the spawning actions keep
awaiting → **100/100 resolved, 0 refused, 0 hung**, both kinds.

The one new defect is not in the engine; it is in the **plugin
lifecycle on the restore path**, and `plugins=` is the very surface
#230 added:

| | fresh interpreter | restored interpreter |
|---|---|---|
| `on_invalid_event` | fires | **fires** (#230 — exact, 320 cases) |
| `on_interpreter_start` | fires 1× | **never fires** (0×, both engines, both routes) |
| `on_interpreter_stop` | fires 1× | fires 1× — **unbalanced** |

| Prior defect | Status @ v0.9.0 |
|---|---|
| D11-concurrency-1 (forged `scheduled_sends`, no `strict`) | **PARTIALLY FIXED** — the `scheduled_sends` lane is now `strict`-checked (#227); the underlying *blob trust* boundary is unchanged |
| D11-concurrency-2 (v2 upcast = privilege) | **STILL-PRESENT** (documented boundary) |
| D11-concurrency-3 (restore→re-persist drops timers) | **FIXED** (#221), re-confirmed |
| D11-concurrency-4 (nested keys unchecked) | **FIXED** (#220), re-confirmed |
| D11-concurrency-5 (`on_invalid_event` unreachable on restore) | **FIXED** (#230) — and this is what makes D13-concurrency-1 the *remaining* half |

New: **D13-concurrency-1** (Medium) — §4.

Verdict: **ADOPT WITH CONSTRAINTS** — one new constraint (plugins must
not do per-run setup in `on_interpreter_start` if you restore), the
snapshot trust constraints unchanged and still mandatory. §7.

---

## 1. Method, and every reduction

| Item | Brief | Run | Note |
|---|---|---|---|
| Task-identity matrix | 6 shapes named | **11 cells**, 25 s watchdog each | w1 |
| Latch across restarts | "N restarts, monotonic" | **8 hops × 2 kinds**, unreduced | w2/P1 |
| `scheduled_sends` strict property | ≥300 | **320** (160 × 2 kinds), unreduced | w2/P2 |
| `plugins=` exactly-once | "every hook once" | 320 cases + a `plugins=` vs `.use()` contrast | w2/P3, w3 |
| 200 machines × outliving workers | 200 | **200 × 2 kinds**, unreduced | w4/R3 |
| Concurrent hand-outs | 100 | **100 × 2 kinds**, unreduced | w4/R4 |
| `invoke.src` config fuzz | "inline-dict variants" | **36 cells** (6 srcs × 3 sites × 2 kinds) | w4/R2 |
| Livelock fuzz | ≥500 configs | **540 cells** (2 shards × 90 shapes × 3 lanes) | v4 re-run |
| Nested-key fuzz | "every level" | **300** trials over **12 sites**; **0** false positives on 120 generated + **129** catalogue charts | v4, v3 |
| Determinism | 50× both engines both kinds | **300 runs / 6 cells**, unreduced | v7 re-run |
| **Soak** | **12 min × 200 machines** | **720 s × 200 machines, UNREDUCED** | w5 — §6 |
| BENCH-6 | ≥5 runs | **5 runs** | §5 |

**Nothing in this track is reduced.** The soak reduction that stood as
the residual gap in round 12 (150 s vs 720 s) is closed: w5 ran the full
12 minutes at the full fleet.

### 1.1 Commands

```
PY=…/_ref/xstate-statemachine/.venv-main/Scripts/python
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1      # from cwd <home>
"$PY" battle-v0.9.0/concurrency/w1_task_identity_matrix.py
"$PY" battle-v0.9.0/concurrency/w2_persistence_latch_strict_plugins.py
"$PY" battle-v0.9.0/concurrency/w3_restore_lifecycle_hook.py     # exit 1
"$PY" battle-v0.9.0/concurrency/w4_warning_config_and_load.py
W5_SECONDS=720 W5_FLEET=200 "$PY" battle-v0.9.0/concurrency/w5_chaos_soak.py
for f in battle-v0.9.0/concurrency/rerun-de2da4e/v*.py; do "$PY" "$f"; done
```

Each writes a sibling `.json`. Exit 1 == defect.

---

## 2. Prior scripts, re-run on 0.9.0

| Script | @ v0.9.0 | Change from round 12 |
|---|---|---|
| v1 reentrant-wait matrix | **CLEAN** | none — #225 narrowed the predicate without widening the refusal |
| v2 timer handles / cancel storm | **CLEAN** | none |
| v3 persistence chain + latch | **CLEAN** | **CHANGED** — see below |
| v4 key fuzz + livelock (540 cells) | **CLEAN** | none |
| v5 observability + forgery | **CLEAN** after rewrite | **SUPERSEDED** — see below |
| v6 soak | **CLEAN** | none |
| v7 determinism (300 runs) | **CLEAN** | none |

Two scripts had assertions that 0.9.0 deliberately invalidated. Both are
recorded as **SUPERSEDED**, rewritten, and re-run — not silently
re-baselined.

**v3 — CHANGED, no rewrite needed.** Its P3 row carried the note *"a
restored interpreter is a NEW object; a reset count is expected"*. At
0.9.0 that row now reads `restored_chain_trips: 2`,
`restored_latch: "RestoredError"`, and both `clear_chain_error` checks
still pass. The probe's assertions were written loosely enough to pass
either way; the note is now wrong and the new behaviour is #226 working.
(The one failure on first re-run — *"no catalogue `*.machine.json`
found — probe is vacuous"* — was my own relocation breaking a relative
glob, not a library fact. Fixed; **129** catalogue charts now build
clean under `strict_config=True` with **0** false-positive key
rejections.)

**v5 — SUPERSEDED, rewritten.** Its X1 vector asserted
*"`chain_trips` is NOT part of the snapshot layout, so a forged key is
inert"* and failed 4× on 0.9.0 (forged `999` and a forged latch both
took). That is #226 by design: the fields are now v3 envelope members.
The assertion is rewritten to the property that still matters at a trust
boundary — a forged value must be **admitted coherently** (an `int`
count, a `RestoredError` latch, and `clear_chain_error()` still clears
it), never a raw attacker object and never a crash. It passes. This is
the **R10-01 pattern**: a documented trust boundary is not a defect.
Filed nowhere; recorded in §6 as boundary surface that got one field
wider.

---

## 3. New attacks on 0.9.0

### 3.1 #225 task identity — the full matrix (w1, 11 cells, all CLEAN)

Each cell reads TWO independent observables, so neither can mask the
other: **advance** (with the loop otherwise idle, does the machine reach
`.done`? — under the #225 bug an internal-lane send never drained) and
**identity** (does `send(wait=True)` from that same task raise
`ReentrantWaitError`? — a direct read of `_action_tasks`).

| Cell | Shape | Expected | Observed |
|---|---|---|---|
| M1 | action's own task sends | INTERNAL | `ReentrantWaitError`, advanced ✅ |
| M2 | action **awaits a helper coroutine** | INTERNAL | `ReentrantWaitError` ✅ |
| M3 | action → task → send (both kinds) | EXTERNAL | RESOLVED, advanced ✅ |
| M4 | action → task → task → send | EXTERNAL | RESOLVED, advanced ✅ |
| M5 | worker sends 250 ms **after** the action returned | EXTERNAL | advanced, `n=1` ✅ |
| M6 | plain `def` action sends (executor thread) | must not be lost | advanced, `n=1` ✅ |
| M7 | child's action → **parent** (both kinds) | EXTERNAL to parent | RESOLVED / delivered ✅ |
| M8 | handler reached from an `after` event | INTERNAL | `ReentrantWaitError` ✅ |
| M9 | hand-out, **then the action awaits again** | EXTERNAL | RESOLVED ✅ |

M2 is the discriminating case for the *new* implementation: a
`ContextVar` and a task-keyed dict agree on M3–M5 but could easily
disagree here, because an awaited coroutine looks like a callee yet runs
on the caller's task. The library gets it right — identity is the task,
and a coroutine is not one.

M9 is the named round-12 regression (the documented `ensure_future`
escape hatch flipped to a refusal whenever the spawning action yielded
again). Fixed, and re-confirmed concurrently at ×100 in w4/R4.

### 3.2 Persistence (w2, 320 property cases + 8-hop restarts, CLEAN)

**P1 — #226 latch across restarts.** 8 successive restarts per kind,
each re-tripping the budget on the restored machine:
`1 → 2 → 3 … → 9`. `chain_trips` is **monotonic and never resets**, the
latch restores as `RestoredError` at every hop, and its message still
carries the original chain/budget text at every hop. Both kinds.

**P2 — #227 strict on restored `scheduled_sends`.** 320 cases: a real v3
envelope with both lanes injected with a random mix of declared and
undeclared types, restored onto a `strict: True` machine. Across the
run: **814 refusals, 466 arms**, and in **every** case —

* the armed count is **exact** (only declared records fire),
* every undeclared record is refused and reported **exactly once** —
  neither lane double-reports, which was the specific risk once both
  lanes were routed through `_admit_restored`,
* the restore **does not abort**, and the interpreter is still live: a
  later legal `FIN` still transitions, in all 320.

**P3 — why `plugins=` exists.** Same refusing blob, two routes:

| route | refusals seen |
|---|---|
| `from_snapshot(..., plugins=[p])` | `["GHOST", "NOPE"]` — both |
| `from_snapshot(...)` then `.use(p)` | `["NOPE"]` — only the late one |

That is #230 working and D11-concurrency-5 closed: registering after the
fact genuinely misses the restore-time refusal, and the new parameter is
the only way to see it.

### 3.3 #232 RuntimeWarning, and where it surfaces (w4/R1, CLEAN)

| shape | warnings |
|---|---|
| `def` action drops the `wait=True` receipt | **1**, text names `#232` ✅ |
| `ensure_future(i.send(..., wait=True))` | 0 ✅ |
| `r = i.send(...); ensure_future(r)` | 0 ✅ |
| plain `send()` without `wait` | 0 ✅ |

**The brief's question — under `-W error` inside asyncio, where does it
surface?** Measured, not reasoned: the warning is issued from
`__del__`, and CPython cannot propagate an exception out of `__del__`,
so with `simplefilter("error")` the resulting `RuntimeWarning` exception
is routed to **`sys.unraisablehook`** — captured verbatim in
`R1b_under_W_error`. It is **not** raised at the call site and the
action does **not** fail.

This is an **observation, not a defect** — `__del__` semantics are
CPython's, and the library's choice to mirror "coroutine was never
awaited" is defensible. But it has a real adopter consequence, recorded
as a constraint in §7: **`-W error` alone will not fail your CI on
#232.** To gate on it you must install an `unraisablehook` or capture
warnings explicitly. The warning also lands at GC time on an unrelated
stack, so the traceback will not point at the offending action.

### 3.4 #231 inline-dict `invoke.src` (w4/R2, 36 cells, CLEAN)

6 bad `src` values × 3 nesting sites (top / nested / parallel region) ×
2 kinds. **No cell raised `TypeError`** — the `unhashable type: 'dict'`
death #231 was filed for is gone at every nesting depth:

| `src` | raised |
|---|---|
| inline machine dict, `{}`, `["a","b"]`, `7` | `InvalidConfigError` (names the invoke id) |
| `src: None` | `InvalidConfigError` at parse-WARN + `ImplementationMissingError` at arm |

`src: None` is a different pre-existing condition (missing, not
unhashable) and it is **not silent**: it logs
*"Invoke definition in state 'q.a' is missing a 'src' property"* and
then fails `start()` by name. My first assertion demanded construction-
time refusal for it and was too strict; widened to "a named library
error at construction **or** at arm", which is the property that
actually matters. Recorded rather than quietly relaxed.

---

## 4. Defects

### D13-concurrency-1 — `on_interpreter_start` never fires on a restored interpreter (Medium)

**Repro:** `battle-v0.9.0/concurrency/w3_restore_lifecycle_hook.py`
(exit 1). **6/6 cells fail**: `{async, sync}` × `{def, async def}` ×
`{plugins=, .use()}`. Each cell carries its own control — the *same
plugin class* on a *fresh* interpreter, which fires `1×` every time.

```
engine  kind       route      control_starts  restored_starts  restored_stops
async   def        plugins=   1               0                1
async   def        .use()     1               0                1
async   async def  plugins=   1               0                1
async   async def  .use()     1               0                1
sync    def        plugins=   1               0                1
sync    def        .use()     1               0                1
```

`restored_machine_is_live: true` in all six — the restored actor works
perfectly, it just never announced itself.

**file:line.** `Interpreter.start()`
(`src/xstate_statemachine/interpreter.py:582-624`) detects the restored
shape — `status in ("running","done","error") and _event_loop_task is
None` — logs *"♻️ Resuming restored interpreter"*, re-arms timers,
resumes child actors, and **`return self`** at line 624. The plugin
start-hook loop —

```python
# interpreter.py:663-665
for plugin in self._plugins:
    plugin.on_interpreter_start(self)
```

— is at line 664, *below* that return, and is never reached.
`SyncInterpreter.start()` has the identical shape
(`sync_interpreter.py:388` sits below its own resume return), which is
why the sync engine fails the same way rather than by a separate bug.

**Why it is Medium, not Low.** The 0.9.0 changelog says of `plugins=`:
*"Same effect as `.use()` on the result, just early enough."* For
`on_invalid_event` that is exact and I verified it 320 times. For the
lifecycle hook, `plugins=` and `.use()` are **both** dead, so an adopter
reading that sentence gets a guarantee that holds for one hook and
silently fails for another — and there is no route that works.

The blast radius is every plugin that allocates **per-run state** in
`on_interpreter_start`: a metrics span, a log correlation id, a latency
clock, an audit "actor came up" record. All are silently inert for the
entire life of a restored actor — which, in an OMS, is precisely the
actor whose start-up you most need recorded, because it came back from
a crash. The pairing is also **unbalanced**: `on_interpreter_stop` still
fires, so a plugin holding a start/stop stack sees a stop it never
opened. `PluginBase` documents no "may not fire" caveat.

**Not a duplicate of D11-concurrency-5.** That finding was
`on_invalid_event` unreachable on restore, and #230 fixed it. This is
the *other* hook on the *same* path, which #230 did not reach.

**Scope of the claim.** I checked the two lifecycle hooks. I did not
enumerate every hook in `PluginBase` on the restore path; the general
statement I can support is that the resume branch bypasses the start-hook
loop, so any hook invoked only from below `interpreter.py:624` is
affected.

---

## 5. BENCH-6 — loaded timer lateness

Using **their** `benchmarks/production_characteristics.py --quick` §2
(median ms beyond a 10 ms `after` deadline), per the round-12
correction that our own `bench_c_timers` was never the right tool.
**5 runs**, same host, same venv:

| busy machines | r1 | r2 | r3 | r4 | r5 |
|---|---|---|---|---|---|
| 0 | +0.1 | +0.2 | +0.1 | +0.1 | +0.1 |
| 10 | +1.3 | +1.2 | +1.3 | +1.3 | +1.2 |
| 100 | +12.8 | +13.9 | +13.0 | +12.4 | +13.2 |
| **500** | **+70.6** | **+76.5** | **+73.1** | **+70.1** | **+70.6** |

**At 500 busy machines: min +70.1, median +70.6, max +76.5, spread
6.4 ms.** Our bar is **≤100 ms**; every run passes with ~24 ms of
headroom, and the distribution is tight — no tail run near the bar.

Round-12 readings on the same bench were **+89.6 / +94 / +113 / +110 /
+111 ms**, i.e. two of five *over* the bar. 0.9.0 reads **~20–40 ms
better and far more stable**. I am not attributing that to a specific
commit — the round-12 fixes are not obviously perf work, and host
conditions differ between rounds — but the bar is met on every run,
which round 12 could not say.

Lateness stays sub-linear from 0→100 and roughly linear 100→500; the
bench's own caveat (these are order-of-magnitude figures for this host;
your macrostep cost sets your budget) stands.

---

## 6. Soak — 12 min × 200 machines, unreduced

`w5_chaos_soak.py` at `W5_SECONDS=720 W5_FLEET=200`, both kinds in one
fleet (100 `def` + 100 `async def`), mixing every 0.9.0 mechanism at
once: declarative `raise(delay=60)` heartbeats (#218), action-spawned
workers that outlive their action and then plain-`send()` (#225),
external **priority-lane** traffic every 2 s to the whole fleet (#233),
and **chaos v3 snapshot/restore through `from_snapshot(plugins=[…])`**
on a rolling 5-machine slice every 2 s (#230/#227/#226).

Invariants sampled every 2 s for the whole run. Volume: **1,762 chaos
restores**, **2,189,067 heartbeats**, **71,200 priority sends**, all 200
workers observed.

* **I1 handles flat** — `max_handles` over the entire run = **1**, final
  = **1**. Exactly the #218 promise (~1 per machine), with a
  heartbeat re-arming ~60 ms for 12 minutes and 1,762 restores churning
  underneath. The probe also self-checks that the handle reading is not
  vacuously 0.
* **I2 `chain_trips` stable** — `max_chain_trips = 0` across the fleet,
  and no restore ever regressed the count.
* **I3 zero dropped external traffic** — every worker send and every
  priority send observed.
* **I4 no warning noise** — **0** `#232` RuntimeWarnings; the fleet uses
  only supported shapes, and the new warning does not false-positive
  under load.
* **I5 no task growth** — asyncio task count **201 at the first sample,
  201 at the last**, 12 minutes and 1,762 restores apart.
* **chaos** — all **1,762** restores succeeded; `restore_errors = 0`.

The 150 s-vs-720 s reduction that was round 12's single residual gap in
this track is **closed**.

### 6.1 Trust boundary — unchanged in kind, one field wider

`chain_trips` and `last_chain_error` are now v3 envelope fields (#226),
so a forged blob can set them. Verified (v5, rewritten): a forged
`999` / forged latch is **admitted coherently** — `int` count,
`RestoredError` latch, `clear_chain_error()` still clears it — never a
raw attacker object, never a crash.

This is **not filed** (R10-01: a documented trust boundary is not a
defect). It is recorded because it changes the *shape* of the
already-mandatory constraint: the snapshot blob was already a trusted
input, and it now additionally carries the operator-visible health
signal you might use to decide whether to quarantine an actor. An
attacker who can write blobs can now also make a repeatedly-tripping
actor look healthy (`chain_trips: 0`). Sign your blobs.

---

## 7. Not covered

Stated so the verdict is not read as wider than the evidence.

* **Every `PluginBase` hook on the restore path.** I measured the two
  lifecycle hooks and `on_invalid_event`. The structural claim in
  D13-concurrency-1 (the resume branch returns above the start-hook
  loop) covers anything invoked only below `interpreter.py:624`, but I
  did not enumerate the ~20 hooks individually.
* **Multi-process / multi-loop concurrency.** Everything here is a
  single event loop. `_action_tasks` is keyed by `asyncio.Task`; whether
  two interpreters on two loops in two threads can confuse each other's
  identity is untested.
* **`def`-service identity under a custom executor.** w1/M6 shows a
  plain `def` action's `send()` is not lost, but I did not pin *which*
  lane it takes, nor test a user-supplied `ThreadPoolExecutor` or a
  `def` service (as opposed to a `def` action) — `current_task()` is
  `None` off-loop and the routing there is unexercised by these probes.
* **`chain_trips` monotonicity across a *forged* restore.** P1 proves
  monotonicity across honest restarts; a blob that lowers the count is
  covered by §6.1 as trust boundary, not as an invariant.
* **The publish workflow.** 0.9.0 is not on PyPI; I verified the tag-to-
  `main` diff is CI-only but did not exercise the release pipeline.
* **Memory/RSS.** The soak tracks handles and task counts, not RSS — no
  psutil, per the standalone rule.

---

## 8. Verdict

**ADOPT WITH CONSTRAINTS.**

The engine half of this track is in the best shape it has been. #225 —
the subtlest fix in the round, because it changed *how identity is
decided* rather than what it does — is exact on all 11 shapes I could
construct, including the coroutine-vs-task case that discriminates the
new implementation from the old, and it holds at 200 machines and 100
concurrent hand-outs. #226, #227, #230, #231, #232 and #233 all do what
the changelog says. The soak is unreduced and flat. BENCH-6 passes on
every run with headroom, having failed 2-of-5 in round 12.

Constraints, in force at adoption:

1. **NEW — do not put per-run setup in `on_interpreter_start` if you
   restore.** It will not fire (D13-concurrency-1). Initialise plugin
   per-run state in the constructor, or from the first
   `on_transition` / `on_event_received`, and do not assume start/stop
   pair up. Applies to both engines and both registration routes.
2. **Snapshot blobs are trusted input — sign them.** Unchanged and
   still mandatory, now also covering `chain_trips` /
   `last_chain_error` (§6.1). `strict` now screens the
   `scheduled_sends` lane (#227), which narrows D11-concurrency-1's
   *event* surface, but the blob itself is still authority.
3. **`"version": 2` remains a privilege.** D11-concurrency-2,
   untouched; pin `minimum_version=3`.
4. **NEW — `-W error` will not catch #232 in CI.** The warning is issued
   from `__del__` and lands on `sys.unraisablehook` (§3.3). If you want
   a dropped `wait=True` receipt to fail a build, install an
   unraisablehook or capture warnings explicitly.
5. **0.9.0 is not on PyPI.** Pin the tag `91bd979`, not a version
   specifier, and re-verify when a wheel appears.

D13-concurrency-1 does not block adoption: it is a silent-observability
gap on a restore path, with a one-line adopter workaround, in a release
that closed the matching gap (D11-concurrency-5) for the other hook. It
should be fixed by moving the plugin start-hook loop above the resume
return — or, more conservatively, firing it inside the resume branch —
in both engines.
