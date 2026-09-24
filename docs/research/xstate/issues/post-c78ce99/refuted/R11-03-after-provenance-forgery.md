# R11-03 — "the `after`-provenance boundary is forgeable four ways" — REFUTED

Filed **High** (carry-forward from round 10). **Refuted outright; severity None.** Not filed upstream.

All four vectors re-run verbatim against `c78ce99` and reproduce. No trust boundary is crossed by any of them.

## Vector-by-vector

| vector | why it is not a defect |
|---|---|
| **V1 — hand-built public `AfterEvent`** (the CONTROL) | **Correctly refused with `UnknownEventError`.** This is the only vector reachable from the documented public API, and it is exactly the claim #195/#203 make. The boundary holds. |
| **V2 — import path `engine_after()`** | Requires importing a **non-exported implementation module**. Probe Q1: `engine_after` / `engine_done` / `engine_error` / `_EngineAfter` are absent from the top level and from `__all__`; `events` is not in `__all__`. This is in-process privileged code that could equally monkeypatch the interpreter. |
| **V3 — `type(held_engine_event)(...)`** | Requires **already holding a genuine engine-minted event**. Zero escalation. |
| **V4 — pickle round-trip** | Same premise. Probe Q3, both `def` and `async def` lanes: original and pickle clone behave **identically**. `events.py:249-251` documents copying as the legitimate case. |
| **V5 — hand-written snapshot record `engine:true`** | Requires authoring arbitrary snapshot bytes. Probe Q2, both lanes: that same writer reaches `n1.expired` with context `{"fired": 99}` using `state_ids`/`context` alone — **no event at all**. `events.py:409-420` states this verbatim: *"a caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright (#185), so this is the correct trust boundary."* The R10-01 pattern. |

## The claim being attacked does not exist

"Type identity is not a capability" is true of Python and attacks a capability claim **the library never makes**. XState v5 likewise has no cryptographic event provenance and restores caller-supplied snapshots unchecked; SCXML §5.10 treats the queue as engine-internal.

#212 concerns delayed self-sends and does not touch provenance.

## Carried forward

Only as a **consumer constraint**, which we already hold: authenticate/sign persisted snapshots at the storage boundary (**CV-C23**'s HMAC clause, hardened as **CV-C53**). The library's `machine_hash` is explicitly "not a MAC" — the tag is the boundary, and `strict` never was one.

## Round note

This is the third consecutive round in which a Blocker/High filed against engine-event provenance has been refuted by a control probe. Recommend retiring this line of attack rather than repeating it a fourth time, and adopting the control as a **triage precondition**: if the same writer reaches the same place with `state_ids`/`context` alone, there is no defect.
