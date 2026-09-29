# Runbook: Bybit clock drift alarm (E08-S07)

## Alerts

| Alert | Metric | Threshold | Meaning |
|---|---|---|---|
| `BybitClockDriftWarning` | `bybit_clock_drift_ms` | 500 < \|x\| ≤ 2000 ms | Offset is drifting; trading still allowed. |
| `BybitClockDriftCritical` | `bybit_clock_drift_ms` | \|x\| > 2000 ms | Hard threshold breached; `assert_healthy()` raises `ClockDriftError` and order entry (E29) is refused. |
| `BybitClockOffsetStale` | `clock_offset_age_seconds` | > 900 s | `GET /v5/market/time` has been failing; the last known offset is still applied but is aging out. |

`bybit_clock_drift_ms` is signed: positive means the local clock is **ahead**
of the exchange, negative means **behind** (matches `ClockGuard.describe()`
on the health screen, SCR-147).

## What to do

1. **Check the direction and magnitude** on the health screen or
   `bybit_clock_drift_ms` in Grafana. A slow, steady drift is a host clock
   problem; a sudden jump usually means the host slept/resumed (WSL is a
   known drift source after host sleep — ticket Context paragraph).
2. **Fix the host clock, do not widen `recv_window`.** `recv_window_ms` is
   pinned at 5000 and its Pydantic validator caps it at 10 000
   (`RestClientConfig._validate_recv_window`) — widening it as a mitigation
   is explicitly forbidden (Security notes) and enforced by that validator's
   test (`test_recv_window_out_of_bounds_rejected`).
   - Linux/WSL host: ensure `chrony` (or `systemd-timesyncd`) is running and
     force a resync: `sudo chronyc makestep` (chrony) or
     `sudo timedatectl set-ntp true` (`timesyncd`).
   - After a host sleep/resume, WSL's clock can lag by seconds; restarting
     the WSL distro (`wsl --shutdown` then relaunch) also resyncs it.
3. **Confirm the alarm clears.** `ClockGuard` re-measures every 5 minutes
   (`resync_interval_s`, default 300 s) — once the host clock is fixed,
   `bybit_clock_drift_ms` should drop under 500 ms within one or two
   resync cycles. You do not need to restart the process.
4. **If `BybitClockOffsetStale` fires instead (or alongside)**: check
   outbound connectivity to the Bybit REST host (`ALLOWED_REST_HOSTS` in
   `candleviewer/exchange/bybit/config.py`) — the endpoint itself may be
   down or blocked. The system keeps applying the last known offset and
   never silently falls back to an uncorrected local clock while this
   alarm is active.
5. **If critical persists after the host clock is confirmed correct**,
   treat it as a P1: order entry is blocked system-wide by design
   (`ClockDriftError`) until this clears — escalate per `SECURITY.md`/
   `docs/plan/04-security-program.md` if a signing/API-side cause is
   suspected rather than a host clock cause.

## Demo (Sprint Review)

Step the local clock forward by >2 s on the demo environment (or simulate
via a fake `ServerTimeFetcher` returning a skewed offset in a controlled
demo build) and confirm: `BybitClockDriftCritical` fires, `assert_healthy()`
raises, and the alarm clears automatically once the clock is corrected and
the next resync cycle completes.
