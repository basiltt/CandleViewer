# CandleViewer Research — Index & Executive Summary

Research phase only — no build tickets exist yet. This document indexes every research artifact under `docs/research/`, then distills the findings into a scope recommendation and a list of decisions the owner needs to make before design/implementation begins.

Scope reminder: private, self-hosted, simplified TradingView-alternative for one owner + a few account managers. Monolith (React frontend, Python/WSL backend). Crypto-only, Bybit-first. Demo + live (testnet low priority). WebSockets wherever available. Full trading facilities (paper trading, fast order controls, rule-based stops). Target: replicate DeepCharts' (Volumetrica-engine) order-flow visibility (Deep Print footprint, Deep Profile, Deep Stats, Big Trades, imbalance tracker, speed of tape, VWAPs, DeepDOM heatmap, liquidity tracker, stop-run/iceberg detectors, market regime, tick replay, trading terminal, auto-tracker).

---

## 1. Document index

### Source research docs (01–12)

- **01-tradingview-charting.md** — Inventory of TradingView's charting surface: ~20 chart types, 110+ drawing tools, ~195 built-in indicators (vs "400+" marketing), footprint/tick/second-interval tiering, bar replay depth formulas, layout/watchlist/alert quotas per plan, and a TV-vs-DeepCharts gap table concluding TV has no real DOM heatmap/tape-speed/stop-run/iceberg/regime layer — CandleViewer must build those directly against Bybit feeds.
- **02-tradingview-trading.md** — TV's Trading Panel/broker-integration model, confirmed Bybit↔TV integration specifics (order types, TP/SL mechanics, position mode), paper trading (idealized fills, no slippage model), DOM panel, Pine Script sandbox limits, Strategy Tester/Deep Backtesting caps, and the critical charting-library licensing finding: Advanced Charts' free license forbids private/unpublished use, so CandleViewer must build on Lightweight Charts (Apache-2.0) or fully custom canvas/WebGL instead.
- **03-tradingview-gaps.md** — 24 ranked TV shortfalls (no true footprint, no DOM heatmap, 24h broker re-auth, fragile webhook automation, idealized paper fills, no native OCO/scale-in, Pine sandbox restrictions, no ladder hotkeys, etc.), each mapped to a CandleViewer fit rating — nearly all rated "Strong" fit because building directly against Bybit's API sidesteps TV's entire broker-bridge architecture.
- **04-deepcharts-deepchart.md** — Full DeepCharts "Deepchart" product feature inventory (Deep Print/footprint, Deep Stats, Deep Profile, Big Trades, Imbalance Tracker, Unfinished Auction, Bar POC, Speed of Tape, VWAP+Envelopes, CVD, Market Profile/TPO, Deep-M Effort/IVB, Deep V-Tracker, Deep Pattern Builder, Deep Profile Swing, Deep Replay, Trading Terminal, keyboard shortcuts, Stop Run/Deep Wall, Imbalance Rejector, Deep Delta, Confluence Identifier, Auction Gap Tracker, Performance Analysis reports, Templates/Workspaces) with per-feature Bybit-feasibility notes — almost everything is buildable from Bybit's public trade/kline/L2 streams except true iceberg/MBO detection, which is heuristic-only everywhere (no exchange has retail MBO).
- **05-deepcharts-deepdom-gamma.md** — DeepDOM (liquidity heatmap/DOM/MBO features, Windows-only) and DeepGamma (SPX/CBOE options-gamma overlay) feature grids with per-feature MBO-dependency analysis; confirms Deep Reload, Deep Liquidity Scan, Market Regime/Book Speed, and core Absorption are fully buildable from Bybit's L2 (MBP) stream with no MBO dependency, while Iceberg/Stop-Run/Big-Passive-Trade remain heuristic proxies; recommends Deribit as the primary data source if a crypto options/GEX analog is ever pursued.
- **06-bybit-api.md** — Ground-truth Bybit v5 API reference: UTA 2.0 account architecture, environments (mainnet/testnet/demo, including demo's WS-trade-order-entry gap later resolved in doc 12), product categories, REST/WS endpoint catalogue, auth/rate-limit rules (per-UID not per-key), historical-data/bulk-download options, SDK choice (pybit), fee-schedule caveats, sub-account/API-key permission model, and a pitfalls section (no checksum on orderbook, `confirm` flag gating kline bar-close, price-distance-only trailing stop, no derivatives OCO, no native Iceberg/TWAP order types).
- **07-crypto-orderflow-competitors.md** — Competitive landscape of commercial order-flow platforms (Exocharts, TensorCharts, Bookmap, ATAS, Quantower — several with native Bybit connectors), aggregated-derivatives-data platforms (Hyblock, Coinglass, Coinalyze, Velo, Laevitas), on-chain analytics (CryptoQuant, Glassnode — deprioritized), and open-source reference projects (Tucsky/aggr, footprint_analyzer, OrderFlow-Analysis-Pro, lightweight-charts, KLineChart) that inform CandleViewer's architecture choices (chassis, exchange-abstraction pattern, ingestion pipeline, POC/delta math).
- **08-crypto-data-metrics.md** — Precise recipes for deriving every order-flow metric from raw Bybit v5 endpoints: trades/CVD, footprint cells/imbalances, volume profile/TPO, VWAP variants, OI/funding/liquidations, big-trade clustering, iceberg-reload heuristics, speed of tape, stop-run/absorption/exhaustion detection, and market-regime classification (ADX/ATR/Hurst) — with default thresholds for each heuristic and a large open-questions list around unverified rate limits and archive schemas.
- **09-execution-risk-tools.md** — Survey of order-entry UX patterns (DOM ladder, hotkeys, one-click arm toggle), scale-in/chase/TWAP/iceberg/OCO mechanics and which are native vs must-be-emulated on Bybit, trailing-stop variants (ATR-based/structure-based are differentiators, not offered natively anywhere), rule-automation engine precedents (Coinrule, Kryll, Freqtrade Protections) informing a proposed Rule DSL, paper-trading fill-simulation approaches, multi-account/RBAC precedents (recommending one Bybit sub-UID per manager, trade+read-only, withdrawal disabled), and trade-journal schema elements (MAE/MFE, auto-tagging).
- **10-frontend-tech.md** — Charting-library decision matrix (Lightweight Charts v5 recommended chassis; KlineCharts and LightningChart JS Trader as fallbacks; TV Advanced Charts explicitly not recommended due to licensing) plus a per-surface rendering plan: footprint via custom series (largest single engineering item, 2-3 weeks), DOM heatmap via dedicated WebGL/PixiJS layer, DOM ladder via list virtualization, drawing tools via LWC primitives — with an 11-17-week full-custom-rendering effort estimate and a Tauri-vs-Electron desktop-wrap recommendation (Tauri default, smoke-test WebGL early).
- **11-backend-tech.md** — Python backend architecture: full Bybit v5 WS surface (public/private/trade streams, depth/frequency tiers, demo-trading constraints), idempotency/reconciliation/clock-drift handling, and a storage recommendation (QuestDB hot tier + Parquet/DuckDB cold tier + Postgres/SQLite relational tier) with concrete storage-sizing estimates (~7GB/day raw, ~1-1.5GB/day compressed at 200-depth/2 symbols) and a risk register covering pybit threading, QuestDB benchmark disputes, and demo/live behavioral divergence.
- **12-scope-and-users.md** — Multi-user/account scoping: Bybit sub-account caps (5 standard / 20 KYC-business), security architecture (least-privilege API keys, envelope encryption, RBAC: Owner/Manager/Viewer, audit logging, Tailscale-only network exposure), a 9-step session workflow, 4 personas, 13 top-level screens, legal/ToS considerations (CandleViewer as "API Client," managers as "Authorized Individuals," DeepCharts trademark-avoidance guidance), and a ~80-item MVP MoSCoW list across 10 functional domains — this doc is the direct precursor to 20-feature-matrix.md.

### Synthesis docs (20–23)

- **20-feature-matrix.md** — The master feature matrix: every feature surfaced across docs 01-12 and view-catalogue 23, organized into domain sections A-O (chart/bar types, scales/sessions, drawing tools, indicators, order-flow footprint/profile/stats/tape/CVD/DOM/heatmap/detectors/regime, crypto derivatives data, trading/order entry, risk automation, paper trading, replay/backtest, alerts, layouts/UX, journal/analytics, multi-account/admin/security, data infrastructure), each row scored MoSCoW with a Bybit-v5 feasibility column (Y/Partial/N). Totals: Must=149, Should=118, Could=79, Won't=28 (374 rows).
- **21-gap-analysis.md** — Synthesizes docs 01-12 into a ranked list of TV shortfalls, a DeepCharts value-add glossary, seven "critical gaps CandleViewer fills" (including the multi-account/RBAC model and a cost/self-hosting rationale showing ~$260-340/mo commercial-stack cost vs ~$0 incremental self-hosted), and an explicit "what we deliberately drop" list (true MBO iceberg, DeepGamma/options GEX, multi-exchange aggregation, TV Advanced Charts, Pine Script, social/community layer) plus a 10-item product risk register.
- **22-architecture-options.md** — The architecture recommendation: component diagram, ingestion data-flow, storage comparison, chart-engine decision matrix, OMS + rule-engine design (rule DSL, failover mitigations, clock-drift/rate-limit handling), paper-trading matcher and replay engine, env/key management, auth/roles, deployment plan (WSL→VPS via docker-compose, Tailscale-only exposure), and 10 concrete spikes to run before committing, landing on §12's Recommended Option: Lightweight Charts v5 + custom canvas + PixiJS/regl heatmap; QuestDB + Parquet/DuckDB + SQLite/Postgres; Python asyncio + pybit; REST-first OMS with native-where-possible/emulated-elsewhere plus a native hard-SL backstop.
- **23-views-and-screens.md** — Catalogue of 21 numbered views/screens (Main Chart through Admin/Users), each with Purpose/Data inputs/Key settings/Visual encoding/Interactions-hotkeys/DeepCharts-TV equivalent/ASCII wireframe, plus cross-cutting notes (global hotkey layer, demo/live gating, "(estimated)" badges for heuristic order-flow signals, recorder-history dependency) and 5 open design questions (rule-builder UI paradigm, DOM heatmap color convention, "Auto-Tracker" branding uncertainty, legal/regulatory scale limits, visual design system).

### Digests (`digests/`)

Condensed, source-cited versions of the above with explicit open-questions sections; content summarized inline in the corresponding entries above (01-12) plus:

- **23-views-and-screens.digest.md** — Condensed version of 23-views-and-screens.md (same 21-view structure, same cross-cutting notes/open questions, compressed to ~50 lines).

---

## 2. Top 30 findings

1. **No exchange (Bybit included) exposes L3/MBO order-level data** — every iceberg, true stop-run, absorption, and "order-count" footprint feature that DeepCharts/DeepDOM markets as MBO-driven must be built as a heuristic proxy on CandleViewer and explicitly badged "(estimated)" in the UI.
2. **TradingView Advanced Charts' free license legally forbids CandleViewer's use case** (private, unpublished, non-public tool) — do not embed it without a negotiated commercial license. Build on Lightweight Charts (Apache-2.0) instead.
3. **Lightweight Charts v5 is the recommended chassis**, extended with custom Canvas series/primitives for footprint/volume-profile/drawing-tools and a dedicated WebGL (PixiJS/regl) layer for the DOM heatmap; total custom-rendering build is estimated at 11-17 weeks before any backend integration.
4. **Footprint cell rendering is the single largest frontend engineering risk** (2-3 week estimate, no public benchmark found for text-heavy cell rendering at realistic densities) — should be spiked early.
5. **Bybit demo trading does NOT support WS order entry** — REST-only for demo order placement; live trading can use the faster WS trade endpoints. Any OMS abstraction must branch on this.
6. **Bybit demo trading DOES have a private WS stream** (`wss://stream-demo.bybit.com`) for order/position/execution/wallet — corrects an earlier assumption; paper mode can still be largely WS-driven.
7. **No native Bybit derivatives OCO** — spot has OCO; derivatives require emulating OCO by racing two orders and cancelling the loser on fill notification.
8. **No native Bybit Iceberg order type via API** — no `orderType=Iceberg`/`displayQty` field exists on `/v5/order/create`; iceberg-style execution must be emulated as client-side order slicing.
9. **No native Bybit TWAP order type** — must be emulated via timed repeated REST order-creation calls.
10. **Bybit trailing stop is price-distance-only, not percentage** — a client-side translation layer is required to expose "% trailing" to users.
11. **Bybit orderbook WS has no checksum field** — desync must be detected heuristically and resolved via drop-and-resubscribe, not checksum validation.
12. **Kline WS messages carry a `confirm` boolean** that must gate all "bar closed" logic — using bar arrival alone will cause premature/incorrect bar-close triggers.
13. **Bybit rate limits are per-UID, shared across all API keys under that UID** — not per-key; the recorder/OMS must budget rate-limit consumption account-wide, not key-by-key.
14. **Bybit "Chase Limit" exists only as a sub-algo of the Iceberg order ticket** (Taker/Maker/Offset/Fixed-Price variants) with unconfirmed exact numeric parameters (max chase distance, refresh interval) — needs live-API confirmation before implementation.
15. **Sub-account cap is 5 for regular accounts, 20 for KYC-Business accounts** — directly bounds how many account managers CandleViewer can isolate via one-sub-account-per-manager without upgrading Bybit account tier.
16. **New Bybit accounts have a 48-hour API-key-creation cooldown** — onboarding a new manager needs 2 days of lead time budgeted.
17. **Recommended storage architecture is a three-tier hybrid**: QuestDB (hot tier, live ticks/L2/bars), Parquet+DuckDB (cold tier, archive/replay/analytics), Postgres or SQLite (relational: OMS state, users, audit, rules) — not a single database.
18. **Storage sizing estimate**: ~7GB/day raw / ~1-1.5GB/day compressed at 200-depth for 2 symbols (~30-45GB/month, ~0.4-0.5TB/year); scaling to 1000-depth or many more symbols multiplies this 2-3x+ — needs real instrumentation, current figures are first-principles estimates.
19. **QuestDB's performance-superiority claims vs ClickHouse are disputed** by a ClickHouse maintainer rebuttal — treat ingestion-speed claims as directionally true but validate with CandleViewer's own realistic footprint/replay queries before committing.
20. **No mature async-Python Bybit private-WS client exists with pybit's ergonomics** — CandleViewer likely needs to hand-build (or heavily wrap) the private-stream/order-entry client; this is flagged as the highest-leverage OMS-correctness decision.
21. **A hard native stop-loss should always exist as a backstop** behind any emulated/client-side stop logic (trailing, rule-based, scaled) — if the backend/rule-engine goes down, an in-exchange native SL protects capital; this is a core risk-mitigation design requirement, not optional.
22. **DeepCharts is a white-label front end on the Volumetrica engine** — "Deepchart" and "DeepDOM" are separate product SKUs (plus a separate "DeepGamma" options overlay); nearly all Deepchart/DeepDOM sub-features (Deep Print, Deep Stats, Deep Profile, Big Trades, Imbalance Tracker, Speed of Tape, VWAP, CVD, TPO, Deep Reload, Deep Liquidity Scan, Market Regime, Absorption, Stop-Run) are buildable from Bybit's public trade+L2+kline streams alone.
23. **DeepCharts/Volumetrica trademarks and UI/text must not be reused** — CandleViewer should use generic internal names ("Footprint Chart," "DOM Heatmap," "Volume Profile") since these are generic order-flow techniques shared across many platforms (Bookmap, ATAS, Sierra Chart, Jigsaw), not exclusive IP.
24. **Crypto markets have no natural session/RTH boundary** — session-anchored features (VWAP resets, TPO day-boundaries, Deep-M IVB opening-range) must define an artificial anchor (commonly UTC 00:00, or Bybit funding times 00:00/08:00/16:00 UTC) as a CandleViewer-specific design decision.
25. **TradingView itself has no genuine DOM/liquidity heatmap, tape-speed gauge, stop-run detector, or market-regime classifier** — these are CandleViewer's true differentiators versus the "TradingView alternative" framing, not merely feature parity items.
26. **Regulatory/legal exposure from the multi-manager model is unresolved** — "managers" trading on the owner's behalf on a private, non-fee tool likely avoids formal investment-adviser triggers in US/UK/EU frameworks, but this is a reasoned inference, not legal advice; counsel should be consulted before scaling beyond a couple of managers.
27. **Recommended security posture**: one Bybit sub-UID per manager, trading key with Withdrawal permission always OFF, IP-whitelisted, envelope-encrypted at rest, app-layer RBAC (Owner/Manager/Viewer) enforced server-side, append-only audit log of every order action and key-management event, and Tailscale-only network exposure (no public internet-facing backend).
28. **WSL2 has a specific security footgun**: binding a server to `0.0.0.0` inside WSL can leak to LAN/internet via portproxy/UPnP misconfiguration — must bind to `127.0.0.1`/WSL-internal only and run the Tailscale client on the Windows host.
29. **Tauri is recommended over Electron for desktop packaging** (lower memory footprint, matters when co-resident with the Python backend/WSL), but WebView2's WebGL behavior under sustained 100ms-cadence heatmap updates is unverified and should be smoke-tested early; Electron is a low-regret fallback since the web app itself is shell-independent.
30. **Multiple numeric/behavioral facts remain unconfirmed and need live-API verification before implementation**: exact Bybit REST public rate limit (~600 req/5s/IP, sourced from a mirror not primary docs), exact orderbook depth/frequency tiers per category, max API keys per UID (conflicting 5/10/20/30/100 figures across sources), and whether sub-accounts can independently enable Demo Trading.

---

## 3. Recommended scope in one page

**Product framing:** a private, Bybit-first, WebSocket-driven trading terminal that fuses TradingView-grade charting UX with genuine order-flow depth (footprint, DOM heatmap, tape, CVD, detectors) that neither TradingView nor most retail platforms offer natively for crypto — plus a full execution/risk/journal loop for a small team of discretionary managers under one owner's Bybit account.

**In scope for v1 (Must-priority, ~149 rows in the matrix):**
- Core charting: candlestick/bar/line, multi-timeframe, multi-pane synced layouts, horizontal/trend/ray/rectangle/Fibonacci drawing tools, standard TA indicator library (MA family, MACD, RSI, Bollinger, ATR, ADX, etc.), session/VWAP anchoring for 24/7 markets.
- Order flow: footprint (Deep Print analog) with bid/ask/delta cell modes, Deep Stats bar summary, volume profile + TPO, Big Trades bubble overlay, imbalance tracker, CVD panes, speed-of-tape gauge, DOM ladder + liquidity heatmap (DeepDOM analog), all heuristic-labeled where MBO would normally be required.
- Derivatives context: OI, funding rate (with countdown), liquidations (bars/heatmap from recorder only, no exchange history endpoint exists).
- Trading: market/limit/stop/stop-limit orders, bracket orders (TP/SL), native hard-SL backstop, fast hotkey-driven entry, one-click arm toggle, position-sizing calculator, emulated OCO/iceberg/TWAP/scale-in where Bybit lacks native support, rule-based trailing stops (ATR/structure-based as differentiators) and rule-based auto-exits via a custom Rule DSL.
- Paper trading: Bybit demo-trading integration (REST for orders, WS for state) as primary, plus a local simulated fill engine for gap-filling.
- Multi-account/admin: one Bybit sub-account per manager, app-layer RBAC (Owner/Manager/Viewer), owner kill-switch/risk dashboard, API-key management with self-check, append-only audit log, 2FA, Tailscale-only remote access.
- Journal: auto-logged trades from execution stream, tags/notes, aggregate stats (win rate, expectancy, R-distribution).
- Infrastructure: Bybit WS recorder as the system of record (ticks, L2 deltas, liquidations) since Bybit's own REST history is thin/absent for most of these; hybrid storage (QuestDB hot + Parquet/DuckDB cold + Postgres/SQLite relational).

**Should-priority (~118 rows), phase 1.5:** replay/backtest mode, stacked-imbalance/absorption/stop-run detectors, market regime classifier, anchored VWAP variants, composite/multi-period volume profile, breakeven-at-R automation, chart-trading draggable order lines, layout templates, alerting engine.

**Could-priority (~79 rows) / explicitly deferred:** true tick-by-tick backtesting engine, custom indicator scripting language, iceberg/stop-run confidence-scored detectors as first-class alerts, CSV/PDF journal export, multi-exchange abstraction beyond Bybit.

**Won't-do / deliberately dropped (~28 rows, per 21-gap-analysis.md §4):** true MBO-based iceberg detection (no exchange offers it at retail tier), DeepGamma/options-GEX equivalent (crypto-only v1; revisit only if Bybit/Deribit options become a priority), multi-exchange price/liquidity aggregation, TradingView Advanced Charts library, Pine Script or any user-scripting sandbox, social/community layer (sharing, comments, public profiles).

**Estimated frontend build effort:** ~11-17 weeks for the full custom-rendering surface (chassis integration, footprint, volume/delta profile, drawing tools, chart-trading lines, DOM heatmap, DOM ladder) before backend integration.

---

## 4. Decisions needed from the owner

> **RESOLVED 2026-09-14 — see `24-owner-decisions.md` for the outcomes.** Headline changes vs the recommendations below: #1 fully custom WebGL engine (not Lightweight Charts); #4 user-managed recorded-symbol list + auto-record open charts/positions; #5 multi-account "trade group fan-out" with per-account profiles; #7 Electron primary pending spike; #11 both form and node-graph rule editors in v1. The original options/recommendations are kept below for context.

Each decision lists the options considered and a recommendation. These should be resolved before detailed design/architecture sign-off.

### 1. Charting engine
- **Options:** (a) TradingView Lightweight Charts v5 + custom Canvas/WebGL layers; (b) KlineCharts v9/v10; (c) LightningChart JS Trader (commercial, ~$4,900/yr); (d) TradingView Advanced Charts; (e) fully custom D3/WebGL from scratch.
- **Recommendation:** (a) Lightweight Charts v5 as primary chassis, with a PixiJS/regl WebGL layer for the DOM heatmap. It's Apache-2.0 (no licensing risk, unlike Advanced Charts), has the best 100k+-candle performance, and native multi-pane support. Budget a 1-2 week spike on footprint-cell rendering early to validate the approach; fall back to KlineCharts (friendlier overlay/drawing-tools model) or LightningChart (paid, solves heatmap natively) only if the spike fails.

### 2. Storage engine(s)
- **Options:** (a) QuestDB (hot) + Parquet/DuckDB (cold) + Postgres/SQLite (relational) hybrid; (b) TimescaleDB unified for everything; (c) ClickHouse; (d) ArcticDB for replay tier.
- **Recommendation:** (a) the three-tier hybrid, as detailed in 22-architecture-options.md §12 — but run a short prototype of QuestDB vs TimescaleDB against CandleViewer's actual footprint/replay query shapes before fully committing, since QuestDB's performance claims are disputed and TimescaleDB's "just Postgres" simplicity may be worth more at this modest single-user scale.

### 3. Bybit product categories to support
- **Options:** (a) USDT perpetuals only; (b) USDT perps + spot; (c) USDT perps + spot + inverse; (d) all four including options.
- **Recommendation:** start with (a) USDT linear perpetuals only for v1 — this is almost certainly the owner's primary trading activity and keeps the OMS/position-mode model (UTA, One-Way vs Hedge, `positionIdx`) simple. Add spot in phase 1.5 if used for accumulation/rebalancing. Treat inverse and options as Could/Won't for now (options additionally requires the separate Deribit-vs-Bybit sourcing decision in #9 below).

### 4. Symbols to record continuously
- **Options:** (a) BTCUSDT + ETHUSDT only; (b) a fixed watchlist of ~10-20 majors; (c) dynamically record whatever the owner/managers have open charts or positions on.
- **Recommendation:** (b) fixed core watchlist of the instruments actually traded, starting with BTCUSDT/ETHUSDT (as assumed throughout the research) plus a handful of other liquid perps the owner names. Recording is the gating factor for footprint/profile/replay depth — every symbol not recorded has no order-flow history — so this list should be decided explicitly, not left implicit. Add symbols opportunistically but understand new symbols start with zero history.

### 5. Account / sub-account model
- **Options:** (a) one Bybit standard sub-account per manager (max 5, or 20 with Business KYC); (b) shared trading sub-account with app-layer attribution only; (c) one Bybit Main account per manager (fully separate, no shared collateral).
- **Recommendation:** (a) one sub-account per manager, trade + read-only permissions, Withdrawal permission always OFF, IP-whitelisted key. This gives real blast-radius isolation (a manager's losses can't draw down others' capital) at low operational cost. If more than 5 managers are ever needed, Business KYC upgrade (→20 cap) is the path, not consolidating managers onto shared sub-accounts (which forfeits isolation).

### 6. Remote access model for managers
- **Options:** (a) Tailscale-only (WireGuard mesh, no public internet exposure); (b) public HTTPS with reverse proxy + WAF; (c) VPN (WireGuard/OpenVPN self-managed).
- **Recommendation:** (a) Tailscale-only, per 12-scope-and-users.md §2.5 and 22-architecture-options.md's deployment plan. Simplest to operate correctly, avoids the WSL2 `0.0.0.0`-binding leak risk entirely, and matches the private/small-team nature of the tool. Combine with Tailscale ACLs to restrict which managers reach which ports/services.

### 7. Desktop wrap
- **Options:** (a) Tauri; (b) Electron; (c) browser-only (no native wrapper), PWA install.
- **Recommendation:** (a) Tauri as default given its lower memory footprint (relevant when co-resident with the Python backend/WSL on the same box), but explicitly smoke-test the WebGL DOM-heatmap layer inside Tauri's WebView2 (Windows) early in development — this is an unverified risk area. Electron is a low-regret fallback since the underlying web app is shell-independent either way.

### 8. Testnet priority
- **Options:** (a) skip testnet entirely, use demo trading as the only non-live environment; (b) support testnet as a first-class environment alongside demo/live; (c) support testnet only for early connectivity smoke-tests, not ongoing use.
- **Recommendation:** (c) — testnet is explicitly low priority per the original brief. Use it only for initial API/WS connectivity validation during development; Bybit's demo-trading environment (real matching engine, realistic liquidity) is the actual paper-trading environment end users will rely on day-to-day, per doc 03's explicit recommendation to prefer exchange demo accounts over synthetic simulators.

### 9. Options / GEX analog
- **Options:** (a) skip entirely (crypto perps/spot only); (b) build a Deribit-sourced options/GEX overlay later as a phase-3 feature; (c) attempt a Bybit-native options overlay now.
- **Recommendation:** (a) skip for v1 — explicitly listed as "deliberately dropped" in 21-gap-analysis.md §4 and consistent with the crypto-only/Bybit-first framing. If revisited later, (b) Deribit should be the primary data source (dominant options OI/volume venue; Bybit's own options OI is much smaller), per 05-deepcharts-deepdom-gamma.md's recommendation — this would need its own dedicated research pass (Deribit API chain endpoints, OI-by-strike, IV surface) before scoping.

### 10. DOM heatmap Buy/Sell color convention
- **Options:** (a) green=bid/buy, red or violet=ask/sell (standard convention, matches most platforms); (b) follow DeepCharts' own documented convention (green=Buy Limit/violet=Sell Limit); (c) follow Volumetrica's own VolBook article convention (green=Sell Limit/red=Buy Limit) — note DeepCharts' own docs contradict Volumetrica's docs on this point.
- **Recommendation:** (a) — adopt the more universally recognized green=bid/buy, red=ask/sell convention rather than either of DeepCharts/Volumetrica's internally-contradictory conventions. Make it a user-configurable theme setting regardless, since this is subjective and easy to get "wrong" for any given user's prior platform experience.

### 11. Rule Builder UI paradigm
- **Options:** (a) structured form/condition-list editor (like Coinrule); (b) visual node/block-graph editor (like Kryll); (c) both, starting with the simpler form editor.
- **Recommendation:** (c) — ship the structured-form editor first (faster to build, matches most of the referenced precedents like Coinrule/Freqtrade config), and treat a node-graph editor as a Could/phase-2 UX upgrade. DeepCharts' own Pattern Builder UI paradigm was never confirmed (open question in doc 04), so there's no strong parity argument either way.

---

## 5. Known unknowns / follow-up research

Carried forward from the digests' open-questions sections, grouped by theme:

**Bybit API specifics needing live verification before implementation:**
- Exact REST public rate limit (~600 req/5s/IP figure is sourced from a mirror, not primary docs) and exact orderbook depth/frequency tiers per category (spot/linear/inverse/option) — re-confirm against live V5 docs.
- Max API keys per UID (conflicting figures: 5/10/20/30/100 across sources) and API-key expiry behavior for non-IP-bound keys (90-day figure unverified).
- Whether a sub-account can independently enable Demo Trading (doc 06's explicitly unresolved open question #1).
- Exact VIP fee schedule (blocked by anti-scraping on Bybit's pricing page; must call `GET /v5/account/fee-rate` live).
- Bybit "Chase Limit" order's exact numeric parameters (max chase distance, refresh interval) and whether it exists as an independent order type outside the Iceberg ticket.
- Precise per-endpoint rate limits for order placement/amend/cancel per sub-account (affects rule-engine polling design).
- Exact meaning of Bybit error code `10018` and temporary IP-ban duration for rate-limit violations.
- Bybit's exact historical retention window for OI/funding/liquidation REST endpoints (not empirically verified).

**Architecture/engineering spikes flagged as needed before committing (from 22-architecture-options.md §11 and 10-frontend-tech.md):**
- Footprint custom-series rendering performance at realistic cell/bar densities (no public benchmark found — the single largest unresolved engineering-risk question).
- QuestDB vs TimescaleDB prototyped against CandleViewer's actual footprint/replay query shapes (not synthetic benchmarks), given disputed vendor performance claims.
- Tauri WebView2 behavior under sustained 100ms-cadence WebGL heatmap updates (no data found; needs early smoke test).
- pybit thread-based WS bridging reliability under high message rates vs. a custom asyncio private-WS client (highest-leverage OMS-correctness decision, per doc 11).
- Real instrumentation of actual Bybit message rates and storage growth at production symbol count (all current sizing figures are first-principles estimates, could be off 2-3x).

**Legal/regulatory (flagged, not resolved by this research, requires counsel):**
- Full Bybit API Terms & Conditions text (only partially retrieved) — clauses on automated/algorithmic tools, liability, multi-user restrictions.
- Regulatory status of "managers" trading on the owner's behalf under US (Investment Advisers Act), UK (FCA), and EU (MiFID II) frameworks — reasoned inference only in doc 12, not legal advice.
- Whether TradingView would ever grant a commercial Advanced Charts license for a private/unmonetized internal tool (moot if Lightweight Charts path is taken, per Decision #1).

**Feature-design open questions carried from 23-views-and-screens.md:**
- DOM heatmap Buy/Sell color convention (addressed as Decision #10 above, but implementation still pending).
- Whether DeepCharts literally brands a feature "Auto-Tracker" (unconfirmed) — CandleViewer's Journal view spec is derived from the project brief, not confirmed DeepCharts parity; doesn't block building it, just a naming/parity note.
- Visual design system, color tokens, and window-management behavior (single-window multi-pane vs. multi-OS-window) — no design pass has been done yet.
- Rule Builder UI paradigm — partially addressed as Decision #11, but DeepCharts' own paradigm (node-graph vs form) was never confirmed, so there's no parity target to benchmark against, only first-principles UX judgment.

**Data-modeling / heuristic-threshold tuning needed empirically (from 08-crypto-data-metrics.md and 04/05):**
- DeepCharts/Volumetrica's exact internal iceberg/stop-run classification thresholds are proprietary and unpublished — CandleViewer must tune its own thresholds (diagonal-imbalance ratio, stacked-imbalance depth, big-trade z-score, iceberg-reload count/tolerance) empirically against recorded Bybit data rather than copying undisclosed competitor parameters.
- Estimated-liquidation-levels modeling (inferring liquidation price clusters from OI + leverage-tier assumptions, à la Coinglass/Hyblock) is proprietary at those vendors and would need its own dedicated design phase after CandleViewer has accumulated real liquidation data to calibrate against.
- Value Area computation: CandleViewer's planned single-step price-level expansion is a simplification of the "textbook" two-row TPO expansion algorithm — decide whether exact parity with a reference platform matters enough to implement the more complex version.

---

## Summary of consistency-pass fixes applied

As part of this research pass, two fixes were applied in place:
1. **20-feature-matrix.md**: removed two stray literal tab characters that were breaking Markdown table-row formatting (rows `|282|` and `|304|`).
2. **23-views-and-screens.md**: expanded View 1 (Main Chart)'s Purpose statement to explicitly claim ownership of the Drawing Tools (matrix §C) and classic TA Indicators (matrix §D) feature domains, both of which had Must/Should-scoped matrix rows but no view had explicitly hosted them before this edit.

All other feasibility labels in 20-feature-matrix.md were cross-checked against digest 06-bybit-api.digest.md and found consistent (no further edits required) — including the correct "Partial" feasibility ratings for OCO, Iceberg, and TWAP, the correct "Y with a caveat" rating for trailing stop (price-distance not %), and the correct "N"/"Won't" rating for WS-Trade-on-demo.
