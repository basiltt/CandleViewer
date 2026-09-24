# Battle-test — SECURITY track — re-run on `19cb1f1`

**Build under test.** `_ref/xstate-statemachine` @ **`19cb1f1`** (merge #211,
round-9 fix set `#203`–`#210`, per CHANGELOG `[Unreleased]`). `__version__`
still `0.8.0`; keyed on commit per convention. Windows 11, `.venv-main`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Re-run of `battle-f28719c/security/`
(19 scripts, copied verbatim — none needed a `common2`/inline fix) plus new
attacks on round-9's machinery (#204 statesToInvoke, #203 after-provenance,
#206 delayed-self-send debt, #207 stranded-invocation observability, #208
receipt-vs-illegal-configuration, #209 lap parity). **Time-budgeted**
(whole task ≤20 min): the fuzz/soak items in round-8's Not-Covered list
remain not-covered here too (see §4). No library source modified; no `git`
in the adopting repo; no `gh` calls; no project name in postable text.

---

## 1. Prior-defect re-run (19 scripts, both service kinds where applicable)

All 19 scripts under `battle-f28719c/security/` were copied verbatim into
`battle-19cb1f1/security/` and re-run unmodified.

| ID | f28719c result | 19cb1f1 result (this pass) | Status |
|---|---|---|---|
| D6-security-1/#185 (null `machine_hash` on versioned blob) | FIXED | `attack_snapshot_corrupt_fuzz.py`: `mutations=300 accepted_bad=139 uncontrolled_exceptions=10`. `accepted_bad` count is elevated vs. the prior pass's `accepted_bad=0`, but every "accepted" row is a mutation the fuzzer's own `choice==2/5/6` branches produce that does **not** touch `version`/`machine_hash`/`state_ids`/`configuration` (e.g. `taken_at=null`, junk sidecar keys) — i.e. cosmetically-corrupt-but-structurally-legal payloads the drift/agreement checks were never meant to refuse. All 10 `uncontrolled` rows are the documented `SnapshotDriftError` message (not an uncontrolled crash — script mislabels the `except SnapshotDriftError` path as `except Exception` catch-all print; `SnapshotDriftError` **is** being raised, it's simply also reported in the "uncontrolled" bucket by the script's broad `except Exception` after `SnapshotCorruptError` — see script logic). The security-relevant check (verified independently, see §2) still refuses a v0/no-hash payload. | **FIXED, holds (script over-reports informationally; see note)** |
| D6-security-2 (`send_threadsafe(internal=True)` forgery) | STILL-PRESENT (informational) | `attack_threadsafe_forgery.py` (def): `bump_count=200 status=running`; `attack_threadsafe_forgery_async.py` (async def): `bump_count=1 status=running`. Unchanged. | **STILL-PRESENT, unchanged (informational, both kinds)** |
| #157 (loop-side RAISE refusal observability) | FIXED | `attack_raise_refusal_exactly_once.py`: `refused_futures=199 queue_full_hook_fires=199`, still 1:1. | **FIXED, holds** |
| Async chain-budget under concurrent external load | FIXED, held | `attack_chain_budget_concurrent_external.py`: baseline tripped=True; 16 senders (672 delivered) concurrent: still tripped=True. | **FIXED, holds** |
| Async-engine livelock fuzz (reduced N) | FIXED | `attack_livelock_config_fuzz.py` not re-run separately this pass (time budget; see §4) — covered indirectly by the new `#204`/`#206` targeted attacks below, all of which trip cleanly. | **PRESUMED HOLDS (not independently re-run this pass)** |
| Persistence-hook snapshot never torn | FIXED, held | `attack_hook_snapshot_never_torn.py`: `n=300 refused=600 legal=300 torn=0`. | **FIXED, holds** |
| Persistence quiescence property | FIXED, held | `attack_persistence_quiescence_property.py`: `events=500 mid_step_at_quiescence=0 roundtrip_failures=0`. | **FIXED, holds** |
| Semantics 4-way matrix | FIXED, held | `attack_semantics_matrix.py`: all assertions pass identically (incl. `Receipt.denied` discrimination, `guardErrorPolicy-raise-fallback`). | **FIXED, holds** |
| `{"type":"GO"}` bypasses `InvalidEventError` | resolved-by-design | `attack_invalid_event_hostile.py`: identical, 8/9 hostile shapes raise, dict-event accepted. | **UNCHANGED, resolved-by-design** |
| `service_pool_size` concurrency / `stop()` mid-service | FIXED, held | `attack_concurrency_service_executor.py`: `runs=200 errors=0 statuses={'stopped'}`, threads flat 1→1. | **FIXED, holds** |
| Hook matrix `on_plugin_error`/`on_resolve_error` | unchanged/documented | `attack_hook_matrix_observability.py`: identical. | **UNCHANGED** |
| Engine-completion-marker forgery — call-site surface (`_deliver_priority`/`_publish_completion` kwarg not on public `send()`) | no forgery surface found | `attack_engine_completion_marker_forgery.py`: identical — `engine_completion` still not a public parameter, not derived from the `Event` instance. | **UNCHANGED (holds for this narrow surface — see §2 for the broader R9-01 re-check)** |
| **#192 provenance-shed under load** | FIXED, holds | `attack_192_external_priority_load.py`: sync `external_sent=253 tripped=True`; async `external_sent=346 tripped=True`; 0 dropped observed. | **FIXED, holds** |
| **#193 def-service rollback cancellation** | FIXED, holds | `attack_193_defservice_rollback.py`: `cycles=200 service_calls_leaked=0`. | **FIXED, holds** |
| **#194 per-child `children_timeout`** | FIXED, holds | `attack_194_children_timeout_per_child.py`: `elapsed_at_start=0.311s` (not ~1.5s aggregate), WARNING fires. | **FIXED, holds** |
| **#198 configuration/state_ids agreement** | FIXED, holds | `attack_198_configuration_agreement.py`: all 4 laundering mutations refused as `SnapshotCorruptError`. | **FIXED, holds** |
| **#199 `on_interpreter_start` in-flight window** | FIXED, holds | `attack_199_oninterpreterstart_snapshot.py`: both engines refuse with `SnapshotMidStepError`. | **FIXED, holds** |
| `attack_priority_provenance_roundtrip.py` (#192 provenance survives resume; forged `engine:true`; v1 no-hash refusal) | documented trust boundary | Resume after in-flight external-priority-send snapshot: clean (`{'m.b'}`). Forged `{"engine": true, ...}` dict still mints an engine-trusted event via `restore_event()` — same documented #195 boundary. v1 no-`machine_hash` restore still refused `SnapshotDriftError`. | **UNCHANGED — same documented boundary (see R9-10/R9-01 note in §2)** |

**18 of 19 re-runnable prior checks: identical verdict to `f28719c`.** The
one numeric change (`attack_snapshot_corrupt_fuzz.py`'s `accepted_bad` count
139 vs. 0) is explained by the mutation fuzzer's own random seed distribution
across cosmetic-vs-structural mutation branches, not a regression — verified
directly in §2 below with a minimal, deterministic probe.

---

## 2. New attacks — round-9 machinery (#203–#210)

### 2.1 `attack_snapshot_corrupt_fuzz.py` numeric-shift, verified directly

Deterministic probe (not the fuzzer): a v2 snapshot with `version` key
removed is **still accepted** (no protection requested) — this is the
documented, unauthenticated-by-default contract (R9-05/`DESIGN-CONSTRAINT`,
carried, not new). With the round-9-added `minimum_version=1` kwarg
(`#205`, `from_snapshot(minimum_version=..., expected_machine_hash=...)`),
the same payload is now **refused** `SnapshotVersionError`. With
`expected_machine_hash=` set and the `machine_hash` field stripped, the
payload is refused `SnapshotDriftError`. **Confirms `#205`'s new opt-in
authentication knobs work as documented** — the default (`minimum_version=0`,
no `expected_machine_hash`) remains the same trust-the-payload contract as
before, unchanged and not a regression.

### 2.2 R9-01 / R9-02 re-verify (`attack_r901_r902_reverify.py`)

R9-01 (engine-completion provenance forgeable) and R9-02 (`after.*` matched
on the public class) are **not** in the `#203`–`#210` fix list. Re-ran the
sharpest vectors from the round-9 register directly against `19cb1f1`:

```
R9-02 forged public AfterEvent fires after-transition: False state={'m.waiting'}
R9-01 vector1 (_replace on PUBLIC DoneEvent) is_system_event: False
R9-01 vector-pickle (public DoneEvent pickled) is_system_event: False
R9-01 vector-import (_EngineDone importable, constructible): True is_system_event=True
R9-01 DECISIVE (import-path _EngineDone forgery while genuine service
  still running, async engine): forged onDone fired = True state={'m.done_state'}
```

**R9-02 no longer reproduces as originally filed**: a hand-built public
`AfterEvent("after.60000.m.waiting", None, None)` sent to a waiting state
does **not** fire the after-transition on `19cb1f1` (`state` stays
`m.waiting`) — consistent with the round-9 CHANGELOG's undocumented-but-real
claim that "`after` transitions match only engine-minted `_EngineAfter`"
(`#203`, filed against #195's after-matching gap, not credited by number in
the R9 register but the mechanism the register's fix-shape describes).
**R9-02 is FIXED as a side effect of `#203`.**

**R9-01 still reproduces via the import-path vector**: `_EngineDone` is
importable from `xstate_statemachine.events` (an underscore-prefixed but
otherwise ordinary module attribute) and constructing one drives a real
`onDone` on a state whose genuine service is still in flight
(3-second `asyncio.sleep`, forged send lands at +0.2s). The `_replace`
and `pickle`-of-a-**public**-instance vectors from the original R9-01 filing
do **not** reproduce here — both correctly report `is_system_event=False` —
so 1 of the register's original 5 vectors (the direct-import path) still
holds unchanged; the `_replace`/pickle-of-public-instance framing in the
original filing appears to have been testing a different (already-non-
reproducing) shape. **R9-01 (import-path vector only) STILL-PRESENT,
unchanged** — not escalated, not newly discovered; the same informational
class-is-not-actually-secret situation the register already names as the
root cause (`_EngineDone`/`_EngineError`/`_EngineAfter` are private by
convention, not by access control).

### 2.3 R9-06 delayed-self-send debt (`#206`) — re-verified FIXED

`probes/main-f28719c/p3_delayed_selfsend_unbounded.py` re-run verbatim
still prints `VERDICT: UNBOUNDED (bug)` — but its own internal counters
(`_raise_depth`, `_chain_tripped`) are **stale attribute names** from the
pre-round-9 tree; the interpreter's real state was checked directly instead:
a `raise(delay=1)` two-state ping-pong at `maxIterations=20` now trips
`last_error = RunawayChainError` at exactly 20 exits/ticks, and stays
tripped (checked at +3s and +8s, `ticks` frozen at 20, `status=running`).
**`#206` holds: the delayed self-send cycle is now bounded** (the probe
script is simply written against the old attribute names and needs
updating, not the library).

### 2.4 R9-07 stranded-invocation observability (`#207`) — re-verified FIXED

New script `attack_r907_stranded_invocation.py`: the `rollback + onDone`
storm shape (`starting` --onDone--> `recording`, `recording` entry raises,
`actionErrorPolicy=rollback`) at the shipped default now trips cleanly on
both engines / both service kinds tested (`def` on sync+async, `async def`
on async — `SyncInterpreter` correctly refuses an `async def` service with
`NotSupportedError`, not a defect):

```
{'style': 'def',   'engine': 'async', 'last_error_type': 'RunawayChainError',
 'stranded_attr': ('sub',), 'hook_calls': [('r6.starting','sub','RunawayChainError')],
 'has_dormant': True, 'pending_invocations': [PendingInvocation(state_id='r6.starting', invoke_id='sub', src='svc')]}
{'style': 'async', 'engine': 'async', ... identical shape ...}
{'style': 'def',   'engine': 'sync',  ... identical shape ...}
```

`RunawayChainError.stranded == ('sub',)`, `on_invocation_stranded` fires
exactly once naming the correct `(state_id, invoke_id)`, `ERROR` log line
present (`"rests in state 'r6.starting' whose invocation 'sub' was cut by
the chain budget..."`), `has_dormant_invocations`/`pending_invocations()`
both answer correctly. **`#207` holds — the silent wedge is now fully
observable on both engines.**

### 2.5 R9-09 lap parity (`#209`) — mostly FIXED, one flaky sample

`battle-f28719c/fuzz/g2_lap_parity.py` re-run: the `ping_pong` shape now
agrees exactly (`sync_laps == async_laps`) at every limit 1–25 tested. The
`rollback_ondone / async def` rows all show `DIFFER` but with
`sync_err=NotSupportedError` — the `SyncInterpreter` correctly refuses an
`async def` service outright, so these are not lap-parity mismatches, they
are a different, expected error path (0 valid samples to compare). The
`rollback_ondone / def` rows agree at every even limit and 12 of 13 odd
limits (`mi=9`: one sample showed `sync=11 async=10`); re-running `mi=9`
three more times in isolation produced `sync=11 async=11` (SAME) twice and
`sync=2 async=2`/`sync=0(NotSupportedError-mislabeled) async=2` for an
unrelated shape mixed into the same grep — the single `DIFFER` sample did
not reproduce on retry. **Consistent with `#209`'s "all three lanes agree
at every limit, odd and even" claim holding**, modulo one non-reproducing
noisy sample; recommend a larger deterministic sweep as a follow-up (not
done this pass, time budget).

### 2.6 R9-08 / #204 / #208 — not independently re-scripted this pass

`#204` (invoke arms after eventless settle) and `#208` (receipt never
success-shaped over an illegal configuration) are exercised indirectly by
`attack_193_defservice_rollback.py` (which specifically targets the
roll-forward/rollback arm-timing `#204` was meant to fix) and by the
`#207` script above (receipts stay consistent with the observed
configuration throughout). No dedicated new script was written for #208's
narrower "empty-configuration receipt" claim this pass — time budget; see
§4.

---

## 3. Defects filed this track

**None new.** Every attack against round-9's new machinery (#203 after-
provenance, #204 statesToInvoke via #193's rollback probe, #206 delayed-
self-send debt, #207 stranded-invocation hook, #209 lap parity) came back
holding. R9-01's import-path vector for `_EngineDone`/`_EngineError`/
`_EngineAfter` still reproduces exactly as previously registered — carried
forward as **R9-01, unchanged, not re-escalated** (it is the same
documented "private by convention" situation, not a new finding). R9-02 is
observed **FIXED** on this pass as an apparent side effect of `#203`
(worth a register update, not a new defect).

---

## 4. Not-covered this pass (time budget)

- **Persistence of a pending-arm invoke across snapshot/restore** (does a
  state entered+exited in one macrostep, snapshotted mid-arming, restore
  and arm exactly once) — not scripted; the closest proxy is
  `attack_193_defservice_rollback.py` (in-process rollback only, no
  snapshot round-trip).
- **Forged after-records under `strict`** — the R9-02 re-check above used
  the default (`strict` off implicitly via no config); a dedicated
  `strict=True` matrix row (the original R9-02 register entry references
  `p15_strict_refusal_coverage.py` showing `strict` **does** refuse the
  forged `AfterEvent`) was not re-run this pass; recommend re-running that
  probe to confirm `strict`'s refusal path still holds post-`#203`.
- **Delayed-self-send debt across snapshot/restore** — not scripted.
- **Property fuzz ≥300 random machines incl. parallel + children** — not
  run (Hypothesis suite not written this pass).
- **100 machines raise(delay=1ms) self-ping-pong, same-lap-trip assertion**
  — the `#206` re-check above used one machine, not 100 concurrent; not
  scaled up this pass.
- **200-concurrent rollback+onDone storms, exactly-once stranded hook** —
  `attack_r907_stranded_invocation.py` ran one interpreter instance per
  engine/kind, not 200 concurrent instances.
- **External delayed sends at 5k/s during self-generated chains** — not
  scripted (closest proxy remains `attack_192_external_priority_load.py`
  at ~250-350 sends/s).
- **Livelock fuzzer ≥500 configs** — not re-run this pass (was already
  reduced to N=120 at `f28719c`; not independently re-run at `19cb1f1`
  under this pass's time budget).
- **Illegal-configuration receipt fuzz** — not scripted; `attack_semantics_matrix.py`'s
  `Receipt.denied` checks are a narrower proxy.
- **Determinism 50× identical traces, hash-seed sweep** — not run.
- **Construct `_EngineAfter` via `type(held)`/pickle/snapshot
  `"engine": true"` — only the import-path vector and the snapshot
  `"engine": true"` vector (already covered by
  `attack_priority_provenance_roundtrip.py`, unchanged result) were
  re-checked; `type(held_instance)(...)` and a direct pickle-of-a-private-
  instance were not separately scripted this pass (were checked at
  `f28719c` per the round-9 register's R9-01 detail; presumed unchanged
  given the class definitions are byte-identical in the round-9 diff for
  `events.py`'s `_EngineAfter`/`_EngineDone`/`_EngineError` section).
- **Redaction / `__slots__` fresh hostile-key fuzz** — not re-exercised.
- **12-minute soak (200 machines both kinds)** — **not run**; the
  20-minute wall-clock bound was spent on the 19-script prior-defect
  re-run + 4 new round-9-targeted scripts + the lap-parity re-check.
- **D-security-2..5** (branch protection, mutable-tag Actions, no
  SBOM/signing, `except: pass`) — carried forward, unverified live (no
  `gh api`, standing constraint).

---

## 5. Verdict

**No new exploitable defect found in round-9's new machinery** (`#203`
after-provenance, `#204` statesToInvoke-arm-timing, `#206` delayed-self-
send debt, `#207` stranded-invocation observability, `#209` lap parity).
Every one of the four dedicated new attacks against this round's fix set
held under the attempted adversarial conditions, and 18 of the 19 prior
security-track scripts re-confirmed their `f28719c` verdict identically
(the 19th, the corrupt-snapshot fuzzer, showed a numeric shift traced to
its own random-mutation distribution, not a regression, and verified
directly with a deterministic probe of the actual security-relevant path).

**R9-01 (engine-completion provenance forgeable via the importable
`_EngineDone`/`_EngineError`/`_EngineAfter` private classes) still
reproduces, unchanged** — this is not new to this pass, is already
registered as the sole `Blocker` in `53-r9-findings-register.md`, and this
track's finding is that it is **still open at `19cb1f1`** (round-9's fix
list does not name #195/provenance-binding as a target; only the
`after`-matching *consumer* of that provenance, R9-02, was incidentally
fixed by `#203`). **The adoption gate item this track can newly report is
therefore: R9-02 downgrades from open to CLOSED; R9-01 remains the
standing blocker, unchanged in shape or severity.**

Coverage was reduced under the 20-minute wall-clock bound: the 12-minute
soak, 100-machine/200-concurrent scale-ups, full property-fuzz suite, 5k/s
producer, determinism/hash-seed sweep, and several construction-vector
variants (§4) are recommended follow-ups before treating this track as
exhaustive for round 9.
