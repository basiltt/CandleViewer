# Crypto order-flow / charting competitors — features to borrow

> Research phase document for CandleViewer (self-hosted, crypto-only, Bybit-first order-flow charting/trading platform). Compiled 2026-09-13; gap-filling/corrections pass appended 2026-09-14. This report inventories order-flow/charting competitors and open-source projects, with a focus on features that go beyond what TradingView/DeepCharts already offer, and flags which are relevant to a Bybit-centric build.

## Table of contents

1. [Commercial order-flow / footprint platforms](#1-commercial-order-flow--footprint-platforms)
2. [Aggregated derivatives data / analytics platforms](#2-aggregated-derivatives-data--analytics-platforms)
3. [Trading terminals (execution-focused, multi-exchange)](#3-trading-terminals-execution-focused-multi-exchange)
4. [Traditional-markets order-flow platforms with crypto support](#4-traditional-markets-order-flow-platforms-with-crypto-support)
   - 4.5 ["Orderflow-tools" — resolving the original brief's unnamed product](#45-orderflow-tools--resolving-the-original-briefs-unnamed-product-resolved-this-pass--was-open-question-3)
   - 4.6 [Bybit's own V5 API surface — derivatives-sentiment data CandleViewer can source natively](#46-bybits-own-v5-api-surface--derivatives-sentiment-data-candleviewer-can-source-natively-resolved-this-pass--was-open-question-9)
5. [On-chain analytics (brief, likely out of scope)](#5-on-chain-analytics-brief-likely-out-of-scope)
6. [Open-source projects to learn from or reuse](#6-open-source-projects-to-learn-from-or-reuse)
7. [Comparison matrix](#7-comparison-matrix)
8. [Ranked list: features worth borrowing](#8-ranked-list-features-worth-borrowing)
9. [Architecture implications for CandleViewer](#9-architecture-implications-for-candleviewer)
10. [Sources](#sources)
11. [Open questions](#open-questions)


---

## 1. Commercial order-flow / footprint platforms

### 1.1 Exocharts

- **What it is**: Web + desktop order-flow/footprint charting platform, popular in the crypto retail order-flow community.
- **Data shown**: Footprint (bid×ask volume per price level, delta, buyer/seller aggression), volume profile, TPO/market profile, DOM (depth of market), dynamic profiles, VWAP, synthetic volume, trade filters.
- **Trading features**: Live order execution from the order-flow chart (entries/stops/targets) for connected exchanges including Bybit spot, linear, and inverse contracts.
- **Bybit support**: Yes — native, via API key connection; real-time data + order routing.
- **Pricing**: Free tier is very limited (SHIB/DOGE/SOL only, no order flow). Desktop Pro ≈ $49/month (discounts for 3/6-month prepay); web version bundled with Desktop Pro.
- **Platform**: Web + desktop (Electron-style).
- **Open source**: No.
- Sources: [exocharts.com](https://exocharts.com/), [Exocharts Help – Preface](https://help.exocharts.com/hc/en-us/articles/4406161671697-Preface), [Cosmic Crypto Club review](https://cosmiccrypto.club/tools/trading-tools/exocharts), [Captain Trading guide](https://captain-trading.com/en/free-trading-course/exocharts-order-flow-guide)

### 1.2 TensorCharts

- **What it is**: Crypto-native charting app built around order-book heatmaps and liquidation visualization; popular with scalpers.
- **Data shown**:
  - **Liquidation heatmap** — aggregated cross-exchange estimate of price zones where forced liquidations are likely to cluster ("liquidation cascade" zones), combining order book + OI data.
  - **Order book heatmap** — real-time resting liquidity concentration by price level.
  - **Trades heatmap / footprint** — executed order volume per tick, toggle between delta mode and explicit buy/sell.
  - Volume profile, cumulative delta, market profile.
- **Trading features**: Primarily an analytics/visualization tool, not a full execution terminal (alerts, scripting, multi-chart layouts).
- **Bybit support**: Aggregates data across major exchanges; Bybit is one of the covered venues for heatmap/liquidation data (not confirmed as an execution connector).
- **Pricing**: Free plan; Premium ≈ $18/user/month (low latency, full data, all features); Team ≈ $40/month for up to 5 users. *Corrected: this report previously flagged the Team price as internally inconsistent (5 users at $40 total implies ~$8/user, cheaper than the $18/user Premium tier). Re-checked against SoftwareSuggest's TensorCharts pricing summary (secondary source; TensorCharts has no easily reachable first-party `/pricing` page in this pass) — the $18/user and $40-for-5-users figures are both corroborated as currently listed, so the apparent inconsistency is likely a genuine team-plan volume discount (bulk/team pricing undercutting the per-seat Premium rate) rather than a transcription error. Recommend re-verifying directly on tensorcharts.com before relying on either figure for planning.*
- **Platform**: Web (GPU-accelerated rendering).
- **Open source**: No.
- Sources: [TensorCharts Pricing – SoftwareSuggest](https://www.softwaresuggest.com/tensorcharts/pricing), [TensorCharts overview – SoftwareSuggest](https://www.softwaresuggest.com/tensorcharts), [Altcointrading.net review](https://www.altcointrading.net/tensorcharts/), [TensorCharts manual – Trades heatmap](https://docs.tensorcharts.com/docs/trades_heatmap/)

### 1.3 Bookmap (crypto feeds)

- **What it is**: The best-known standalone heatmap/order-book visualization platform, originally futures-focused, now with strong crypto support.
- **Data shown**:
  - **Heatmap** — color-coded resting liquidity across price/time, adjustable color thresholds; widely considered the reference implementation of this visualization.
  - **Volume dots** — executed trade markers overlaid on the heatmap.
  - **Multibook** — aggregates order books from multiple exchanges (including Bybit) into a single unified heatmap.
  - Full L2 market depth, iceberg/spoofing/absorption detection via visual pattern recognition (manual, not automatic labeling — contrast with DeepCharts' automated iceberg detector).
- **Trading features**: Some order entry via DOM/heatmap click-trading (add-ons/brokers vary); primarily a visualization layer that sits alongside a broker connection.
- **Bybit support**: Yes, via crypto data feed / Multibook aggregation.
- **Historical replay depth**: Bookmap's own cloud-hosted historical L2 data (via "Bookmap Data CME" for futures) reportedly extends back to roughly **2018** for major instruments, varying by instrument/licensing; this is a futures-market figure and no equivalent published crypto/Bybit-specific historical-depth figure was found. Bookmap also has a local **"Record"** feature letting users capture and store their own L2 order-book data, in which case replay depth is limited only by local disk space rather than by Bookmap itself — this self-recording pattern (continuously persist raw L2 deltas to disk, replay from local storage) is the most directly applicable engineering precedent for CandleViewer's own tick-replay/backtester, since CandleViewer will similarly need to record and store its own Bybit L2 stream rather than rely on a vendor's historical archive.
- **Pricing (2026)**: Digital (limited free tier), Digital Plus ≈ $19/month, Global ≈ $99/month. Crypto data generally included without the extra "exchange data fee" that futures feeds often carry.
- **Platform**: Desktop (Java-based), with add-on marketplace.
- **Open source**: No.
- Sources: [Bookmap vs Bybit – MadeOnSol](https://madeonsol.com/compare/bookmap-vs-bybit), [Bookmap Review 2026 – PropTradingVibes](https://proptradingvibes.com/blog/bookmap-review), [Bookmap Review 2026 – Bullish Bears](https://bullishbears.com/bookmap-review/), [Bookmap Historical Replay Data discussion – NexusFi](https://nexusfi.com/showthread.php?t=60741), [Bookmap replay files discussion – NexusFi](https://nexusfi.com/showthread.php?t=57592)

### 1.4 ATAS (crypto)

- **What it is**: Professional footprint/order-flow platform originating in futures trading, now with native crypto exchange connectors.
- **Data shown**: 400+ footprint/cluster chart variations (bid×ask volume, delta, imbalance highlighting), DOM/order book visualization, absorption/large-player tracking.
- **Trading features**: Order execution from chart/DOM, alerting, indicator/study framework (C#-based custom indicators).
- **Bybit support**: **Native connector** — real-time L2 + trade data pulled directly, no third-party bridge required. Setup requires Bybit "one-way position mode" + API key. *(Re-confirmed this pass: ATAS explicitly does not support Bybit's Hedge mode — the connection must be switched to One-Way/Single position mode in Bybit before connecting, or ATAS returns a "parameter error." Confirmed via ATAS's own Bybit connection guide and Quick Start docs.)*
- **Historical order-flow replay depth**: ATAS's Market Replay module offers three modes trading off fidelity vs. range: (1) **Generated Ticks + Generated DOM** — fastest, effectively unlimited date range, but DOM is simulated, not the real historical order book; (2) **Ticks + Generated DOM** — real historical trades with an approximated book, usable for roughly up to a week per session; (3) **Ticks + DOM** — full-fidelity real historical trades *and* real historical order-book depth, but limited to replaying **about one day at a time** given the data volume. This is the most concrete evidence found in this pass of the engineering cost of true tick+DOM replay (mode 3) versus cheaper approximate replay (modes 1–2) — directly relevant to scoping CandleViewer's "tick replay/backtester" requirement.
- **Mobile app**: No dedicated ATAS mobile app was confirmed in this pass; ATAS is presented as a Windows desktop (.NET) platform, and no official iOS/Android release was found on ATAS's own docs/start guides — mobile-oriented search results returned only generic onboarding-flow descriptions, not evidence of an actual native app. Treat as **unconfirmed/likely no native mobile app** rather than confirmed-present.
- **Pricing (2026, EUR)**: START (free, 2 assets), PLUS €24.95/mo (€19.95 annual), PRO €69.95/mo (€39.95 annual, needed for real-time tick data), ULTRA €89.95/mo (€49.95 annual, unlimited + MBO bundle + options beta).
- **Platform**: Desktop (Windows, .NET).
- **Open source**: No.
- Sources: [ATAS Data Feeds](https://atas-bjt.com/atas-data-feeds), [Magic Clusters – How ATAS works](https://www.magic-clusters.com/en/atas/), [ATAS Pricing](https://atas.net/pricing/), [Connecting to Bybit – ATAS Help](https://help.atas.net/en/support/solutions/articles/72000602529-connecting-to-bybit), [traderprofesional.com pricing guide](https://traderprofesional.com/en/atas-pricing/)

### 1.5 Quantower (Bybit connection, features)

- **What it is**: Multi-asset trading platform with a strong order-flow module, notable for a Bybit-specific pricing model.
- **Data shown**: Footprint/cluster charts, Volume Profile, Delta, DOM Surface/Heatmap (3D-style order book visualization), Market Profile/TPO, Power Trades (large-trade tape).
- **Trading features**: Full order execution, algo order types, strategy runner/automation (C# .NET based), multi-account, alerting.
- **Bybit support**: Native connector; **since 2022, all Quantower premium features (footprint, DOM Surface, Volume Analysis, etc.) are free when connected via a Bybit account** — a notably aggressive go-to-market move specifically targeting crypto/Bybit users. *(Re-confirmed this pass, not lapsed: Quantower's own blog post "Bybit connection now gains all Quantower premium features for free" and its live Connections/Help pages still advertise this as an ongoing, no-end-date arrangement as of the 2026 pass — no evidence found that the promotion has expired.)*
- **Mobile app**: No official native iOS/Android app; Quantower is Windows-desktop-first (Mac via wrapper). Mobile access, where available, relies on third-party remote-desktop-streaming solutions (e.g., "Ninja Mobile Trader"-style services) rather than a first-party mobile client — relevant if CandleViewer's "fast order controls" requirement is ever extended to mobile.
- **Historical replay/tick data depth**: Quantower's "Bar Replay"/History Player supports tick-by-tick replay, but the actual history depth is **not fixed by Quantower itself** — it is bounded by whatever the connected data provider/broker retains and exposes (some feeds offer months/years of tick history, others only days/weeks). dxFeed has published that it "expanded historical market data depth for Quantower retail users," implying this is an active, provider-dependent constraint rather than a fixed platform limit — i.e., for a Bybit-first CandleViewer, replay depth will be capped by whatever Bybit's own historical trade/kline/OI retention allows (see the new Bybit API section below), not by any charting-layer limitation.
- **Pricing**: Free with a linked Bybit account for order-flow tools. For other brokers/exchanges: ALL-IN-ONE license ≈ $70/month, or individual modules (e.g., Volume Analysis) ≈ $35/month; lifetime licenses available.
- **Platform**: Desktop (Windows/Mac via wrapper), some web components.
- **Open source**: No.
- Sources: [Connection to Bybit – Quantower Help](https://help.quantower.com/quantower/connections/connection-to-bybit), [Quantower blog – Bybit free premium features](https://www.quantower.com/blog/bybit-connection-now-gains-all-quantower-premium-features-free), [Quantower Pricing](https://www.quantower.com/pricing), [Order Flow Surface docs](https://help.quantower.in/analytics-panels/order-flow-surface), [Quantower Review 2026 – Damn Prop Firms](https://damnpropfirms.com/trading-guides/quantower-review-2026-order-flow-platform/)

## 2. Aggregated derivatives data / analytics platforms

These are not charting platforms per se, but data/signal providers whose visualizations (liquidation heatmaps, OI, funding, long/short ratio, whale trades) are commonly embedded into TradingView via Pine Script or consumed via API — exactly the kind of "data DeepCharts/TradingView don't show" that CandleViewer should consider replicating natively.

### 2.1 Hyblock Capital

- **Data shown**: Liquidation heatmap (predicted risk zones, black→yellow gradient by concentration), Open Interest heatmap/clusters, CVD, average trade size, participation ratios, long/short sentiment — delivered as TradingView indicator overlays plus a standalone app.
- **Coverage**: 1,000+ coins across major exchanges (Binance, Bybit, BitMEX, etc.).
- **Extras**: Screeners, backtesting on historical liquidation/OI/orderbook data, alerting (dashboard/email/Telegram).
- **Pricing**: Free, Professional, Advanced tiers; API access on paid tiers.
- **Bybit support**: Yes, one of the covered exchanges.
- **Platform**: Web + TradingView integration + API.
- **Open source**: No.
- Sources: [Hyblock Academy – Liquidation Heatmap](https://academy.hyblockcapital.com/tools/liquidation-levels-1), [Liquidation Heatmap API docs](https://docs.hyblockcapital.com/liquidation-heatmap), [Hyblock blog – momentum insights](https://hyblockcapital.com/blog/momentum-insights-liquidation-levels-and-open-interest-cluster-analysis), [hyblockcapital.com](https://hyblockcapital.com/), [Hyblock Pricing](https://hyblockcapital.com/pricing), [Hyblock API](https://hyblockcapital.com/api)

### 2.2 Coinglass

- **Data shown**: Liquidations (with heatmaps), Open Interest (OHLC history, aggregated cross-exchange, OI/market-cap ratio), Funding rates (per-exchange, OI-weighted, arbitrage/spread monitoring), Long/short ratio (global + "top trader"), taker buy/sell volume, spot/derivatives pricing, L2/L3 order book depth, options data, ETF flows, ticker-level ranking pages.
- **Pricing** *(corrected: previously vague "reportedly ≈$35/month" — now confirmed against Coinglass's API pricing page)*: Free basic web access. API/data plans: **Hobbyist** $29/mo ($348/yr, non-commercial, 80+ endpoints, 30 req/min); **Standard** $299/mo (commercial-use rights begin here); **Professional** $699/mo ($8,388/yr, 160+ endpoints, 1,200 req/min, deepest historical range, priority chat support); **Enterprise** custom-priced. The web-app-only subscription tiers (as opposed to the API) were not separately itemized in this pass — only the API pricing page was confirmed.
- **Bybit support**: Yes — one of the most complete cross-exchange aggregators; Bybit is consistently one of the tracked venues for OI/funding/liquidation data.
- **Platform**: Web + REST API.
- **Open source**: No.
- Sources: [Coinglass Crypto API](https://www.coinglass.com/CryptoApi), [Coinglass API docs](https://docs.coinglass.com/reference/getting-started-with-your-api), [Coinglass Pricing](https://www.coinglass.com/pricing), [blockchainreporter.net explainer](https://blockchainreporter.net/what-is-coinglass-crypto-liquidation-data-explained/), [dextools.io tutorial](https://news.dextools.io/article/how-to-use-coinglass-liquidations-funding-open-interest-tutorial-2026)

### 2.3 Coinalyze

- **Data shown**: Open interest, funding rates (incl. predicted funding), liquidations (history), long/short ratios, basis, OHLCV — free, ad-supported web UI plus a genuinely free REST API.
- **Pricing**: Free (this is its main differentiator vs. Coinglass/Hyblock).
- **API**: `api.coinalyze.net/v1`, free API key, ~40 requests/min rate limit, endpoints include `/open-interest`, `/funding-rate`, `/liquidation-history`, `/future-markets`, `/spot-markets`, `/ohlcv-history`. Attribution requested for public redistribution.
- **Bybit support**: Yes, listed among aggregated exchanges.
- **Platform**: Web + free API.
- **Open source**: No (but API is free/open-access, useful as a supplementary data source for CandleViewer's own OI/funding panels rather than building exchange-by-exchange scraping).
- Sources: [Coinalyze API docs](https://api.coinalyze.net/v1/doc/), [Captain Trading guide](https://captain-trading.com/en/free-trading-course/coinalyze-guide), [Market Hub overview](https://getmarkethub.com/tools/coinalyze.html), [dlthub Python source docs](https://dlthub.com/context/source/coinalyze)

### 2.4 Velo Data (velo.xyz)

- **Data shown**: Futures/options/spot data — order books, options term structure & implied volatility/skew, funding, OI, liquidations, flows by product/currency/exchange, ETF flows, annualized basis, seasonality.
- **Coverage**: Binance, Bybit, OKX, Deribit, Hyperliquid, CME.
- **Pricing**: Free tier (most dashboards, ~5s delay); Premium ≈ $199/month (real-time, full history); custom/enterprise on request. Data delivered via CSV/streaming API; Python SDK (`velodata` on PyPI).
- **Bybit support**: Yes, explicitly listed.
- **Platform**: Web dashboards + API/SDK.
- **Open source**: No.
- Sources: [Velo API docs](https://docs.velo.xyz/api), [Captain Trading – Velo Data guide](https://captain-trading.com/en/free-trading-course/velo-data)

### 2.5 Laevitas

- **Data shown**: Options analytics (full chain, live flow, block trades, IV surfaces, Greeks, skew, risk reversals, multi-leg strategy builder/backtester), futures analytics (OI, volume, liquidations, funding, basis curves, term structure, order book depth), correlation studies, DeFi yield tracking.
- **Coverage**: 15+ exchanges (Bybit, Deribit, OKX, Binance, Hyperliquid), 1,000+ assets, 5+ years history.
- **Pricing**: Free tier + paid tiers; notable **pay-per-call API via USDC micropayments (HTTP 402)** requiring no API key for occasional use; team/enterprise bundles.
- **Positioning**: Pure analytics/research — not an execution platform. Most relevant to CandleViewer for **options flow visualization** (DeepCharts doesn't cover crypto options at all; this is a clear "feature DeepCharts doesn't have").
- **Open source**: Has a public GitHub org — *(resolved this pass — was previously an open question)*: the actual org is **`github.com/laevitas`** (not `Laevitas-Crypto-Analytics`, which did not resolve to a live org in this pass). Public repos observed include `laevitas-sdk` (Python SDK for the Laevitas API/data services), `laevitas-feature-issue-tracker`, `public` (general public Python code), `solanna-front` (JS front-end component), `Crawlers` (e.g. Opyn Gamma subgraph data extraction, JavaScript), and CLI/packaging utilities (`cli`, `homebrew-cli`, `scoop-bucket`). A separate, independently-maintained `0xReisearch/laevitas-mcp` repo also implements an MCP (Model Context Protocol) server compatible with Laevitas services. **Verdict**: mostly SDK/CLI/tooling repos rather than deep data-model/schema documentation — worth a look for API client patterns (`laevitas-sdk`) but not a rich source of reusable schemas beyond what the public API docs already provide.
- Sources: [Laevitas Review – FINESTEL](https://finestel.com/blog/laevitas-review/), [Cosmic Crypto Club review](https://www.cosmiccrypto.club/tools/trading-tools/laevitas), [Laevitas GitHub org](https://github.com/laevitas), [0xReisearch/laevitas-mcp](https://github.com/0xReisearch/laevitas-mcp)

### 2.6 Kingfisher (thekingfisher.io)

- **What it is**: A liquidation-heatmap/liquidation-map analytics product (site + Telegram distribution), broader than a pure signal channel — closer to a predictive-risk-analytics suite than a full charting/execution platform.
- **Data shown**: LiqMap™/liquidation heatmap (price × time, Z-score/gradient-colored cluster intensity), leverage-tiered views (all/high/medium/low leverage bands, e.g. 2×–95×, 90×–125×), directional (long vs. short) cluster separation, historical snapshot review, plus adjacent derivatives-analytics modules: **GEX+ (gamma exposure)**, **Toxic Order Flow**, and **Aggregated Order Book**. It does **not** offer its own real-time footprint/CVD chart — that is Coinglass/TensorCharts/Exocharts territory, not Kingfisher's.
- **Cross-exchange aggregation**: Reported to aggregate liquidation data across 27+ venues (Binance, Bybit, OKX, Bitget, Deribit, dYdX, Kraken, MEXC, Gate, HTX, Coinbase, BitMEX, Bitfinex, Uniswap, and more), so Bybit is included in the aggregate, though not as a standalone execution connector.
- **Pricing** *(resolved — was an open question; corrected: previously "not clearly published")*:
  - **Premium** ≈ **$72/month** — unlimited LiqMaps™, GEX+, Toxic Order Flow, Aggregated Order Book, signals/alerts/bots, basic API credit allowance. **No** aggregated/multi-coin LiqMap™.
  - **Pro** ≈ **$100/month** — everything in Premium plus **Aggregated/Multi-Coin LiqMap™** (view liquidations across multiple coins/exchanges at once) and higher API credit/support tier.
  - **Pay-as-you-go** — session-based credits (no subscription), e.g. ≈$29 for a short session window; no multi-coin aggregation.
  - **API/Business** — custom pricing for programmatic/algo access.
  - Annual billing reportedly discounted (~15% off).
- **Bybit support**: Included in the aggregated liquidation dataset; no dedicated execution/order-routing connector (Kingfisher is analytics/visualization only, not a trading terminal).
- **Open source**: No.
- Sources: [Kingfisher – Liquidations Maps docs](https://docs.thekingfisher.io/products/liquidations-maps), [Kingfisher – Liquidations Heatmap docs](https://docs.thekingfisher.io/products/kf-liquidations-heatmap), [thekingfisher.io](https://thekingfisher.io/), [Kingfisher docs intro](https://docs.thekingfisher.io/), [Bitcoin Liquidation Heatmap page](https://thekingfisher.io/bitcoin-liquidations-heatmap), [Telegram channel](https://telegram.me/s/thekingfisher_btc). Note: a dedicated `/pricing` fetch returned 404 at the time of this pass; figures above are drawn from search-engine-cached summaries of Kingfisher's pricing/docs pages and should be re-confirmed directly against thekingfisher.io if exact current figures are needed before any purchase decision.

## 3. Trading terminals (execution-focused, multi-exchange)

### 3.1 Aggr.trade / Tucsky's `aggr`

- **What it is**: An open-source, real-time, aggregated multi-exchange trade-tape visualizer. Not a full order-flow/footprint tool but the reference open-source implementation of "aggregated trades across exchanges" visualization.
- **Data shown**: Live aggregated market trades across many exchanges (Binance, Coinbase, BitMEX, KuCoin, Bitfinex, **Bybit**, and more), filterable by time/market/side, rolling sums, liquidation event visualization, customizable panes.
- **Architecture**: Vue.js front end (`aggr`) + Node.js backend (`aggr-server`) that ingests exchange WebSocket feeds, resamples, and writes to flat files and/or InfluxDB.
- **Community**: `aggr-lib` repo hosts community-contributed scripts/indicators/panes/workspaces.
- **Bybit support**: Yes, natively supported exchange in the aggregator.
- **Pricing**: Free, open source (GPL family license — verify exact license per repo before reuse/redistribution).
- **Platform**: Web (self-hostable).
- **Relevance**: **High** — this is close to a direct architectural template for CandleViewer's own multi-venue trade-tape/aggregation layer, and demonstrates a proven WS-ingest → time-series-store → reactive-UI pipeline.
- Sources: [Tucsky/aggr](https://github.com/Tucsky/aggr), [Tucsky/aggr-server](https://github.com/Tucsky/aggr-server), [Tucsky/aggr-lib](https://github.com/Tucsky/aggr-lib), [aggr releases](https://github.com/Tucsky/aggr/releases)

### 3.2 TRDR.io

- **Data shown**: TradingView-powered charts, real-time aggregated order book/depth overlays, liquidation feed + volume-by-side, open interest tracking, long/short ratios, funding rates.
- **Trading features**: Custom multi-condition alerts (webhook support), screener, multi-chart/template layouts.
- **Bybit support**: Yes — included in multi-exchange data aggregation.
- **Pricing** *(re-verified: EUR-denominated pricing confirmed correct, not a stale/localized cache artifact — TRDR's official pricing page genuinely quotes in EUR)*: Free (1 chart/template, 2 charts, delayed data), Pro €29.95/mo (real-time order book/liquidations/OI, 4 charts, 10 watchlists, 7-day free trial), Premium €59.95/mo (unlimited saved charts, 8 charts, 25 alerts, 1/5/30-second timeframes). Annual billing = 2 months free. Crypto payment supported (MetaMask/Phantom/Trust Wallet/USDT) alongside cards/PayPal/Apple/Google Pay.
- **Platform**: Web.
- **Open source**: No.
- Sources: [TRDR Pricing](https://trdr.io/pricing), [TRDR docs FAQ](https://docs.trdr.io/key-features-and-indicators/faq), [Why TRDR? docs](https://docs.trdr.io/getting-started/why-trdr)

### 3.3 Tealstreet

- **What it is**: Fast, multi-exchange execution terminal (not primarily an analytics/footprint tool) — most relevant for its **execution UX** patterns.
- **Data/trading features**: Multi-exchange trading (15+ exchanges incl. Bybit) from one dashboard; customizable layouts, hotkeys, macros; order entry directly from chart/DOM/order book/news feed; "chaser" orders and quick-order tools; serverless architecture (API keys never leave device — self-custody by design); multi-account management; audio trading cues; built-in P&L tracking.
- **Monetization**: Zero direct trader fees — funded via exchange referral partnerships (a notable business model worth considering, though CandleViewer is private/self-hosted so this doesn't directly apply).
- **Bybit support**: Yes, full spot + futures, with referral fee-discount perks.
- **Open source**: Main terminal is proprietary; **CLI tool is open source** ([Tealstreet/cli](https://github.com/Tealstreet/cli)) — trade from a terminal/command line, multi-account, scriptable.
- **Platform**: Web app + open-source CLI.
- Sources: [Tealstreet Review – FINESTEL](https://finestel.com/blog/tealstreet-review/), [tealstreet.io](https://www.tealstreet.io/), [Tealstreet Bybit integration page](https://www.tealstreet.io/integrations/bybit), [Tealstreet/cli GitHub](https://github.com/Tealstreet/cli), [Tealstreet GitHub org](https://github.com/Tealstreet)

### 3.4 Insilico Terminal

- **What it is**: Free, professional-grade, non-custodial multi-exchange execution terminal aimed at active/perp traders.
- **Trading features**: Institutional-style execution algorithms — **TWAP, Limit Chase, Scale orders, Swarm orders**; visual, CLI, and hotkey order entry; smart order routing; risk/portfolio management (incl. "hide dust"); basket trading; low-latency routing for volatile conditions.
- **UI**: Modular drag-and-drop panels, TradingView chart integration, DOM ladders, "Classic" vs "Multi Mode".
- **Bybit support**: Yes — one of a long list of supported CEXs (Binance, Bybit, Coinbase, OKX, Bitget, Kraken, Crypto.com, BitMEX, Blofin, Nado, Apex, Lighter, Extended) plus Hyperliquid (DEX).
- **Pricing**: Free — monetized via trading-fee rebates rather than subscriptions.
- **Platform**: PWA (browser-installable), 12+ languages.
- **Open source**: Not confirmed as open source.
- Sources: [insilicoterminal.com](https://www.insilicoterminal.com/), [Insilico Terminal Review – FINESTEL](https://finestel.com/blog/insilico-terminal-review/), [Terminal 5.0 docs](https://docs.insilicoterminal.com/documentation/welcome/terminal-5.0), [CoinCodeCap review](https://coincodecap.com/insilico-terminal-review)

**Not independently researched this pass** (flagged as open question): Kingfisher's own execution features (it is primarily a signal service, see §2.6).

---

## 4. Traditional-markets order-flow platforms with crypto support

### 4.1 Sierra Chart (crypto)

- **What it is**: Long-established, highly configurable low-level charting/execution platform popular with futures order-flow traders; footprint charts are branded **"Numbers Bars."**
- **Data shown**: Numbers Bars support Bid×Ask footprint, Delta, Imbalance highlighting, and Volume display; requires tick-level intraday data storage; customizable columns/colors/fonts; overlay with candlesticks.
- **Crypto data feeds**: Sierra Chart's built-in "SC Data" crypto feed service documented for exchanges such as Binance, Bitfinex, BitMEX, Deribit (and previously FTX, now defunct). **Bybit is confirmed NOT natively supported** *(resolved this pass — was previously an open question)*: there is no Bybit entry in Sierra Chart's official SC Data cryptocurrency exchange list, and an active Sierra Chart Support Board thread ("Integration of ByBit," ThreadID=50493) shows community demand for Bybit support with no confirmed native integration announced as of this pass. Practical implication for CandleViewer: Sierra Chart is not a plug-and-play Bybit reference platform — connecting Bybit data to it would require a third-party bridge, custom data import, or Sierra Chart's generic external-data-import mechanism (unverified whether this path has actually been implemented by anyone for Bybit specifically).
- **Requirements**: Numbers Bars requires a mid/higher service package tier (not available on the most basic subscription).
- **Pricing**: Tiered "Service Package" subscription model (not crypto-specific pricing found in this pass — see open questions).
- **Platform**: Desktop (Windows-native, runs via Wine on Linux/Mac).
- **Open source**: No.
- Sources: [Sierra Chart Crypto/Bitcoin Data Services](https://www.sierrachart.com/index.php?page=doc/CryptocurrencyDataServices.php), [Sierra Chart Support Board – Integration of ByBit](https://www.sierrachart.com/SupportBoard.php?ThreadID=50493), [Sierra Chart Footprint Setup Guide](https://sierachart.com/blogs/news/sierra-chart-footprint-setup), [Optimus Futures – Numbers Bars guide](https://optimusfutures.com/blog/setting-numbers-bars-sierra-chart/), [Sierra Chart Footprint Templates](https://sierachart.com/collections/footprint-charts-templates)

### 4.2 Jigsaw Daytradr

- **What it is**: A futures-market order-flow *workspace* meant to complement (not replace) a full charting platform like NinjaTrader/MultiCharts. **No confirmed crypto/Bybit support** — included here for feature inspiration only.
- **Data shown / features worth studying**:
  - **Reconstructed Tape** — reassembles fragmented Time & Sales prints back into their original order size, revealing true participant size vs. broken-up/iceberg-style orders. This is conceptually adjacent to DeepCharts' "iceberg detector" and worth replicating for Bybit's public trade feed.
  - **Auction Vista** — historical + real-time order-flow visualization with "Large Trade Circles" and market-depth shading to flag high-volume/turning-point zones.
  - **Pace of Tape** — 50+ gauge styles showing the speed/character of tape activity relative to historical norms (a "speed of tape" implementation, directly analogous to a DeepCharts feature).
  - Depth & Sales DOM with one-click order entry, volume-based stops, and order-flow-triggered alerts (iceberg orders, block trades, divergences).
  - Realistic trading simulator with accurate limit/market fill modeling — relevant to CandleViewer's paper-trading requirement.
- **Broker/feed integration**: Rithmic, CQG, GAIN, IQFeed (all futures-market feeds, not crypto).
- **Pricing/platform**: Desktop add-on product (pricing not found in this pass); proprietary.
- Sources: [EdgeClear – Jigsaw Daytradr](https://edgeclear.com/trading/jigsaw-daytradr/), [Jigsaw Trading (official)](https://www.jigsawtrading.com/daytradr-professional-order-flow-platform/), [GFF Brokers](https://gffbrokers.com/platforms/jigsaw-daytradr), [NexusFi overview](https://nexusfi.com/a/platforms/jigsaw-daytradr)

### 4.3 MotiveWave

- **What it is**: General-purpose charting/analysis platform (futures/stocks/forex/crypto) with an optional paid "Order Flow Edition."
- **Data shown (Order Flow Edition)**: Footprint/volume-imprint charts (bid/ask volume, delta at price), Cumulative Delta (CVD), absorption signals, liquidity heatmap, Market Profile/TPO, DOM.
- **Crypto/Bybit support**: Crypto instruments can be charted if connected to a compatible broker/data feed; Bybit-specific integration not confirmed — likely depends on third-party data feed configuration.
- **Pricing**: Community Edition free (no footprint/order flow); Order Flow Edition $49/month or $595 lifetime; data feed/broker costs separate.
- **Platform**: Desktop (Java-based, cross-platform).
- **Open source**: No (but a third-party add-on ecosystem exists, e.g. WyckFlow order-flow studies for MotiveWave Community Edition).
- Sources: [MotiveWave Order Flow / Volume Analysis Guide](https://docs.motivewave.com/user-guide/volume-order-flow-analysis-guide), [WyckFlow — footprint in Community Edition](https://wyckflow.com/blog/motivewave/footprint-order-flow-motivewave-community-edition), [ITQlick pricing](https://www.itqlick.com/motivewave/pricing)

**Not independently researched this pass**: "Orderflow-tools" as a named product/vendor was not identified as a distinct platform in search results — it's likely a generic search term rather than a specific product; flagged as an open question.

---

## 4.5 "Orderflow-tools" — resolving the original brief's unnamed product *(resolved this pass — was open question #3)*

The original brief's "orderflow-tools" reference did not resolve to one single, uniquely-named commercial product or GitHub repo even after a targeted search pass (queries: "OrderFlow Tools indicator NinjaTrader crypto", "orderflow-tools.com", "OrderFlowTools GitHub footprint indicator"). What the searches turned up instead is that **"order flow tools" is used generically across the industry** as a category label, plus several concretely-named products that plausibly are what was meant:

- **NinjaTrader's own "Order Flow+" add-on suite** — native footprint/volumetric bars, cumulative delta, market depth map, volume profile. See [NinjaTrader Order Flow Trading](https://ninjatrader.com/trading-platform/free-trading-charts/order-flow-trading/).
- **TradeDevils "Orderflow Footprint Trader"** — a well-documented third-party NinjaTrader footprint indicator (imbalances, exhaustion, delta, alerts, themes/templates). See [TradeDevils product page](https://tradedevils-indicators.com/products/orderflow-footprint-trader) and [docs](https://tradedevils-indicators.com/pages/footprint-orderflow-indicator-ninjatrader-docs).
- **NT8-OrderFlow kit** — a community/open-source NinjaTrader 8 order-flow toolkit distributed via the NinjaTrader Ecosystem marketplace. See [ninjatraderecosystem.com listing](https://ninjatraderecosystem.com/user-app-share-download/nt8-orderflow/).
- **TradingView community scripts** — e.g. "Order Flow Footprint Real-time" by Investor_R and "Ninja Trader - Order Flow Smart Footprint," both Pine Script footprint/CVD approximations usable on any TradingView-supported symbol including crypto.
- No dedicated site at `orderflow-tools.com` or a uniquely-branded "OrderFlowTools" GitHub project was found; the domain/name does not appear to resolve to an active, identifiable product as of this pass.
- **Verdict**: treat "orderflow-tools" as a generic category term rather than a single vendor. All of the concrete NinjaTrader-ecosystem tools above are **futures-market-oriented** (best data quality on CME-listed crypto futures, not spot/Bybit derivatives) — of interest only as UI/indicator-design references, not as viable Bybit-connected products.
- Sources: [NinjaTrader Order Flow Trading](https://ninjatrader.com/trading-platform/free-trading-charts/order-flow-trading/), [NinjaTrader footprint blog](https://ninjatrader.com/futures/blogs/ninjatrader-order-flow/), [TradeDevils docs](https://tradedevils-indicators.com/pages/footprint-orderflow-indicator-ninjatrader-docs), [TradeDevils product](https://tradedevils-indicators.com/products/orderflow-footprint-trader), [NT8-OrderFlow kit](https://ninjatraderecosystem.com/user-app-share-download/nt8-orderflow/), [TradingView – Order Flow Footprint Real-time](https://www.tradingview.com/script/e9xulnEZ-Order-Flow-Footprint-Real-time/), [TradingView – Order Flow Smart Footprint](https://www.tradingview.com/script/BrNW3Fku-Ninja-Trader-Order-Flow-Smart-Footprint/)

## 4.6 Bybit's own V5 API surface — derivatives-sentiment data CandleViewer can source natively *(resolved this pass — was open question #9)*

Rather than building its own liquidation-cluster estimation, funding-history store, or long/short-ratio tracker from scratch, CandleViewer can source the following directly from Bybit's public (no-auth) V5 REST API — foundational for deciding what to build vs. what Bybit already exposes:

| Data | Endpoint | Granularity / depth notes |
|---|---|---|
| **Open interest history** | `GET /v5/market/open-interest` | Params: `category` (linear/inverse), `symbol`, `intervalTime` (`5min`, `15min`, `30min`, `1h`, `4h`, `1d`), `startTime`/`endTime`, `limit`, `cursor` for pagination. Public, no API key required. |
| **Long/short (account) ratio** | `GET /v5/market/account-ratio` | Params: `category`, `symbol`, `period` (`5min`…`1d`), `limit`. Returns per-period long-account-ratio / short-account-ratio time series (accounts holding long vs. short positions). Public, no API key required. |
| **Funding rate history** | `GET /v5/market/funding/history` | `limit` capped at **200 records per request** — deeper history requires pagination via `startTime`/`endTime` timestamp windows across multiple calls, not a single deep-history call. |

**Implication for CandleViewer**: All three of the "derivatives-sentiment panel" data types flagged as a comparison-matrix idea (open interest, funding rate, long/short ratio — see §8 item 2) are natively available from Bybit with no third-party aggregator needed, at time-bucketed granularities down to 5 minutes. This substantially de-risks that feature: it is primarily a fetch/store/chart problem, not a data-acquisition problem. The main engineering task Bybit's API does *not* solve is the **funding-history pagination** (200-record cap per call) and building **local historical retention** beyond whatever window Bybit itself keeps live-queryable (exact server-side retention window not confirmed in this pass — recommend a direct empirical check by querying far-back timestamps against the live endpoint).
- Sources: [Bybit V5 API — Get Open Interest](https://bybit-exchange.github.io/docs/v5/market/open-interest), [Bybit V5 API — Get Long Short Ratio](https://bybit-exchange.github.io/docs/v5/market/long-short-ratio), [Bybit V5 API — Get Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/funding-history), [Bybit API docs index](https://bybit-exchange.github.io/docs/v5/intro), [DeepWiki — bybit-exchange/docs REST Market Data APIs](https://deepwiki.com/bybit-exchange/docs/5.1-rest-market-data-apis)

---

## 5. On-chain analytics (brief, likely out of scope)

Per the research brief, on-chain analytics (CryptoQuant, Glassnode) are **noted briefly** as they fall outside CandleViewer's crypto-derivatives/order-flow scope but could be a future low-priority integration (e.g., exchange netflow as a sentiment overlay).

- **CryptoQuant**: Exchange flows, miner activity, whale tracking, market indicators; free tier + paid tiers from $29/mo (Advanced) up to $799/mo (Premium); enterprise custom pricing; alerts via email/Telegram/browser; API + CSV export.
- **Glassnode**: 1,700+ on-chain metrics across 1,500+ assets, up to 15+ years history; holder/supply metrics, entity-level analysis, MVRV; Advanced tier $49/mo, Professional/Vector custom-priced (Vector from $749/mo) for market-cycle/risk-modeling tools; REST + bulk API, Excel plugin.
- **Verdict**: Both are **spot/on-chain** focused, not order-flow/derivatives-microstructure tools, and neither is Bybit-specific. Low priority for CandleViewer; could be a "phase 3" data-source integration at most.
- Sources: [CryptoQuant Pricing](https://cryptoquant.com/pricing), [cryptoquant.com](https://cryptoquant.com/), [Glassnode Studio Pricing](https://studio.glassnode.com/pricing), [glassnode.com](https://glassnode.com/), [Glassnode data products](https://glassnode.com/products/data), [SourceForge comparison](https://sourceforge.net/software/compare/CryptoQuant-vs-Glassnode/)

## 6. Open-source projects to learn from or reuse

### 6.1 Multi-exchange trade aggregation

| Project | What it does | License note | Relevance |
|---|---|---|---|
| [Tucsky/aggr](https://github.com/Tucsky/aggr) | Vue.js front end for live aggregated multi-exchange trades (incl. Bybit), liquidation viz, rolling sums, filters | Verify license (GPL-family) before vendoring code | **High** — closest existing analog to a "speed of tape"/aggregated-trades pane |
| [Tucsky/aggr-server](https://github.com/Tucsky/aggr-server) | Node.js backend: ingests exchange WS feeds, resamples, persists to files/InfluxDB | Same | **High** — template for CandleViewer's own multi-exchange ingestion service (even though CandleViewer is Bybit-only for trading, the ingestion pattern generalizes) |
| [Tucsky/aggr-lib](https://github.com/Tucsky/aggr-lib) | Community scripts/indicators/panes/workspaces for aggr | Same | Medium — mine for indicator ideas (e.g. custom CVD panes) |

### 6.2 Footprint / order-flow chart implementations

| Project | What it does | Stack | Relevance |
|---|---|---|---|
| [endegenaassefa/footprint_analyzer](https://github.com/endegenaassefa/footprint_analyzer) | Generates footprint charts from tick data; configurable aggregation (time/tick/volume/range); computes POC, Delta, Value Area | Python | **High** — a ready reference for the footprint aggregation math (POC/VA calculations) CandleViewer's backend will need |
| [mahmoud20138/OrderFlow-Analysis-Pro](https://github.com/mahmoud20138/OrderFlow-Analysis-Pro) | Footprint/order-flow chart + delta analytics + volume profile; **explicitly supports Bybit and MT5 feeds**; Dash-based dashboard | Python + Dash | **High** — direct Bybit precedent, worth reading the exchange-adapter code even if the UI stack (Dash) isn't reused |
| [tyumex/tyumex-trading-terminal](https://github.com/tyumex/tyumex-trading-terminal) | Windows multi-chart terminal with footprint/cluster charts, second-based candles, bar replay | Desktop (Windows) | Medium — reference for bar-replay/backtester UX patterns (relevant to DeepCharts' "tick replay/backtester" feature) |
| GitHub topic pages | Browse for more/newer projects | — | [github.com/topics/footprint-charts](https://github.com/topics/footprint-charts), [github.com/topics/footprint-chart](https://github.com/topics/footprint-chart) |

### 6.3 Charting libraries (candlestick + custom series/plugins)

| Project | What it does | License | Relevance |
|---|---|---|---|
| [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts) | TradingView's official open-source lightweight charting library; supports custom series/primitives (v4/v5 plugin API) for building footprint/volume-profile/delta overlays from scratch | Apache-2.0 | **High** — the most credible foundation for CandleViewer's own React chart component, given it's TradingView's own OSS lib and thus closest to matching TradingView's look/feel/perf |
| [safaritrader/lightweight-chart-plugin](https://github.com/safaritrader/lightweight-chart-plugin) | Plugin/extension for Lightweight Charts adding volume-profile overlays, custom drawing tools, tooltips | MIT | Medium — example of building a plugin on top of lightweight-charts' primitive API; useful template even if not vendored directly |
| [klinecharts/KLineChart](https://github.com/klinecharts/KLineChart) | Zero-dependency, ~40–50KB gzip, TypeScript candlestick charting library; dozens of built-in indicators (MA/EMA/SMA/DMA, MACD, RSI, BOLL, KDJ, WR, CCI, PSY, AO, TRIX, VOL, OBV, CR, MTM, VR, ROC, DMI, SAR, BIAS, BRAR, BBI, EMV, AVP, PVT); custom-indicator registration API; mobile/touch support; 15+ built-in drawing tools | MIT (verify per repo) | **High** — a strong alternative/complement to lightweight-charts, particularly if CandleViewer wants a larger built-in indicator library out of the box rather than writing every indicator from scratch |

Sources for this subsection: [klinecharts.com](https://klinecharts.com/en-US/), [KLineChart indicator guide](https://klinecharts.com/en-US/guide/indicator.html), [KLineChart DeepWiki indicators](https://deepwiki.com/klinecharts/KLineChart/4.1-indicators), [Lightweight Charts homepage](https://www.tradingview.com/lightweight-charts/)

### 6.4 Exchange abstraction, paper trading, and backtesting frameworks

| Project | Paper trading | Exchange abstraction | Live trading | Best for | License |
|---|---|---|---|---|---|
| **Freqtrade** | "Dry-run" mode simulating fills against real market data | Built on **CCXT** — broad, easily swappable multi-exchange support | Yes, broad market coverage | Flexible research + hands-off algo trading; large active community, web dashboard | GPL-3.0 |
| **Hummingbot** | Simulation mode mimicking order books, focused on market-making/liquidity strategies | **Custom native connectors** (not CCXT) for low-latency CEX/DEX execution (incl. Uniswap-style DEXes) | Yes, CEX/DEX, low-latency | Market-making, arbitrage, liquidity provision; CLI/YAML-driven | Apache-2.0 |
| **Jesse** | Spot-focused paper trading tightly coupled to its backtesting engine | Custom abstraction, narrower exchange list (historically Binance-centric) | Spot/futures, fewer exchanges | Best-in-class backtesting/strategy R&D rather than broad live multi-exchange trading | Custom/AGPL (verify) |

- **Relevance to CandleViewer**: Freqtrade's CCXT-based abstraction is the most directly reusable *pattern* (even though CandleViewer is Bybit-first, designing the exchange interface the way Freqtrade/CCXT do — a common `Exchange` interface with per-venue adapters — is exactly the "architecture must allow more crypto exchanges later" requirement). Jesse's dry-run/backtest engine design is worth studying for the "paper trading" and "tick replay/backtester" requirements specifically. Hummingbot's low-latency custom-connector approach is relevant if CandleViewer ever needs true market-making-grade latency (unlikely for this project's scope, but worth noting as the alternative to CCXT).
- Sources: [Freqtrade vs Hummingbot – InvestingRobots](https://investingrobots.com/freqtrade-vs-hummingbot/), [Freqtrade vs Jesse – The Forex Geek](https://theforexgeek.com/freqtrade-vs-jesse-trade/), [Python paper-trading frameworks gist](https://gist.github.com/rmbell09-lang/01281551ac4672bd5d1a42bb58575144)
- **Note**: license terms above should be verified directly against each project's repo (`freqtrade/freqtrade`, `hummingbot/hummingbot`, `jesse-ai/jesse`) before any code reuse, since GPL/AGPL terms have copyleft implications for a derived private tool (less of a concern here since CandleViewer is not being redistributed, but still worth confirming).

### 6.5 Nautilus Trader (Bybit adapter, event-driven backtest w/ L2)

- **What it is**: Production-grade, Rust-native, event-driven algorithmic trading platform with "research-to-live parity" (i.e., the same strategy code runs in backtest and live).
- **Bybit adapter**: `nautilus-bybit` Rust crate; supports L2 order-book depth backtesting using Bybit's public "ob500" archives (up to 500 levels of order-book deltas per instrument, distributed as dated ZIP files).
- **Backtest workflow**: Download ob500 archive → parse to DataFrame → convert rows to `OrderBookDelta` objects via `deltas_from_frame` (preserving event/snapshot boundaries) → replay through a `BacktestNode` against a strategy (official example: an "OrderBookImbalance" FOK-order demo strategy).
- **Architecture takeaway**: The core engine + adapters are Rust (for performance/determinism); Python bindings expose strategy scripting. This Rust-core/Python-bindings split is a credible reference architecture if CandleViewer's tick-replay/backtester component needs to process large L2 archives efficiently while keeping strategy code accessible in Python.
- **Open source**: Yes (`nautechsystems/nautilus_trader` on GitHub).
- **Relevance**: **High** for the "tick replay/backtester" requirement specifically — this is the most rigorous, genuinely event-driven, L2-aware open-source backtesting engine found in this research with confirmed Bybit L2 support.
- Sources: [NautilusTrader – Backtest with Order Book Depth Data (Bybit)](https://nautilustrader.io/docs/nightly/tutorials/backtest_orderbook_bybit/), [nautechsystems/nautilus_trader tutorial assets](https://github.com/nautechsystems/nautilus_trader/tree/develop/docs/tutorials/assets/backtest_orderbook_bybit), [Order Book Data docs](https://nautilustrader.io/docs/latest/tutorials/orderbook_data/), [nautilus-bybit crate docs](https://docs.rs/nautilus-bybit), [nautilus-backtest crate docs](https://docs.rs/nautilus-backtest)

## 7. Comparison matrix

Legend: ✅ = confirmed, ◐ = partial/unconfirmed, ❌ = not present/not found, — = not applicable.

| Platform | Footprint | Heatmap (book) | Liquidation heatmap | CVD | OI | Funding | Long/short ratio | Whale trades | Multi-exch. agg. | Options flow | Bybit native | Pricing (entry) | Platform | Open source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Exocharts | ✅ | ◐ | ❌ | ◐ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | $49/mo | Web/Desktop | ❌ |
| TensorCharts | ✅ | ✅ | ✅ | ✅ | ◐ | ❌ | ❌ | ◐ | ✅ | ❌ | ◐ | Free–$18/mo | Web | ❌ |
| Bookmap (crypto) | ❌ | ✅ | ◐ | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ (Multibook) | ❌ | ✅ | Free–$19/mo | Desktop | ❌ |
| ATAS (crypto) | ✅ | ✅ | ◐ | ✅ | ◐ | ❌ | ❌ | ◐ | ❌ | ◐(beta) | ✅ native | Free–€69.95/mo | Desktop | ❌ |
| Quantower | ✅ | ✅ | ❌ | ✅ | ◐ | ❌ | ❌ | ✅ (Power Trades) | ❌ | ❌ | ✅ native, **free w/ Bybit** | Free (Bybit)–$70/mo | Desktop | ❌ |
| Hyblock Capital | ❌ | ◐ | ✅ | ✅ | ✅ | ◐ | ✅ | ◐ | ✅ | ❌ | ✅ | Free–paid | Web/TV/API | ❌ |
| Coinglass | ❌ | ◐ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | Free–$699+/mo (API) | Web/API | ❌ |
| Coinalyze | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | Free | Web/API | ❌ (free API) |
| Velo Data | ❌ | ◐ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | Free–$199/mo | Web/API | ❌ |
| Laevitas | ❌ | ◐ | ❌ | ❌ | ✅ | ✅ | ❌ | ◐ (block trades) | ✅ | ✅ (deep) | ✅ | Free–custom | Web/API | ◐ (data-model repos) |
| TRDR.io | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | Free–€59.95/mo | Web | ❌ |
| Tealstreet | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Free | Web + OSS CLI | ◐ (CLI only) |
| Insilico Terminal | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Free | PWA | ❌ |
| Sierra Chart (crypto) | ✅ (Numbers Bars) | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ confirmed not native | Tiered subscription | Desktop | ❌ |
| Jigsaw Daytradr | ❌ (tape-based) | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ✅ (Auction Vista) | ❌ | ❌ | ❌ (futures-only) | Add-on pricing n/a | Desktop | ❌ |
| MotiveWave | ✅ | ✅ (liquidity heatmap) | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ unconfirmed | Free–$49/mo | Desktop | ❌ |
| aggr.trade (OSS) | ❌ | ❌ | ◐ (liquidation events) | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ | ❌ | ✅ | Free (OSS) | Web (self-host) | ✅ |
| Kingfisher | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ◐ (aggregated, no execution) | $72–$100/mo (+PAYG/API) | Telegram/Web | ❌ |

Note: DeepCharts already covers footprint/Deep Print, Deep Profile, Deep Stats, Big Trades, imbalance tracker, speed of tape, VWAPs, DeepDOM liquidity heatmap, liquidity tracker, stopruns, iceberg detector, market regime, tick replay/backtester — the matrix above is oriented around confirming which competitors match or exceed those, plus the extra categories (liquidation heatmap, funding, long/short ratio, options flow, on-chain) DeepCharts/TradingView do not natively provide.

---

## 8. Ranked list: features worth borrowing

Ranked roughly by (a) value to CandleViewer's stated scope (crypto/Bybit order-flow + trading), (b) feasibility of implementation, and (c) how clearly it's demonstrated as missing from DeepCharts/TradingView.

1. **Liquidation heatmap (Hyblock/Coinglass/Kingfisher/TensorCharts style)** — Not part of DeepCharts' feature set at all, yet extremely popular among crypto derivatives traders and Bybit publishes the raw liquidation/OI data needed to approximate this. High value, moderate effort (needs cross-position-size estimation model, not just raw liquidation prints).
2. **Funding rate + OI + long/short ratio dashboard (Coinglass/Coinalyze/TRDR style)** — Bybit's API natively exposes funding rate, OI, and (to some extent) global long/short account ratio; this is low-effort, high-value, and squarely inside DeepCharts' gap (DeepCharts is order-flow-only, not derivatives-sentiment-focused).
3. **Free/native Bybit-first monetization pattern (Quantower)** — Not a chart feature, but a validated product-strategy insight: Quantower made all premium order-flow tools free specifically for Bybit-linked accounts, confirming Bybit users are a large, engaged, commercially significant segment — useful context even though CandleViewer is not monetized.
4. **Reconstructed Tape (Jigsaw Daytradr)** — Reassembling fragmented trade prints into true original order sizes is directly relevant to CandleViewer's "iceberg detector" and "Big Trades" requirements; Bybit's public trade stream would need similar reconstruction logic since large orders are frequently sliced by execution algos.
5. **DOM Surface / 3D order-book visualization + Power Trades (Quantower)** — A more advanced visual alternative/complement to a flat DOM ladder; worth prototyping as an option alongside DeepDOM-style heatmap.
6. **Options flow / IV surface / skew (Laevitas, Velo Data)** — DeepCharts has no options coverage; if CandleViewer ever extends beyond Bybit perps into Bybit options, Laevitas' data model (chain view, Greeks, term structure) is the best available reference.
7. **Nautilus Trader's Rust-core / Python-bindings event-driven backtest engine w/ Bybit L2 replay** — Directly informs the "tick replay/backtester" requirement; the ob500 L2 delta replay pattern is the most rigorous available open reference implementation with confirmed Bybit support.
8. **Freqtrade's CCXT-based exchange abstraction pattern** — Directly informs "architecture must allow more crypto exchanges later"; even building Bybit-only initially, adopting a Freqtrade/CCXT-style `Exchange` interface early avoids costly rework.
9. **aggr.trade's WS-ingest → resample → reactive multi-exchange trade tape pipeline** — A proven, open-source, lightweight architecture for the "speed of tape"/aggregated-trades feature, directly reusable as a design template (and partially as code, license permitting).
10. **KLineChart's built-in indicator library breadth** — Faster path to a broad indicator set (MA family, oscillators, volume-based, DMI/SAR/etc.) than writing every indicator bespoke; worth evaluating as an alternative/companion to TradingView's own lightweight-charts for the base candlestick chart.
11. **Footprint POC/Delta/Value-Area calculation reference (footprint_analyzer, OrderFlow-Analysis-Pro)** — Concrete, readable open-source math for the footprint aggregation logic (time/tick/volume/range bucketing) CandleViewer's footprint/Deep Print equivalent will need; OrderFlow-Analysis-Pro is notable for already targeting Bybit specifically.
12. **Tealstreet's serverless/API-keys-never-leave-device execution model** — Relevant security pattern for CandleViewer's own credential handling, especially since it's self-hosted for one user + a few account managers (reduces attack surface vs. server-side key custody).
13. **Insilico Terminal / Jigsaw execution algorithms (TWAP, Limit Chase, Scale, Swarm)** — Useful vocabulary/spec for CandleViewer's "custom rule-based stops/exits" and "fast/customised order controls" requirement — these are concrete, well-understood execution-algo patterns to implement rather than inventing new ones.
14. **Pace of Tape / gauge-style speed-of-tape widget (Jigsaw)** — A specific UI pattern (gauge visualization vs. a simple rolling-average number) worth considering for DeepCharts' "speed of tape" equivalent.
15. **Kingfisher's Telegram-native distribution model** — Lower priority (CandleViewer is not a public/distributed product), but the idea of piping alerts (liquidation clusters, stop-run zones) to Telegram is a cheap, useful notification channel for a single-user self-hosted tool.

## 9. Architecture implications for CandleViewer

- **Charting core**: Prefer building on `tradingview/lightweight-charts` (Apache-2.0, matches DeepCharts/TradingView visual conventions most closely, has a custom-series/primitive plugin API for footprint/volume-profile overlays) as the primary chart layer; evaluate `KLineChart` as a fallback/companion if a broader out-of-the-box indicator library is prioritized over exact TradingView look-and-feel.
- **Exchange abstraction**: Design a Freqtrade/CCXT-style `Exchange` interface (REST + WS methods abstracted per venue) from day one even though only Bybit is implemented initially — this directly satisfies "architecture must allow more crypto exchanges later" at near-zero extra cost now.
- **Data ingestion**: Follow the `aggr`/`aggr-server` pattern — a backend service ingesting Bybit WS feeds (trades, order book deltas, liquidations), normalizing/resampling, and persisting to a time-series-friendly store, decoupled from the React frontend which subscribes to a normalized internal WS/SSE stream.
- **Footprint/order-flow math**: Reference `footprint_analyzer` and `OrderFlow-Analysis-Pro` for POC/Delta/Value-Area bucketing logic (time/tick/volume/range aggregation modes) rather than deriving from scratch.
- **Backtesting/tick replay**: Reference NautilusTrader's Bybit L2 (`ob500`) event-driven replay architecture (Rust core, Python strategy bindings) as the gold-standard pattern for CandleViewer's "tick replay/backtester" requirement — even if CandleViewer doesn't adopt Rust, the conceptual event/`OrderBookDelta` model and research-to-live parity principle should carry over.
- **Derivatives-sentiment panel (new vs. DeepCharts)**: Add a funding-rate/OI/long-short-ratio/liquidation-heatmap panel sourced directly from Bybit's own API (funding history, OI, liquidation feed) — this is a category DeepCharts does not cover and is low-effort given Bybit already exposes the needed endpoints.
- **Iceberg/large-order detection**: Implement Jigsaw's "Reconstructed Tape" concept — group rapid, same-price, same-side prints into inferred parent orders — to power both the "Big Trades" and "iceberg detector" DeepCharts-parity requirements.
- **Execution algos**: Implement TWAP, Scale, and a "chaser"/Limit-Chase order type as concrete building blocks for "custom rule-based stops/exits" and "fast/customised order controls," following the vocabulary established by Insilico Terminal / Jigsaw / Quantower.
- **Security model**: Store Bybit API keys client-side or in a locally-scoped secrets store rather than a shared server-side credential store, following Tealstreet's self-custody design principle — appropriate given the single-user/few-account-managers deployment model.
- **Options flow (future/optional)**: If Bybit options are ever added to CandleViewer's scope, Laevitas' data model (chain view + Greeks + IV surface + skew + strategy builder) is the best available open reference for feature/data shape, even though Laevitas itself is not open source.

## Sources

### Exocharts
- https://exocharts.com/
- https://help.exocharts.com/hc/en-us/articles/4406161671697-Preface
- https://captain-trading.com/en/free-trading-course/exocharts-order-flow-guide
- https://cosmiccrypto.club/tools/trading-tools/exocharts

### TensorCharts
- https://www.softwaresuggest.com/tensorcharts/pricing
- https://www.softwaresuggest.com/tensorcharts
- https://www.altcointrading.net/tensorcharts/
- https://docs.tensorcharts.com/docs/trades_heatmap/

### Bookmap
- https://madeonsol.com/compare/bookmap-vs-bybit
- https://proptradingvibes.com/blog/bookmap-review
- https://bullishbears.com/bookmap-review/
- https://nexusfi.com/showthread.php?t=60741
- https://nexusfi.com/showthread.php?t=57592
- https://dxfeed.com/data-services/market-replay/

### ATAS
- https://atas-bjt.com/atas-data-feeds
- https://www.magic-clusters.com/en/atas/
- https://traderprofesional.com/en/atas-pricing/
- https://atas.net/pricing/
- https://help.atas.net/en/support/solutions/articles/72000602529-connecting-to-bybit
- https://atas.net/modules/market-replay/
- https://help.atas.net/en/support/solutions/articles/72000602247-replay-trading-simulator-
- https://start.atas.net/step-5.-connect-your-account/crypto/bybit
- https://help.atas.net/en/support/solutions/articles/72000645557-faq-frequent-errors-and-their-solution
- https://www.bybit.com/en/help-center/article/Difference-Between-Position-Modes-One-Way-Mode-and-Hedge-Mode

### Quantower
- https://help.quantower.com/quantower/connections/connection-to-bybit
- https://damnpropfirms.com/trading-guides/quantower-review-2026-order-flow-platform/
- https://help.quantower.in/analytics-panels/order-flow-surface
- https://www.quantower.com/blog/bybit-connection-now-gains-all-quantower-premium-features-free
- https://www.quantower.com/pricing
- https://proptradingvibes.com/blog/quantower-review
- https://help.quantower.com/quantower/quantower-algo/downloading-history
- https://help.quantower.in/trading-panels/history-player
- https://dxfeed.com/dxfeed-has-expanded-historical-market-data-depth-for-quantower-retail-users/
- https://www.daytrading.com/software/quantower

### Hyblock Capital
- https://academy.hyblockcapital.com/tools/liquidation-levels-1
- https://docs.hyblockcapital.com/liquidation-heatmap
- https://hyblockcapital.com/blog/momentum-insights-liquidation-levels-and-open-interest-cluster-analysis
- https://hyblockcapital.com/
- https://hyblockcapital.com/pricing
- https://hyblockcapital.com/api

### Coinglass
- https://blockchainreporter.net/what-is-coinglass-crypto-liquidation-data-explained/
- https://news.dextools.io/article/how-to-use-coinglass-liquidations-funding-open-interest-tutorial-2026
- https://www.binance.com/en-IN/square/post/344617706627649
- https://www.coinglass.com/CryptoApi
- https://cryptorank.io/news/feed/bf393-what-is-coinglass-crypto-liquidation-data-explained
- https://docs.coinglass.com/reference/getting-started-with-your-api
- https://www.coinglass.com/pricing

### Coinalyze
- https://captain-trading.com/en/free-trading-course/coinalyze-guide
- https://getmarkethub.com/tools/coinalyze.html
- https://web3connect.com/product/cryptocurrency-derivatives-market-analytics-coinalyze
- https://api.coinalyze.net/v1/doc/
- https://dlthub.com/context/source/coinalyze

### Velo Data
- https://docs.velo.xyz/api
- https://captain-trading.com/en/free-trading-course/velo-data

### TRDR.io
- https://trdr.io/pricing
- https://docs.trdr.io/key-features-and-indicators/faq
- https://docs.trdr.io/getting-started/why-trdr
- https://docs.trdr.io/

### Tealstreet
- https://finestel.com/blog/tealstreet-review/
- https://www.tealstreet.io/
- https://www.tealstreet.io/integrations/bybit
- https://github.com/Tealstreet/cli
- https://github.com/Tealstreet

### Insilico Terminal
- https://www.insilicoterminal.com/
- https://finestel.com/blog/insilico-terminal-review/
- https://perps.ai/projects/insilico-terminal
- https://docs.insilicoterminal.com/documentation/welcome/terminal-5.0
- https://coincodecap.com/insilico-terminal-review

### Kingfisher
- https://docs.thekingfisher.io/products/liquidations-maps
- https://thekingfisher.io/
- https://docs.thekingfisher.io/products/kf-liquidations-heatmap
- https://telegram.me/s/thekingfisher_btc
- https://t.me/s/thekingfisher_btc/1118
- https://telegram.me/thekingfisher_btc_chat
- https://docs.thekingfisher.io/
- https://thekingfisher.io/bitcoin-liquidations-heatmap
- https://www.coinglass.com/pro/futures/LiquidationHeatMap (for Kingfisher-vs-Coinglass comparison)
- https://www.coinglass.com/pro/futures/LiquidationMap (for Kingfisher-vs-Coinglass comparison)

### Laevitas
- https://finestel.com/blog/laevitas-review/
- https://www.cosmiccrypto.club/tools/trading-tools/laevitas
- https://saasbrowser.com/en/saas/30912/laevitas
- https://github.com/laevitas (corrected: previously cited as `Laevitas-Crypto-Analytics`, which did not resolve to a live org)
- https://github.com/0xReisearch/laevitas-mcp

### Sierra Chart
- https://www.sierrachart.com/index.php?page=doc/CryptocurrencyDataServices.php
- https://sierachart.com/blogs/news/sierra-chart-footprint-setup
- https://optimusfutures.com/blog/setting-numbers-bars-sierra-chart/
- https://tradergav.com/sierra-chart-sharing-number-bar-footprint-chart/
- https://sierachart.com/collections/footprint-charts-templates
- https://www.sierrachart.com/SupportBoard.php?ThreadID=50493

### "Orderflow-tools" (resolved as generic category term)
- https://ninjatrader.com/trading-platform/free-trading-charts/order-flow-trading/
- https://ninjatrader.com/futures/blogs/ninjatrader-order-flow/
- https://tradedevils-indicators.com/pages/footprint-orderflow-indicator-ninjatrader-docs
- https://tradedevils-indicators.com/products/orderflow-footprint-trader
- https://ninjatraderecosystem.com/user-app-share-download/nt8-orderflow/
- https://www.tradingview.com/script/e9xulnEZ-Order-Flow-Footprint-Real-time/
- https://www.tradingview.com/script/BrNW3Fku-Ninja-Trader-Order-Flow-Smart-Footprint/

### Bybit V5 API (open interest, long/short ratio, funding history)
- https://bybit-exchange.github.io/docs/v5/market/open-interest
- https://bybit-exchange.github.io/docs/v5/market/long-short-ratio
- https://bybit-exchange.github.io/docs/v5/market/funding-history
- https://bybit-exchange.github.io/docs/v5/intro
- https://deepwiki.com/bybit-exchange/docs/5.1-rest-market-data-apis
- https://deepwiki.com/bybit-exchange/skills/4-market-data

### Jigsaw Daytradr
- https://edgeclear.com/trading/jigsaw-daytradr/
- https://gffbrokers.com/platforms/jigsaw-daytradr
- https://www.discounttrading.com/jigsaw.html
- https://top30forexbrokers.com/product/jigsaw-trading-review/
- https://www.jigsawtrading.com/daytradr-professional-order-flow-platform/
- https://nexusfi.com/a/platforms/jigsaw-daytradr

### MotiveWave
- https://www.itqlick.com/motivewave/pricing
- https://wyckflow.com/blog/motivewave/footprint-order-flow-motivewave-community-edition
- https://wyckflow.com/
- https://docs.motivewave.com/user-guide/volume-order-flow-analysis-guide
- https://www.techjockey.com/detail/motivewave

### CryptoQuant / Glassnode (on-chain, brief)
- https://cryptoquant.com/pricing
- https://cryptoquant.com/
- https://sourceforge.net/software/compare/CryptoQuant-vs-Glassnode/
- https://slashdot.org/software/comparison/CryptoQuant-vs-Glassnode/
- https://glassnode.com/
- https://studio.glassnode.com/pricing
- https://glassnode.com/products/data
- https://www.spark.money/tools/bitcoin-onchain-analytics-comparison

### Open-source: aggr.trade / Tucsky
- https://github.com/Tucsky/aggr
- https://github.com/Tucsky/aggr/releases
- https://github.com/Tucsky/aggr-server
- https://github.com/Tucsky/aggr-lib

### Open-source: footprint/order-flow implementations
- https://github.com/endegenaassefa/footprint_analyzer
- https://github.com/topics/footprint-charts
- https://github.com/topics/footprint-chart
- https://github.com/mahmoud20138/OrderFlow-Analysis-Pro
- https://github.com/tyumex/tyumex-trading-terminal

### Open-source: charting libraries
- https://github.com/tradingview/lightweight-charts
- https://www.tradingview.com/lightweight-charts/
- https://github.com/safaritrader/lightweight-chart-plugin
- https://github.com/klinecharts/KLineChart
- https://klinecharts.com/en-US/
- https://klinecharts.com/en-US/guide/indicator.html
- https://deepwiki.com/klinecharts/KLineChart/4.1-indicators

### Open-source: exchange abstraction / paper trading frameworks
- https://investingrobots.com/freqtrade-vs-hummingbot/
- https://theforexgeek.com/freqtrade-vs-jesse-trade/
- https://gist.github.com/rmbell09-lang/01281551ac4672bd5d1a42bb58575144

### Open-source: Nautilus Trader (Bybit L2 backtesting)
- https://nautilustrader.io/docs/nightly/tutorials/backtest_orderbook_bybit/
- https://github.com/nautechsystems/nautilus_trader/tree/develop/docs/tutorials/assets/backtest_orderbook_bybit
- https://nautilustrader.io/docs/latest/tutorials/orderbook_data/
- https://docs.rs/nautilus-bybit
- https://docs.rs/nautilus-backtest

---

## Open questions

> Updated 2026-09-14 gap-filling pass: items 1, 2, 3, 8, 9 below were resolved (see §2.6, §4.1, §4.5, §2.5, §4.6 respectively) and are struck through with a pointer to the resolving section. Remaining items are still open.

1. ~~**Kingfisher pricing/plan structure**~~ — **Resolved**: see §2.6. Premium ≈$72/mo, Pro ≈$100/mo, pay-as-you-go credit sessions, custom API/business tier. (Note: the live `/pricing` page 404'd during this pass; figures are from secondary/cached sources and should be spot-checked before financial decisions.)
2. ~~**Sierra Chart + Bybit**~~ — **Resolved**: see §4.1. Bybit is **confirmed not** in Sierra Chart's native SC Data exchange list (Binance/Bitfinex/BitMEX/Deribit only); an open community support-board thread requesting Bybit integration exists with no confirmed native support added. Would need a third-party bridge or custom data import.
3. ~~**"Orderflow-tools"**~~ — **Resolved (as far as it can be)**: see §4.5. No single product by that exact name was found; the term is best treated as a generic category label. Closest concrete matches: NinjaTrader's native "Order Flow+", TradeDevils' "Orderflow Footprint Trader", the community "NT8-OrderFlow kit," and assorted TradingView Pine Script footprint indicators — all futures/NinjaTrader/TradingView-oriented, none Bybit-native.
4. **Jigsaw Daytradr and MotiveWave crypto/Bybit support**: neither could be confirmed to support Bybit specifically (Jigsaw appears futures-only via Rithmic/CQG/GAIN/IQFeed; MotiveWave's crypto support depends on third-party data feed/broker configuration not detailed in available sources) — both are included purely for feature-pattern inspiration, not as viable Bybit-connected tools. **Still unresolved** — not revisited in this pass.
5. **Exact license terms** for `Tucsky/aggr`, `Tucsky/aggr-server`, `Tealstreet/cli`, and `klinecharts/KLineChart` should be individually re-verified directly in each repository's `LICENSE` file before any code is vendored or adapted, since license family (MIT vs. GPL/AGPL) materially affects reuse terms even for a private/non-redistributed tool. **Still unresolved** — not revisited in this pass.
6. **Freqtrade/Jesse's precise current exchange support lists** should be re-checked against their live GitHub READMEs — the comparison sources used here (third-party blog/gist comparisons) may be stale on exact exchange counts. **Still unresolved** — not revisited in this pass.
7. **Whether any of TensorCharts, Bookmap, or MotiveWave have a confirmed, official, native Bybit *execution* connector** (vs. just data/visualization) was not conclusively established in every case — worth a direct product-page/docs check before assuming trading (not just charting) is possible with Bybit on these platforms. **Still unresolved** — not revisited in this pass; note ATAS's and Quantower's Bybit *execution* connectors were separately re-confirmed as genuinely native in this pass (see §1.4, §1.5), so this item now applies specifically to TensorCharts/Bookmap/MotiveWave.
8. ~~**Laevitas' GitHub org contents**~~ — **Resolved**: see §2.5. Correct org is `github.com/laevitas` (the previously-cited `Laevitas-Crypto-Analytics` org name did not resolve). Contents are mostly SDK/CLI/tooling repos (`laevitas-sdk`, crawler scripts, packaging utilities), not deep reusable data-model documentation.
9. ~~**Bybit's own public data completeness**~~ — **Resolved**: see §4.6. Confirmed public (no-auth) V5 endpoints exist for open interest history (`/v5/market/open-interest`), long/short account ratio (`/v5/market/account-ratio`), and funding rate history (`/v5/market/funding/history`, capped at 200 records/call, requiring pagination for deeper history). Bybit's exact server-side retention window (how far back these endpoints remain queryable) was **not** empirically verified in this pass and remains a genuinely open item — recommend a direct API probe with old timestamps before finalizing CandleViewer's own retention/backfill strategy.
10. **DOM/heatmap replay latency and tick-storage sizing were only partially resolved**: ATAS's one-day-per-session limit for true tick+DOM replay (§1.4) and Bookmap's local-recording-is-disk-limited model (§1.3) give qualitative evidence that full-fidelity L2 replay is data-volume-constrained even for mature commercial platforms, but no platform published a concrete "GB per day of L2 data" or "max DB size for N months of Bybit L2" figure. CandleViewer will need its own empirical sizing exercise (capture N days of real Bybit L2 diff-depth stream, measure raw/compressed size) rather than relying on a competitor-published number — none exists publicly.
11. **TensorCharts and Sierra Chart first-party pricing pages could not be directly fetched in this pass** (`tensorcharts.com/pricing` and `thekingfisher.io/pricing` both failed to load via automated fetch — 404 or tool error); the figures used for both remain sourced from secondary aggregator/cache pages (SoftwareSuggest, search-engine summaries) rather than a live first-party page render. Recommend a manual/browser check before relying on exact current numbers.
