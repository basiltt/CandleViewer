# Battle track: SEMANTICS @ `19cb1f1`

**Library:** `_ref/xstate-statemachine` @ `19cb1f1` (merge of #211; unreleased
0.8.1, `__version__` still reports 0.8.0 — keyed on the commit).
**Scope:** round-10 re-verification of every round-9 semantics defect, a full
re-run of the prior suite on **both service lanes**, plus new attacks aimed at
this round's machinery: deferred invoke arming per SCXML §6.1 `statesToInvoke`
(#204), `after`-transition provenance (#203), the delayed self-`send` debt
(#206), the stranded-invocation hook and `RunawayChainError.stranded` (#207),
receipt resolution after the in-flight flag drops (#208) and lap parity across
all three lanes (#209).

**Scripts** (all standalone — stdlib + `xstate_statemachine` only, every
helper inlined, proven from neutral cwd `<home>`):
`battle-19cb1f1/semantics/{p_persistence,c_concurrency,f_fuzz,s_semantics_sec,k_soak}.py`.
Repro under `repro/`, machine-readable results under `results/`.

Financial-OMS standard applied throughout: nothing is counted as a defect
without a standalone repro that reproduces on a clean interpreter, and every
service/action-bearing check runs with **both `def` and `async def`**.

---

## 1. Prior-defect table (round 9 → round 10)

| Prior | Title | R9 severity | **R10 status** | Evidence |
|---|---|---|---|---|
| **D9-semantics-1** (R9-01) | A genuine engine completion can be **re-typed** by `_replace` into any other completion, defeating #195 | High | **STILL-PRESENT — and CHANGED (widened to `after`)** | The round-9 repro `battle-f28719c/semantics/repro/d9_sem_1_replace_forgery.py` still exits **1** unchanged at `19cb1f1` (`async` lane: `state=['oms.settled']`, `booked=[('done.invoke.fill', {'qty': 999999})]`, `last_error=None`). #203 extended provenance-by-type to `AfterEvent` without closing the `_replace` route, so the **same vector now also forges timers** — see **D10-semantics-1**, which reproduces on **both** kinds. |
| **D9-semantics-2** (R9-13) | `strict` does not gate events restored from a snapshot's `pending_events` | Low | **STILL-PRESENT** | Prior `p_persistence::P2` re-run at `19cb1f1`: `strict/bare_done` → `status=running err=None recv=['done.invoke.q']`; `strict/plain_undeclared` → `status=running err=None recv=['BOGUS']`. `onUnhandled:"error"` still catches both. Unchanged by #203–#210. |

### 1b. Prior-suite whole-run (all four round-9 scripts, both lanes)

| Script | Result at `19cb1f1` | Note |
|---|---|---|
| `p_persistence.py` | 3/4 PASS | the one FAIL is `P2` = D9-semantics-2, still present |
| `c_concurrency.py` | **4/4 PASS** | C1 (10k external priority sends/kind during a live chain, 0 shed), C2, C3, C4 all hold |
| `f_fuzz.py` | **1/1 PASS** | 500 configs × 2 kinds × 2 engines: 0 hangs, 0 unbounded, 0 silent, 0 lap mismatch |
| `s_semantics_sec.py` | 1/2 PASS | the one FAIL is `S2` = D9-semantics-1, still present; forgeable surfaces unchanged (`_replace_retype`, `private_import_path`, `type_of_held_instance`, `Event_plus_ENGINE_MARK`) |

**No regression.** Every round-9 fix that passed still passes; the two open
round-9 findings are both still open, one of them now with a wider blast
radius.

---

## 2. New attacks on this round's machinery

| ID | Attack | Result |
|---|---|---|
| `P1` | Snapshot of a machine parked in an **invoking** state → restore → the service must arm **exactly once** (#204), both kinds | **PASS** — `armed_after_restore = 0` on both kinds, with `dormant=true` and `pending=[('pk.run','s1')]` correctly reported. A restore does **not** silently re-arm; liveness is the caller's to re-establish, and the API says so |
| `P3` | Forged `after` **pending record** under `strict` / `onUnhandled` / plain: `engine:true` / absent / `"true"` / `1` | **PASS** — only the genuine `engine: true` record restores as `_EngineAfter` and fires; `absent`, truthy-string and integer-`1` all restore as the public `AfterEvent` and leave the 60 s timer unfired. The flag is compared with `is True` |
| `P4` | Delayed self-`send` debt (#206) across snapshot/restore | **PASS** — live chain trips at 14 laps on both kinds and is bounded; the restored machine carries no un-charged resurrected chain (`laps=0`, bounded) |
| `P5` | Property: **300** random machines (parallel regions + nested children + `after` + `invoke`), snapshot at quiescence → restore | **PASS** — 300/300 checked, 0 configuration mismatches, 0 over-arms, 0 exceptions |
| `C1` | **100 machines** × `raise(delay=1ms)` self-ping-pong: every machine must trip, all at the **same lap**, both kinds | **PASS** — `distinct_laps = [12]` for `def` **and** `async def`; 100/100 tripped; all bounded. #206's parity claim holds at scale |
| `C2` | **200 concurrent** rollback+onDone storms: `on_invocation_stranded` exactly-once with correct ids; `err.stranded` agrees | **PASS** — `hook_count_distribution=[1]`, 200/200 exactly one, 0 wrong ids, 200/200 `RunawayChainError.stranded` agrees with the hook, **0 dormant without a hook**, on both kinds |
| `C3` | **5,000 external delayed sends** (~23k/s issue rate) during a live self-generated delayed chain | **PASS** — `EXTERNAL_dropped = 0`, `actions_fired = 5000` on both kinds; only 1 self-generated item shed per run |
| `C4` | Hook **ordering**: `on_event_dropped(chain_budget)` must precede `on_invocation_stranded` | **PASS** — `[('drop','done.invoke.sb','chain_budget'), ('stranded','r.b','sb')]` identically on the async engine (both kinds) **and** the sync engine |
| `F1` | Livelock fuzz: **500 configs × {def, async def} × {sync, async}** = 1,334 runs over `always` / `invoke` / `after` / `raise0` / **delayed-raise** / **`always`+`invoke`** cycles, 5 s watchdog | **PASS** — **0 hangs, 0 unbounded, 0 silent runaways, `def_vs_asyncdef_lap_mismatch = 0`, `async_vs_sync_engine_lap_mismatch = 0`** |
| `F2` | Illegal-configuration **receipt fuzz**: 480 cells over random `actionErrorPolicy` × `onUnhandled` × {clean, guard-denied, undeclared, action-raised} | **PASS** — **0** receipts `ok` over an illegal configuration, **0** errors over a legal step, 0 exceptions from `send(wait=True)` |
| `S1` | SCXML §6.1 `statesToInvoke` matrix: enter+exit in one macrostep via **`always` / `rollback` / parallel-sibling-`final` / `history`**, both engines, both kinds | **PASS** — `service_submitted = 0` in **all 16 cells**. #204's central claim holds on every exit route tested |
| `S2` | `after`-provenance matrix (#203): public class / **import path** / `type(held)` / **`_replace`** / pickle / deepcopy / snapshot flag | **FAIL → D10-semantics-1** — `_replace` on a genuine `AfterEvent` fires an arbitrary timer; `private_import_path` also mints one |
| `S3` | **50× identical traces** (transitions + drops + **stranded**) on both engines and both kinds, plus a `PYTHONHASHSEED` sweep (0/1/12345/99999) | **PASS** — **1 distinct trace** in every one of the four lanes; hash-seed sweep also 1 distinct trace |
| `S4` | Receipt **6-way** matrix incl. a step that **stranded** an invocation | **PASS** — clean / no-handler / guard-denied (`denied=true`) / action-raised / stopped / stranded all correctly shaped; the stranded cell reports `dormant=true`, hook `('q.inv2','si2')` and `err.stranded=['si2']` |
| `K1` | **Reduced soak** (90 s, not 12 min — see §4): 200 machines (100 `def` + 100 `async def`), always→invoke + rollback+onDone + delayed self-sends + external priority producer + chaos snapshots | **PASS** — 582,400 external sends, **0 dropped**, 582,400 actions fired, 2,640 chaos snapshots all accepted, 20 stranded reports and **0 dormant without a hook**, CPU 47%, RSS **+1.2 MB** |

---

## 3. Defects

### D10-semantics-1 — `after`-transition provenance (#203) is forgeable by `_replace` on the event an `after` action is HANDED, firing any timer instantly (**High**)

**Repro:** `repro/d10_sem_1_after_replace.py` — exit 1 == reproduced.
Deterministic, reproduces on **both** service/action kinds.

```
{'kind': 'plain', 'forged_is_system_event': True,
 'state': ['oms.margin.called', 'oms.settle.done'],
 'margin_call_fired_early': ['after.86400000.oms.margin.healthy'],
 'last_error': None, 'REPRODUCED': True}
{'kind': 'async', ... identical ... 'REPRODUCED': True}
```

**Root cause.** #203 closed the *name*-matching hole: `after` selection now
requires an engine-minted `_EngineAfter` rather than any `AfterEvent`, so a
hand-built event or a forged snapshot record can no longer fire a 60-second
timer instantly (`P3` and the cold surfaces of `S2` confirm that half is
genuinely closed). But provenance is carried by **type identity**, and
`NamedTuple._replace` returns `self.__class__` — a property the comment at
`events.py:558-562` deliberately preserves so that `deepcopy` and `pickle`
round-trip an engine event (`_EngineMark.__deepcopy__` / `__reduce__`,
`events.py:246-267`).

The gap is *who holds an instance*. An `after` transition may declare
`actions`, and those actions are **handed the genuine engine-minted
`AfterEvent`** as their `event` argument — that is the documented way user
code reads `scheduled_for` / `fired_at`. From there:

```python
def relay(interp, ctx, event, action):        # event IS _EngineAfter
    forged = event._replace(type="after.86400000.oms.margin.healthy")
    assert is_system_event(forged)            # True
    interp.send(forged)                       # fires the 24-HOUR timer NOW
```

In the repro the machine is `strict: true`, a 5 ms settle timer's action
re-types its own event into the descriptor of a **24-hour margin-call**
timer in a *parallel* region, and the margin call fires within 250 ms. The
forged event passes `is_system_event`, is therefore exempt from `strict` and
from `onUnhandled`, and drives the real `after` transition — verbatim the
scenario #203 is written to close ("a hand-built event or a forged snapshot
record fired a 60-second timer instantly"), reached by an easier route than
the one it blocked, because it requires no private name.

This is the **same structural defect as D9-semantics-1 / R9-01**, which
remains open: #203 extended the type-identity provenance model to a third
event class without closing the re-type route, so the round-9 Blocker's
blast radius now includes every `after` transition, not only `onDone` /
`onError`. The secondary surface is unchanged too: `_EngineAfter` is still
importable as `xstate_statemachine.events._EngineAfter` and
`type(held)(...)` still mints a trusted instance (`S2`:
`is_system_event` true and the timer fires for both).

**Severity High, not Blocker in isolation** — it requires the application's
own action code to do this, so it is not reachable by external traffic
alone; it is a defence-in-depth failure. It is High because the property
#203 advertises does not hold and **a wrapper cannot restore it**: the
wrapper cannot intercept `_replace` on an object already passed to user
code. As an *increment* to the still-open R9-01 it does not raise that
finding's severity, it widens its scope.

**`file:line`:** `src/xstate_statemachine/events.py:579` (`_EngineAfter`
definition) and `events.py:558-562` (the comment sanctioning
subclass-preserving `_replace`); trust site `events.py:272-285`
(`is_system_event`); selection site the `after` provenance check added by
#203.

**Remedy shape (for the maintainer), unchanged from R9-01.** Bind the
marker to the `(type, src)` pair at mint time and verify it at the trust
site, or override `_replace` on the private subclasses to return the
**public** class. Fixing it once at the subclass level closes `done`,
`error` and `after` together.

### D10-semantics-2 — `strict` does not gate events restored from a snapshot's `pending_events` (**Low**, carried forward)

Unchanged from **D9-semantics-2 / R9-13**; re-verified at `19cb1f1` by the
prior `p_persistence::P2`. `events.py:403-414` documents that a record
*without* `"engine": true` restores as "user traffic, subject to `strict` /
`onUnhandled`". `onUnhandled` is honoured; `strict` is not — `_check_strict`
runs at the `send()` call site, and the restore path re-enqueues through
`_enqueue_restored` → `_put_inbox`, bypassing it. Low: a caller who can write
`pending_events` already controls `state_ids` and `context` outright. The
defect is that the documented sentence over-promises.
**`file:line`:** `src/xstate_statemachine/base_interpreter.py:1767`.

**No new defect was found in #204, #206, #207, #208, #209 or #210.** Every
attack aimed at those six landed clean, several at 5–20× the volume of the
round-9 checks.

---

## 4. Not covered / reduced, with reasons

| Area | Status |
|---|---|
| **12-minute soak** | **Reduced to 90 s** (`k_soak.py`, `SOAK_SECONDS` env-overridable). The full 12 minutes does not fit this task's 20-minute wall-clock bound alongside the 1,334-run fuzz and the dual-lane prior-suite re-run. At 90 s the soak already issued **582,400** external sends with **0** dropped and RSS growth of **+1.2 MB** with CPU at 47%, so neither a leak nor a livelock is masked by the shorter window — but the long-horizon question (drift over minutes) is **not answered**. Recommend running `k_soak.py` with `SOAK_SECONDS=720` unattended before the gate. |
| `after_cycle` lap parity in `F1` | **Excluded by construction, recorded in the script.** A 1 ms `after` cycle is *wall-clock paced*: each firing is its own macrostep, so it is not a runaway chain and `maxIterations` neither does nor should trip. Its lap count is a function of the sampling window, so it is checked for hangs and boundedness only. My first pass asserted trip-observability on it and produced 166 false "silent runaways" — a harness artefact, corrected. |
| Sync-engine lane for `raise_delay` / `after_cycle` in `F1` | Skipped: a timer-paced self-send on `SyncInterpreter` is driven by the caller's `tick()` and has user standing by construction — the CHANGELOG states this for #206. Comparing laps in a single `send()` is not meaningful. |
| Redaction | Not re-attacked this round; untouched by #203–#210 and passing at `6db65d8`. Gap. |
| Thread-leak / sync-child-reaping | Still not directly instrumented (carried gap from round 9). `F1`'s sync lane (≈334 runs, no hang) exercises it indirectly only. |
| `guard_denied` under `onUnhandled: "error"` | **Not a defect** — verified against `docs/api/index.md:1924`: `guard_denied` is a documented `onUnhandled` disposition, so an `UnhandledEventError` on that receipt is correct. My initial `F2` assertion encoded the opposite and was stale; corrected in the script with the citation. |

---

## 5. Verdict

**The round-9 fix set (#204, #206–#210) holds under every attack in this
report, several at much larger scale than round 9 used.** The strongest
evidence is concentrated:

- **#204 (`statesToInvoke`)** — `service_submitted = 0` in **all 16 cells** of
  the S1 matrix, across four distinct same-macrostep exit routes (`always`
  roll-forward, `rollback`, parallel-sibling-`final`, history re-entry), on
  both engines and both service kinds. This is the round's cleanest result.
- **#206 (delayed self-send debt)** — 100 machines per kind all trip at the
  **same lap (12)**, `def` and `async def` identical; and 5,000 *external*
  delayed sends issued at ~23k/s during that live chain suffer **zero** loss,
  so charging the self-send did not sweep external traffic into the shed set.
- **#207 (stranded)** — across **400 concurrent** storms the hook fires
  **exactly once** per machine with correct `(state_id, invoke_id)`,
  `RunawayChainError.stranded` agrees **400/400**, ordering
  (`drop` → `stranded`) is identical on both engines, and there are **0
  dormant invocations without a hook** in the storm test *and* in a 90 s
  200-machine soak.
- **#208 / #209** — 480 receipt-fuzz cells produced no `ok` over an illegal
  configuration and no error over a legal step; 1,334 fuzz runs produced
  **0** lap mismatches between kinds and **0** between engines.

**No new defect exists in this round's machinery.** The one new finding,
**D10-semantics-1**, is not a regression in #203 — it is the *unfixed*
round-9 Blocker (**R9-01 / D9-semantics-1**, still reproducing verbatim at
`19cb1f1`) reappearing on the surface #203 newly brought under the same
type-identity provenance model. `after` now joins `done` and `error` as a
class of engine event that an ordinary handler is handed and can re-type via
`_replace` into any other descriptor — here turning a 5 ms settle timer's
action into an instant 24-hour margin call, under `strict`, with
`last_error=None`.

**Gate impact (this track's input only): conditional pass, unchanged
constraint set plus one widened rule.**
Nothing here blocks adoption that was not already blocked. The wrapper rule
carried from round 9 — *never re-type an engine event with `_replace`;
construct a fresh user `Event` instead* — must be **widened from completions
to `after` events**, and enforced by lint, since a wrapper cannot enforce it
at runtime. Fixing `_replace` once on the private subclasses closes
`done`, `error` and `after` together and would retire this rule entirely.
The two reduced/uncovered items in §4 (the full 12-minute soak, the
thread-leak check) should be closed before the final verdict; neither showed
any warning sign at the reduced parameters.
