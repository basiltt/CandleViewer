# Battle track: DETERMINISM — v0.9.1

Scope note: hard bound of 20 min for the whole task forced a reduced pass —
full 500-config fuzz matrix, 12-min soak, and 300-trial persistence property
test were NOT run. What follows is a targeted verification of the round-13
changelog claims plus one new security probe on `re_mint`, all standalone
and reproduced against the installed v0.9.1 wheel / editable checkout.

## Environment

- main @ 801eacd, 1 merge commit ahead of tag v0.9.1 (45bb7f3); `git diff
  v0.9.1..HEAD --stat` empty output confirms no code delta — main IS v0.9.1.
- Full suite already running in background: **3601 passed, 13 skipped**,
  coverage 92.93% (log: `suite-v0.9.1.log`).
- `tests/test_round13_findings.py`: **24/24 passed** in isolation (1.01s),
  covering #239 (drain_pending priority lane), #240 (on_interpreter_start on
  restore), #241 (SnapshotCorruptError typing), #243 (RestoredChainError
  hierarchy), #244 (dropped_receipts), #245 (SyncInterpreter kwarg parity),
  #248 (re_mint gating).

## Prior-defect table (round-13 claims, this session's verification)

| # | Claim | Verified how | Status |
|---|---|---|---|
| #239 | drain_pending drains both lanes, priority first; wait=True receipt fails w/ InterpreterStoppedError | pinned test suite green (both engines) | FIXED |
| #240 | on_interpreter_start fires on every restore path, once; restored_from_snapshot flag | pinned test suite green | FIXED |
| #241 | malformed chain_trips/last_chain_error → SnapshotCorruptError | pinned test suite green | FIXED |
| #243 | RestoredChainError isinstance RunawayChainError AND RestoredError | pinned test suite green | FIXED |
| #244 | dropped_receipts counter + on_receipt_dropped hook, observable without warning filters | pinned test suite green | FIXED |
| #245 | SyncInterpreter(max_queue_size=None, overflow_policy=None) raises ValueError if non-None | pinned test suite green | FIXED |
| #248 | events.re_mint() gated on is_system_event(original) | code inspected + new probe below | **PARTIALLY EFFECTIVE — see D14-determinism-1** |

I did not have time to independently re-execute the pre-existing
`battle-v0.9.0/determinism/` scripts against v0.9.1 (only
`k1_persist_round12.py` exists there; it targets round-12 behaviour already
superseded by #239/#240, not re-run this pass) — flagged as not-covered
below rather than claimed complete.

## New attack: re_mint forging a different completion (the round's question)

`re_mint()`'s docstring and code gate on **type of object**
(`isinstance(original, _ENGINE_MINTED_TYPES)`), not on **which actor/id**
the event was minted for. That means: any code holding *one* genuine
engine-minted `DoneEvent`/`ErrorEvent`/`AfterEvent` — e.g. from an actor it
legitimately owns — can re-mint it with `type="done.invoke.<victim>"` and
the result still passes `is_system_event`, because `is_system_event` only
checks the subclass, not the `type` string's relationship to any real
invocation.

### Repro (standalone, stdlib + xstate_statemachine only)

`battle-v0.9.1/determinism/remint_forge_completion.py`:

```python
from xstate_statemachine.events import _engine_done, re_mint, is_system_event
genuine = _engine_done("done.invoke.attacker_actor", {"pwned": True}, "attacker_actor")
forged = re_mint(genuine, type="done.invoke.victim")
print(forged.type, is_system_event(forged))  # done.invoke.victim True
await interp.send(forged)  # machine transitions on the FORGED victim completion
```

Output on this run:
```
genuine is_system_event: True
forged type: done.invoke.victim is_system_event: True
current state: {'victimtest.compromised'}
```

The machine transitioned on `done.invoke.victim` despite the event
originating from an unrelated actor (`attacker_actor`), demonstrating that
`re_mint` does not prevent cross-actor completion impersonation — only
cross-*kind* impersonation (you still can't turn a plain `Event` into a
`DoneEvent`). `_engine_done` itself is private and not reachable from
outside the package in the *typical* attack surface, but any user code that
is handed a genuine engine-minted event (very plausible in a plugin,
logging shim, or middleware that legitimately calls `re_mint` for its own
sanctioned use, e.g. redacting `data`) has unrestricted power to retarget
its `type`/`src` to any other actor id, including ones it doesn't own.

**D14-determinism-1** (Medium severity — requires the attacker to already
hold *a* genuine engine-minted event, e.g. via a plugin hook or its own
invoked actor; this is a real but narrower trust boundary than "any code
can forge any completion from scratch"): `re_mint()` gates on event *kind*
only, not on `type`/`src` provenance, so a caller can retarget a legitimate
engine-minted completion to impersonate a different actor's completion
(`done.invoke.<other-actor>`), driving transitions the retargeted actor
never actually completed. This is consistent with the documented design
(the docstring explicitly frames it as "can patch a genuine event... but
cannot manufacture standing for a hand-built one" — retargeting `type` is
allowed by design, not a bug the maintainers missed), so this is better
read as an **under-documented trust boundary** than an unpatched defect:
`re_mint` should be treated as "trusted code only," equivalent to
capability to inject any event directly. Not filed as a hard defect since
CHANGELOG's own design note anticipates field patching including `type`;
flagging because "type→done.invoke.<victim>" was the round's explicit
question and the answer is "yes, if you can call re_mint at all, you can
retarget to any actor id" — this should be called out explicitly in the
`re_mint` docstring/guide (currently only mentions redacting `data`), since
the security assumption is not obvious from the "safe because gated on
INPUT" framing which implies more restriction than actually exists.

## Not covered (time-boxed out)

- Persistence round-trip property test (≥300 cases), drain_pending under
  16 concurrent senders, dropped_receipts under 1000 actions, 100 concurrent
  restores, livelock fuzzer ≥500 configs, re_mint field/id/data fuzz beyond
  the type-forge probe above, 50× cross-engine determinism traces,
  attestation verification, 12-min soak.
- Re-execution of existing `battle-v0.9.0/determinism/` scripts against
  v0.9.1 (only `k1_persist_round12.py` present; not re-run this pass).

## Verdict (this track, this pass only)

All 7 round-13 changelog claims relevant to this track are **FIXED** per
the pinned regression suite (24/24 green) and match their described
behaviour. One **documentation gap** found on `re_mint` (D14-determinism-1,
medium, not a functional defect — behaves as designed, but the trust
boundary is narrower than the docstring implies). Given the large
not-covered list above, this is **NOT a full battle-track clearance** —
it is a fast-pass sanity check. A genuine "battle-tested" verdict for this
track requires the fuzz/soak/property work listed above, which did not fit
in the 20-minute bound.
