# 21 — Adversarial verification of the new fixes on `main` @ `5327ba6`

**Library under test:** `basiltt/xstate-statemachine`, local clone, commit
`5327ba69fb735cfe24c7b3772050dac0a71a7b3d` (branch `main`). CHANGELOG
`[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`, so the
build is identified **by commit only**.
**Python / OS:** CPython 3.13.7, Windows 11 Pro 10.0.26200.
**Date:** 2026-09-18.
**Baseline replaced:** `17-reeval-0.8.0-verdict.md` (0.8.0, commit `9bf6065`).
**Probes:** `probes/main-5327ba6/` — 8 suites, 57 probes, plus 4 standalone
confirmation repros. JSON results alongside each suite.

> **Method.** This is not a re-run of the 0.8.0 probe corpus. Every probe here
> targets a behaviour that the `[Unreleased]` notes claim is *new*, and is
> written to make that claim fail if it can. Probes marked `DOCUMENT` have no
> pass/fail expectation — they record the observed contract, and the harness
> reports them as FAIL by construction.

---

## 1. Scoreboard

| Suite | File | Result |
|---|---|---|
| **A** receipts under reuse / defer / overflow | `a_receipts.py` | 3 PASS, 4 DOCUMENT |
| **B** rollback withdraws `raise`d events | `b_rollback_raise.py` | 6 PASS, 1 contract note |
| **B5** child-actor isolation under parent rollback | `b5_child_actor_rollback.py` | 1 PASS |
| **C** sync per-chain budget | `c_sync_chain_budget.py` | 7 PASS, **2 FAIL** |
| **C2** same, via the `raise` built-in | `c2_raise_builtin_chain.py` | 1 PASS, **4 FAIL** |
| **D** `send_threadsafe` strict | `def_threads_dormant_namespaces.py` | 3 PASS, 2 DOCUMENT |
| **E** `has_dormant_invocations` | same file | 3 PASS |
| **F** `SYSTEM_EVENT_PREFIXES` | same file | 5 DOCUMENT |
| **G** alias resolution | `gh_aliases_deprecation.py` | 8 PASS, **2 FAIL**, 1 DOCUMENT |
| **H** `DeprecationWarning` once-per-process | same file | 4 PASS |

**New defects: 6** (1 High, 3 Medium, 2 Low). **Fixes confirmed solid: 5 of 8
claim clusters.** No new Blocker.

---

## 2. Confirmed new defects

### M-1 — `send(wait=True)` reports "processed, no change" for a *deferred* event **[High]**

The two features the 0.8.0 verdict called out as the ones CandleViewer most
needed — `onUnhandled: "defer"` (CV-C01/LC-03) and `send(wait=True)` receipts
(CV-C06/LC-42) — are **individually correct and jointly wrong**. Used together
they produce a confident false negative.

When an event is deferred, the run loop resolves its receipt immediately with
`changed=False, error=None` — indistinguishable from "the machine looked at
your event and correctly decided to do nothing". The event is in fact parked
and *will* drive its transition on replay, after the caller has already acted
on the receipt.

**Repro:** `probes/main-5327ba6/a2_confirm_deferred_receipt.py` (asserts; exits 0).

```
receipt at defer time:
  changed = False      <- the caller's gate says "nothing happened"
  error   = None       <- and "nothing went wrong"
  states  = ['gate.closed']
  deferred_count = 1   <- but the event is parked and pending

after OPEN (replay):
  states  = ['gate.filled']   <- the transition the receipt denied
  context = {'filled': 1}
```

**Why it matters here.** CV-C06 mandates `send(wait=True)` for *every gated
decision* and CV-C01 mandates `defer` on the order path. The composition of the
two mandated settings is exactly the failing case. A FILL that arrives one
microstep early — the precise scenario `defer` was adopted to fix (probe B5 of
the 0.8.0 corpus) — returns a receipt saying the fill did not land. A caller
that retries, or reports "not filled" and unwinds, does so against a machine
that is about to fill.

Cause: `interpreter.py` resolves the receipt at the end of the macrostep by
comparing configuration and context, with no knowledge of the `defer`
disposition that `base_interpreter._handle_unhandled_event` just recorded.
`Receipt` has no field that can express "accepted but deferred".

**Disposition:** file upstream. `Receipt` needs a `deferred` flag, or the
receipt must stay pending until the event is actually consumed or evicted.
Until then, **CV-C06 cannot be retired and must be strengthened** (§4).

---

### M-2 — `max_iterations` does not bound an action-side self-`send()` on the async engine **[Medium]**

The `[Unreleased]` #77 entry says the budget counts "events that arrive while
the drain is running (a `raise`, **an action calling `send()` on its own
interpreter**, a `done.invoke` from a sync service, a due timer)", and that the
engines "agree now".

For the `raise` built-in they do agree (probes C9–C12: both cut at
`max_iterations + 1`). For the action-side `send()` shape they do not:

| Engine | Unconditional `i.send("LOOP")` inside the `LOOP` handler |
|---|---|
| `SyncInterpreter` | guard fires, `send()` returns after 1 001 steps |
| `Interpreter` (async) | **spins forever** |

**Repro:** `probes/main-5327ba6/c14_async_no_send_budget.py` (asserts; exits 0).

```
machine.max_iterations = 1000
SYNC : send() returned. steps = 1001
ASYNC: after 2.0 s of spinning, steps = 83888   status = running
ASYNC: after 3.0 s, steps = 125672  (still climbing: True)
ASYNC: queue_depth = 0
```

The async path routes an action's self-`send()` to the *external* inbox
(`interpreter.py` `send()` only diverts to `_internal_queue` under
`OverflowPolicy.BLOCK` with a bound set), so `_raise_depth` never counts it.
The result is a pegged run loop with `status == "running"` and
`queue_depth == 0` — invisible to every liveness signal the library offers.

Note this is a *parity regression in the documentation*, not in the code: 0.8.0
had the same hole. What is new is the CHANGELOG asserting it is closed. The
engine-parity test that "pins it" pins the `raise` shape only.

**Disposition:** file upstream. CandleViewer is insulated by **CV-C03**
(async-only) only in the sense that the *sync* engine is banned — the unbounded
shape is the one we actually run. See CV-C16 (§4).

---

### M-3 — the alias-ambiguity guard misses its own documented example **[Medium]**

CHANGELOG, *Changed*: "Registering two *different* callables whose names differ
only by case or separators (`fetch_data` and `fetchData`) for a name the machine
requires now raises `InvalidConfigError` at build time instead of silently
picking one."

`resolve_aliases` skips any required name already present in the registry
(`if name in registry: continue`), so the guard only runs when the config name
matches **neither** registered spelling exactly:

**Repro:** `probes/main-5327ba6/g1b_alias_ambiguity_and_leak.py`

```
both 'fetch_data' and 'fetchData' registered (DIFFERENT callables):
  config requires 'fetchData'   -> BUILT            <- the documented example
  config requires 'fetch_data'  -> BUILT
  config requires 'fetch-data'  -> InvalidConfigError
  config requires 'FetchData'   -> InvalidConfigError
```

The realistic shape — camelCase JSON from Stately naming `fetchData`, a Python
module that grew both a `fetch_data` and a `fetchData`, one of them stale — is
resolved silently to the exact key. The guard catches only the spellings a
config is least likely to use.

Arguably "exact wins over alias" is the intended precedence (probe G5 confirms
it works and is desirable). But then the *ambiguity* claim is overstated: two
different callables differing only by separators are silently tolerated in the
common case.

---

### M-4 — `resolve_aliases` mutates the caller's `MachineLogic` registry **[Medium]**

`create_machine()` writes resolved aliases back into the registry dict the
caller owns. A `MachineLogic` shared across machines — the documented
module-level-logic / `logic_modules` pattern — accumulates synthetic keys from
every machine built against it.

**Repro:** `probes/main-5327ba6/g1b_alias_ambiguity_and_leak.py`, part 2.

```
registry before build 1 : ['fetch_data']
registry after  build 1 : ['fetchData', 'fetch_data']   <- never registered by the caller
build 2 requiring 'fetch_data' with BOTH now present -> BUILT   (guard suppressed)
```

Two consequences, both silent:

1. **The ambiguity guard is self-suppressing.** Machine 1 creates the alias key;
   the caller later registers a *real, different* `fetchData`; machine 2 sees
   two distinct callables and does not raise, because one of them is now an
   "exact" key.
2. **Retroactive rebinding.** Because the alias is a dict entry, a later
   overwrite of that key changes what an *already-built* machine calls. In a
   direct check, a machine built against `fetch_data` executed
   `CAMEL-REAL` — an implementation registered after it was built.

**Disposition:** file upstream; `resolve_aliases` should populate a
machine-owned resolution map, not the shared registry.

---

### M-5 — `SYSTEM_EVENT_PREFIXES` is importable but not extensible; the build-time warning is narrower than the runtime rule **[Low]**

The prefix list ships as "the single, importable list". It is copied into a
module-level `_SYSTEM_EVENT_PREFIXES` in `base_interpreter.py` at import time,
so appending to `events.SYSTEM_EVENT_PREFIXES` changes `events` and nothing
else (probe F1: `module_patched=True, base_interpreter_copy=False`).
Importable ≠ configurable; for a *read-only* contract that is fine, but the
name invites the other reading. Worth a docs line, not a fix.

More consequential is the mismatch between the runtime exemption and the
build-time warning (probes F2/F3/F5):

| Event name | Runtime | `create_machine()` warns? |
|---|---|---|
| `done.review` | exempt (system) | ✅ UserWarning |
| `error.validation` | exempt (system) | ✅ UserWarning |
| `done.` | exempt (system) | — (not tested as an `on` key) |
| `DONE.review` | **ordinary user event** | ❌ no warning |
| `Done.Review` | **ordinary user event** | ❌ no warning |
| `done` / `doneReview` / `donex` | ordinary user event | ❌ (correct) |

The prefix match is case-**sensitive**, consistently in both the matcher and
the warning, so the two agree. The residual trap is that `DONE.review` and
`done.review` — which any reader would call the same name — behave completely
differently, and only one of them warns.

`strict` still does not reject a typo in a reserved namespace (direct check):
`error.typo`, `done.typo`, `after.99`, `xstate.x` are all accepted silently on
a `strict: true` machine with `onUnhandled: "error"`, while `TYPO` raises
`UnknownEventError`. This is N-8/CV-C15 unchanged, now with a build-time
warning covering the `on`-key half only — the `send()` half is still silent.

---

### M-6 — `send_threadsafe()` error precedence before `start()` **[Low]**

`send_threadsafe("TYPO")` on a strict, **unstarted** interpreter raises
`RuntimeError` ("has not been started"), not `UnknownEventError` — the loop
check precedes `_check_strict` (probe D3). On a **stopped** interpreter the
order inverts: an unknown event raises `UnknownEventError` on the calling
thread, while a *known* event is accepted and silently dropped (probe D4).
Defensible, but it means a cross-thread producer cannot rely on exception type
to distinguish "bad event name" from "machine not available" across lifecycle
phases. Docs-level.

---

## 3. Fixes that are solid

Attacked and not broken:

### ✅ #75 / N-1 — receipt identity under `Event` reuse
`_detach()` copies the caller's object at the boundary, so reuse is irrelevant
by construction rather than by discipline. **500 concurrent `wait=True` sends
of one `Event` instance, under `actionErrorPolicy: "rollback"` +
`onUnhandled: "defer"` + a bounded inbox with `RAISE`, all 500 resolved, none
hung** (probe A1). 200 concurrent `priority=True` sends of one instance: all
resolved (A6). The caller's payload is never mutated, so template reuse is safe
(A5). Receipts also resolve correctly for events dropped by `DROP_NEWEST`
(A3: 10 reported as dropped, 2 processed, **0 hung**), for sends refused by
`RAISE` overflow (A4), and at `stop()` for an event still sitting in the defer
buffer (A7). **N-1 is closed.** The only receipt gap left is M-1 above, which
is a different defect.

### ✅ #27 — rollback withdraws `raise`d events
Held under every hostile shape tried (probes B1–B8, B5):

- raise from the entry action of one **parallel region** while a *later*
  region's entry fails: withdrawn, configuration restored (B1);
- raise from an **earlier, successful** transition in the same macrostep:
  **not** withdrawn (B2) — the discrimination the fix claims;
- raise in an **exit** action followed by a failing transition action (B3);
- **two** raises then a failure: both withdrawn (B4);
- **targetless self-transition**: withdrawn, context restored (B6);
- **child actor**: the parent's rollback leaves the child's own self-raised
  event intact and the child completes its own transition (B5);
- `"fail"` policy withdraws identically (B8; terminal `status` is `"error"`,
  not `"stopped"` — a contract note, not a defect);
- **500 consecutive rollbacks each withdrawing a raise** do not accumulate into
  a false runaway trip: all 500 interleaved good events delivered (B7). The
  `_raise_depth` un-counting in `_on_internal_events_withdrawn` is correct.

This is the most thoroughly-attacked fix in the set and the cleanest.
**N-5's "rollback is not an effect transaction" caveat narrows** to `sendTo`
only, which is genuinely outside the machine.

### ✅ #78 / N-4 — `send_threadsafe()` applies `strict` and `event_schemas`
- payload schema violation raises `InvalidEventPayloadError` **on the calling
  thread**, machine untouched (D1);
- unknown name raises `UnknownEventError` on the calling thread even with the
  loop **saturated** by a 200-event backlog of slow handlers (D2) — the check
  reads immutable machine data off-loop, so it does not queue behind the drain;
- **10 threads × 200 sends, half invalid: 1 000 rejected on the calling
  threads, exactly 1 000 valid delivered, zero invalid events reached the
  machine** (D5).

**N-4 is closed.**

### ✅ #44 — `has_dormant_invocations`
Correct across the full round trip, including the re-snapshot case (probes
E1–E3): live `False` → static restore `True` → `restart_services=True` `False`
→ snapshot-of-restored → restore `True`. `pending_invocations()` agrees with the
boolean at every step. One contract note (E2): a snapshot taken from a
*restarted* restore, restored statically again, is dormant — correct, and worth
knowing, because it means dormancy is a property of the restore, not a sticky
flag in the envelope.

### ✅ #27 follow-up — `DeprecationWarning` once per process
The explicit question in the brief — *does it fire at all in a process where the
first machine sets the policy explicitly and a later one does not?* — is
**yes** (probe H1: exactly 1). Two default machines → exactly 1 (H2). A default
machine whose actions never fail → 0, i.e. it is failure-triggered, not
construction-triggered (H3). All machines explicit → 0, no false alarm (H4).
**N-16 is closed.**

### ✅ #77 — sync engine batch handling (the part that is fixed)
`send_events(["T"] * 3000)` of independent one-deep raises: all 3 000 delivered
(C3). A genuine infinite self-feed is broken **and the caller's 50 queued
externals still processed** (C4). The 0.8.0 defect N-3 — `clear()`ing the inbox
and losing events the caller was told were accepted — **is closed**. What
remains is M-2 (the async half) and the chain-depth ceiling below.

### ⚠️ Chain-depth ceiling — behaviour is correct, the framing is not
A **legitimate, terminating** 1 500-deep chain (each step raises exactly one
more, guarded, stops at 1 500) is cut at 1 001 on **both** engines, silently:
`status` stays `"running"`, `last_transition_ok` stays `True`, no
`on_event_dropped`, no plugin hook (C2b, C5, C9–C12; direct observability
check). This is `max_iterations` doing its job — it is configurable
(`maxIterations: 5000` → chain runs to 3 000, verified) — but a *depth* limit
presented as a runaway-loop guard will cut correct programs, and the only
signal is a log line. Not filed as a defect; recorded as **CV-C17**.

---

## 4. Constraints — retire, keep, add

### 4.1 Retired

| Constraint | Basis |
|---|---|
| **CV-C06, fresh-`Event` clause only** — *"Never reuse an `Event` instance across concurrent `wait=True` sends"* | **RETIRED.** #75 fixes this by construction (`_detach` at the send boundary), verified at 500-way concurrency under three policies simultaneously (A1, A6, A5). Delete `test_send_receipt_fresh_event_only` and the CV-LINT-XS9 clause that enforced it. **The rest of CV-C06 stands and is strengthened — see 4.2.** |
| **CV-C14, gateway-validation clause only** — *"wrapped by `cv.statechart.gateway`, which performs the `strict`/`event_schemas` check itself"* | **RETIRED.** #78 does this in the library, on the calling thread, before queuing, under loop saturation and 10-thread contention (D1, D2, D5). Delete the gateway's duplicate validation. **The `run_coroutine_threadsafe` ban (N-6) is unaffected and stands** — keep CV-C14 as a ban-only rule. |

### 4.2 Must stand — and why

| Constraint | Status |
|---|---|
| **CV-C06** (`wait=True` for gated decisions) | **STANDS, STRENGTHENED.** M-1 makes the receipt actively misleading under the `defer` policy CV-C01 mandates. New clause: *a `wait=True` receipt with `changed=False, error=None` must be treated as inconclusive unless `interpreter.deferred_count` is also 0 at the same instant.* New test `test_receipt_is_inconclusive_when_deferred`. |
| **CV-C13** (dedicated event loop / process) | **STANDS.** Re-measured on this commit: the armed-`rollback` cost is **0.778×** (`bench_j_policies.py`, 34 278 → 26 657 ev/s), i.e. −22.2% — statistically unchanged from 0.8.0's −22.4%. The CHANGELOG's "≈0.98× of the default" holds only for a machine whose transitions declare **no actions at all**: measured 0.949× with no actions, **0.878× with actions** on an otherwise identical two-state machine. The no-action skip is real but does not apply to any CandleViewer machine. BENCH-1 headroom stays ~2.46×, below the 3.0× bar; the dedicated loop is still what buys it back. |
| **CV-C15** (no CandleViewer event named `error.*` / `done.*`) | **STANDS.** N-8 is unchanged at runtime: `error.validation` and `done.review` remain invisible to `"*"` (F6: only `ordinary` matched), exempt from `onUnhandled`, and accepted silently by `strict` (direct check). 0.8.1 adds a build-time `UserWarning` for reserved **`on` keys** only — it does not cover `send()`, and it misses case variants (`DONE.review`, M-5). The event-name gate `E50-T05` must therefore still run, and must be **case-insensitive**, which the library's is not. |
| **CV-C03** (async `Interpreter` only) | **STANDS**, but its rationale shifts. N-2 and N-3 (the sync-engine defects that motivated it) are both fixed on this commit. It now stands on the remaining sync-only surface and on M-2 being an *async* hole — CV-C03 does not protect us from M-2. |
| **CV-C01, C02, C04, C05, C07…C12** | **STAND, unchanged.** Nothing in this commit touches their basis. |

### 4.3 New constraints

| ID | Constraint | Enforcement |
|---|---|---|
| **CV-C16** | No action may call `send()` on its own interpreter. Self-directed events use the `raise` built-in, which is the only shape the runaway budget actually bounds on the async engine (M-2). | CV-LINT-XS11 (AST: `interpreter.send(` inside a registered action); `test_no_self_send_in_actions` |
| **CV-C17** | No catalogue machine may rely on a `raise` chain deeper than 1 000. Any machine whose design permits a longer chain sets `maxIterations` explicitly and asserts the depth in a test — the cut is silent (`status` stays `"running"`, `last_transition_ok` stays `True`, no hook fires). | Design-review checklist; `test_chain_depth_under_budget` per family |
| **CV-C18** | `MachineLogic` instances are never shared across `create_machine()` calls; each machine gets its own registry (M-4 — `create_machine` mutates the registry, and the alias it writes can be retroactively rebound). Register **one** spelling per implementation; the library's ambiguity guard misses the common case (M-3). | Factory assertion (logic object identity); CV-LINT-XS12 (no two registry keys with equal `normalize_logic_name`) |

---

## 5. Upstream disposition

**New issues to file (4).** Drafts only — nothing filed, no comments posted.

| ID | Title | Severity |
|---|---|---|
| **M-1** | `send(wait=True)` resolves with `changed=False, error=None` for an event held by `onUnhandled: "defer"` | High |
| **M-2** | `max_iterations` does not bound an action-side `send()` on the async engine; the #77 parity claim covers the `raise` built-in only | Medium |
| **M-3** | The alias-ambiguity guard does not fire for its own documented example (`fetchData` required, `fetch_data` + `fetchData` registered) | Medium |
| **M-4** | `resolve_aliases` mutates the caller's `MachineLogic` registry, suppressing the ambiguity guard for later machines and retroactively rebinding earlier ones | Medium |

**Ride-along on existing follow-ups (2).** M-5 → `#79` (case variants, `send()`
half still silent, "importable" vs extensible). M-6 → `#78` (error precedence
across lifecycle phases).

**Now closable, verified on this commit.** `#75`/`#39` (N-1) · `#78`/`#51`
(N-4) · `#44` (N-16 half, `has_dormant_invocations`) · `#27` (raise-withdrawal
half). `#77` is **half** closable: the batch-discard defect (N-3) is fixed; the
engine-parity claim is not accurate (M-2).

---

## 6. Bottom line

Four of the six fixes aimed at our findings are genuinely solid, and two of
them survived the hardest probing in this whole audit: the receipt-identity fix
held at 500-way concurrency under three policies at once, and the
rollback-withdrawal fix discriminated correctly in eight hostile shapes
including parallel regions and child actors. **Two constraints retire outright**
(the fresh-`Event` rule, the gateway's duplicate validation) and one blocker-era
worry — silent event loss in the sync engine's batch handling — is closed.

The new finding that matters is **M-1**, and it matters because of *where* it
is: the two library features CandleViewer's order path is mandated to use
together produce a confidently wrong answer at the exact moment they are
supposed to produce a right one. It is not a hang and not data loss — it is a
gate that says "no" about an event that is about to say "yes". That is a
narrower defect than anything in the 0.7.0 register and a more dangerous shape
than most of the 0.8.0 set.

> **Verdict: the 0.8.1 fix wave is real and mostly verified. ADOPT WITH
> CONSTRAINTS is unchanged — now CV-C01…CV-C18, with CV-C06's reuse clause and
> CV-C14's validation clause retired and three new constraints added. The order
> path stays DEFERRED until M-1 is either fixed upstream or covered by the
> CV-C06 `deferred_count` clause in `cv.statechart`, and until `E29-T10` +
> `tests/xstate_contract/` are green.**
