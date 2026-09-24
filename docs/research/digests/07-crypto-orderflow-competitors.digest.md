# Digest: 07-crypto-orderflow-competitors.md

Source compiled 2026-09-13/14. Bybit-first order-flow charting research.

## 1. Commercial order-flow/footprint platforms

- **Exocharts** — footprint, delta, volume profile, TPO, DOM, dynamic profiles, VWAP; live order execution incl. Bybit spot/linear/inverse. Free tier limited (SHIB/DOGE/SOL, no orderflow). Desktop Pro ≈$49/mo. Web+desktop. Not OSS.
- **TensorCharts** — liquidation heatmap (cross-exchange, OI+book based), order-book heatmap, trades heatmap/footprint, volume profile, cumulative delta. Analytics-only (no full execution). Bybit data-only (execution unconfirmed). Free; Premium ≈$18/user/mo; Team ≈$40/mo (5 users, likely genuine bulk discount, unverified). Web (GPU). Not OSS.
- **Bookmap (crypto)** — heatmap (reference impl.), volume dots, Multibook (multi-exchange incl. Bybit aggregation), full L2, manual iceberg/spoofing/absorption pattern recognition. Some click-trading via DOM. Bybit via data feed/Multibook. Historical L2 replay ~2018+ for futures (no crypto-specific figure); local "Record" feature = disk-limited self-capture — **direct precedent for CandleViewer's own L2 recording**. Pricing: Digital (free tier), Digital Plus ≈$19/mo, Global ≈$99/mo (crypto data included, no extra fee). Desktop (Java). Not OSS.
- **ATAS (crypto)** — 400+ footprint/cluster variations, delta/imbalance, DOM, absorption tracking, C#-custom-indicator framework. **Native Bybit connector** (real L2+trade data, no bridge) but requires Bybit One-Way position mode (Hedge mode unsupported → "parameter error"). Market Replay: 3 modes — (1) Generated Ticks+DOM: unlimited range, simulated DOM; (2) Ticks+Generated DOM: real trades/approx book, ~1 week/session; (3) Ticks+DOM: full-fidelity real L2, **~1 day/session limit** (key data-volume evidence point). No confirmed mobile app. Pricing (EUR): START free (2 assets), PLUS €24.95/mo (€19.95 annual), PRO €69.95/mo (€39.95 annual, needed for real-time tick data), ULTRA €89.95/mo (€49.95 annual, unlimited+MBO+options beta). Desktop (.NET/Windows). Not OSS.
- **Quantower** — footprint/cluster, volume profile, delta, DOM Surface/heatmap (3D), Market Profile/TPO, Power Trades (large-trade tape). Full execution, algo order types, C#.NET strategy runner. **Native Bybit connector; all premium features FREE when connected via Bybit account since 2022** (re-confirmed ongoing 2026, no end date) — notable GTM precedent. No native mobile app (3rd-party remote-desktop only). Replay depth = provider/broker-bounded, not platform-fixed (for CandleViewer this means Bybit's own retention is the real cap). Pricing: free w/ Bybit; else ALL-IN-ONE ≈$70/mo or modules ≈$35/mo, lifetime available. Desktop (Win/Mac wrapper) + some web. Not OSS.

## 2. Aggregated derivatives data/analytics platforms

- **Hyblock Capital** — liquidation heatmap (predicted zones, gradient), OI heatmap/clusters, CVD, avg trade size, participation ratios, long/short sentiment; TradingView overlays + standalone app. Coverage 1,000+ coins incl. Bybit. Extras: screeners, backtesting on liquidation/OI/orderbook data, alerting. Free/Professional/Advanced tiers, API on paid. Web+TV+API. Not OSS.
- **Coinglass** — liquidations+heatmaps, OI (OHLC, cross-exch, OI/mcap ratio), funding (per-exch, OI-weighted, arb monitor), long/short ratio (global+top-trader), taker buy/sell vol, spot/deriv pricing, L2/L3 depth, options data, ETF flows, ticker rankings. Bybit included. Pricing (confirmed via API page): Free web; Hobbyist $29/mo ($348/yr, non-commercial, 80+ endpoints, 30 req/min); Standard $299/mo (commercial rights start here); Professional $699/mo ($8,388/yr, 160+ endpoints, 1,200 req/min, deepest history, priority support); Enterprise custom. Web+API. Not OSS.
- **Coinalyze** — OI, funding (incl. predicted), liquidations history, long/short ratios, basis, OHLCV. **Free**, ad-supported + genuinely free REST API (`api.coinalyze.net/v1`, free key, ~40 req/min). Endpoints: `/open-interest`, `/funding-rate`, `/liquidation-history`, `/future-markets`, `/spot-markets`, `/ohlcv-history`. Attribution requested for redistribution. Bybit included. Web+free API. Not OSS but usable as supplementary data source.
- **Velo Data (velo.xyz)** — futures/options/spot: order books, options term structure/IV/skew, funding, OI, liquidations, flows, ETF flows, annualized basis, seasonality. Coverage: Binance/Bybit/OKX/Deribit/Hyperliquid/CME. Free tier (~5s delay, most dashboards); Premium ≈$199/mo (real-time, full history); custom/enterprise. CSV/streaming API, Python SDK `velodata`. Web+API/SDK. Not OSS.
- **Laevitas** — options analytics (chain, live flow, block trades, IV surfaces, Greeks, skew, multi-leg strategy builder/backtester), futures analytics (OI, vol, liquidations, funding, basis curves, term structure, book depth), correlation studies, DeFi yield. Coverage 15+ exchanges incl. Bybit, 1,000+ assets, 5+ yrs history. Notable: **pay-per-call API via USDC micropayments (HTTP 402)**, no API key needed for occasional use. Best reference for **options flow** (DeepCharts has none). GitHub org = `github.com/laevitas` (corrected from `Laevitas-Crypto-Analytics`) — mostly SDK/CLI tooling (`laevitas-sdk`, crawlers, packaging), not deep schema docs. Separate `0xReisearch/laevitas-mcp` = independent MCP server. Free+paid tiers. Web/API.
- **Kingfisher (thekingfisher.io)** — LiqMap™/liquidation heatmap (price×time, Z-score/gradient), leverage-tiered views (2×–95×, 90×–125×), directional (long/short) cluster separation, historical snapshot review, plus GEX+ (gamma exposure), Toxic Order Flow, Aggregated Order Book. No own footprint/CVD chart. Aggregates 27+ venues incl. Bybit (not an execution connector). Pricing: Premium ≈$72/mo (unlimited LiqMaps, GEX+, Toxic Order Flow, Agg Order Book, signals/alerts/bots, basic API credits, no multi-coin LiqMap); Pro ≈$100/mo (adds Aggregated/Multi-Coin LiqMap + higher API/support tier); Pay-as-you-go ≈$29/session (no aggregation); API/Business custom; annual ~15% discount. `/pricing` page 404'd during research — figures from cached sources, re-verify before purchase. Telegram+Web. Not OSS.

## 3. Trading terminals (execution-focused, multi-exchange)

- **Aggr.trade / Tucsky's `aggr`** — OSS real-time aggregated multi-exchange trade-tape visualizer (Binance/Coinbase/BitMEX/KuCoin/Bitfinex/**Bybit**+more), filterable, rolling sums, liquidation viz, customizable panes. Architecture: Vue.js front end + Node.js backend (`aggr-server`) ingesting exchange WS, resampling, writing to flat files/InfluxDB. `aggr-lib` = community scripts/panes. Free, OSS (GPL-family — verify per-repo). Web (self-hostable). **Relevance: High** — architectural template for CandleViewer's multi-venue ingestion layer.
- **TRDR.io** — TradingView-powered charts, real-time aggregated order book/depth overlays, liquidation feed+volume-by-side, OI tracking, long/short ratios, funding. Custom multi-condition alerts (webhook), screener, multi-chart layouts. Bybit included in aggregation. Pricing (EUR, confirmed genuine): Free (1 chart/template, 2 charts, delayed); Pro €29.95/mo (real-time book/liq/OI, 4 charts, 10 watchlists, 7-day trial); Premium €59.95/mo (unlimited saved charts, 8 charts, 25 alerts, 1/5/30s timeframes); annual = 2 months free; crypto payment supported. Web. Not OSS.
- **Tealstreet** — multi-exchange execution terminal (15+ exchanges incl. Bybit), customizable layouts/hotkeys/macros, order entry from chart/DOM/order book/news, "chaser" orders, **serverless — API keys never leave device (self-custody by design)**, multi-account, audio cues, built-in P&L. Monetized via exchange referral partnerships (zero trader fees). Bybit full spot+futures w/ referral discounts. Main terminal proprietary; **CLI is OSS** (`Tealstreet/cli`). Web app + OSS CLI.
- **Insilico Terminal** — free, professional, non-custodial multi-exchange terminal. Execution algos: **TWAP, Limit Chase, Scale orders, Swarm orders**; visual/CLI/hotkey entry; smart order routing; risk/portfolio mgmt (hide dust); basket trading; low-latency routing. Bybit + long CEX list + Hyperliquid DEX. Free (monetized via fee rebates). PWA, 12+ languages. Not confirmed OSS.

## 4. Traditional-markets platforms with crypto support

- **Sierra Chart (crypto)** — "Numbers Bars" footprint (Bid×Ask, Delta, Imbalance, Volume), tick-level storage, customizable. Crypto feeds: Binance/Bitfinex/BitMEX/Deribit (ex-FTX). **Bybit confirmed NOT natively supported** (no SC Data entry; community thread ThreadID=50493 requests it, unresolved). Would need 3rd-party bridge/custom import. Numbers Bars requires mid/higher service tier. Desktop (Windows-native, Wine on Linux/Mac). Not OSS.
- **Jigsaw Daytradr** — futures-only workspace, no confirmed crypto/Bybit support (inspiration only). Features: **Reconstructed Tape** (reassembles fragmented T&S prints into true order size — directly relevant to iceberg detector), **Auction Vista** (large-trade circles + depth shading), **Pace of Tape** (50+ gauge styles for tape speed — analogous to "speed of tape"), Depth&Sales DOM w/ one-click entry, realistic fill-modeling simulator. Broker feeds: Rithmic/CQG/GAIN/IQFeed (all futures). Pricing not found; desktop add-on, proprietary.
- **MotiveWave** — general charting w/ paid "Order Flow Edition": footprint/volume-imprint, CVD, absorption signals, liquidity heatmap, Market Profile/TPO, DOM. Crypto charting via compatible broker/feed; Bybit not confirmed. Pricing: Community free (no orderflow); Order Flow Edition $49/mo or $595 lifetime; feed/broker costs separate. Desktop (Java). Not OSS (3rd-party add-ons exist, e.g. WyckFlow).
- **"Orderflow-tools"** (open Q3, resolved as generic term) — no single named product found. Concrete matches: NinjaTrader "Order Flow+" (native footprint/volumetric bars, CVD, depth map, vol profile); TradeDevils "Orderflow Footprint Trader" (imbalances, exhaustion, delta, alerts); NT8-OrderFlow community kit; TradingView Pine Script footprint scripts ("Order Flow Footprint Real-time", "Ninja Trader Order Flow Smart Footprint"). All futures/NinjaTrader/TradingView-oriented, none Bybit-native — reference for UI/indicator design only.

## 4.6 Bybit V5 public API surface (resolved open Q9) — key numeric limits

| Data | Endpoint | Limits/notes |
|---|---|---|
| Open interest history | `GET /v5/market/open-interest` | Params: category, symbol, intervalTime (5min/15min/30min/1h/4h/1d), startTime/endTime, limit, cursor. Public, no auth. |
| Long/short account ratio | `GET /v5/market/account-ratio` | Params: category, symbol, period (5min…1d), limit. Public, no auth. |
| Funding rate history | `GET /v5/market/funding/history` | **limit capped at 200 records/request** — deeper history needs pagination via startTime/endTime windows. |

Implication: CandleViewer can source all 3 "derivatives-sentiment" data types natively from Bybit, no need to build own estimation. Bybit's exact server-side retention window for these endpoints **not empirically verified** — recommend direct API probe with old timestamps.

## 5. On-chain analytics (brief, low priority/out of scope)

- **CryptoQuant** — exchange flows, miner activity, whale tracking, market indicators. Free + paid $29/mo (Advanced) to $799/mo (Premium); enterprise custom. Alerts (email/Telegram/browser). API+CSV.
- **Glassnode** — 1,700+ on-chain metrics, 1,500+ assets, 15+ yrs history. Holder/supply metrics, entity-level analysis, MVRV. Advanced $49/mo; Professional/Vector custom (Vector from $749/mo). REST+bulk API, Excel plugin.
- Both spot/on-chain focused, not derivatives-microstructure, not Bybit-specific. Verdict: low priority, phase-3 at most.

## 6. Open-source projects

### 6.1 Multi-exchange trade aggregation
| Project | Function | License | Relevance |
|---|---|---|---|
| Tucsky/aggr | Vue.js live aggregated multi-exch trades (incl. Bybit), liq viz, rolling sums, filters | GPL-family, verify | High — closest analog to "speed of tape"/aggregated-trades pane |
| Tucsky/aggr-server | Node.js: ingests WS feeds, resamples, persists to files/InfluxDB | Same | High — template for ingestion service |
| Tucsky/aggr-lib | Community scripts/indicators/panes/workspaces | Same | Medium — indicator ideas (custom CVD panes) |

### 6.2 Footprint/order-flow implementations
| Project | Function | Stack | Relevance |
|---|---|---|---|
| endegenaassefa/footprint_analyzer | Footprint charts from tick data, configurable time/tick/volume/range aggregation; computes POC, Delta, Value Area | Python | High — reference for POC/VA math |
| mahmoud20138/OrderFlow-Analysis-Pro | Footprint/orderflow chart + delta analytics + volume profile; **explicitly supports Bybit and MT5 feeds** | Python+Dash | High — direct Bybit precedent |
| tyumex/tyumex-trading-terminal | Windows multi-chart terminal, footprint/cluster charts, second-based candles, bar replay | Desktop | Medium — bar-replay/backtester UX reference |
| github.com/topics/footprint-charts(-chart) | Browse for more projects | — | — |

### 6.3 Charting libraries
| Project | Function | License | Relevance |
|---|---|---|---|
| tradingview/lightweight-charts | TradingView's OSS lightweight charting lib; custom series/primitives (v4/v5 plugin API) for footprint/vol-profile/delta overlays | Apache-2.0 | High — most credible base for CandleViewer chart component |
| safaritrader/lightweight-chart-plugin | Plugin adding volume-profile overlays, drawing tools, tooltips to Lightweight Charts | MIT | Medium — plugin-building template |
| klinecharts/KLineChart | Zero-dep, ~40-50KB gzip, TS candlestick lib; built-in indicators: MA/EMA/SMA/DMA, MACD, RSI, BOLL, KDJ, WR, CCI, PSY, AO, TRIX, VOL, OBV, CR, MTM, VR, ROC, DMI, SAR, BIAS, BRAR, BBI, EMV, AVP, PVT; custom-indicator API; mobile/touch; 15+ drawing tools | MIT (verify) | High — alt/complement if broader built-in indicator library wanted |

### 6.4 Exchange abstraction / paper trading / backtesting
| Project | Paper trading | Exchange abstraction | Live trading | Best for | License |
|---|---|---|---|---|---|
| Freqtrade | Dry-run vs real market data | Built on **CCXT** — broad/swappable | Yes, broad | Flexible research + algo trading, large community, web dashboard | GPL-3.0 |
| Hummingbot | Simulation mimicking order books | Custom native connectors (not CCXT), CEX/DEX | Yes, low-latency | Market-making/arbitrage/liquidity provision | Apache-2.0 |
| Jesse | Spot-focused, tied to backtest engine | Custom, narrower (historically Binance-centric) | Spot/futures, fewer exchanges | Best-in-class backtesting/strategy R&D | Custom/AGPL (verify) |

Relevance: Freqtrade's CCXT `Exchange` interface pattern most directly reusable for "allow more exchanges later." Jesse's dry-run/backtest engine relevant to paper-trading/tick-replay reqs. Hummingbot relevant only if true market-making latency needed (unlikely).

### 6.5 NautilusTrader (Bybit L2 backtest)
- Rust-native, event-driven, "research-to-live parity" (same strategy code backtest+live).
- `nautilus-bybit` Rust crate; L2 backtesting via Bybit's public **"ob500" archives** (up to 500 book-depth levels per instrument, dated ZIP files).
- Workflow: download ob500 → parse to DataFrame → `deltas_from_frame` → `OrderBookDelta` objects → replay via `BacktestNode` (example: OrderBookImbalance FOK strategy).
- Architecture: Rust core (perf/determinism) + Python strategy bindings.
- OSS (`nautechsystems/nautilus_trader`). **Relevance: High** for tick-replay/backtester requirement — most rigorous open L2-aware Bybit-confirmed backtest engine found.

## 7. Comparison matrix (condensed; ✅=confirmed ◐=partial/unconfirmed ❌=absent)

| Platform | Footprint | Book heatmap | Liq heatmap | CVD | OI | Funding | L/S ratio | Whale trades | Multi-exch agg | Options flow | Bybit native | Entry price | Platform | OSS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Exocharts | ✅ | ◐ | ❌ | ◐ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | $49/mo | Web/Desktop | ❌ |
| TensorCharts | ✅ | ✅ | ✅ | ✅ | ◐ | ❌ | ❌ | ◐ | ✅ | ❌ | ◐ | Free–$18/mo | Web | ❌ |
| Bookmap | ❌ | ✅ | ◐ | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ Multibook | ❌ | ✅ | Free–$19/mo | Desktop | ❌ |
| ATAS | ✅ | ✅ | ◐ | ✅ | ◐ | ❌ | ❌ | ◐ | ❌ | ◐beta | ✅ native | Free–€69.95/mo | Desktop | ❌ |
| Quantower | ✅ | ✅ | ❌ | ✅ | ◐ | ❌ | ❌ | ✅ Power Trades | ❌ | ❌ | ✅ native, free w/Bybit | Free(Bybit)–$70/mo | Desktop | ❌ |
| Hyblock | ❌ | ◐ | ✅ | ✅ | ✅ | ◐ | ✅ | ◐ | ✅ | ❌ | ✅ | Free–paid | Web/TV/API | ❌ |
| Coinglass | ❌ | ◐ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | Free–$699+/mo | Web/API | ❌ |
| Coinalyze | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | Free | Web/API | ❌(free API) |
| Velo Data | ❌ | ◐ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | Free–$199/mo | Web/API | ❌ |
| Laevitas | ❌ | ◐ | ❌ | ❌ | ✅ | ✅ | ❌ | ◐ | ✅ | ✅deep | ✅ | Free–custom | Web/API | ◐ |
| TRDR.io | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | Free–€59.95/mo | Web | ❌ |
| Tealstreet | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Free | Web+OSS CLI | ◐CLI only |
| Insilico | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Free | PWA | ❌ |
| Sierra Chart | ✅Numbers Bars | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ not native | Tiered | Desktop | ❌ |
| Jigsaw Daytradr | ❌tape | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ✅Auction Vista | ❌ | ❌ | ❌futures-only | n/a | Desktop | ❌ |
| MotiveWave | ✅ | ✅liquidity heatmap | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐unconfirmed | Free–$49/mo | Desktop | ❌ |
| aggr.trade | ❌ | ❌ | ◐liq events | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ | ❌ | ✅ | Free OSS | Web self-host | ✅ |
| Kingfisher | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ◐agg,no exec | $72–100/mo+PAYG/API | Telegram/Web | ❌ |

Note: DeepCharts already covers footprint/Deep Print, Deep Profile, Deep Stats, Big Trades, imbalance tracker, speed of tape, VWAPs, DeepDOM liquidity heatmap, liquidity tracker, stopruns, iceberg detector, market regime, tick replay/backtester. Matrix's purpose = confirm competitor parity/excess + extra categories DeepCharts/TV lack (liq heatmap, funding, L/S ratio, options flow, on-chain).

## 8. Ranked list — features worth borrowing (1=highest priority)

1. **Liquidation heatmap** (Hyblock/Coinglass/Kingfisher/TensorCharts style) — not in DeepCharts; Bybit exposes raw liq/OI data needed. High value, moderate effort (needs cross-position-size estimation model, not just raw prints).
2. **Funding rate + OI + long/short ratio dashboard** (Coinglass/Coinalyze/TRDR style) — Bybit API natively exposes all three. Low effort, high value, squarely fills DeepCharts gap.
3. **Free/native Bybit-first monetization pattern** (Quantower) — product-strategy insight, not a feature; confirms Bybit users are commercially significant segment.
4. **Reconstructed Tape** (Jigsaw Daytradr) — reassemble fragmented prints into true order size; feeds iceberg detector + Big Trades.
5. **DOM Surface/3D order-book viz + Power Trades** (Quantower) — alt/complement to flat DeepDOM heatmap.
6. **Options flow/IV surface/skew** (Laevitas, Velo Data) — DeepCharts has zero options coverage; Laevitas data model best reference if Bybit options ever added.
7. **NautilusTrader Rust-core/Python-bindings event-driven backtest w/ Bybit L2 replay** — most rigorous open reference for tick-replay/backtester requirement.
8. **Freqtrade's CCXT-based exchange abstraction pattern** — informs multi-exchange-ready architecture even if Bybit-only initially.
9. **aggr.trade's WS-ingest → resample → reactive multi-exchange trade-tape pipeline** — proven lightweight OSS architecture, reusable as design template (partially as code, license permitting).
10. **KLineChart's built-in indicator library breadth** — faster path to broad indicator set vs. bespoke.
11. **Footprint POC/Delta/Value-Area calc reference** (footprint_analyzer, OrderFlow-Analysis-Pro) — concrete OSS math for time/tick/volume/range bucketing; OrderFlow-Analysis-Pro already targets Bybit.
12. **Tealstreet's serverless/API-keys-never-leave-device model** — security pattern for self-hosted single-user+few-account-managers deployment.
13. **Insilico/Jigsaw execution algos** (TWAP, Limit Chase, Scale, Swarm) — vocabulary/spec for custom rule-based stops/exits + fast order controls.
14. **Pace of Tape gauge-style widget** (Jigsaw) — UI pattern alternative to plain rolling-average speed-of-tape number.
15. **Kingfisher's Telegram-native alert distribution** — low priority but cheap notification channel idea (liq clusters, stop-run zones → Telegram).

## 9. Architecture implications for CandleViewer (decisions/recommendations)

- **Charting core**: build on `tradingview/lightweight-charts` (Apache-2.0) primary; `KLineChart` as fallback/companion if broader built-in indicators prioritized over exact TV look.
- **Exchange abstraction**: Freqtrade/CCXT-style `Exchange` interface (REST+WS per venue) from day one, Bybit-only implementation initially.
- **Data ingestion**: follow `aggr`/`aggr-server` pattern — backend ingests Bybit WS (trades, book deltas, liquidations), normalizes/resamples, persists to time-series store; decoupled from React frontend via normalized internal WS/SSE stream.
- **Footprint/order-flow math**: reference `footprint_analyzer` + `OrderFlow-Analysis-Pro` for POC/Delta/Value-Area bucketing (time/tick/volume/range modes).
- **Backtesting/tick replay**: reference NautilusTrader's Bybit L2 (ob500) event-driven replay architecture (Rust core / Python bindings) as gold-standard conceptual model even without adopting Rust.
- **Derivatives-sentiment panel**: add funding-rate/OI/long-short-ratio/liquidation-heatmap panel sourced directly from Bybit API — category DeepCharts lacks, low effort.
- **Iceberg/large-order detection**: implement Jigsaw's "Reconstructed Tape" — group rapid same-price/same-side prints into inferred parent orders.
- **Execution algos**: implement TWAP, Scale, "chaser"/Limit-Chase order types per Insilico/Jigsaw/Quantower vocabulary.
- **Security model**: store Bybit API keys client-side / locally-scoped secrets store (not shared server-side custody), per Tealstreet's self-custody principle.
- **Options flow (future/optional)**: if Bybit options ever added, use Laevitas' data model (chain view + Greeks + IV surface + skew + strategy builder) as best available reference.

## Open questions (status as of pass)

1. ~~Kingfisher pricing structure~~ — Resolved (§2, Premium ≈$72/mo, Pro ≈$100/mo, PAYG, custom API tier); `/pricing` page 404'd, figures from cached sources — spot-check before financial decisions.
2. ~~Sierra Chart + Bybit~~ — Resolved: confirmed NOT natively supported; community request thread open, unresolved.
3. ~~"Orderflow-tools"~~ — Resolved as far as possible: no single named product; generic category term; closest matches are NinjaTrader Order Flow+, TradeDevils, NT8-OrderFlow kit, TV Pine scripts — all futures/NinjaTrader/TV-oriented, none Bybit-native.
4. **Jigsaw Daytradr / MotiveWave Bybit support** — unconfirmed (Jigsaw futures-only via Rithmic/CQG/GAIN/IQFeed; MotiveWave depends on unconfirmed 3rd-party feed/broker). Still open — not revisited.
5. **Exact license terms** for `Tucsky/aggr`, `aggr-server`, `Tealstreet/cli`, `klinecharts/KLineChart` — must verify each repo's LICENSE file (MIT vs GPL/AGPL) before vendoring code. Still open.
6. **Freqtrade/Jesse's precise current exchange support lists** — should recheck live GitHub READMEs (used sources were 3rd-party comparisons, possibly stale). Still open.
7. **TensorCharts/Bookmap/MotiveWave native Bybit *execution* connector** (vs. data/viz only) — not conclusively established for any of the three. Still open (ATAS's and Quantower's execution connectors were separately re-confirmed as genuinely native).
8. ~~Laevitas' GitHub org~~ — Resolved: correct org is `github.com/laevitas`; mostly SDK/CLI tooling, not deep data-model docs.
9. ~~Bybit's own public data completeness~~ — Resolved: confirmed public V5 endpoints for OI history, L/S account ratio, funding history (200-record/call cap, needs pagination). Bybit's **exact retention window** for these endpoints NOT empirically verified — recommend direct API probe with old timestamps before finalizing retention/backfill strategy.
10. **DOM/heatmap replay latency + tick-storage sizing** — only partially resolved. ATAS's 1-day/session limit and Bookmap's disk-limited local recording give qualitative evidence full-fidelity L2 replay is data-volume-constrained even for mature platforms, but **no platform publishes a concrete GB/day-of-L2 or max-DB-size figure**. CandleViewer needs its own empirical sizing exercise (capture N days of real Bybit L2 diff-depth stream, measure raw/compressed size).
11. **TensorCharts and Sierra Chart first-party pricing pages** could not be directly fetched (`tensorcharts.com/pricing`, `thekingfisher.io/pricing` both failed — 404/tool error); figures sourced from secondary aggregators (SoftwareSuggest, search summaries) — recommend manual/browser check before relying on exact current numbers.
