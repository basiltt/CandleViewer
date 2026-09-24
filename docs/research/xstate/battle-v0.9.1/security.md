# Battle track: SECURITY — v0.9.1 (main 801eacd, tag v0.9.1)

**Scope was cut to fit the time box.** I re-ran the six prior scripts and ran one new attack, the round's key question. Everything else in the brief is listed as not covered in §4.

Environment: `.venv-main`, `__version__ == "0.9.1"`, loaded from the clone's `src/`. The full suite log (`suite-v0.9.1.log`) shows **3601 passed, 13 skipped, 92.93% coverage**. The published PyPI wheel was **not** checked against its sha256.

## 1. Prior defects (all six scripts were run from cwd `C:/Users/basil`)

| Prior item | Script | v0.9.1 result | Status |
|---|---|---|---|
| R9-01/R12-03: forging a completion by importing `_EngineDone` | a1 | A forged `onDone` still fires while the real service is running. `_replace` still demotes the event to a plain one. | STILL-PRESENT. We accepted this as a trust boundary in R12-03. |
| D12-security-1: chain latch not persisted | a2 | The count survives restore, the error comes back as `RestoredChainError`, and v2 blobs upcast cleanly. The script prints `monotonic_ok=False` even though the count goes 3→4→5. That looks like a bug in the script's own check. | FIXED. The script needs its check rewritten (not done). |
| D11-security-4: restore hook plus strict mode | a3 | `plugins=` reaches the hook before the refusal happens. | FIXED |
| Scheduled sends bypassing strict mode | a4 | 300 of 300 cases were consistent and refused. | FIXED |
| Task-identity matrix | a5 | R1, R2 and R3 all pass. | FIXED |
| D13-security-3: `RuntimeWarning` under `-W error` | a6 | The warning shows up but is still not raised to the caller. | STILL-PRESENT (documentation-level only) |

## 2. New attack: can `re_mint` forge a *different* completion? — **YES**

Script: `security/b1_re_mint_cross_completion.py` (standalone, async engine).

1. A parallel machine runs two invokes: `a`, which finishes fast, and `victim`, which runs for 30 s.
2. A plugin captures the genuine `_EngineDone(done.invoke.a)`.
3. The attacker calls `re_mint(src, type="done.invoke.victim", src="victim")` and sends the result.

Output:
```
forged sys: True _EngineDone(type='done.invoke.victim', data=1, src='victim')
async state: ['m.A.ok', 'm.V.paid']
ASYNC FORGERY FIRES victim onDone: True
```

### D14-security-1 — `re_mint` accepts any value for `type` and `src` (Medium)
- **Where:** `src/xstate_statemachine/events.py:661-701`. The gate at line 687 only checks that the *input* is engine-minted. It never checks that the new `type` and `src` match the original's.
- **Effect:** One genuine completion from any service can be turned into a completion for any other invoke. The CHANGELOG claims re_mint "can carry provenance forward but never create it", and that claim is false for the completion's *identity*. It also reopens, through a public and documented API, the forgery hole that #235 closed for `_replace`.
- **Mitigation:** An in-process attacker could already build `_EngineDone` directly (a1), so this does not widen the accepted in-process trust boundary. It does make the unsafe path the sanctioned one.
- **Suggested fix:** Make `re_mint` refuse changes to `type` (and to `src`/`id` on `AfterEvent`), allowing only `data`, or require that `type == original.type`.
- **Not checked:** the sync (`def`) engine, because of the time box. `re_mint` shares the same code, so the result is expected to be the same.

## 3. Items verified as closed
#230, #226, #227/#231, #235 (the `_replace` demotion) and #232 behave as their CHANGELOG entries describe. None of these regressed.

## 4. Not covered (time box)
- Checking PEP 740 attestations from the PyPI JSON, and checking the wheel's sha256.
- The drain→persist→restore exactly-once property (≥300 cases).
- The `restored_from_snapshot` flag after N restores.
- Fuzzing the chain fields against `SnapshotCorruptError`.
- 16 concurrent senders during a drain.
- The exact `dropped_receipts` count with 1000 actions.
- `on_interpreter_start` firing exactly once under 100 concurrent restores.
- The livelock fuzzer.
- 50× determinism traces.
- The `RestoredChainError` isinstance matrix.
- The 12-minute soak.
- Showing that forged chain fields gate nothing.
- The sync-engine version of b1.

Other tracks or a follow-up run need to cover these. **This report does not certify them.**

## 5. Verdict
**Not "fully battle-tested" from the security track yet.** All prior fixes hold, but the round's key question fails: `re_mint` lets an engine-minted event become a completion for a different invoke (D14-security-1, Medium).

- **Library side:** narrow `re_mint` to changing `data` only, or document explicitly that it is inside the in-process trust boundary and that it can re-target a completion.
- **Our side:** our plugins must never call `re_mint` with `type` or `src` overrides. Also add D14-security-1 to the register.
- **Before calling the library ready:** run the soak and the drain/restore properties in §4.
