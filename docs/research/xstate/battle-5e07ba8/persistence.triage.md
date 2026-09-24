# Triage: persistence track (battle-5e07ba8)

Re-verification pass over `persistence.md`. Each defect was re-run in a
fresh process (`.venv-main` interpreter, `PYTHONIOENCODING=utf-8
PYTHONUTF8=1`, `PYTHONPATH=.../src`), and the cited library source was
re-read to confirm the root cause. No library source modified; no git run
in CandleViewer.

## Re-run log (this pass, 2026-09-18)

| Script | Command | Exit | Observed |
|---|---|---|---|
| `d3_torn_snapshot.py` | full | 0 | `state_ids=[]`, `configuration=['torn']`, restored `status=running error=None has_dormant_invocations=False`, PING receipt `state_ids=frozenset()` — matches doc verbatim |
| `d2_after_timer_lost.py` | full | 0 | reference fires at 6 s (`fired=True`); both `restart_services=False` and `=True` restores show `dormant=False pending_invocations=[] clock.pending=0` and never fire by 11 s — matches doc |
| `d6_priority_lane.py` | full | 0 | `_priority_queue=['after.1000.lanes.waiting']` but `SNAPSHOT pending_events=[]` and `SNAPSHOT deferred=[]`; restored machine never fires even after +60 s virtual time — matches doc |
| `t3_probes.py` | full (P1–P10) | 0 | P1/P6/P6c/P8/P9/P9b/P10 PASS; P5 FAILs exactly as claimed (`lateness lost: 1.0/2.0 -> 0.0/0.0`); P7 reproduces all 17 mutation outcomes (4 well-handled, 3 correctly-refused, 3 silently-accepted incl. `status=banana` and `ctx=42`, 7 raw-builtin leaks) — matches doc |
| `t4_receipts_provenance.py` | full (P11/P12) | 0 | P11: replayed event gets no receipt, confirmed; P12: `after.hours`→`system=True`, `xstate.custom`→`system=True`, `done.review` correctly stays `system=False` — matches doc |
| `t7_rollback.py` | full | 0 | post-rollback restore is correct (`states=['rb.a']`, withdrawn SELF not replayed); mid-macrostep snapshots during the same failing transition are torn (`state_ids=[]` with `n=1 log=['bump']` at the `raise`/`explode` boundary) — matches doc |
| `t8_midstep_property.py` | **reduced to 500 cases** (doc used 2,000; time-bound) | 0 | `snapshots taken=150, legal=88, EMPTY=31, missing_region=31, => 62/150 = 41.3% TORN`, `snapshot raised=0` — same order of magnitude as the doc's 37.6%/447; confirms the finding, exact percentage not expected to match at 1/4 the sample |

Library source re-read and confirmed to match the doc's citations exactly
(comment text is verbatim in the current tree):
- `base_interpreter.py` "ATOMICITY: exit → actions → enter is ONE
  transaction" comment, `get_persisted_snapshot()` reading
  `self._active_state_nodes` directly with no processing-flag interlock,
  and `from_snapshot()`'s configuration-reconstruction loop performing no
  legality check (non-empty / one-leaf-per-region).
- `from_snapshot()` signature: `(cls, snapshot_str, machine, *,
  verify_machine_hash=True, restart_services=False)` — no `clock=`
  parameter; docstring states explicitly "no invoked service or `after`
  timer is restarted" as the static default, and `restart_services=True`
  → `_restart_dormant_invocations()` iterates `state.invoke` only, never
  `state.after`.
- `Interpreter.__init__` takes `clock: Optional[Clock] = None`, confirming
  a restored interpreter (built via `cls(machine)` inside `from_snapshot`)
  always gets the default clock unless the caller does private-attribute
  surgery.

## Disposition table

| ID | Doc sev | Re-run | Root cause confirmed in source | Kind | Re-assessed sev | Reason |
|---|---|---|---|---|---|---|
| D-persistence-3 | Blocker | ✅ reproduced (both minimal repros + 41.3%/150 quantification, same order as doc's 37.6%/447) | ✅ `get_persisted_snapshot()` reads `_active_state_nodes` with no interlock on the documented "ONE transaction" window; `from_snapshot()` has no configuration-legality check | LIBRARY-DEFECT | **Blocker** (unchanged) | On the order path a crash is exactly "interruption at an arbitrary moment"; this makes 30–40% of realistic crash windows produce a silently-healthy, permanently-inert order. No downgrade: the harness's crash-injection technique (`on_action_execute` hook + async freeze) is public API, not a synthetic edge case, and the missing legality check is confirmed absent in the current source. |
| D-persistence-2 | High | ✅ reproduced (both restart modes fail to re-arm, no signal) | ✅ docstring confirms static default; `_restart_dormant_invocations` only walks `state.invoke`, never `state.after`; `pending_invocations()`/`has_dormant_invocations` are invoke-only by construction | DESIGN-CONSTRAINT (documented default) **+ LIBRARY-DEFECT** (missing opt-in / missing signal) | **High** (unchanged) | The static default itself is documented and defensible (DESIGN-CONSTRAINT), but the *absence of any opt-in to re-arm* and the *absence of any dormancy signal for timers* are gaps against the library's own stated goal (§44's dormancy APIs) — those two gaps are genuine defects, not documented behavior. For an OMS where `after` encodes the exchange-ack deadline, an invisible dead timer is a silent architectural hazard, consistent with High. |
| D-persistence-6 | High | ✅ reproduced (`_priority_queue` non-empty, `pending_events`/`deferred` both empty in the snapshot, timer never fires post-restore) | ✅ `_snapshot_pending_events()` reads only the inbox (`_event_queue`); priority lane (`_priority_queue`) has no persistence path and no doc comment analogous to the internal lane's "mid-macrostep state; never persisted" | LIBRARY-DEFECT | **High** (unchanged) | Confirmed asymmetry with the internal lane: the internal lane's omission is intentionally documented, the priority lane's is not, and the priority lane holds an event the engine has already committed to delivering (deadline elapsed). Combined with D-2 this leaves no crash-survivable window for an `after`-driven deadline — directly relevant to the exchange-ack timeout on the order path. No downgrade. |
| D-persistence-4 | Medium | ✅ reproduced (all 17 mutation outcomes match, including the 3 silently-accepted and 7 raw-builtin-leak shapes) | ✅ `json.JSONDecodeError` is wrapped at the decode step (`base_interpreter.py`) but the field reads after it are not; the `isinstance(dict)` merge guard falls through to a bare assign on type mismatch; `restore_event`'s `if` ladder has no `else: raise` | LIBRARY-DEFECT | **Medium** (unchanged) | Correctly scoped: the four realistic corruption shapes (truncated/empty/null/wrong-type-container) are handled well via `XStateMachineError`; only synthetic field-level corruption inside an otherwise-valid JSON object escapes as a raw builtin or is silently accepted. A corrupt store is already an out-of-band failure mode for an OMS, so Medium (not High) is appropriate, but it should be filed since `except XStateMachineError` — the library's own documented catch-all — does not actually catch all its own failure modes. |
| D-persistence-1 | Medium | ✅ reproduced (`harness.attach_clock` needed for every timer-relevant script in this pass; `from_snapshot` signature has no `clock=`) | ✅ `from_snapshot()` constructs via `cls(machine)`, discarding any `clock=` the caller might want; `Interpreter.__init__` accepts `clock=` but `from_snapshot` has no matching parameter | LIBRARY-DEFECT | **Medium** (unchanged) | Genuine API gap, not a design constraint — nothing about virtual time make it un-persistable, it's simply an omitted parameter. Kept at Medium: the workaround (`attach_clock`, two attribute writes) is small and stable, and most production deployments run `RealClock`, but any deterministic-time test harness (which an OMS certainly wants) hits this immediately. |
| D-persistence-7 | Medium | ✅ reproduced (`P5 v2 round-trip: AfterEvent lateness lost: 1.0/2.0 -> 0.0/0.0`) | ✅ `persist_event`/`restore_event` for `AfterEvent` write/read only `kind`+`type`, defaulting `scheduled_for`/`fired_at` to 0.0 | LIBRARY-DEFECT | **Medium** (unchanged) | Small, well-isolated codec gap ("two lines" per the doc). Currently masked by D-6 (the event this affects is never persisted at all today), but fixing D-6 without this makes a false "on-time" telemetry value live — worth tracking together but each is independently Medium: it's an observability defect, not a correctness/money defect on its own. |
| D-persistence-8 | Low | ✅ reproduced (`after.hours`→laundered `system=True`, `xstate.custom`→laundered, `done.review` correctly not laundered — 3/3 match doc) | ✅ `restore_event`'s v1 branch: `kind = "system" if etype.startswith(ENGINE_EVENT_SHAPES) else "event"`, confirmed name-based re-derivation with no other signal available at that boundary | LIBRARY-DEFECT (narrow, ride-along) | **Low** (unchanged) | Requires a v1 blob (pre-0.8.1) containing a user event with an engine-shaped name, which #79 now rejects going forward at `send()` — so the exposure window is closed for new events, only legacy blobs are affected. Correctly scoped as a ride-along on #79/#86 rather than a standalone High; no upgrade or downgrade. |

## Gate impact (unchanged from doc)

D-persistence-3 remains a confirmed Blocker after independent re-run and
source re-read, and per the standing decision rule a Blocker is dispositive
regardless of High count. **Recommendation unchanged: library-adoption half
stays DEFER for the persistence path; the in-house shim carries the
order-lifecycle persistence responsibility**, with CV-P01–CV-P07 as stated
in the source document (validate every restored configuration; never trust
`after` alone for an order-lifecycle deadline; wrap `from_snapshot()`
restore in `except Exception` + explicit post-restore assertions; treat
`InterpreterStoppedError` as "unknown," never "did not happen").

## What this pass did not re-verify

- `t1_crashpoints.py` and `t2_property.py` (quiescent-boundary 2,000-case
  clean result) were not re-run this pass — the six defects above do not
  depend on that result, and it was not challenged. Take the doc's
  20/22 + "0 failures / 2,000" figures as previously established, not
  re-confirmed here.
- `t8_midstep_property.py` was re-run at 500 cases instead of 2,000 to fit
  the 90 s time bound; the 41.3%/150-snapshot result is the same order of
  magnitude as the doc's 37.6%/447 and is sufficient to confirm the defect
  is real and not a fluke of sample size, but the exact percentage was not
  reproduced to the doc's precision.
- `d5_invoke_dormancy.py` (documented, not a defect — CV-P05) was not
  re-run separately; its content is subsumed by `t3_probes.py` P3, which
  was re-run and matches.
