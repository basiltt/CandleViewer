# R10-C4 adversarial refutation — "kill/cancel deferrable for the full service duration"

Commit 19cb1f1. Repro: `battle-19cb1f1/contracts/b6b10/r10c4_refute.py` (standalone,
stdlib + `xstate_statemachine`, run from neutral cwd `<home>`), plus re-runs of
`kb_killdefer.py` and `ka_killswitch.py` in both service styles.

## Verdict: REFUTED (modelling error, documented behaviour) — retain as a Low modelling constraint

## Re-run evidence (both lanes, polled to convergence)

`kb_killdefer.py` async: 8/8 PASS. As-catalogued B6 `applied_s=1.454`, B9 `applied_s=1.466`;
with the handler declared on the invoking state, `0.001s`. `def` lane: all four rows
`applied_s<=0.002` — the blocking service completes inside the macrostep, so the kill
arrives with the machine already back in `armed` (that is R10-D2, not this finding).
Nothing dropped, nothing lost, `deferred_count` returns to 0 in every row.

## Why the finding does not stand

Isolated three shapes of the same kill switch (async lane, in-flight service):

| shape | applied_s |
|---|---|
| A sibling-only handler (the catalogued B6/B9 shape) | 1.458 |
| B handler on the **parent** (standard XState kill-switch idiom) | 0.001 |
| C handler on the invoking state | 0.000 |

B6 declares `USER_CANCEL` only on `armed`/`price_blocked`/`paused`; B9 declares
`KILL_SWITCH` only on `armed`/`cooling_down`/`paused_degraded`. In the invoking
configuration there is **no handler on the active state or any ancestor**, so under
SCXML §3.13 / XState v5 event selection no transition is selectable and the event is
simply ignored. `onUnhandled: "defer"` is the library's documented improvement on that:
README line 1462 — *"replays it after the next state change"* — and that is exactly the
observed 1.45s (the next state change is `onDone` of the 1.5s service). The library
therefore **loses less** than the reference semantics, not more.

`priority=True` is documented as delivering "ahead of the inbox" (README 1495/1613) —
inbox ordering, never configuration-level handler selection. The receipt returns in
~1ms with `deferred=True`; no send is dropped or charged (K2: 200/200).

Refutation axes: **documented** — yes (defer replay semantics, priority = inbox lane).
**API/contract misuse** — yes (kill handler absent from the active configuration and its
ancestors; the one-line parent handler fixes it). **XState v5/SCXML agrees** — it is
stricter (event dropped outright). **Measurement artefact** — no; polled to convergence,
result unchanged.

## Residual constraint (carry forward, Low)

CV-C4x: every kill/cancel event must be declared on an **ancestor** of all invoking
states (parent-level `on`), never on siblings only. Cheap to lint statically from the
catalogue JSON; without it the kill is latency-bound by the in-flight service.
