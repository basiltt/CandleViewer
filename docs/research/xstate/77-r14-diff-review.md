# 77 — Round-14 diff review, v0.9.0 → v0.9.1

**Scope:** `git diff v0.9.0..v0.9.1` (35 files, +1746/−123). `git diff v0.9.1..origin/main` (801eacd) is **empty**: main is only the merge commit for PR #249. **Suite:** `suite-v0.9.1.log` shows 3601 passed, 13 skipped, 0 failed, 92.93% coverage. **Time box:** about 20 min, so I reviewed all of `src/` and read `tests/test_round13_findings.py` in part. I did **not** run the attestation workflow or the `--json` benchmark. Probes are in `probes/v0.9.1/`. They use only the stdlib and xstate_statemachine, and they run from cwd `C:/Users/basil`.

## Verdict

**Not a clean pass.** One real hole was reproduced: **T-1**. It sits in the fix that was meant to be this round's security question. The other fixes look correct on review, and their probes agree.

## Findings

### T-1 — `re_mint()` can change `type` and `src`, so a real completion from one invoke can drive a different invoke's `onDone` (REPRODUCED, async engine) — **High**
`re_mint` checks only that the *input* is engine-minted. It then applies any `**fields`, including `type` and `src`, and hands back an `_EngineDone` that `is_system_event()` accepts. Code that holds one genuine completion, such as a plugin that sees `done.invoke.cheap` in `on_event_received`, can turn it into `done.invoke.settle` with arbitrary `data`. The engine then takes that invoke's `onDone` while the real service is still running.
`probes/v0.9.1/p_t1_remint_forge.py` (async def services, parallel machine):
```
forged: _EngineDone(type='done.invoke.settle', data={'amount': 1000000000}, src='settle') is_system_event: True
state: ['m.pay.settled', 'm.probe.ok']
VERDICT: FORGERY SUCCEEDS
```
The CHANGELOG and the comment in `events.py` say re_mint "cannot manufacture standing". In practice, one genuine event of any kind gives standing for every event type of that kind. The tests only patch `data`, `src` and `fired_at`; none tries to change `type`. **Suggested fix:** refuse `type` and `src` in `fields`, or allow only `data` for Done/Error and `fired_at` for After, and add a test that changing `type` raises. **Trust boundary:** plugins are in-process code. Still, the API was shipped specifically as the safe, gated route, so this counts as a defect and not a documented boundary.
The sync-engine probe (`p_t1_remint_forge_sync.py`, def services) was **inconclusive**. A sync invoke finishes inline, so I could not build a window where the target invoke is still pending within the time box. The sync engine uses the same `is_system_event` checks, so I expect it is exposed too, but I have not reproduced it.

### T-2 — the `drain_pending()` receipt error is `InterpreterStoppedError` even when the machine keeps running — Low
`p_t2_drain.py`: after `await drain_pending()` with no `stop()`, the receipt resolves to `Receipt(changed=False, error=InterpreterStoppedError('drained: removed by drain_pending()'))`. `status` stays `running` and later events are processed. Nothing hangs, which is correct. The problem is that code branching on `isinstance(err, InterpreterStoppedError)` will wrongly conclude the machine is down. The docstring presents drain-then-stop as the recipe, and draining without stopping is not documented. **Suggested fix:** document it, or use a dedicated `EventDrainedError` subclass. Both lanes were drained in priority-first order, as documented.

### T-3 — `check_shape` accepts `chain_trips` strings that `int()` accepts — Info
From `p_t3_chain_trips.py`:
- **Rejected with `SnapshotCorruptError`:** `bool`, `"1e3"`, `3.0`, `2.5`, `-1`, `"-1"`.
- **Accepted:** `"-0"`→0, `" 7 "`, `"+3"`, the Arabic-Indic digit `"٣"`→3, `"1_000"`→1000, and `10**30`.

No raw `ValueError` or `TypeError` escapes, so #241 is closed. Rejecting floats is a stricter choice than the task premise assumed, and it is reasonable. Accepting Unicode digits and underscores is lenient, but it is not a safety issue.

### T-4 — `RestoredChainError` MRO — no defect found
MRO: `RestoredChainError → RestoredError → RunawayChainError → XStateMachineError`. I found no `isinstance` dispatch in `src/` that branches on `RestoredError` or `RunawayChainError` in a way that would now match both. `.limit` and `.dropped` are class-level `None`. `RunawayChainError.__init__` is skipped, and the new code reads only `str()` and `chain_trips`. No dereference of `.limit` or `.dropped` was found outside the constructor.

### T-5 — `dropped_receipts` and `on_receipt_dropped` — review only, one caveat
The counter is incremented and the hook is called from `Receipt.__del__`. That runs in whatever thread triggers garbage collection, which may not be the loop thread, and it can run after `stop()`. The counter is a plain `+=` with no lock. Plugin hooks called from a finaliser have their exceptions swallowed and sent to `sys.unraisablehook`. `re_mint` creates events, not receipts, so it cannot double-count. **Caveat to document:** the hook may run off-loop and after stop. I did not probe this under GC pressure (time box).

### T-6 — `on_interpreter_start` on restore — review OK
All three sync resume branches and the async resume branch now call `_notify_interpreter_start()`. The sync "already running" branch has a `_start_notified` guard. `restored_from_snapshot` stays `True` for the instance's lifetime, does not flip after the first event, and is not persisted. That matches the docstring. I did not probe `from_snapshot(plugins=)` and `.use()` together.

### T-7 — `SyncInterpreter` keyword parity — OK
`max_queue_size` other than `None` raises `ValueError`, and the message names the alternative. `overflow_policy` on its own, without a bound, is silently ignored. That is minor and documented.

### T-8 / T-9 / T-10
- **T-8, `--json` schema:** only the tests were read (`test_host_info_has_the_documented_keys`). No schema version field was seen. Not verified.
- **T-9, `publish.yml`:** the +30 lines add Trusted Publishing and attestations. Not executed.
- **T-10, test changes:** the tests diff has no deleted `def test` lines and no `xfail`. The only test change is the new file, `test_round13_findings.py`.

## Recommendation
**Do not sign off as fully battle-tested yet.** Ask the maintainers to restrict the fields `re_mint` will accept (T-1) and to decide on T-2. Everything else in round 13 checks out as closed.
