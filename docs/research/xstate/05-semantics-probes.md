# Study 5 — Semantic Conformance Probes

**Library:** `xstate-statemachine` 0.7.0 (PyPI), async `Interpreter`
**Python:** 3.12, venv at `.venv-xstate/`
**Probes:** `docs/research/xstate/probes/` — `harness.py`, `p01..p03`, raw JSON in `probes/results/`
**Run:** `./.venv-xstate/Scripts/python.exe docs/research/xstate/probes/p0N_*.py`

**Result: 41 / 51 probes pass.** 10 failures, of which **6 are silent** — wrong behaviour with no exception and `is_running == True`.

| Suite | Pass | Area |
|---|---|---|
| `p01_core_transitions` | 16/20 | entry/exit order, self-transitions, guards, `always`, wildcards, unknown events |
| `p02_invoke_timers_history` | 14/14 | invoke lifecycle, `done.*`/`error.platform`, cancellation, `after`, history |
| `p03_context_snapshot_determinism` | 11/17 | context isolation, snapshot round-trip, determinism, `raise`/`sendTo`, validation |

A note on method: several first-draft failures were **my** errors, not the library's, and were corrected before this report — guards are `(context, event)` not `(interp, ctx, evt)`, and built-in actions need their arguments nested under `"params"` (`{"type":"raise","params":{"event":"X"}}`, not `{"type":"raise","event":"X"}`). The wrong spelling of a built-in action's params is itself a silent failure mode: the action parses fine and does nothing. Everything below survived that correction and was re-verified against library source.

---

## 1. What works, and works well

This is the majority of the surface, and it is the part an OMS leans on hardest.

**Invoke lifecycle is solid (14/14).** `done.invoke.<id>` carries the service return value in `event.data` (B1). `error.platform.<id>` carries the exception *object* (B2, `type(e.data).__name__ == "RuntimeError"`). Cancellation on state exit is genuine `asyncio` cancellation — the service observes `CancelledError` mid-`await` (B4) — and a cancelled invoke does **not** later deliver a stale `done.invoke` (B5). That last one matters: a late fill callback landing after the order left `pending` would be a real corruption bug, and the library gets it right.

**An unhandled invoke error is loud (B3).** No `onError` ⇒ `status` becomes `"error"`, `is_running` becomes `False`, and `interpreter.error` holds the exception. It does not sit in the invoking state pretending to be healthy. Good.

**Timers are correct (B9–B11).** `after` fires on schedule, is cancelled on state exit, and **restarts rather than resumes** on re-entry — verified by re-entering at 150 ms of a 200 ms timer and confirming it had not fired 120 ms later.

**History is correct (B12–B14),** including the subtlety that shallow history restores the immediate child and then *that child's own initial descendant* (`m.A.A1.x`, discarding the remembered deep leaf `y`), while deep history restores `m.A.A1.y`. No-prior-visit falls back to the parent's initial state.

**`onDone` / final-state `output` (B6–B8).** Compound `onDone` fires on child final; parallel `onDone` fires only once **all** regions are final (verified with the intermediate state `["m.P.A.af","m.P.B.b1"]`); `output` on a final state surfaces as `event.data` on the `done.state` event.

**Entry/exit ordering (A1, A2).** Exit runs innermost-first, entry outermost-first, and across a compound→parallel target the order is exactly `xA1, xA, eB, eP, ep1, eQ, eq1`. Transition actions land correctly between exit and entry (`xA, tAct, eB`).

**Context isolation is genuinely safe (C1–C3).** Actions mutate `context` in place, which looked like a snapshot-leak risk, but `get_snapshot()` / `get_persisted_snapshot()` deep-copy: a snapshot taken before a mutation still reads `{"n": 0}` afterward, including for nested mutable values (`{"orders": []}` vs `{"orders": ["o1"]}`). Two interpreters over the *same* machine object do not share context. For an audit trail this is the property that matters and it holds.

**Determinism holds (C8, C9, C17).** Identical event sequences over repeated runs produce byte-identical state + context + action traces — 1 unique result across 5 runs for a sequential OMS machine, across 5 runs with 3 orthogonal parallel regions, and across 10 and 15 runs in a harder burst-send variant racing an async invoke. Re-run three times to check for flakiness; stable each time. **For the replay engine, the core execution model is replayable.** The caveats are in §2.6 and §2.7, and they are about *which events reach the machine*, not about the machine's response to them.

**Wildcards work** — bare `*` (A11), prefix `order.*` (A13), and an explicit handler correctly out-prioritises `*` for a matching event (A12). **Unknown events are ignored, not errors** (A14) — state unchanged, `is_running` stays `True`, nothing raised. **Child-over-ancestor transition precedence is correct** (A16).

---

## 2. Failures

### 2.1 🔴 `always` that targets its own state deadlocks silently (A10)

The single worst finding for a rule engine.

```python
"loop": {"entry": ["inc"],
         "always": [{"target": "done", "guard": "enough"},   # n >= 5
                    {"target": "loop"}]}                      # self-target fallback
```

Expected `m.done` with `n == 5`. Observed **`m.loop` with `n == 1`** — it ran once and stopped.

Cause (`base_interpreter.py:1769`): `if target_state == transition.source and not transition.reenter` classifies *any* self-target as an internal transition — actions only, no exit/entry. An `always` self-target therefore never re-enters, `entry` never re-runs, the guard is never re-evaluated, and the machine parks. No error, `is_running == True`.

A19 confirms the diagnosis: the identical loop routed through a distinct intermediate state (`A → B → A`) converges correctly to `m.done` with `n == 5`. So "accumulate until a threshold" — a completely ordinary rule-engine and iceberg-slicing shape — works or silently hangs depending on whether you happened to write the loop through a second state.

### 2.2 🔴 `sendTo` cannot address an actor by its `invoke` `id` or `systemId` (C16)

```
by_service_key ("child") -> "PONG"   ✅
by_invoke_id   ("kid")   -> None     ❌  invoke: {"id": "kid", "src": "child"}
by_system_id   ("kid")   -> None     ❌  invoke: {"id": "kid", "src": "child", "systemId": "kid"}
```

Only the **service key** resolves. The declared `id` and `systemId` are both ignored. Actor ids are minted as `parent:<serviceKey>:<uuid>` — the `id` never enters the string — and `_resolve_actor_target` matches on `actor_id.split(":")[1:]`, i.e. the service key or the uuid. The failure is a `logger.warning` and a **dropped event**.

This is a hard blocker for trade-group fan-out, where you invoke the *same* child machine under several distinct ids and address them individually. The service-key path is not just an alias — it is the *only* working name, and it is ambiguous by construction when N children share one `src` (the code logs "ambiguous, event dropped" for >1 match). Verified the transport itself is fine by delivering directly to the actor object, which produced the expected `p.got` / `PONG`.

### 2.3 🟠 A self-transition with an explicit target does not re-enter (A3 / A17)

`{"target": "A", "actions": ["tAct"]}` from state `A` logs only `["tAct"]` — no `xA`, no `eA`. XState v5 treats an explicit self-target as **external** (exit + action + entry); `internal: true` or omitting the target is how you opt out. This library inverts the default.

`reenter: True` is the workaround and works correctly (A17 → `["xA", "tAct", "eA"]`). Note `"internal": False` does **not** work — only `reenter` is read. The consequence: any OMS state whose `entry` arms a timeout or re-arms a subscription will silently skip that work on a self-transition. It is the same root cause as §2.1.

### 2.4 🟠 Relative `.child` targets silently do nothing (A5, A18)

```
target ".A2"       -> [] , stays m.A.A1     ❌ silent no-op
target "A2"        -> ["xA1","eA2"] , m.A.A2  ✅
target "#m.A.A2"   -> ["xA1","eA2"] , m.A.A2  ✅
target ".zzz"      -> [] , stays m.A.A1     ❌ silent no-op
```

The leading-dot relative syntax — standard XState, and all over the Stately docs — resolves to nothing. `_resolve_target_state_node` returns `None`, and the caller treats `None` as "no transition" rather than raising `StateNotFoundError`. A typo'd target and a valid-but-unsupported target are indistinguishable: both are silent.

### 2.5 🟠 An unknown target state never fails (C15)

`{"on": {"GO": "nowhere_at_all"}}` passes `create_machine()` and, on `send("GO")`, does nothing: state unchanged, `running == True`, nothing raised. Contrast C14 — an unknown **action** name raises `ImplementationMissingError` at `create_machine()` time, which is the right behaviour. Targets get no such validation at any point. For config-driven rule IR this means a bad rule deploys clean and fails open at runtime.

### 2.6 🔴 Events are dropped while the machine is mid-invoke (C17)

```python
await i.send("NEW")                      # new -> pending (invoke ack, ~5ms)
await i.send("PARTIAL", qty=10)          # arrives while in `pending`
await i.send("PARTIAL", qty=10)
await i.send("FILL", qty=10)
# expected: oms.filled, filled == 30
# observed: oms.live,   filled == 0      ← all three silently dropped
```

There is no queue, no deferral, no error — an event with no handler in the *current* state is discarded (the same `_process_event` "no transition found" path as an unknown event, §A14). Deterministic across 10 runs, so it is not a race; it is the design.

For an OMS this is the most dangerous item in the report, because it is invisible. Fills that arrive during an ack round-trip vanish, and the machine's `filled` total silently disagrees with the exchange. Any adoption needs an explicit deferral mechanism (a `deferred` buffer drained on state entry, or a wildcard re-queue handler in every transient state) rather than relying on the interpreter.

### 2.7 🟠 `raise` is queued behind pending external events (C10)

Expected `["entry", "RAISED", "EXTERNAL"]`, observed `["entry", "EXTERNAL", "RAISED"]`. In XState a raised event is part of the same macrostep and settles before the next external event is dequeued. Here `raise` goes through `_deliver` onto the same FIFO queue as external sends, so an event enqueued earlier wins. Internal consistency is preserved (deterministic), but the microstep/macrostep distinction is not — a state's raised follow-up can be observed *after* an external event that arrived during the transition.

### 2.8 🟡 Guards keep evaluating after a branch is chosen (A6)

Guard array `[g1 false, g2 true, g3 true]` selects `m.second` correctly — but calls `["g1", "g2", "g3"]`. The chosen branch is right; `g3` should never have run. Harmless for pure predicates, not harmless for guards that log, count, or hit a cache. Worth knowing before writing guards with side effects.

### 2.9 🟡 A guard that raises is swallowed as `False` (A20)

Documented behaviour (`base_interpreter.py:2918`), and defensible — but combined with a fallback branch it means a **crashing** risk check and a **failing** risk check are indistinguishable, and both fall through to the permissive branch. For live-enablement gating that is the wrong default; guards on that path need their own try/except and an explicit deny.

### 2.10 🟡 Snapshot restore does not resume timers or invokes (C6, C7)

`from_snapshot()` restores state ids, context, history and actor records correctly (C4, C5 — a restored interpreter starts and processes events fine). But a snapshot taken mid-`after` does not resume the timer (C6: `fired == False` after 400 ms on a 150 ms timer), and one taken mid-`invoke` does not re-run the service (C7: `calls == 0`).

This is **explicitly documented** — "does not re-run entry actions of the restored states or restart any invoked services or `after` timers" — so it is a known limitation, not a bug. Listed because the consequence is severe and easy to miss: an OMS restored from a persisted snapshot comes back with every timeout disarmed and every in-flight exchange call abandoned. Failover needs a reconciliation sweep that re-arms timers and re-issues invokes from the restored configuration.

### 2.11 No strict mode, no payload validation

There is no XState-style `strict` option anywhere in the source. `send("E", qty="not-a-number")` is accepted silently (C12) — payloads are an untyped `dict`, and nothing validates shape or type. Validation must live in our own layer.

---

## 3. Implications for CandleViewer

**Blocking, would need fixing or working around before adoption:**

1. **Event drops during transient states (§2.6)** — the OMS cannot lose fills. Needs an explicit deferral layer; this is not something a config convention fixes.
2. **Actor addressing by `id` (§2.2)** — trade-group fan-out invokes one child machine under many ids. Currently impossible via config; needs a library fix or direct-delivery escape hatch.
3. **`always` self-target deadlock (§2.1)** — affects rule engine and algo slicing. Workaround (route through an intermediate state) exists and is cheap, but it is an unwritten rule that fails silently when forgotten.

**Needs a house style guide, since the defaults are wrong or surprising:**

4. Always write `reenter: True` on self-transitions (§2.3).
5. Never use `.child` relative targets; use absolute `#m.a.b` (§2.4).
6. Validate every rule-IR target against the machine tree at deploy time — the library will not (§2.5).
7. Guards must be pure and must try/except internally on any safety-critical path (§2.8, §2.9).

**Architectural requirement:**

8. Failover/restore must re-arm timers and re-issue invokes itself (§2.10).

**The good news for the replay engine:** determinism is real and survived every attempt to break it, including burst sends racing an async invoke across 15 runs. Given the *same event sequence actually delivered*, the machine's response is reproducible. The risk to replay is not the interpreter — it is §2.6, where the live machine and the replayed machine could see different event sets if timing differs. Fixing the deferral problem fixes replay fidelity too.

**Overall honest read:** the invoke/timer/history core is production-quality and better than I expected — cancellation semantics in particular are correct in ways that are easy to get wrong. The failures cluster in two places: a single root cause (self-target ⇒ internal transition) producing §2.1 and §2.3, and a general pattern of *resolution failures degrading to silent no-ops* rather than errors (§2.2, §2.4, §2.5, §2.6). That second pattern is the real adoption risk. The library's own `docs/FEATURE_GAP_ANALYSIS.md` identified silent failure as "the headline risk" and closed 73 gaps in 0.6.0; the class of defect it named has not been fully eliminated in 0.7.0.

---

## 4. Probe index

| ID | Probe | Status |
|---|---|---|
| A1 | Exit/entry order, nested compound → parallel | PASS |
| A2 | exit → transition action → entry ordering | PASS |
| A3 | Self-transition w/ target, no `reenter`, re-enters | **FAIL** §2.3 |
| A4 | Internal self-transition (no target) skips entry/exit | PASS |
| A5 | Relative `.child` target resolves | **FAIL** §2.4 |
| A6 | Guard fallthrough stops at first match | **FAIL** §2.8 |
| A7 | All guards false ⇒ no transition, no error | PASS |
| A8 | `always` chain with guards settles | PASS |
| A9 | Unguarded `always` A↔B is bounded, survives | PASS |
| A10 | `always` self-target loops until guard flips | **FAIL** §2.1 |
| A11 | Wildcard `*` catches unmatched | PASS |
| A12 | Explicit handler beats `*` | PASS |
| A13 | Prefix wildcard `order.*` | PASS |
| A14 | Unknown event ignored, not an error | PASS |
| A15 | Parallel regions handle event independently | PASS |
| A16 | Child transition beats ancestor | PASS |
| A17 | `reenter: True` re-runs exit+entry (workaround) | PASS |
| A18 | Nonexistent `.child` target is a silent no-op | PASS (documents defect) |
| A19 | `always` loop via distinct state converges | PASS (contrast w/ A10) |
| A20 | Raising guard swallowed as False | PASS (documents §2.9) |
| B1 | `done.invoke.<id>` carries return value | PASS |
| B2 | `error.platform.<id>` carries exception object | PASS |
| B3 | Unhandled invoke error ⇒ `status == "error"` | PASS |
| B4 | Invoke cancelled mid-await on state exit | PASS |
| B5 | Cancelled invoke sends no late `done` | PASS |
| B6 | Compound `onDone` on child final | PASS |
| B7 | Parallel `onDone` only when all regions final | PASS |
| B8 | Final-state `output` on `done.state` data | PASS |
| B9 | `after` fires on time | PASS |
| B10 | `after` cancelled on state exit | PASS |
| B11 | `after` restarts (not resumes) on re-entry | PASS |
| B12 | Shallow history → immediate child + its initial | PASS |
| B13 | Deep history → full nested leaf | PASS |
| B14 | History with no prior visit → parent initial | PASS |
| C1 | In-place mutation doesn't leak into prior snapshot | PASS |
| C2 | Deep mutation doesn't retro-edit prior snapshot | PASS |
| C3 | Two interpreters, one machine, no shared context | PASS |
| C4 | Snapshot round-trip restores ids + context | PASS |
| C5 | Restored interpreter starts and processes events | PASS |
| C6 | Restore mid-`after` resumes the timer | **FAIL** §2.10 |
| C7 | Restore mid-`invoke` re-runs the service | **FAIL** §2.10 |
| C8 | Determinism, sequential OMS machine, 5 runs | PASS |
| C9 | Determinism, 3 parallel regions, 5 runs | PASS |
| C10 | `raise` settles before next external event | **FAIL** §2.7 |
| C11 | Event payload shapes survive intact | PASS |
| C12 | No payload validation (wrong type accepted) | PASS (documents §2.11) |
| C13 | Action exception doesn't kill interpreter | PASS |
| C14 | Unknown action name raises at `create_machine` | PASS |
| C15 | Unknown target state fails loud | **FAIL** §2.5 |
| C16 | `sendTo` by invoke `id` / `systemId` | **FAIL** §2.2 |
| C17 | Events during invoke are not dropped | **FAIL** §2.6 |
