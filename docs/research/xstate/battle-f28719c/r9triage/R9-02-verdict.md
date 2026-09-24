# R9-02 adversarial triage — CONFIRMED (high)

Claim: `after.*` selection tests the PUBLIC `AfterEvent` class, so a
hand-built one fires a 60 s timer instantly. Cause:
`base_interpreter.py:4523` `if isinstance(event, AfterEvent):` — a bare
isinstance against the public class, never `is_system_event` /
`_ENGINE_MINTED_TYPES`, unlike the `DoneEvent`/`ErrorEvent` branch right
below it (which #195 gated with `_completion_is_for_live_invocation`).

## Refutation attempts and results (commit f28719c)

1. **"Open namespace, not provenance" (the R9-12 effect).** REFUTED by the
   discriminating control `t1_plain_event_control.py`:
   - `AfterEvent("after.60000.m.work")` -> `['m.expired']`
   - plain `Event(type="after.60000.m.work")` -> `['m.work']`
   - bare string `"after.60000.m.work"` -> `['m.work']`
   The public class is genuinely privileged; the name alone is inert. (The
   `DoneEvent` half of the same control is open-namespace — plain Event and
   DoneEvent both reach `m.finished` — which is why that half is *not*
   claimed here.) `after` targets are timer-only and otherwise unreachable
   by name, so this grants reachability the machine author never exposed.
2. **"Documented / API misuse."** Only partly mitigating. `docs/api/index.md:1153`
   and the `AfterEvent` docstring say a developer "typically does not create
   this event manually" — guidance, not a contract, and `AfterEvent` is
   exported from the package root (`__init__.py:223`). More decisively, #195's
   own stated contract in CHANGELOG [Unreleased] is that a forged record
   "restores as user traffic" and user traffic must not drive engine
   transitions. `after` is a straight miss of that contract, not misuse.
3. **"`strict` closes it."** Only the in-process vector, and `strict` is off
   by default (`p15_strict_refusal_coverage.py`: TRANSITIONED with the
   shipped default). `t2_after_vectors.py`:
   - strict=False, forged `AfterEvent` -> `['m.expired']`
   - strict=True , forged `AfterEvent` -> refused (`UnknownEventError`)
   - `restore_event({"kind":"after","type":"after.60000.m.work"})` (no
     `"engine": true`) -> public `AfterEvent`, `is_system_event=False`
4. **"Snapshot path is covered by #195."** REFUTED — this is the strongest
   vector. `t3_snapshot_after.py`: a forged `pending_events` record with no
   `"engine"` flag restores as user traffic exactly as #195 intends, then
   `_enqueue_restored` (`base_interpreter.py:1768`) puts it straight on the
   inbox, bypassing the `send()`-time strict check entirely. Result with
   **strict=True**: `after restore, states: ['m.expired']` — a 60 s timer
   fired instantly from untrusted persisted data, with no API misuse at all.
   Snapshots are untrusted by the library's own threat model (#186/#198).
5. **"Duplicate of a closed issue."** No. #195 closed the `DoneEvent` /
   `ErrorEvent` completion path (live-invocation check) and added
   `_EngineAfter` + `engine_after`, but the `after` *selection* site was
   never switched to the minted subclass — the machinery exists and is
   simply not consulted at 4523.

## Correct usage, re-run
Correct usage is never to construct `AfterEvent` and to let the engine mint
timers (`engine_after`, `base_interpreter.py:4874`); under correct usage the
in-process vector does not arise. It does not rescue vector 4, where the
application makes no API call at all. Re-run under correct usage on the
snapshot path still reaches `m.expired`.

## Verdict
**CONFIRMED, severity high.** Fix: select `after` transitions on the minted
subclass (`is_system_event(event) and isinstance(event, AfterEvent)`), the
same gate `is_system_event` already applies elsewhere.

Artefacts: `t1_plain_event_control.py`, `t2_after_vectors.py`,
`t3_snapshot_after.py` (this dir); `probes/main-f28719c/p2_forged_after.py`
(exit 1, both engines), `p15_strict_refusal_coverage.py`.
