# Architecture Decision Records

MADR-format records for CandleViewer. The authoritative index (with summaries) is §16 of [`../20-architecture.md`](../20-architecture.md).

Status values: `decided` (binding now), `proposed` (decision deadline stated inside the record), `proposed (gated)` (part of the record is binding now and part is gated — the record says which), `superseded` (points at its replacement).

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001-stack-selection.md) | Technology stack selection | decided |
| [ADR-0002](ADR-0002-custom-webgl-chart-engine.md) | Custom WebGL chart engine | decided |
| [ADR-0003](ADR-0003-storage-tiers.md) | Three-tier storage | decided |
| [ADR-0004](ADR-0004-modular-monolith.md) | Modular monolith with an internal event bus | decided |
| [ADR-0005](ADR-0005-ws-protocol-and-binary-encoding.md) | WS protocol and binary encoding | decided |
| [ADR-0006](ADR-0006-oms-state-machine.md) | OMS state machine, idempotency and reconciliation | decided |
| [ADR-0007](ADR-0007-rule-ir.md) | A single rule IR shared by both editors | decided |
| [ADR-0008](ADR-0008-trade-group-fanout.md) | Trade-group fan-out with a mandatory native SL | decided |
| [ADR-0009](ADR-0009-secrets-and-key-management.md) | Secrets and Bybit API-key management | decided |
| [ADR-0010](ADR-0010-auth-and-rbac.md) | Authentication, RBAC, admin inside the web app | decided |
| [ADR-0011](ADR-0011-electron-vs-tauri.md) | Electron vs Tauri desktop shell | proposed (deadline: end of Sprint 03) |
| [ADR-0012](ADR-0012-testing-pyramid.md) | Testing pyramid and shared fixtures | decided |
| [ADR-0013](ADR-0013-ci-pipeline.md) | CI/CD pipeline on GitHub Actions | decided |
| [ADR-0014](ADR-0014-observability.md) | Observability stack | decided |
| [ADR-0015](ADR-0015-recording-policy.md) | Recording and retention policy | decided |
| [ADR-0016](ADR-0016-statechart-runtime.md) | Statechart contracts and a gated runtime | **proposed (gated)** (deadline: Sprint 08 go/no-go, `E50-X01`) |
| [ADR-0017](ADR-0017-board-automation.md) | GitHub Projects v2 board automation: capability and limits | decided |
| [ADR-0018](ADR-0018-monorepo-tooling.md) | Monorepo tooling: pnpm+Turborepo (JS) and uv+Hatch (Python) | decided |
| [ADR-0019](ADR-0019-visual-regression-tooling.md) | Visual-regression tooling for design-system snapshots | decided (wall-clock/flake numbers deferred to E05-T04) |
| [ADR-0020](ADR-0020-session-access-token-and-revocation-model.md) | Session access-token format, WS re-auth cadence, and rotation-family revocation | **proposed** (owner approval pending, spike E09-K01) |
| [ADR-0022](ADR-0022-hot-tier-questdb-vs-timescaledb.md) | Hot tier: QuestDB confirmed for five of six query shapes; replay scan deferred | **accepted-partial** (owner approval pending, spike E07-K01) |

## Writing a new ADR

1. Copy the structure of an existing record: title, status, date, deciders, consulted, related; then context and problem statement, decision drivers, considered options, decision outcome, consequences, why not the alternatives, validation.
2. Number sequentially; filename `ADR-00NN-<slug>.md`.
3. Never edit a `decided` record's outcome in place — either amend it with a dated amendment section (for refinements) or write a superseding ADR and set the old one to `superseded`.
4. Add the row here and to §16 of `20-architecture.md` in the same PR.
5. ADRs are code-owned by the architect (see `.github/CODEOWNERS`).
