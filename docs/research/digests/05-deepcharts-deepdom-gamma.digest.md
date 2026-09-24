# Digest: 05-deepcharts-deepdom-gamma.md

Crawl date 2026-09-13/14. DeepCharts = white-label front end on Volumetrica engine. 3 products: Deepchart (footprint/orderflow), DeepDOM (liquidity heatmap/DOM/MBO), DeepGamma (SPX GEX overlay, native to Deepchart).

## Company/structure
- deepcharts.com licenses Volumetrica (volumetricatrading.com) engine; "Deepchart"/"DeepDom" are Volumetrica's own product names too.
- MBP (aggregated depth/level) vs MBO (order-level, persistent IDs, via dxFeed/Rithmic) — MBO required for Iceberg/Stop-Run/"smart money" tools.
- DeepDOM: Windows-only desktop app, no web/Mac/Linux.

## Pricing
- DeepDom: $39/mo or $468/yr; terms 1mo/3mo/6mo/1yr/Lifetime Addon. Single bundle (no tiers).
- Included: Heatmap, Liquidity Tracker, Stopruns, Iceberg Detector, Market Regime, Deep Reload, MBO Indicators bundle, Backtester+Journal, Orderflow Mastery Course, VIP Discord.
- DeepGamma: "From $46/mo" for Cboe 1-min data + orderflow-chart integration + backtesting; "$250/mo"/"third-party only" rows likely competitor-comparison, unconfirmed as DeepCharts prices.

## 3. DeepDOM feature grid
### MBO features (require MBO feed)
- Iceberg Detector (onchart) — spots native iceberg loading to absorb aggressors — Bybit: heuristic proxy only, not true detection.
- Stoprun Detector (onchart) — spots stop-order sweep — Bybit: proxy via L2+trade tape "Liquidity Sweep Detector", promising.
- Stop/Iceberg Tracker (cumulative) — cumulative line, one line per activity type — MBO-only end to end per dedicated KB article.
- MBO Replay ("2 weeks and counting", in development) — replay w/ MBO data for backtesting.
- Big Passive Trade — filters/highlights biggest book orders order-by-order — MBO-only (order-by-order).

### DeepDom Indicators
- Deep Reload — detects book reloading w/ fresh directional liquidity — Bybit: fully feasible, no proxy caveat (MBP-compatible), high feasibility from L2 delta stream (~20ms push).
- Market Regime — clusters liquidity to assess volatility regime — Bybit: feasible as derived rolling dispersion/concentration metric; needs original design for output/visual.
- Deep Liquidity Scan — cumulative book thickness/variation, Bid/Ask/Delta — confirmed MBP-only (no order-count dependency) — fully feasible on Bybit incl. calc modes + Fresh Only filter.
- Deep Trades — Volume Bubbles filtered by size for "smart money" — feasibility not fully assessed (partial doc).
- Book Speed — tracks book change speed for calm/nervous regime — feasible: count L2 delta msgs/sec; full settings undocumented (article wouldn't render).
- Absorption — (marketing copy duplicate of Book Speed = confirmed ongoing copy-paste error on live site) — real distinct mechanic found in dedicated KB (4.6a): aggressive flow absorbed by passive liquidity without price moving — Bybit feasible except Max Orders Number (MBO-only) knob.

### Volume Indicators
- Deep Profile — volume profile (volume/delta/bid-ask), resettable/fixed/daily/weekly modes.
- CVD — cumulative delta of aggressive flow, histogram/line, customizable metric.
- VWAP and Envelopes — daily/weekly/custom developing VWAP w/ stddev bands.
- Classic Volume — volume-by-time, per tick/time/candle.
- DeepDelta — proprietary "Delta-Filtered Bars" isolating meaningful delta.

### General Features
- DOM Liquidity Heatmap — customizable color/intensity/contrast/MBO highlights/MM filters.
- Aggressive Orderflow Bubbles — customizable bubbles (2D/3D, grouping, size).
- Deep Replay (all current contracts) — tick-by-tick replay of every order, backtest+auto-track metrics.
- Volumetrica Bridge — shared feed bridge Deepchart+DeepDOM, no separate feed.
- Trading Terminal — OCO strategies, trade/manage orders on heatmap.
- Automatic Metrics Journal — auto-tracks SIM/prop/real/replay/backtest trades.
- 24-hour Backfill Data — up to 24h historical DOM preloaded on chart open.
- Classic Advanced DOM — traditional price-ladder DOM view.
- Times & Sales — legacy tape, every traded volume at time/price.
- Important Levels — daily highs/lows, VWAPs, POCs on-chart.
- Candlesticks — normal candlestick overlay on any timeframe atop heatmap.

### "Why DeepDom" marketing claims
- Easy on CPU/easy to use; Advanced Backtester; "0.01s Precision" (marketing) vs "0.015s refresh" (third-party review site cited elsewhere); Stop Run/Market Regime included by default vs competitors (implicit dig at Bookmap's paid add-on model for MBO features).

## 4. Per-feature detail

### 4.1 Heatmap (core)
- Colors: Red=highest liquidity, Orange=2nd, Yellow/White/Blue/Black=progressively thinner. Adaptive/relative scale (rescales when new large order appears).
- Buy/Sell color-coding: Green=Buy Limit(bid), Violet=Sell Limit(ask) per DeepCharts docs — CONTRADICTS Volumetrica's own VolBook Heatmap article (green=Sell Limit, red=Buy Limit) — unreconciled discrepancy (open question).
- Level 2 depth: Volumetrica states VolBook analyzes 1000+ book levels — far deeper than typical crypto exchange public WS feeds (Bybit tops out 50/200/500 levels by tier).
- Default view: opens w/ 1 hour of history (Volumetrica variant).

### 4.2 Advanced DOM / Chart DOM
- Columns (L-to-R): B.PS (Bid Pull/Stack), B (buy mgmt col), Bid, Ask, S (sell mgmt col), A.PS (Ask Pull/Stack).
- Order-type toggle: Automatic/Limit/Market/Conditional.
- Automatic mode click grammar: Right-click Bid→Buy Market; Right-click Ask→Sell Market; Left-click Bid below price→Buy Limit; Left-click Bid above price→Buy Stop; Left-click Ask above price→Sell Limit; Left-click Ask below price→Sell Stop.
- Order mgmt: drag=move, right-click=delete, double-click=modify qty.
- Pull/Stack cols: green=added, red=removed (Bid side); reversed logic on Ask side (A.PS).
- Trades cols: BT=vol sold at market (aggressor sell hit bid), AT=vol bought at market (aggressor buy lift ask). Offers columns = # discrete orders resting per level (MBO-only figure).
- Settings panel: Font size, Text format, Bid/Ask column colors, Pull Stack filter (average/none), Filled filter, B.T/A.T footprint columns (auto-reset on swing/manual), Last Filled, Order View, Price Scale, P/L Column, Markers, Column Order.

### 4.4 Iceberg Detector
- Bybit feasibility: true MBO-based detection impossible (no exchange exposes order-ID persistence publicly). Proxy: heuristic reload/replenishment detector tracking level depletion+refresh pattern — must be labeled heuristic, not "iceberg detector."

### 4.5 Stop Run Detector
- What: shows when large # of stop orders triggered, explaining sudden fast price moves.
- Signals: volume spike, fast price move (near-jump), quick reversal after, DOM levels emptying, large aggressive orders in Footprint.
- Settings: Minimum Tick (min move to flag), Maximum Ord Num (cap orders considered), Max MS (max time window for single event, e.g. 50ms→5ms tightens), Min. Stop Run Vol. (min qualifying volume). Plot: Ask/Bid Color, Marker Width. Text Settings undocumented.
- Bybit feasibility: true MBO stop-trigger visibility impossible (universal limitation, not Bybit-specific); externally observable signature (fast move+vol spike+book emptying+reversal) fully constructible from L2 WS + public trade WS + kline. Rename "Liquidity Sweep Detector" to avoid overclaiming. Strong roadmap candidate.

### 4.6 Market Regime
- "Analyses current clustering of liquidity to assess potential volatility regime." Related Book Speed metric shares description with Absorption (confirmed copy-paste error, not same feature).
- Bybit: feasible via rolling book depth dispersion/concentration or L2 msg rate; output format needs original design.

### 4.6a Absorption (dedicated KB article, verified)
- What: identifies price areas showing strong ability to absorb buy/sell orders (aggressive vol executes into level without moving price due to passive liquidity).
- Settings: Max Tick (price-tolerance window, e.g. 1 vs 15), Max Orders Number (MBO-only, caps orders counted/weights trader significance), Max MS (time window, e.g. 2050 vs 10), Min. Absorption Vol. (min qualifying volume, e.g. 20 vs 50). Plot: Display Mode (Text/Diamond/Square), Ask/Bid Color, Marker Width. Text Settings: Enable Text toggle (rest uncaptured).
- Bybit: Max Orders Number not replicable (MBO-only); core mechanic (trade tape vs L2 resting-size hold/refresh) fully constructible from publicTrade.{symbol} + orderbook.{depth}.{symbol} WS. Drop/approximate Max Orders Number.

### 4.6b Deep V-Tracker (Deepchart-side, not DeepDom)
- Separate "Absorption & Pressure" module under Deepchart product (distinct from DeepDom's Absorption indicator).

### 4.7 Deep Reload
- Detects book reloading with fresh directional liquidity supporting current move; suggested combined use w/ CVD + Deep Trades.
- Bybit: high feasibility — buildable from L2 orderbook delta stream (orderbook.{depth}.{symbol}, ~20ms push per Bybit docs), rolling aggregation near best bid/ask, configurable size threshold, optional trend filter from kline/VWAP.

### 4.8 Deep Liquidity Scan (aka Liquidity Tracker)
- Description: tracks cumulative level+variation in book thickness for Bid/Ask/Delta; best combined w/ Heatmap or DOM panel.
- Settings: Num Lev Depth (# levels from touch, e.g. 200=far, low=near-touch focus); Calc Mode = Exponential (weights near levels more, configurable falloff via Exp Half-Weight Lev) / Last (vs immediately preceding reading) / Peak (vs running-max baseline); Value Smooth (noise reduction); freshness filter All vs Fresh Only.
- Delta Settings: Delta Enable toggle — plots Bid-minus-Ask liquidity differential, described as one of most important readings.
- Bybit: fully feasible — sum of bid/ask sizes across N levels from L2 WS, no MBO dependency; Fresh Only reuses same freshness-tracking layer as Heatmap.

### 4.9 MBO-feature Bybit feasibility summary table
| Feature | MBO required? | True MBO on Bybit | Heuristic proxy on Bybit |
|---|---|---|---|
| Iceberg Detector | Yes | No | Yes (heuristic replenishment) |
| Stop Run Detector | Yes (marketing) but signature derivable from MBP | No | Yes (sweep+reversal detector) |
| Deep Reload | Not strictly | N/A | Yes, directly |
| Deep Liquidity Scan | No | N/A | Yes, directly, all calc modes+filter |
| Market Regime/Book Speed | No | N/A | Yes, as derived score |
| Absorption | Mostly no (Max Orders Number is) | No (for that setting) | Yes for core signal |

## 5. DeepGamma
- SPX/index-options-specific, real CBOE MM data, native overlay to Deepchart (not standalone app).
- Feature list: GEX Profile, Heatmap (gamma-specific), Gamma Bands, Gamma Profile, Deep Option Trades, Expected Move, Total Options Volume, Net Option Delta.
- Claims: "100% certain if market maker or not" via real CBOE MM data (SPX). SPY/QQQ use "proprietary formulas" (likely OPRA-based inference, non-CBOE-certain).
- Resolution: 1-min for SPX real-time. Backtest: replay up to 9 months orderflow+SPX option flow, "through November 2025" (fixed lookback, not rolling). Proprietary, no 3rd-party tools needed. Pricing "From $46/mo."
- Crypto-analog assessment (Deribit/Bybit options):
  - Options OI by strike/expiry: Deribit yes (public REST); Bybit yes (GET /v5/market/open-interest category=option; GET /v5/market/instruments-info; WS topic option.open_interest).
  - MM-tagged trade flow: no public equivalent on either Deribit or Bybit — cannot replicate DeepGamma's deterministic MM claim.
  - Options trade tape: Deribit yes (public feeds); Bybit yes but far lower liquidity/volume.
  - GEX computation: both venues only assumption-based (assume MMs short gamma), same limitation as most non-CBOE GEX tools; Bybit noisier/thinner than Deribit.
  - Expected Move/Total Vol/Net Delta analogs: computable from OI+IV(mark IV field on Bybit)+trade tape on both.
  - **Recommendation**: Deribit is architecturally better primary source (dominant crypto options venue); layer Bybit optionally for BTC/ETH. Any crypto GEX = assumption-based estimate, research-stage only, not a build decision.

## 6. Volumetrica (white-label parent)
- Deepchart (Volumetrica desc): Volume Profile/Deep Trades/Delta Profile/TPO/Order Flow Analyzer; DeepBars/Range/Renko chart types; DOM (Book) + T&S; OCO execution/risk mgmt; win-rate/risk-return reports; 15-min data delay + Sim Account.
- DeepDom (Volumetrica desc): Heatmap = "historical order book liquidity, support/resistance/institutional activity"; Volume Bubbles = tick-by-tick trades w/ nanosecond precision (HFT); Indicators: Iceberg, Stop Run, CVD, Liquidity Tracker; candles+drawing tools on heatmap; advanced DOM (truncated).
- Volumetrica KB categories (Deepchart product): 7 total sections — Common issues(4), Configurations(8), Features(6), Trading(6), Indicators-Common(37, generic TA library e.g. ADX), Indicators-Volume(31, e.g. Auction Gap Tracker/Bar POC/Big Trades), VolAnalyzer(1, VolSwing). Confirms large generic TA-indicator library beyond orderflow tools, underemphasized on DeepCharts-branded pages.
- "Big Trades"(Volumetrica)≈"Deep Trades"/"Big Passive Trade"(DeepCharts). "Bar POC"/"Auction Gap Tracker" not named on DeepCharts pages — possible unexposed/renamed features (open question).
- VolBook Heatmap article: default 1hr history; green=Sell Limit/red=Buy Limit (CONTRADICTS DeepCharts docs, see 4.1); explicit Level-2 depth requirement, 1000+ book levels supported; adaptive color rescaling confirmed; settings tree: Import all annotations, Model, Indicators, Properties, Line Bid/Ask, Heatmap, Color Levels-DOM, Imbalance Book, Cumulative-Delta, Last-Level, Price-Line, Graphic-Settings.
- "Imbalance Book" setting confirms a distinct imbalance-tracking feature (cf. "Session Imbalance" indicator name, section 7.1a #12) — possibly 2-3 overlapping/distinct "imbalance" features, undisambiguated.

## 7. Helpdesk KB inventory (partial enumeration)
- Total KB articles: 172 (corrected from earlier estimate of 135).
- DeepDom sub-category: 39 articles fully enumerated by title/section; ~133 remaining (general Deepchart, DeepGamma, generic TA library, install/licensing) not individually enumerated.
- DeepDom KB nav structure (5 sections): Common Issues (Cache/Installation/Licence issues), How To (General Settings, Install/First Config, Add Markets), Trading (Orders Window, Portfolio-Risk Manager, Simulation Environment), Indicators (Spread Bid/Ask, VWAP+Envelopes, Session Imbalance, etc.), Features/Deep Indicators (Volume Bubbles, Heatmap, Replay Tick Data / Deep Iceberg, Deep Reload, Deep Liquidity Scan).
- 19 DeepDom Indicators enumerated (via /portal/en/kb/deepdom/indicators):
  1. Deep Iceberg (4.4) 2. Spread Bid/Ask — bid-ask spread in ticks, flags liquidity condition changes 3. Deep Reload (4.7) 4. Stop Run (4.5) 5. Deep Liquidity Scan (4.8) 6. Cumulative Iceberg/Stop — MBO-based cumulative line tracker (=Stop/Iceberg Tracker) 7. Absorption (4.6a) 8. Volume Swing — title only, likely swing-high/low marker (cf. Volumetrica's VolSwing) 9. POC Dynamic — rolling-window POC line + historical POC ribbon 10. Volume Profile (=volume-by-price) 11. Book Speed — title/URL confirmed but content unfetchable (open question) 12. Session Imbalance — highlights Initial Balance (first-hour) price levels 13-19: not captured in this read pass.
- Other KB articles noted: Volume (generic) — sub-modes Volume/Order/Aggregate Trade, Filter Min/Max, Calculation Based on Seconds option, background coloring None/Fade/Delta; Rectangle Drawing Tool troubleshooting (antivirus/.NET reqs); Interactive Brokers TWS API connection guide (non-crypto context); Price Chart Settings (candlestick/line "indicator"); Deep-M IVB — ORB-based algorithmic level projector, futures/equities-session-based, needs redesign for 24/7 crypto (no single daily open); Depth of Market (DOM, =4.2); Deep Reload (=4.7); Stop Run Detection third-party explainer (orderflowfutures.com) — fade-the-sweep trading approach.

## Key numeric limits/specs
- DeepDom: $39/mo, $468/yr.
- DeepGamma: from $46/mo, 1-min SPX resolution, 9-month backtest window (through Nov 2025).
- Heatmap precision: 0.01s (marketing) / 0.015s (3rd-party review).
- VolBook depth: 1000+ book levels (vs Bybit's public WS 50/200/500 tiers).
- 24-hour DOM backfill on chart open.
- Bybit orderbook WS push interval: ~20ms (per report; NOT freshly re-verified against live V5 docs — flagged as open question).
- Deepchart 15-min data delay (Volumetrica desc) + Sim Account.
- Absorption example thresholds: Max Tick 1 vs 15; Max MS 2050 vs 10; Min Absorption Vol 20 vs 50.
- Deep Liquidity Scan example: Num Lev Depth e.g. 200.
- KB totals: 172 articles total; 39 in DeepDom sub-category; Volumetrica Deepchart KB: 37 generic + 31 volume-indicator articles.

## Recommendations for CandleViewer (research-stage, not build decisions)
- Rename MBO-dependent features when building heuristic analogs: "Iceberg Detector"→heuristic replenishment detector; "Stop Run Detector"→"Liquidity Sweep Detector".
- Deep Reload, Deep Liquidity Scan, Market Regime/Book Speed, and core Absorption signal are all fully buildable from Bybit public L2+trade+kline feeds without MBO — good roadmap candidates, "Liquidity Sweep Detector" specifically flagged as promising.
- For Absorption: drop or approximate the MBO-only "Max Orders Number" setting.
- For crypto GEX: use Deribit as primary options data source (dominant OI/volume venue), optionally layer Bybit for BTC/ETH; cannot replicate CBOE MM-certainty claim — must be assumption-based dealer-gamma estimate, comparable to other non-CBOE retail GEX tools.

## Open questions (unresolved)
1. Heatmap Buy/Sell color mapping contradiction: DeepCharts docs (green=Buy/violet=Sell) vs Volumetrica VolBook article (green=Sell/red=Buy) — same underlying engine, not reconciled.
2. Full settings for Market Regime, Book Speed, Deep Trades — articles wouldn't render past generic help-widget chrome (Book Speed tried twice); Deep Liquidity Scan and Absorption fully resolved; Session Imbalance partially resolved (truncated).
3. Full enumeration of remaining ~133 of 172 total KB articles (general Deepchart, DeepGamma, generic TA library, install/licensing) not individually captured.
4. Exact Bybit L2 push-frequency/depth-tier table not freshly re-verified against live V5 WS docs (fetch failed mid-session) — re-confirm before implementation, across spot/linear/inverse/option categories.
5. Tooling note: Parallel Search MCP hit rate limits mid-session; WebFetch had an internal error; back-half research relied on WebSearch + curl/Bash scraping — spot-check flagged pages (live Bybit V5 docs, a couple DeepCharts helpdesk articles) if higher confidence needed.
6. "Session Imbalance" (Initial Balance indicator) vs "Imbalance Book" (VolBook heatmap setting) vs generic "imbalance tracker" from research brief — may be 2-3 distinct features sharing terminology, not disambiguated.
7. "Volume" indicator appears twice with near-but-not-quite-matching descriptions (general Deepchart article: Volume/Order/Aggregate-Trade sub-modes; DeepDom Indicators Volume article: total volume + delta background coloring) — unclear if same feature documented twice or two separate features.
8. "Bar POC" and "Auction Gap Tracker" (Volumetrica-native) not explicitly named on crawled DeepCharts pages — possibly additional unexposed/renamed DeepCharts features.
9. DeepGamma pricing table rows ("$250/month", "third-party tools only") may be competitor-comparison copy, not confirmed DeepCharts price points.
10. Exact 1:1 mapping of DeepDom's 5 KB sections to Zoho portal's reported "5 Sections" label not fully confirmed field-by-field.
