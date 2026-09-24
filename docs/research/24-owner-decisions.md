# Owner decisions — research phase close-out

Date: 2026-09-14. Resolves §4 "Decisions needed from the owner" in `00-README.md`.
Status: **Decided** unless marked otherwise. These are inputs to the upcoming design/ADR phase; no build tickets yet.

| # | Decision | Outcome | Notes / consequences |
|---|----------|---------|----------------------|
| 1 | Chart engine | **Fully custom WebGL engine** (owner chose "best feature-rich" over lowest effort) | Highest-effort path (research estimate: Lightweight-Charts route 11–17 wks of custom rendering; fully custom adds ~6–10 wks). Justified because this is a long-lived personal platform and every order-flow view (footprint cells, profiles, DOM heatmap, bubbles, trading overlays, drawing tools) needs pixel-level control anyway. Lightweight Charts remains the **fallback** if the engine spike fails. First spike: footprint-cell + heatmap rendering at realistic density (see `22-architecture-options.md` §11). |
| 2 | Storage | **Owner delegates → 3-tier hybrid** (QuestDB hot tier for ticks/L2/bars · Parquet + DuckDB cold tier for archive/replay/analytics · Postgres for OMS state, users, rules, audit) | Chosen for feature richness over "just Postgres" simplicity. Prototype QuestDB vs TimescaleDB against real footprint/replay query shapes before hard-committing the hot tier (performance claims disputed, see finding #19). |
| 3 | Bybit product categories | **USDT linear perpetuals only** (v1) | Simplifies OMS: single `category=linear`, UTA, One-Way vs Hedge `positionIdx`. Spot / inverse / options are Won't for v1. |
| 4 | Symbols recorded continuously | **User-managed recorded-symbols list (empty by default) + auto-record any symbol with an open chart or open position** | Nothing is recorded until the user acts; history for footprint/profile/CVD/heatmap/replay starts when recording starts. Auto-recording needs a retention policy (proposal: 30 days default, per-symbol override, pin = keep forever). Live views work for any symbol regardless. |
| 5 | Account model | **Main account + sub-accounts all manageable; one trade can target N selected accounts, each executed with its own per-account profile ("trade group fan-out")** | Per-account profile: leverage, sizing rule (% equity / fixed $ / fixed qty / risk-based), SL/TP offsets, max risk/day, allowed symbols. One order ticket → backend fans out per-account orders, tracked as a *trade group*; positions/PnL views aggregate or split. Every account: trade+read key, **Withdrawal OFF**, IP whitelist. Sub-account cap 5 (20 with Business KYC). Rate limits are per-UID, so fan-out must budget per account. |
| 6 | Remote access | **Owner delegates → Tailscale-only** | No public exposure. Backend binds to `127.0.0.1`/WSL-internal only; Tailscale client on the Windows host; Tailscale ACLs per manager. |
| 7 | Desktop wrap | **Owner wants best performance/smoothness → Electron primary, Tauri evaluated in the engine spike** | With a custom WebGL engine, predictable GPU behaviour matters most. Electron bundles a known Chromium with controllable GPU flags; Tauri/WebView2 WebGL behaviour under 100 ms heatmap updates is unverified (finding #29). Decision finalises after the spike measures both; the web app itself stays shell-independent. |
| 8 | Testnet | **Owner delegates → connectivity smoke-tests only** | Demo trading (real matching engine, `stream-demo` private WS, REST-only order entry) is the paper environment. |
| 9 | Options / GEX analog | **Owner delegates → skip for v1** | Revisit later with Deribit as data source; needs its own research pass. |
| 10 | Heatmap colour convention | **Owner delegates → green = bid/buy liquidity, red = ask/sell; user-configurable theme** | Avoids DeepCharts/Volumetrica's mutually contradictory conventions. |
| 11 | Rule builder UI | **Both form/condition-list editor AND visual node-graph editor in v1** | Both must compile to the same rule IR executed by one rule engine (so rules round-trip between editors). Adds meaningful frontend scope; node-graph candidates: React Flow / Rete.js. |

## Cross-cutting consequences

1. **Effort profile shifts frontend-heavy**: custom WebGL engine + dual rule editors + multi-account fan-out UI. Backend scope is unchanged from `22-architecture-options.md`.
2. **Mandatory spikes before design sign-off** (from §11 of doc 22, re-prioritised):
   1. Custom WebGL engine core: candles + footprint text cells + DOM heatmap at 100 ms cadence, 100k bars, 60 fps — in Chromium, Electron and Tauri/WebView2.
   2. QuestDB vs TimescaleDB on real footprint/replay queries.
   3. Bybit private WS client (pybit vs custom asyncio) reliability under load; demo vs live parity.
   4. Multi-account fan-out latency and rate-limit budget with 3–5 sub-accounts on demo.
3. **Safety invariant** (finding #21): every fan-out order carries a native exchange-side SL regardless of rule-engine stops.
4. **Recording policy** needs a small design: recorded-list UI, auto-record triggers (chart open / position open), retention, disk budget display (~0.5–0.75 GB/day/symbol compressed at 200-depth).

## Still open (not blocking design start)

- Retention default for auto-recorded symbols (proposal 30 days).
- Per-account profile schema details (which fields are per-account vs per-trade overrides).
- Which node-graph library for the rule editor.
- Legal review of the multi-manager model (finding #26) — owner's call on timing.
