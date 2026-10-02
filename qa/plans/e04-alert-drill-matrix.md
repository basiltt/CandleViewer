# E04-Q01 — Alert drill matrix (R0 subset)

Status: **prepared, pending staging execution** (not run locally: no docker/Prometheus/Alertmanager on the authoring host).
Each row is filled in by QA during the staging drill: UTC timestamps, delivered Y/N, runbook executable Y/N.
Synthetic injection proves the rule; the **real** drills (PostgresDown by stopping Postgres, PublicWsDown by dropping the public WS) prove the metric reacts.
Near-miss = threshold minus epsilon and duration minus epsilon; both must NOT fire (promtool coverage in `infra/prometheus/tests/system_alerts.test.yml`).
Drill windows are recorded in `system_events`; coordinate security-rule drills (AuthLoginFailureSpike, AuditChainVerificationFailed) with Security.

| Rule | Severity | For | Runbook | Mode | Injected (UTC) | Received (UTC) | <=60 s | Runbook walked | Near-miss silent | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| BybitClockDriftWarning | ticket | 2m | `docs/plan/07-release-and-prr.md#alert-bybitclockdriftwarning` | synthetic | | | | | | pending |
| BybitClockDriftCritical | page | 1m | `docs/plan/07-release-and-prr.md#alert-bybitclockdriftcritical` | synthetic | | | | | | pending |
| BybitClockOffsetStale | ticket | 1m | `docs/plan/07-release-and-prr.md#alert-bybitclockoffsetstale` | synthetic | | | | | | pending |
| LatencyBudgetBreach | ticket | 60s | `docs/plan/07-release-and-prr.md#alert-latencybudgetbreach` | synthetic | | | | | | pending |
| TickToPaintSloFastBurn | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-ticktopaintslofastburn` | synthetic | | | | | | pending |
| SupportBundleSecretDetected | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-supportbundlesecretdetected` | synthetic | | | | | | pending |
| NakedPositionDetected | page | 0m | `docs/plan/07-release-and-prr.md#alert-nakedpositiondetected` | synthetic | | | | | | pending |
| OmsUnknownOrders | page | 1m | `docs/plan/07-release-and-prr.md#alert-omsunknownorders` | synthetic | | | | | | pending |
| PostgresDown | page | 1m | `docs/plan/07-release-and-prr.md#alert-postgresdown` | real+synthetic | | | | | | pending |
| ClockDriftBlockingTrading | page | 1m | `docs/plan/07-release-and-prr.md#alert-clockdriftblockingtrading` | synthetic | | | | | | pending |
| DiskCritical | page | 2m | `docs/plan/07-release-and-prr.md#alert-diskcritical` | synthetic | | | | | | pending |
| AuditChainVerificationFailed | page | 0m | `docs/plan/07-release-and-prr.md#alert-auditchainverificationfailed` | synthetic | | | | | | pending |
| SyntheticAlert | page | 1m | `docs/plan/07-release-and-prr.md#alert-syntheticalert` | synthetic | | | | | | pending |
| PublicWsDown | ticket | 1m | `docs/plan/07-release-and-prr.md#alert-publicwsdown` | real+synthetic | | | | | | pending |
| BookResyncHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-bookresynchigh` | synthetic | | | | | | pending |
| EventLoopLagHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-eventlooplaghigh` | synthetic | | | | | | pending |
| DiskHigh | ticket | 5m | `docs/plan/07-release-and-prr.md#alert-diskhigh` | synthetic | | | | | | pending |
| RuleAutodisarm | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-ruleautodisarm` | synthetic | | | | | | pending |
| EnvMismatchAttempt | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-envmismatchattempt` | synthetic | | | | | | pending |
| CredentialExpiryApproaching | ticket | 10m | `docs/plan/07-release-and-prr.md#alert-credentialexpiryapproaching` | synthetic | | | | | | pending |
| AuthLoginFailureSpike | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authloginfailurespike` | synthetic | | | | | | pending |
| AuthLockouts | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authlockouts` | synthetic | | | | | | pending |
| AuthzDeniedSpike | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-authzdeniedspike` | synthetic | | | | | | pending |
| CredentialVerificationFailures | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-credentialverificationfailures` | synthetic | | | | | | pending |
| OmsRateRejects | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-omsraterejects` | synthetic | | | | | | pending |
| EgressIpChanged | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-egressipchanged` | synthetic | | | | | | pending |
| AlertmanagerNotificationsFailed | ticket | 0m | `docs/plan/07-release-and-prr.md#alert-alertmanagernotificationsfailed` | synthetic | | | | | | pending |
