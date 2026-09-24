# CandleViewer

**The open-source charting platform for traders who outgrew TradingView.**

CandleViewer is a modern, high-performance web (and eventually desktop/PWA) charting platform combining a GPU-accelerated chart engine, multi-source real-time market data, a rich indicator and custom scripting ecosystem, professional drawing tools, alerts, backtesting/replay, and real-time collaboration — fully open source.

> **Status: Pre-alpha.** APIs, architecture, and even the technology stack are still being decided. Expect breaking changes daily. Not ready for production use. Contributions and design input very welcome!

---

## Why CandleViewer instead of TradingView?

| | TradingView | CandleViewer (goal) |
|---|---|---|
| Source | Closed, proprietary | 100% open source (MIT) |
| Rendering | Fast, but capped feature set on free tiers | GPU-accelerated engine targeting 1M+ candles at 60fps, no paywalls on core charting |
| Data | TradingView-curated feeds only | Bring-your-own-adapter multi-source feeds (crypto/stocks/forex), self-hostable |
| Scripting | Pine Script (closed, rate-limited) | Open scripting language, sandboxed WASM execution, no arbitrary limits |
| Backtesting | Strategy Tester (limited history, slow) | Fast historical simulation engine + tick-level replay, walk-forward optimization |
| Collaboration | Limited chart sharing | Real-time multi-user co-editing, embeddable widgets, public share links |
| Extensibility | Closed plugin ecosystem | Fully pluggable indicators, adapters, and scripts; community marketplace |
| Self-hosting | Not possible | First-class support — run your own instance, own your data |

We're not just cloning TradingView — we intend to **exceed it** on performance, openness, and extensibility.

---

## Feature Roadmap

| Milestone | Focus | Key Deliverables |
|---|---|---|
| **M0 — Foundation** | Repo & infra bootstrap | Monorepo scaffolding, CI/CD, MIT license, CONTRIBUTING, ADR-0001 stack decision |
| **M1 — Core Charting Engine** | Rendering core | WebGL/Canvas engine, viewport & coordinate system, candlestick renderer, time/price axes, crosshair, auth scaffolding |
| **M2 — Data Feeds & Indicators** | Data + analysis | Multi-source real-time data adapters (crypto/stocks/forex), TimescaleDB storage, 50+ built-in indicators, streaming computation |
| **M3 — Drawing Tools & Alerts** | Annotation + notification | 20+ drawing tools, snapping/magnet mode, server-side alert engine, multi-channel notifications |
| **M4 — Backtesting & Scripting** | Strategy development | Historical simulation & replay engine, performance analytics, custom scripting language with sandboxed execution |
| **M5 — Collaboration, Layouts & Polish** | UX + real-time collab | Multi-chart layouts, watchlists, real-time co-editing, shareable/embeddable charts, PWA, accessibility polish |

---

## Proposed Architecture (subject to change — see ADR-0001)

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Web)                        │
│  React / Next.js UI  +  Custom WebGL/Canvas Chart Engine      │
│  Watchlists · Drawing Tools · Scripting Editor · Layouts      │
└───────────────────────────▲───────────────────────────────────┘
                            │ WebSocket / REST
┌───────────────────────────┴───────────────────────────────────┐
│                        Backend Services                       │
│  Node or Rust services:                                       │
│   - Data Ingestion & Normalization (crypto/stocks/forex)       │
│   - Alert Evaluation Engine                                   │
│   - Backtesting/Replay Engine                                 │
│   - Scripting Sandbox (WASM)                                  │
│   - Auth & Account Sync                                       │
│   - Collaboration (real-time sync, CRDT)                       │
└───────────────────────────▲───────────────────────────────────┘
                            │
┌───────────────────────────┴───────────────────────────────────┐
│                        Data Layer                              │
│   Postgres + TimescaleDB (OHLCV, ticks, user data)             │
│   Redis / message queue for real-time fan-out                  │
└─────────────────────────────────────────────────────────────┘
```

This stack is a **starting proposal, not a final decision** — see `docs/adr/0001-stack-decision.md` (tracked in M0) for the open questions and rationale as they're resolved. Where possible, issues in this repo are written to remain stack-agnostic until an ADR is merged.

---

## Monorepo Structure (proposed)

```
candleviewer/
├── apps/
│   ├── web/              # Frontend app (Next.js)
│   └── desktop/          # Future Electron/Tauri wrapper
├── packages/
│   ├── chart-engine/     # Core rendering engine
│   ├── indicators/       # Indicator library
│   ├── scripting/        # Custom scripting language + sandbox
│   └── ui/               # Shared UI components
├── services/
│   ├── data-ingestion/
│   ├── alerts/
│   ├── backtesting/
│   └── collaboration/
├── docs/
│   └── adr/              # Architecture decision records
└── infra/                # IaC, Docker, CI configs
```

---

## Getting Started

> Coming soon — local dev setup instructions will land as part of M0 (Infra & DevOps epic).

---

## Contributing

We'd love your help! CandleViewer is early-stage, which means there's a lot of room to shape core architecture.

- Read `CONTRIBUTING.md` before opening a PR.
- Check issues labeled `good-first-issue` and `help-wanted` to get started.
- Larger design discussions happen via ADRs in `docs/adr/` and GitHub Discussions.
- Please be respectful and constructive — see `CODE_OF_CONDUCT.md`.

---

## License

CandleViewer is licensed under the [MIT License](LICENSE).
