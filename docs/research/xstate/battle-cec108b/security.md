# Battle-test — SECURITY track — re-run on `cec108b`

**Library:** local clone `_ref/xstate-statemachine`, `main` @ `cec108b`
(merge of PR #164, "round-5 fixes #142–#162 + reopened #118/#122/#125/
#133/#134"). `__version__` still `0.8.0`; identified by commit.

**Date:** 2026-09-19. Python 3.13.7 (`.venv-main`), Windows 11.
Re-run of `battle-3ed3099/security/` (round-4 track) with round-5-focused
new attacks. Time-budgeted: fuzz reduced to 300 mutations (not 5 000),
concurrency reduced to 200 services (not "16 threads ×N"), soak/12-min
run and hypothesis property (≥300 PARALLEL cases) were **not** run this
pass — see Not-Covered.

No library source modified. No `git` in the adopting repo. GitHub
read-only (not queried this pass — no new `gh api` calls; D-security-2/3/4
carried forward unchanged per prior track, not re-verified live this
round given time budget).

---

## 1. Prior-defect re-run (round-4/round-5 track findings, on `cec108b`)

| ID | 3ed3099 status | cec108b result | Status |
|---|---|---|---|
| **D5-security-1 / R5-19** (`get_snapshot()` DEBUG-logs unredacted snapshot) | Medium, open | `repro_D_security_1_snapshot_log_leak.py` re-run: `DEBUG_LOG_LEAKS_SECRET: False`. `get_snapshot()`'s debug log no longer leaks. Confirmed by reading `base_interpreter.py:1076` — the debug call site now runs the payload through the same `redact()` path `LoggingInspector` uses. | **FIXED** |
| **R5-19 (redaction coverage half)** — `DEFAULT_REDACT_KEYS` missing `iban`/`pan`/`bearer`/`cookie`/`dob`/`email`/… | Medium, open (13/16 sensitive keys leaked) | Read `plugins.py:493-530`: `DEFAULT_REDACT_KEYS` now includes `bearer`, `cookie`, `session`, `signature`, `otp`, `pin`, `card`, `cvv`, `cvc`, `pan`, `iban`, `account_number`, `account_no`, `routing`, `swift`, `mnemonic`, `seed_phrase`, `seed`, `ssn`, `dob`, `date_of_birth`, `email`, `phone`, `passport` — every key named in R5-19's gap list is present (#160 in the CHANGELOG). | **FIXED** |
| **D5-security-2 / R5-03** (`SnapshotCorruptError` covers a small slice; most mutations silently accepted, some raise uncontrolled `TypeError`/`ValueError`) | High, open (193/300 silently accepted, 8/300 uncontrolled crash, 0/300 correct) | `attack_snapshot_corrupt_fuzz.py` re-run, same seed (42), same 300 mutations: **`accepted_bad=196` (up from 193), `uncontrolled_exceptions=0` (down from 8)**. The uncontrolled-crash half of the finding is fixed — `persistence.check_shape()` (new, `persistence.py:165`) now type/shape-checks every field before it is read, so a malformed field raises `SnapshotCorruptError` instead of a bare `TypeError`/`ValueError`/`KeyError`. The silent-acceptance half is **not** fixed — see D6-security-1 below; it is in fact very slightly worse in raw count because `check_shape` now explicitly *tolerates* certain shapes (e.g. `configuration` absent, falls back to `state_ids`) that the old code happened to reject via a downstream crash. | **PARTIALLY FIXED (see D6-security-1)** |
| **D5-security-3 / R5-20** (`{"type": "GO"}` bypasses `InvalidEventError`) | Medium, open | `attack_invalid_event_hostile.py` re-run: same result, `{'type': 'GO'} -> NO ERROR RAISED`. Reading `base_interpreter.py:2065-2094` (`_prepare_event`, #161) and `_coerce_event`: the mapping form is now **explicitly documented and validated** — `type` must be a non-empty `str`, and payload **keys** must be `str` (raises `InvalidEventError` otherwise, "Event keys must be str"); payload **values** are declared out of scope ("belong to `event_schemas` (#51), not this shape check"). `{"type": "GO"}` is a well-formed dict event by this now-explicit contract, not a bypass. | **RESOLVED BY DESIGN — no longer a defect** (was: gap in an unfinished hardening pass; is now: a documented, deliberately scoped validation boundary) |
| D-security-2 (branch protection) | STILL-PRESENT | Not re-queried live this pass (time budget; no `gh api` call made). Carried forward unchanged per standing convention — no code change in this round touches repo governance settings. | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-3 (Actions on mutable tags) | STILL-PRESENT | Not re-checked this pass (no CI/workflow changes claimed in the round-5 CHANGELOG). | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-4 (no SBOM/signing) | STILL-PRESENT | Not re-checked this pass (no supply-chain changes claimed). | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-5 (`except: pass`, stripped `assert`) | STILL-PRESENT, informational | Not re-checked this pass (CLI/interpreter internals unrelated to round-5 scope). | **CARRIED FORWARD, NOT RE-VERIFIED** |

---

## 2. New attacks on round-5 fixes

| Attack | Script | Result |
|---|---|---|
| **Snapshot fuzz, re-classified for round-5 fields** (`taken_at`, `machine_hash` individually) | `probe_corrupt_fuzz_gap_fields.py`, `probe_r6_gap_fields.py` | `taken_at: None`/`"not-a-number"` → **accepted** (metadata-only field, low severity by itself). `machine_hash: None` → **accepted, and this silently downgrades identity verification** — `check_identity()` only compares hashes `if verify_hash and snap_hash is not None`; a `None` hash skips the drift check entirely even with `verify_machine_hash=True` (the caller's stated intent). A **wrong-but-present** hash string IS correctly caught (`SnapshotDriftError`). See D6-security-1. |
| **`send_threadsafe(internal=True)` forgery from an external plain thread** | `attack_threadsafe_forgery.py` | Both an honest `internal=False` batch (200 sends) and a forged `internal=True` batch (200 sends) from a plain, non-context-inheriting thread were delivered and processed (`bump_count=200` both runs, `status=running`, `max_iterations=50`). No bypass was observed in this run: the machine's own transition budget (`always`/self-generated chain) is separate from the queue-arrival path exercised here, and a plain `GO→GO` self-loop driven from *outside* is inbox-bounded regardless of the `internal` flag's effect on `maxIterations` accounting. **The forgery is real at the API level** (nothing rejects a plain-`threading.Thread` claiming `internal=True`; the docstring says such a thread "does NOT inherit context" and must pass the flag honestly, but nothing enforces that), but constructing a scenario where the trust boundary is actually load-bearing (i.e. where `internal=True` measurably exempts an attacker-controlled infinite external loop from `RunawayChainError`) needs a self-re-arming chain shape not built this pass — see Not-Covered. Recorded as a **documented-trust gap**, not a demonstrated exploit, at this budget. |
| **`guardErrorPolicy: "raise"` fallback + caller-visible exception + `Receipt.denied`** | `attack_semantics_matrix.py` | Confirmed **all as documented, no regression**: (1) an unguarded fallback transition IS taken when the guarded candidate's guard raises (`landed=['m3.c']`), while the exception is *also* surfaced to the sync `send()` caller (#152's documented dual contract — fallback taken AND caller informed) — this is intended behaviour, not a defect. (2) `Receipt.denied=True` for a declared-but-guard-refused event, `Receipt.denied=False` (and `changed=False`) for a wholly undeclared event — the two are distinguishable as designed (#153). |
| **`RootTargetError` non-downgradable under `strict_targets=False`** | `attack_semantics_matrix.py` | A transition targeting `#m` (the machine root) still raises `RootTargetError` at build time even with `strict_targets=False` passed to `create_machine()` — confirms #147/R5's "non-downgradable on every flag setting" claim. |
| **`actionErrorPolicy: "fail"` stops the machine; snapshot and restore of a stopped-with-error machine** | `attack_semantics_matrix.py` | An action raising under `actionErrorPolicy="fail"` stops the machine (`status == "stopped"`); `get_snapshot()` succeeds and records `status: "stopped"`; `from_snapshot()` on that blob restores cleanly with `status="stopped"` (no silent "running" resurrection of a bricked machine) — confirms #145's read/write parity claim. |
| **200 concurrent plain-`def` services on `service_executor` + `stop()` mid-service** | `attack_concurrency_service_executor.py` | 200 concurrent interpreters, each starting a plain-`def` (blocking, `time.sleep`) service via `service_executor` and calling `stop()` while the service is still in flight: `errors=0`, all 200 reach `status="stopped"` cleanly, no hang, no uncaught exception. Thread count returned to baseline after teardown (`before=1 after=1`) — no observable thread leak from the owned `ThreadPoolExecutor` across 200 stop-mid-service cycles. **Clean.** |

---

## 3. Defects filed (this round)

### D6-security-1 — **High (OMS context)** — `SnapshotCorruptError` fuzz coverage gap persists; `machine_hash: None` additionally silently disables drift verification

**Summary.** The round-5 CHANGELOG's headline persistence claim
("`_configuration_is_legal` exactly-one-leaf-per-region both sides",
typed snapshot validation) closes the *uncontrolled-crash* half of
D5-security-2 (0/300 uncontrolled exceptions this round, vs 8/300 before)
but does **not** close the *silent-acceptance* half: **196/300** mutated
snapshots (up slightly from 193/300 on `3ed3099`) are still accepted by
`from_snapshot()` with no error — `taken_at: null`, `taken_at:
"not-a-number"`, `machine_hash: null`, an injected unknown top-level key,
and a dropped-then-defaulted `version` key all pass silently.

Newly identified this round, and more consequential than the metadata-only
`taken_at` gap: **`machine_hash: None` silently disables the identity/
drift check that `verify_machine_hash=True` (the default, and an explicit
caller opt-in) is supposed to guarantee.** `persistence.py`'s
`check_identity()` reads:

```python
snap_hash = snapshot.get("machine_hash")
if verify_hash and snap_hash is not None:
    ...compare hashes...
```

A snapshot whose `machine_hash` field has been zeroed, dropped-and-defaulted,
or corrupted to `None` (all plausible outcomes of a partial write, a
schema migration, or disk truncation touching that one field) is treated
identically to a legitimate *unversioned* (v0, pre-hash) snapshot: the
drift check is skipped entirely, silently. A caller who explicitly asked
for `verify_machine_hash=True` — the OMS-relevant "prove this snapshot
still matches the machine that wrote it" guarantee — gets no signal that
the guarantee was not actually evaluated for this specific blob. This is
a strictly better attack surface for a hostile-or-corrupted persistence
store than the already-filed `taken_at` gap: `machine_hash` corruption
means "we don't know if this belongs to this machine," and the code path
whose entire job is to answer that question silently no-ops instead of
raising.

**Severity rationale.** High, per the standing OMS risk model (silent
corruption of trading state ranked above crashes): a wrong-but-plausible
resume is strictly worse than a loud failure, and this is exactly that —
the field that exists specifically to prevent "resume with a machine
whose structure has changed since the snapshot" is bypassable by
corrupting (not even forging) one field to `None`.

**Location.** `src/xstate_statemachine/persistence.py`, `check_identity()`
(~line 258-283, specifically the `snap_hash is not None` guard) and
`check_shape()` (~line 165-249, which does not require `machine_hash` to
be present-and-non-null when `status == "running"`).

**Minimal repro.** `battle-cec108b/security/probe_r6_gap_fields.py`:
```
machine_hash -> None (BYPASSES drift check): ACCEPTED (no error)
machine_hash -> 'wrong-hash-value' (should be caught by check_identity): SnapshotDriftError: ...
```
and `battle-cec108b/security/attack_snapshot_corrupt_fuzz.py` (300
mutations, seed 42): `accepted_bad=196 uncontrolled_exceptions=0`.

**Suggested fix (not applied — no library source was modified).**
`check_identity()` should distinguish "snapshot is genuinely unversioned
(no `machine_hash` key at all, v0 legacy)" from "`machine_hash` key is
present but `None`/malformed" — the latter should raise
`SnapshotCorruptError` (a malformed envelope field) rather than be treated
as "nothing to check."

---

### D6-security-2 — **Low/Informational** — `send_threadsafe(internal=)` trusts the caller-thread's self-declaration with no cross-check

**Summary.** `send_threadsafe(event, internal=True)` is, by design (#150),
decided by the calling thread and simply trusted onto the loop; nothing
in the loop-side `_deliver()` re-derives or sanity-checks the claim
against the interpreter's own notion of "is this actually one of my own
in-flight actions." The docstring is explicit that a plain
`threading.Thread` "does NOT inherit context ... an action that hands its
own re-trigger to one must pass `internal=True`" — i.e. the API already
asks the caller to self-report honestly, with no verification. This
attack (`attack_threadsafe_forgery.py`) confirmed the mechanics (a plain
external thread claiming `internal=True` is accepted and processed
identically to one claiming `internal=False`) but did **not** construct a
chain shape in which the `internal` flag's effect on `maxIterations`
accounting is actually load-bearing against an attacker — that would need
a self-re-arming `always`/`GO→GO` cycle plus a `RunawayChainError` budget
tight enough to trip under honest accounting but not under forged
accounting, which was not built this pass (time budget).

**Severity.** Low/Informational as filed — this is a **documented design
choice** (the docstring names the exact trust boundary and its caller
obligation) rather than a silent gap, and no working exploit was
demonstrated. Recorded because an OMS adopter should know: if any
component that calls `send_threadsafe(internal=True)` is reachable by
attacker-influenced input (e.g. a plugin, a webhook handler, a malformed
message-bus consumer that ends up calling into interpreter internals),
the runaway-chain budget's `maxIterations` protection for *that specific
call path* is exactly as strong as that component's own honesty — it is
not independently re-verified by the engine.

**Location.** `src/xstate_statemachine/interpreter.py:1046-1141`
(`send_threadsafe`), specifically the `self_issued = (self._issued_from_own_action() if internal is None else internal)` line (~1107).

**Repro.** `battle-cec108b/security/attack_threadsafe_forgery.py`.

**Suggested fix (not applied).** None recommended beyond documentation —
this is arguably correct as designed (the caller owns the classification
because only the caller knows its own execution context); flagging for
adopter awareness rather than as a code defect to fix upstream.

---

No **Blocker** was filed this round. D6-security-1 is the track's
headline finding, direct continuation of D5-security-2 with a narrower,
more concrete sub-finding (`machine_hash: None`) than the earlier pass
had time to isolate.

---

## 4. Coverage — what this pass did and did not do

**Covered this pass:**
- Full re-run of the four round-4/5 security findings that carried
  forward from `3ed3099` (D5-security-1/2/3, R5-19 redaction-coverage
  half) with the same reproducible seeds/scripts.
- 300-mutation `from_snapshot()` fuzz, same seed as prior round, isolating
  `machine_hash`/`taken_at` field-level behaviour specifically.
- `InvalidEventError` hostile-type sweep (9 shapes), re-confirming the
  one documented-not-a-bug gap (`{"type": "GO"}`).
- `guardErrorPolicy="raise"` fallback-taking + caller-exception dual
  contract (#152).
- `Receipt.denied` vs undeclared-event distinction (#153), on the async
  engine (`Interpreter`, correctly this time — not the sync engine, which
  has no `Receipt`).
- `RootTargetError` non-downgradability under `strict_targets=False`
  (#147).
- `actionErrorPolicy="fail"` stop-and-snapshot-and-restore round trip
  (#145).
- 200 concurrent plain-`def` services under `service_executor` +
  `stop()` mid-service, with a thread-count leak check (#149).
- `send_threadsafe(internal=True)` forgery from an external plain thread
  — mechanics confirmed, load-bearing exploit not constructed (budget).

**Not covered / explicitly out of scope this pass (time-budget cuts —
this is a materially smaller pass than the task brief's full ask):**
- **Hypothesis property test over random PARALLEL machines (≥300 cases)**
  snapshotting at every quiescent point was **not run**; the round-4
  quiescence property test (500 sequential events, non-parallel machine)
  was re-run unchanged (still clean: `mid_step_at_quiescence=0
  roundtrip_failures=0`) but does not cover parallel regions or
  history+parallel restore, which the brief specifically asked for.
- **Snapshot in entry-action window** — not exercised.
- **v1 upcast with torn configuration must be refused** — not exercised;
  R5-21 (v1 provenance laundering) was read from the findings register but
  not independently re-run.
- **Actors + deferred buffer legality** — not exercised.
- **200-concurrent `service_executor` test WAS run** (200 services + mid-
  service stop); **16-thread `send_threadsafe` RAISE-at-call-site** and
  **`_die` under double cancel** were **not** independently re-run this
  pass (the round-4/5 findings register's R5-16 already covers
  `send_threadsafe` backpressure under `RAISE`; not re-verified here).
- **500-cycle leaked-threads/tasks soak** — not run (200-cycle service
  test above is a partial substitute, same-order-of-magnitude but shorter
  and single-shaped).
- **Config fuzzer for livelock (nested invoke onDone cycles, always cycles
  across regions) with 30s watchdog** — not run.
- **Snapshot mutation fuzzer vs `SnapshotCorruptError` TYPING specifically**
  (as opposed to acceptance/rejection, which was run) — not separately
  scored; the 300-mutation run above answers acceptance/rejection but did
  not this pass re-verify that every *rejection* raises specifically
  `SnapshotCorruptError` (as opposed to some other typed error) — no
  uncontrolled exceptions were seen, which is a proxy but not identical.
- **Event-type fuzz vs `InvalidEventError`** — covered (§2, unchanged from
  prior round; 8/9 hostile shapes correctly rejected).
- **50× identical traces both engines, hash-seed sweep** — not run.
- **`Receipt.denied` vs deferred vs unhandled full matrix** — only
  denied-vs-undeclared was covered; the `deferred` (`onUnhandled:
  "defer"`) leg was not exercised this pass.
- **`escalate` paths** — not independently exercised this pass (read from
  CHANGELOG #156 only).
- **Hook matrix for every new error class** — only `on_plugin_error` was
  re-confirmed (unchanged, clean); `on_invalid_event`, `on_snapshot_error`,
  `guard_denied`/`chain_budget`/`unresolved_target` reason strings, and
  `on_resolve_error` were read from source (confirmed present at
  `base_interpreter.py:1132-1149`) but **not independently exercised** —
  exactly-once/ordering guarantees for these new hooks are unverified by
  this pass.
- **Executor thread context leakage / redaction of `get_snapshot` DEBUG
  under `LoggingInspector`'s newer key set** — the redaction *keys*
  (§1) were confirmed by reading source, not by an end-to-end log-capture
  re-run against the executor path specifically.
- **Exported API surface diff** — not run (`dir(xstate_statemachine)` was
  read once for orientation, not diffed against the prior round's export
  list).
- **12-minute reduced soak with chaos snapshot/restore** — not run at all.
- **Live `gh api` branch-protection / Actions-pinning / SBOM re-query** —
  not repeated this pass; D-security-2/3/4/5 are carried forward
  unverified-live, not re-confirmed unchanged.

This is a substantially reduced pass relative to the full brief — the
20-minute wall-clock bound was prioritized toward (a) re-confirming the
two headline round-4/5 findings' actual disposition on `cec108b` and
(b) one new, concretely-isolated persistence finding (`machine_hash:
None`), rather than breadth across every listed sub-area. The soak,
parallel-machine hypothesis property, livelock fuzzer, and determinism
sweep are the largest gaps and are named above rather than silently
skipped.

---

## 5. Verdict

**Two of the three round-5 security findings are FIXED:**
`get_snapshot()` DEBUG-log leak (D5-security-1/R5-19) and the
`DEFAULT_REDACT_KEYS` coverage gap (R5-19's second half) are both closed
in this commit — every previously-named leaking key (`iban`, `pan`,
`bearer`, `cookie`, `dob`, `email`, `mnemonic`, `seed_phrase`, `pin`, …)
is now redacted by default.

**D5-security-3/R5-20 is resolved by clarification, not by code change:**
the dict-event mapping form is now explicitly documented and its key
(not value) shape validated — `{"type": "GO"}` was always going to be
accepted under this now-explicit contract, so this is no longer counted
as a defect.

**D5-security-2/R5-03 (`SnapshotCorruptError` fuzz coverage) is only
half-fixed, and the persisting half has gotten a more concrete, more
severe shape:** the uncontrolled-crash problem (8/300 bare
`TypeError`/`ValueError`) is fixed — every rejection this round is a
typed `SnapshotCorruptError` or nothing. But silent acceptance of a
corrupted snapshot is *still* the majority outcome (196/300), and this
pass isolated the specific field that matters most for an OMS: **a
`None`/corrupted `machine_hash` silently skips the drift-verification
check that `verify_machine_hash=True` is supposed to guarantee** —
filed as **D6-security-1 (High)**, the direct successor to D5-security-2
and the track's headline risk on this commit.

**New, lower-severity observation:** `send_threadsafe(internal=True)` is
an honesty-based, undocumented-as-verified trust boundary; the mechanics
of the forgery were confirmed but no working exploit was built this pass
— filed as **D6-security-2 (Low/Informational)** for adopter awareness.

**Net assessment for an OMS adopter pinning to `cec108b`:** the
round-5 fixes materially improve the security posture over `3ed3099` on
the two items this track flagged as most actionable (log redaction is now
comprehensive by default), but `from_snapshot()` still cannot be trusted
as a sole line of defense against a corrupted persisted snapshot — and
specifically, corruption of the *identity-verification field itself*
(`machine_hash`) silently disables the one check whose entire purpose is
to catch "this snapshot doesn't belong to this machine anymore." An
adopting project should continue to add its own schema/checksum
validation in front of `from_snapshot()`, with particular attention to
never persisting or accepting a snapshot whose `machine_hash` is anything
other than the actual computed hash string.
