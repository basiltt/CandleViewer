# Battle track FUZZ — v0.9.1 (tag 45bb7f3, main 801eacd)

Environment: `.venv-main`, `__version__ == "0.9.1"`, cwd `<home>`.
`git diff v0.9.1..HEAD --stat` is empty, so main has the same code as the tag.
The PyPI wheel sha256 is `d832d4d9…687162`, which matches `/tmp/xsm091` and the PyPI JSON.
The full suite log (`suite-v0.9.1.log`) shows **3601 passed, 13 skipped, 92.93 % coverage**.

## 1. Prior-defect / prior-script table

| Prior item | v0.9.1 result | Status |
|---|---|---|
| D13-fuzz-1: `on_interpreter_start` skipped on restore (`d13_fuzz_1_restored_start_hook.py`) | The hook fires on both engines, for def and async def, with both `plugins=` and `.use()`. The result is PASS. | **FIXED** (#240) |
| `g1_persistence.py` § A: the script asserted `type(err).__name__ == "RestoredError"` | The script now reports 12 "defects". In each one the latched error is `RestoredChainError`, which is a subclass of both `RestoredError` and `RunawayChainError`. The script's exact-name check predates #243. | **SUPERSEDED**: the check is wrong, not the library. An isinstance check passes (see G1 P5). |
| `g1` § B: strict refusal of restored `scheduled_sends` (320 cases × 2) | 0 defects | FIXED / holds |
| `g1` § C: `from_snapshot(plugins=)` hooks | Correct | holds |
| `g2_concurrency.py` | 0 defects | holds |
| `g3_fuzz_det.py`: livelock fuzz and 50× determinism across both engines and both kinds | 0 defects; `distinct_traces=1` | holds |
| `g4_security.py`: forged chain fields and bypasses of the #227 strict check | 0 defects. There is one trust-boundary note: a writer who controls the blob can erase the latch. This is inside the documented boundary, so it is not a defect. | holds |
| `g5_soak.py` | See § 2. It ran reduced, for 100 s. | holds |

## 2. New attacks on v0.9.1

Each script lives in `battle-v0.9.1/fuzz/` and is standalone.

| Script | Attack | Result |
|---|---|---|
| `g1_new_surface.py` P1 | 300 cases (150 def, 150 async def). Each case randomly mixes `send` and `send_priority`, then runs `drain_pending` → persist the drained list → `from_snapshot` → `start` → resend. | Priority lane comes first; drain order == `pending_events`; each event is replayed exactly once. **0 defects** |
| P2 | `send(wait=True)` ×5, then `drain_pending` | Every receipt settles with `.error` = `InterpreterStoppedError`, and none hangs. **OK** |
| P3 | 10 chained restores, then 100 concurrent restores with starts in parallel | `restored_from_snapshot` is True every time, and `on_interpreter_start` fires exactly once each time. **0 bad** |
| P4 | 1000 def actions each dropping a `wait=True` receipt | `dropped_receipts=1000`, and the hook fired 1000 times. **exact** |
| P5 | `RestoredChainError` isinstance matrix; `SyncInterpreter` kwargs | isinstance is True/True. For the kwargs, `max_queue_size=None` is ok and `=5` raises `ValueError`, both as documented. `overflow_policy="bogus"` is accepted silently, but the docstring says it is ignored, so this is not a defect. |
| `s1_re_mint_forge.py`, `d14_fuzz_1_re_mint_forge.py` | **re_mint type→`done.invoke.<victim>`**, which is this round's open question | **REPRODUCED → D14-fuzz-1** |
| `s1b_re_mint_after_fuzz.py` | 40 mutation trials on a captured `AfterEvent` → `done.invoke.*` / `error.platform.*` | 0/20 forged transitions. This is because `re_mint` keeps the event's class, so an After-kind event does not satisfy onDone matching. The same-kind re-target in § 3 does work, though. |
| Attestation | PyPI integrity API `/provenance` for the wheel | A PEP 740 bundle is present, and its subject digest is the wheel sha256. I did not verify the signature cryptographically (no `pypi-attestations` tool offline). |
| Soak (reduced) | `g5_soak.py SECONDS=100`: 200 machines, both kinds, heartbeats, external sends, chaos persist/restore | 44 000/44 000 applied, 0 lost; 604 chaos rounds with 0 mismatch; handles peaked at 200; 0 RuntimeWarnings. **0 defects** |

## 3. Defects

### D14-fuzz-1 (Medium; contract) — `events.re_mint()` can forge a *different* engine event

- **Location:** `src/xstate_statemachine/events.py:661–702`. The function gates only on the *class* of `original`, then accepts any `type=` / `src=` override and re-mints the event with engine provenance.
- **Why it matters:** CHANGELOG #248 says re_mint "can carry provenance forward but never create it". Re-targeting `done.invoke.fast` to `done.invoke.victim` creates provenance for a completion the engine never produced.
- **Repro:** `d14_fuzz_1_re_mint_forge.py` (standalone). It has three cells:
  - An onDone action of an unrelated invoke calls `i.send(re_mint(e, type="done.invoke.victim", src="victim"))`. Result: `victim` is still sleeping 3600 s, yet `m.B.SETTLED` is reached. Reproduced for both def and async def (2/2).
  - Control: a hand-built `DoneEvent` with the same type is ignored, as intended.
  - Sync engine: `re_mint(after.10…, type="after.99999.s.B.w")` fires a 99 999 ms timer immediately (`s.B.EXPIRED`). The hand-built control is ignored.
- **Mitigating:** only in-process code that already holds a genuine engine event can do this, and such code could import the private `_engine_done` anyway. So this is a contract/documentation hole in a *sanctioned* API, not a remote boundary crossing.
- **Suggested fix:** in `re_mint`, refuse overrides of `type` / `src` (or require them to equal the original's), and allow only `data` and similar payload fields.

## 4. Not covered / reduced (20-min bound)

- **Soak:** the brief asked for 12 min with a drain→persist→restore(plugins=)→start step every 2 s. I ran the prior soak (persist/restore chaos without `drain_pending`) for 100 s instead.
- **Drain under 16 concurrent senders during an in-flight macrostep:** only the randomized single-task P1 was run.
- **Chain-field fuzz vs `SnapshotCorruptError` typing:** only the prior g4 forged-chain cells were run, with no new malformed-type sweep.
- **Determinism on the new fields** (`restored_from_snapshot`, `dropped_receipts`): checked for exactness in P3 and P4, but not across 50 repeated trace runs.
- **Attestation:** signature crypto-verification was not done (see § 2).

## 5. Verdict

Every round-13 fix in this track's scope is confirmed: #239, #240, #243, #244 and #245. D13-fuzz-1 is FIXED, and the only prior "failure" is a SUPERSEDED name check.

There is **one new Medium defect, D14-fuzz-1**: the answer to the round's `re_mint` question is *yes, it can forge a different completion*.

For an OMS: this is **conditionally ready**. Proceed only if the code base bans `re_mint` type/src overrides (by lint or a wrapper) until upstream fixes it, and schedule the full 12-min drain soak before production sign-off.
