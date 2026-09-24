# Probes — xstate-statemachine @ cec108b (unreleased 0.8.1)

Run with:
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python <probe>.py`

| probe | findings |
|---|---|
| p1_legality.py | K-7; verifies #142/#143 read side (torn region, two leaves, final, history, root-only) |
| p2_fail_stop.py | verifies #145 (stopped, cleared config, typed error, restart refused, snapshot round-trip) |
| p3_threadsafe.py | **K-2** (internal=False dodges maxIterations), **K-5** (counter leak) |
| p4_forge_internal.py | **K-1** (internal=True bypasses bounded inbox + RAISE) |
| p5_service_executor.py | K-4 (pool=4), K-6 (threads outlive stop), verifies onError from thread |
| p6_service_blocking.py | **K-3** (sibling-region `after` 5x late during a plain service) |
| p7_sat.py | K-4 latency cliff at multiples of 4 |
| p8_geom.py | PR #141 geometry memo sharing (good); parallel-all-final status note |
| p9_misc.py | RootTargetError, Receipt.denied, _die idempotency, caller executor (all good) |
| p10_counter_leak.py | K-5 consequence (latent, not driven to a trip) |
| p11_parity.py / p11b.py | #145 parent-onError parity, both engines (good) |
| p12_growth.py | K-1 at 200k forged sends |
| p13_budget.py / p13b.py | K-2 boundary cases; trip observability (good) |
