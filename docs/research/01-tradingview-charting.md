# TradingView charting & analysis feature inventory

> Research phase document for CandleViewer (private, self-hosted, crypto-only charting/trading app). This inventories TradingView's charting and analysis feature set (web/desktop Supercharts, Premium/Ultimate tiers) as a reference baseline. Not a build spec.

Last researched: 2026-09-13. Prices/limits reflect TradingView's public pricing page and Help Center at time of research; TradingView changes these periodically — always re-verify against https://www.tradingview.com/pricing before relying on exact numbers.

---

## 1. Chart types

TradingView's Supercharts advertise **"20+ chart types"** (support article: 21 listed at Premium/Ultimate, 17 at Basic/Essential/Plus per the pricing page's "Customizable chart types" row). They are split into time-based vs. price-based, and classic vs. indicator-based.

### 1.1 Time-based, classic chart types
| Chart type | Notes |
|---|---|
| Line | Simple line through closes |
| Line with markers | Line + dot markers per bar |
| Step line | Right-angle step line |
| Area | Filled line chart |
| HLC area | Plots high/low/close as three shaded lines/bands |
| Baseline | Colors above/below a user-set baseline value differently |
| Bar (OHLC) | Classic open-high-low-close bars |
| High-low | Simplified bar chart, high/low only |
| Candlestick | Classic Japanese candles |
| Hollow candlestick | Hollow body = close > open of same bar (vs. prior close) |
| Volume candlestick (volume candles) | Candle body width scaled to bar's volume |
| Heikin Ashi | Smoothed/averaged candle variant |
| Column | Used for macro/economic-indicator series (GDP, rates, etc.), not typically price |

### 1.2 Price-based chart types (no fixed time axis; new elements drawn on price movement)
| Chart type | Notes |
|---|---|
| Renko | Fixed-size brick chart, ignores time |
| Line break | New line drawn only on reversal beyond N previous lines |
| Kagi | Thick/thin reversal line, direction changes on reversal amount |
| Point & figure (P&F) | X/O column reversal chart |
| Range bars | New bar only after a fixed price range is traveled |

Renko, Kagi, Line Break, and P&F do **not** work on tick-based intervals (official caveat). Intraday Renko/Kagi/Line Break/P&F charts are gated to Plus tier and above (Essential/Basic lack intraday granularity for these).

### 1.3 Indicator-based / order-flow chart types
| Chart type | Notes | Plan gate |
|---|---|---|
| **Volume footprint** | Released May 14, 2024 (TradingView Blog: "New chart type — Volume footprint", tradingview.com/blog/en/new-chart-type-volume-footprint-44399 — *confirmed: date re-checked directly against the official blog post title/URL and independently corroborated by FX News Group's contemporaneous coverage; original claim stands unchanged*). Shows seller volume distribution to left, buyer volume to right of each candle, gradient-colored by intensity, imbalance lines, dual POC per side, delta + total volume info box/table below each bar. Retrieves lower-intrabar-interval volume; precision degrades further back in history as available intrabar granularity coarsens. | Premium and higher |
| **Session Volume Profile (SVP)** | Volume histogram anchored to each session, split bull/bear, POC/VAH/VAL highlighted | Requires Volume Profile entitlement (Essential+) |
| **Time Price Opportunity (TPO)** / Market Profile chart | Classic TPO letter-based profile chart type | Plus and higher (per pricing matrix "Time Price Opportunities" row) |

### 1.4 Volume footprint settings detail (from Help Center "Volume footprint charts: a complete guide")
- **Row size**: Auto (0.2 × Normalized ATR, recalculated on chart-type/symbol/timeframe change) or manual tick size.
- **Display mode**: Cluster (equal-width cells) vs. Profile (cell width proportional to volume at that level).
- **Type**: 4 display modes for footprint content (bid/ask volume, delta, volume%, etc. — exact labels configurable).
- **Labels**: numeric value labels per cell, togglable.
- **POC**: Point of Control shown per footprint (per side).
- **Show summary info**: "Info Box" (compact: total volume, buy/sell volume, delta) or "Table" (separate pane below chart).
- Data source: multiple intrabar intervals; interval widens automatically as historical depth increases (least granular furthest back).

### 1.5 Chart type customization limits (from pricing page comparison table)
| | Basic | Essential | Plus | Premium | Ultimate |
|---|---|---|---|---|---|
| Customizable chart types | 17 | 17 | 17 | 21 | 21 |
| Intraday Renko/Kagi/Line Break/P&F | — | — | ✓ | ✓ | ✓ |
| Volume footprint | — | — | — | ✓ | ✓ |
| Time Price Opportunities | — | — | ✓ | ✓ | ✓ |
| Volume Profile indicators | — | ✓ | ✓ | ✓ | ✓ |
| Volume candles | ✓ | ✓ | ✓ | ✓ | ✓ |

(Table reconstructed from tradingview.com/pricing "Compare plans" grid; row presence/absence per tier confirmed, exact checkmark granularity for Basic/Essential on TPO/footprint inferred from combined support+pricing sources — flagged in Open Questions.)

### 1.6 Seconds-based and tick-based intervals (gap-fill)
- **Seconds intervals were officially launched** via TradingView Blog post "Second-Based Timeframes Are Now Supported!" (tradingview.com/blog/en/second-based-timeframes-are-now-supported-13588). Supported granularities: **1, 5, 10, 15, 30, 45 seconds**.
- **Plan gate: Premium and Ultimate only.** Basic, Essential, and Plus do **not** get seconds intervals — this was independently confirmed by a Reddit thread explicitly asking whether Plus includes the 30-second timeframe, answered "no."
- Historical depth on seconds charts is materially shorter than minute/hour charts — third-party sources report roughly **up to ~2 weeks of history / ~10,000 bars** for second-resolution data; this specific figure is **not directly confirmed against TradingView's own copy** in this pass and should be re-verified live (treat as an unconfirmed secondary-source figure, similar caveat to the Bar Replay minute-depth figures below).
- **Tick-based intervals**: a separate, more restrictive feature — the existing per-tier table (Section 7) already notes "Historical data by the tick" = 7 days, Ultimate-only, and Renko/Kagi/Line Break/P&F chart types explicitly do **not** work on tick-based intervals (Section 1.2). No evidence found of tick intervals being available below Ultimate.
- Relevance to CandleViewer: since footprint/order-flow charts need fine intrabar granularity, and Bybit's own WebSocket trade/orderbook feeds are effectively tick-level, this shows TradingView gates its finest granularity to its most expensive tier — a data-access constraint CandleViewer's self-hosted architecture would not inherit (own Bybit tick/orderbook feed, not TradingView's).

### 1.7 Multi-timeframe (MTF) analysis and symbol overlay/comparison (gap-fill)
- **Compare vs. Add Symbol** are two related but distinct entry points from the same "+ Compare or Add Symbol" chart toolbar button (per TradingView Help Center "How to use the Compare tool," support/solutions/43000543053):
  - **Compare**: adds a second (or further) symbol as an overlay, forcing the shared Y-axis into **percentage-change mode** so instruments with very different absolute price levels can be visually compared on relative performance. Default overlay style is a line, though this is customizable. Useful for relative-strength/correlation/divergence analysis (e.g., comparing an altcoin to BTC).
  - **Add Symbol / Overlay**: same underlying mechanism but offers a choice of Y-axis behavior — shared percentage scale (Compare-equivalent), an **independent new price scale** (each symbol keeps its own raw-price axis), or placement in a **new pane** below the main chart instead of an overlay.
  - Both let the secondary symbol take any chart style, not just line, once added.
- **Ratio/spread charts**: TradingView supports synthetic spread-symbol syntax in the symbol search bar (e.g., `BINANCE:BTCUSDT/BINANCE:ETHUSDT` for a BTC/ETH ratio), and the existing per-tier table's "Intraday charts based on custom formulas (spread charts)" row (Section 4) covers building arbitrary cross-symbol formula charts beyond simple ratio division.
- **Multi-timeframe (MTF) analysis on one chart**: for Pine Script authors, this is implemented via the `request.security()` function, which pulls another symbol's or another timeframe's series into the current chart's script context (e.g., plotting a daily moving average on a 1-hour chart). This is a scripting-level capability (available to any tier with Pine Script editor access) rather than a discrete UI toggle — there is no separate "MTF mode" pricing-table row; MTF views are achieved either via `request.security()`-based custom/community indicators or via the multi-chart-layout + sync-axes mechanism (Section 6.1) showing the same symbol at different intervals side-by-side.
- Relevance to CandleViewer: both patterns (relative-comparison overlay and MTF-via-second-data-request) are directly applicable design patterns for a Bybit-data-only app — e.g., overlaying perp funding-adjusted price vs. spot, or pulling a higher-timeframe VWAP/POC onto a lower-timeframe footprint chart.

---

## 2. Drawing tools

Source: TradingView Help Center "Drawing tools available on TradingView" (support/solutions/43000703396) and the Advanced Charts developer docs "Drawings List" (charting-library-docs, which mirrors the web product's tool set). TradingView markets **"110+ smart drawing tools"** (pricing page).

### 2.1 Trend tools (lines)
- Trendline
- Arrow
- Ray
- Info line
- Extended line
- Trend angle
- Horizontal line
- Horizontal ray
- Vertical line
- Crossline
- Anchored VWAP (also listed under forecasting/measurement in some docs)

### 2.2 Channels
- Parallel channel
- Regression trend
- Flat top/bottom
- Disjoint channel

### 2.3 Gann and Fibonacci tools
- Fib retracement
- Trend-based fib extension
- Fib channel
- Fib time zone
- Fib speed resistance fan
- Trend-based fib time
- Fib circles
- Fib spiral
- Fib speed resistance arcs
- Fib wedge
- Pitchfan
- Gann box
- Gann square fixed
- Gann square
- Gann fan

### 2.4 Pitchforks (grouped with Gann/Fib in official docs, sometimes as own category)
- Pitchfork (Andrews)
- Schiff pitchfork
- Modified Schiff pitchfork
- Inside pitchfork

### 2.5 Geometric shapes
- Brush
- Highlighter
- Rectangle
- Rotated rectangle
- Circle
- Ellipse
- Triangle
- Arc
- Path
- Curve
- Double curve
- Polyline

### 2.6 Annotation tools
- Text
- Note
- Anchored note
- Signpost
- Callout
- Comment
- Price label
- Price note
- Table
- Arrow marker
- Arrow mark left / right / up / down
- Flag mark
- Pin

### 2.7 Chart / harmonic patterns
- XABCD pattern
- Cypher pattern
- ABCD pattern
- Triangle pattern
- Three drives pattern
- Head and shoulders
- Elliott impulse wave (12345)
- Elliott triangle wave (ABCDE)
- Elliott triple combo wave (WXYXZ)
- Elliott correction wave (ABC)
- Elliott double combo wave (WXY)
- Cyclic lines
- Time cycles
- Sine line

### 2.8 Predictions & measurement tools
- Long position
- Short position
- Position forecast (forecast)
- Bars pattern
- Projection
- Date range
- Price range
- Date and price range
- Ghost feed
- Sector (sector-relative tool)
- Fixed range volume profile
- Anchored volume profile

### 2.9 Icons / stickers / emojis
- Icons (arbitrary icon library)
- Stickers
- Emojis (uses Twemoji v13.0 icon set)
- Ability to paste X (Twitter) posts / ideas directly onto the chart (per Help Center article listing)

### 2.10 Cursor / interaction modes
- Regular cursor
- Crosshair
- Measure tool (drag-to-measure price/time/% change/bars)
- Zoom-in cursor

### 2.11 Drawing tool feature set (Help Center + Advanced Charts docs)
| Feature | Description |
|---|---|
| Magnet mode | Weak magnet (loose snap to nearby price/OHLC) and Strong magnet (hard snap to nearest bar's OHLC value) |
| Lock | Lock individual drawing or "Lock all drawing tools" to prevent accidental editing |
| Stay in drawing mode | Keep a tool active for repeated placements instead of reverting to cursor after one use |
| Hide all drawings | Global visibility toggle |
| Object tree | List/manage all drawing objects and indicators on a chart, reorder, toggle visibility, lock, delete |
| Visibility per timeframe / interval | Drawings can be set to show only on specific timeframes (e.g., only intraday, only daily+) |
| Templates | Save a drawing's full style config as a default or named template; apply to new drawings or in bulk to existing ones of same type (Help Center: "How to apply a template to several tools of the same type at once") |
| Bulk color change | "How to change the color of multiple tools at once" |
| Sync across charts | Drawing synchronization across multiple charts in a multi-chart layout when charts share the same symbol (toggle in multichart mode) |
| Favorite tools | Pin frequently used tools to a quick-access toolbar row |
| Custom restrictions (Advanced Charts / white-label only) | Restrict which drawing tools are available to end users |
| Drawing API | Programmatic creation/manipulation of drawings (Advanced Charts library) |
| Reverse position | Flip a Long/Short position tool's direction post-placement |
| Undo/redo | Standard history stack for drawing actions |

---

## 3. Indicators

### 3.1 Scale and counts
- TradingView advertises **"400+ pre-built (most popular) indicators"** built into the platform, plus **"100K+ community-powered indicators"** (Pine Script scripts published by users), searchable via the Indicators, Metrics & Strategies panel.
- **Indicators per chart** limit scales by plan (see Section 7 tier table): Basic 2, Essential 5, Plus 10, Premium 25, Ultimate 50.
- **Indicator-on-indicator** (applying one indicator's output as another's input) limit: Basic 1, Essential 1, Plus 9, Premium 24, Ultimate 49.
- **Financials per chart** (fundamental-data overlays): Basic 1, Essential 4, Plus 7, Premium 10, Ultimate 25.
- **Custom indicator templates**: available starting at some paid tier (exact tier not itemized in fetched pricing rows beyond presence/absence; flagged below).

### 3.2 Built-in indicator categories — full itemized catalog **[verified]**

Resolves prior Open Question #2. Source: [TradingView Help Center — Built-in Indicators folder](https://www.tradingview.com/support/folders/43000587405-built-in-indicators) — fetched directly (full_content), which lists **every article title in the "Built-in Indicators" Help Center folder** (209 articles per the folder's own count at https://www.tradingview.com/support/categories/indicators/). This folder mixes classic technical-analysis indicators with crypto on-chain/on-exchange metrics (all delivered through the same Indicators panel for crypto symbols) and a handful of non-indicator conceptual articles filed in the same folder (marked below). Grouped here by category for CandleViewer relevance; the grouping itself is our own classification, not TradingView's (TradingView's own in-app panel groups by "Technicals / Financials / Community" tabs, not by these sub-categories).

**Trend / moving averages**
Arnaud Legoux Moving Average · Double Exponential Moving Average (EMA) · Exponential Moving Average · Hull Moving Average · Kaufman's Adaptive Moving Average (KAMA) · Least Squares Moving Average · MA Cross · McGinley Dynamic · Moving Average Ribbon · Moving Averages · MovingAvg Cross · MovingAvg2Line Cross · Simple Moving Average · Smoothed Moving Average · Triple EMA · TRIX · Volume-Weighted Moving Average (VWMA) · Weighted Moving Average · Linear Regression · Ichimoku Cloud · Parabolic SAR (SAR) · Supertrend · Williams Alligator · Williams Fractal · Zig Zag · Trend Strength Index · Vortex Indicator

**Oscillators / momentum**
Awesome Oscillator (AO) · Balance of Power (BOP) · BBTrend · Bull Bear Power · Chande Momentum Oscillator (CMO) · Coppock Curve · Commodity Channel Index (CCI) · Connors RSI (CRSI) · Detrended Price Oscillator (DPO) · Fisher Transform · Klinger Oscillator · Know Sure Thing (KST) · MACD (Moving average convergence divergence) · Mass Index · Momentum · Percentage Price Oscillator (PPO) · Price Momentum Oscillator (PMO) · Pring's Special K · Rank Correlation Index (RCI) · RCI Ribbon · Rate of Change (ROC) · Relative Strength Index (RSI) · RSI divergence indicator · Relative Vigor Index · SMI Ergodic Indicator · SMI Ergodic Oscillator · Stochastic (STOCH) · Stochastic Momentum Index (SMI) · Stochastic RSI (STOCH RSI) · True Strength Index · Ultimate Oscillator (UO) · Williams %R (%R) · Woodies CCI

**Volatility**
Average Daily Range (ADR) indicator · Average True Range (ATR) · Bollinger Bands (BB) · Bollinger Bands %b (%b) · Bollinger BandWidth (BBW) · Bollinger Bars · Chande Kroll Stop · Chandelier Exit · Choppiness Index (CHOP) · Historical Volatility · Keltner Channels (KC) · Relative Volatility Index · Ulcer Index · Volatility Stop · Donchian Channels (DC) · Envelope (ENV)

**Volume / order-flow-adjacent**
24-hour Volume · Accumulation Distribution (ADL) · Chaikin Money Flow (CMF) · Chaikin Oscillator · Cumulative Volume Delta · Cumulative Volume Index (CVI) · Ease of Movement (EOM) · Elder's Force Index (EFI) · Klinger Oscillator (also volume-based, cross-listed) · Money Flow (MFI) · Negative Volume Index (NVI) · Net Volume · On Balance Volume (OBV) · Positive Volume Index (PVI) · Price Volume Trend (PVT) · Relative Volume at Time · Up/Down Volume · Volume · Volume Delta · Volume Weighted Average Price (VWAP) · Time Weighted Average Price · Visible Average Price · VWAP Auto Anchored

**Directional / trend-strength**
Average Directional Index (ADX) · Directional Movement (DMI) · Chop Zone · Aroon Indicator · Aroon Oscillator

**Auto-drawn analysis tools (technically indicators, not manual drawings)**
Auto Fib Extension · Auto Fib Retracement · Auto key levels · Auto Pitchfork · Auto Trendlines · Pivot Points High Low · Pivot Points Standard · Technical Ratings · Seasonality (+ "Learn using seasonals" companion article) · Correlation Coefficient (CC) · Median · Performance · Rob Booker - ADX Breakout · Rob Booker - Knoxville Divergence · Rob Booker Intraday Pivot Points · Rob Booker Missed Pivot Points · Rob Booker Reversal · Rob Booker Ziv Ghost Pivots (community-author indicators shipped as built-ins) · Trading Sessions · Moon Phases (novelty) · Power-Law Model · Multi-Time Period Charts indicator

**Breadth (index/market-wide)**
Advance/Decline Line · Advance/Decline Ratio · Advance/Decline Ratio (Bars)

**Fundamental / non-price**
Analyst price forecast · Dividend Yield · Price target - indicator · Premium (options-related)

**Crypto on-chain / on-exchange metrics** (delivered as "indicators" on crypto symbols; distinct from classic TA — directly relevant to CandleViewer's crypto-only scope)
1 year active supply % · Active addresses with contracts · Addresses with balance ≥ X (% of supply) · Addresses with balance ≥ X (USD) · Basis · Block height · Blocks mined · Created UTXOs · Difficulty · El Salvador Government balance · ETF balances · ETF flows · Ethereum new deposits · Ethereum new unique depositors · Ethereum new value staked · Ethereum total number of deposits · Ethereum total unique depositors · Ethereum total value staked · Funding rate (+ "Funding rate: a guide to market sentiment" companion article) **[verified: crypto perpetuals funding rate is a built-in indicator, directly relevant to CandleViewer]** · Hash Rate · Held tokens in addresses ≥ X (% of supply / tokens / USD) · Index price · Large transaction volume · Liquidation data (+ "Liquidation data: what to watch and why it matters" companion article) **[verified: liquidation data is a built-in indicator]** · Long/Short Ratio Accounts · Long Short Accounts % · Mark price · Mean/Median block interval, block size, gas used, transaction fees, gas limit, gas price, transaction size, transfer volume, UTXO value created/spent (full mean/median on-chain stats family) · Open Interest **[verified: built-in]** · Realized market cap · Receiving/Sending addresses · Spent Output Profit Ratio (SOPR) · Spent UTXOs · Stock-to-Flow Ratio in USD · Supply Equality Ratio · Top trader long/short accounts (+ ratio) · Top trader long/short positions (+ ratio) · Total block size in bytes · Total gas used · Total transactions size in bytes · Total UTXO value created/spent · Total UTXOs · Transaction fees · Transaction rate · Transfer count · Transfer rate · Understanding crypto open interest (companion article) · US spot crypto ETF balances · US spot crypto ETF flows · Average transaction volume · Median (also cross-listed above)

**Assessment for CandleViewer**: the on-chain/on-exchange metrics group (funding rate, open interest, liquidation data, long/short ratios) is the most directly relevant subset — these map onto Bybit's own REST endpoints (funding rate history, open interest, long/short ratio) and are cheap to replicate without needing TradingView's on-chain data vendor relationships. The classic TA indicator list (moving averages, oscillators, volatility, volume) is a well-trodden, freely-implementable set (all are public formulas) and should be treated as a checklist/backlog rather than something requiring per-indicator research. Total count is **~195 distinct titles** in the fetched list after excluding the ~5 non-indicator companion/conceptual articles (funding rate guide, liquidation data guide, "learn using seasonals", "understanding crypto open interest") that share the same folder — consistent with, though not an exact match for, TradingView's own "400+ pre-built indicators" marketing figure (the marketing figure likely double-counts indicator variants/aliases, drawing-tool-style auto-indicators, and Volume Profile sub-variants (Section 3.3) not separately titled in the Help Center folder, and may count some indicators that ship only in specific locales/exchanges not enumerated in the English-locale Help Center folder). Re-verify by an in-app authenticated crawl of the Indicators panel if an exact reconciled count is later needed.

### 3.3 Order-flow-relevant built-ins and Volume Profile family
| Indicator | Description | Plan gate (from Help Center "Volume Profiles" folder + pricing) |
|---|---|---|
| Fixed Range Volume Profile | Drawing-tool-style: user selects a fixed date/bar range; computes volume-by-price histogram, POC, VAH/VAL for that exact range | Essential+ (Volume Profile family entry point) |
| Session Volume Profile | Auto-recalculates per session (day) | Essential+ |
| Session Volume Profile HD | Higher-resolution/high-definition variant of Session Volume Profile | Premium/Ultimate-leaning (newer HD variant) |
| Periodic Volume Profile | Profile recalculated on a periodic basis (configurable period) beyond single session | Paid tiers |
| Visible Range Volume Profile | Profile recalculated dynamically for whatever range is currently visible on screen | Paid tiers |
| Auto Anchored Volume Profile | Automatically anchors profile to significant swing/pivot points rather than manual placement | Paid tiers |
| Anchored VWAP (drawing tool) | User manually anchors VWAP calculation to any bar; shows standard deviation bands | Available across tiers as drawing tool; per Help Center "Anchored VWAP drawing tool" |
| Session VWAP (built-in indicator) | Standard running VWAP that resets each session, added via Indicators panel (not drawing toolbar) | Broadly available |
| Volume Delta | Indicator showing per-bar difference between estimated buy and sell volume (bar-colored by net delta direction) | Uses `ta.requestVolumeDelta()` Pine function under the hood for script authors; built-in overlay available in Indicators panel |
| Cumulative Volume Delta (CVD) | Running cumulative sum of volume delta over time, plotted as its own "candles" (open = start-of-period/prior close, high/low = intrabar extremes, close = net delta added to cumulative total); configurable anchor period (session/day/week) and intrabar sampling timeframe (auto-recommended); candle or line display style | **Confirmed built-in, first-party indicator** (Help Center article: "Cumulative Volume Delta", support/solutions/43000725058) — not community-script-only. Distinct from, but complementary to, per-bar Volume Delta and the Volume footprint chart type; works best on instruments with real (not synthetic/tick-only) traded volume, i.e. crypto and futures — less reliable on forex spot. *(Resolves Open Q #2's CVD-status ambiguity — see also new §3.6.)* |
| Time Price Opportunity (TPO) | Both a standalone chart type (Section 1.3) and conceptually an indicator/profile view showing letter-coded time-at-price | Plus+ |

### 3.6 CVD vs. Volume Delta vs. Volume footprint — clarified relationship (gap-fill)
All three are **official, first-party TradingView features**, not community-only Pine scripts, though community versions of each also exist:
- **Volume Delta**: per-bar (not cumulative) buy-minus-sell volume, shown as a single oscillator-style series/histogram.
- **Cumulative Volume Delta (CVD)**: running/cumulative total of Volume Delta over a session or custom anchor period, rendered as its own candle series — confirmed built-in per the dedicated Help Center article above.
- **Volume footprint**: a full chart type (not a single-value indicator) showing the complete bid/ask volume distribution *within* each bar/price level, with delta and POC per side (Section 1.3–1.4).
- There is **no evidence of a native "Footprint-style" per-price-level delta indicator separate from the Volume footprint chart type itself** — the granular price-level delta view is only available via the footprint chart type (Premium+), while CVD and Volume Delta are bar-level (not price-level) aggregates available as ordinary indicators on lower tiers. Source: [TradingView Help Center — Cumulative Volume Delta](https://www.tradingview.com/support/solutions/43000725058-cumulative-volume-delta/).

### 3.4 Pine Script
- Pine Script® is TradingView's proprietary scripting language for custom indicators/strategies; gated feature flag appears in the pricing comparison table (present from at least Essential upward per typical TradingView tiering — confirm live).
- Strategy backtesting (Pine strategies): basic report metrics vs. advanced report metrics, CSV/XLSX export, and "Deep backtesting" (extends backtest history/precision) are all separate gated rows in the pricing comparison grid, escalating from Essential (basic) up to Ultimate (deep backtesting + full export).

### 3.5 Auto chart pattern recognition
- "Auto chart patterns" — automatic detection/annotation of classic chart patterns (triangles, head & shoulders, etc.) directly on the chart, gated in pricing table (appears at Plus/Premium+, exact cutoff not fully confirmed — see Open Questions).
- "Candlestick patterns recognition" — separate gated row for auto-detecting candlestick patterns.
- "Auto fib retracement" — automatic placement of Fibonacci retracement based on detected swing high/low.

---

## 4. Chart settings

| Setting/feature | Notes |
|---|---|
| **Price scale types** | Regular (linear), Logarithmic, Percentage, Indexed to 100 — standard scale-type toggle available on the price axis right-click menu |
| **Auto scale vs. lock scale** | Auto-fits visible price range; "lock scale" fixes the scale so panning/zooming price doesn't rescale |
| **Multiple price scales** | Ability to add indicators/symbols with independent right-side or left-side price scales, or overlay on main scale |
| **Sessions / Extended trading hours (ETH)** | Toggle regular vs. extended-hours session data (equities/futures markets); gated to paid tiers per pricing table row "Extended trading hours" |
| **Timezones** | Chart can be set to exchange timezone or user's local timezone |
| **Countdown to bar close** | Shows time remaining until current bar closes, displayed on price scale |
| **Symbol info overlay** | Displays OHLC/change/name info box on the chart, togglable |
| **Bar replay** | Step/play through historical bars as if live; see Section 5 for full detail and per-tier limits |
| **Compare/overlay symbols** | Add other symbols onto the same pane (compare, normalized) or as separate overlay panes |
| **Custom time intervals** | Beyond the standard presets, arbitrary custom-minute/custom-range intervals (gated row present in pricing table across paid tiers) |
| **Second-based intervals** | 1S/5S/etc. charts — data availability starts August 2022 per Help Center bar-replay article; gated to Premium/Ultimate |
| **Tick-based intervals** | Tick charts (BETA at various points); Ultimate-tier gated ("Tick-based intervals" row; "Historical data by the tick" = 7 days on Ultimate only) |
| **Intraday charts based on custom formulas (spread charts)** | Build synthetic spread charts from formulas across symbols; paid-tier gated row |

---

## 5. Bar Replay

Source: Help Center "Bar Replay: how and why to test a strategy in the past" (support/solutions/43000712747) and Optimus Futures coverage of the September 2024 "Synchronized Bar Replay" launch.

- **Single-chart mode**: replay runs on one chart only, functions as originally shipped.
- **Multi-chart / "All charts" mode** (launched ~Sept 2024): Bar Replay can run simultaneously across every chart in a multi-chart layout, tracking different symbols/timeframes at the same synchronized point in time. Larger-interval charts wait for smaller-interval charts' data during replay so time stays aligned across the layout.
- **Session restore**: Bar Replay preserves symbols/intervals on each chart, the last-viewed bar, and replay state when you leave and return — but chart type/style settings are not saved, and restore only works for chart types that support replay; in multi-chart layouts only the charts that support replay are restored.
- **Historical depth for replay**:
  - **Minute-based replay depth (corrected: previously stated as flat "180 days (Essential) / 365 days (Plus) / all (Premium+)" sourced only from Supa.is; re-checked against TradingView's official Help Center article "How much data is available for Bar Replay?", support/solutions/43000692816)**: depth scales **per-interval by formula**, not a flat day count:
    - **Basic (Free)**: no intraday/minute Bar Replay at all — only daily-and-higher timeframes.
    - **Essential**: `months of history ≈ 6 × interval-in-minutes` — e.g. 1-minute chart → 6 months back; 2-minute → 12 months; 3-minute → 18 months; 5-minute → 30 months; 15-minute → 90 months.
    - **Plus**: `years of history ≈ 1 × interval-in-minutes` — e.g. 1-minute chart → 1 year back; 2-minute → 2 years; 5-minute → 5 years; 15-minute → 15 years.
    - **Premium, Expert (if applicable), and Ultimate**: all intraday data TradingView has stored for that symbol — no plan-imposed cap (only limited by how much history actually exists for the instrument).
    - **Tick Replay** (distinct from minute Bar Replay) is an Ultimate-exclusive feature, going back up to **7 days** tick-by-tick.
    - *(This replaces the prior flat 180/365/all-days figures, which are now known to be an oversimplification of TradingView's own interval-scaled formula. Source: [TradingView — How much data is available for Bar Replay?](https://www.tradingview.com/support/solutions/43000692816-how-much-data-is-available-for-bar-replay/))*
  - Second-based timeframes: TradingView stores second-interval data from August 2022 onward; earliest replayable second-bar is August 17, 2022.
  - To reach deep intraday history: start replay on a higher interval (e.g., daily), pick the starting point, then switch down to a lower interval (e.g., 1-minute) and press Play — this works around per-symbol lower-timeframe depth limits.
  - "Select the first available day" option in the date picker jumps to the earliest replayable bar for a symbol.
  - Continuous futures symbols (e.g., `ES1!`, `BANKNIFTY1!`) and futures using "Use settlement as close on daily interval" are exempt from the standard replay depth limits due to synthetic/continuous-contract construction.
- **Hotkeys during replay**: `Shift + ↓` toggles play/pause; `Shift + →` steps forward one bar.
- **Indicators Replay** and **Trading in Bar Replay** (placing simulated orders while replaying) are separate gated rows in the pricing comparison table.
- Per-tier gating: Bar Replay itself is available from Essential upward (Basic/free plan lacks Bar Replay with minute-level data per third-party plan-comparison summaries — confirm exact wording live, see Open Questions); "minute data" replay depth reportedly expands from 180 days (Essential) → 365 days (Plus) → all history (Premium/Ultimate) per secondary sources (not fully confirmed against TradingView's own copy — flagged below).

---

## 6. Layouts, multi-chart, sync, watchlists, symbol search, hotkeys, alerts, screenshots

### 6.1 Multi-chart layouts
- Up to **16 charts per tab** at Ultimate tier (1/2/4/8/16 across Basic/Essential/Plus/Premium/Ultimate — see Section 7 table); Advanced Charts (embeddable/white-label library) documentation separately states **up to 8 charts on one layout** for that product — the two are different products/limits, so treat the 8-chart figure as the embeddable-library ceiling, not the main web-app ceiling.
- **Number of saved chart layouts**: 1 (Basic) / 5 (Essential) / 10 (Plus) / unlimited (Premium/Ultimate, inferred from blank cells in pricing table meaning "unlimited" — TradingView's own layout typically shows a checkmark or number; blank likely renders as unlimited/all — confirm live).
- **Synchronization axes** across charts in a layout: Symbol, Interval (resolution), Crosshair, Time, and Date range — toggled from the "Select Layout" button's sync menu.
- **Drawing sync**: a separate toggle (in multi-chart mode's left panel) syncs drawing objects across charts that share the same symbol; drawings cannot sync across differing symbols.
- **Chart grouping via emoji tags**: an alternate/finer-grained sync mechanism — mark charts with matching emoji "flags" (via the Symbol/Interval chart-syncing icon in the status line or series context menu) to sync just symbol and/or interval between an arbitrary subset of charts, independent of the global layout-wide sync toggle.

### 6.2 Watchlists
- Multiple watchlists supported on paid tiers (Basic/free limited to **1 watchlist**, cap of ~30 symbols per one third-party summary — verify live).
- Custom columns and sorting by name, price change, volume, etc.
- Import/export of watchlists (gated row in pricing table).
- Flagged-symbol colors: 1 color (Basic) vs. 7 colors (all paid tiers) for tagging/flagging watchlist symbols.
- Watchlist alerts: separate quota from price/technical alerts — 0 (Basic/Essential/Plus) → 2 (Premium) → 15 (Ultimate) "Active watchlist alerts" per the pricing grid.

### 6.3 Symbol search
- Global symbol search (type-ahead) across the top bar; supports the hotkey pattern of simply typing while a chart is focused to bring up the search overlay (see hotkeys below).
- Compare/overlay another symbol onto the active chart directly from search or the "Compare or Add Symbol" button.

### 6.4 Hotkeys (selected, from TradingCode.net "Keyboard hotkeys TradingView" and TradingView's own "Hotkeys" support article, which documents desktop-app window/tab management rather than in-chart hotkeys)
**General chart:**
| Action | Hotkey |
|---|---|
| Open script/Pine editor | `/` |
| Load a chart layout | `.` |
| Save current chart layout | `Ctrl+S` |
| Change symbol | start typing (opens symbol search) |
| Change interval | `,` or type digits/letters (e.g. `1`, `5`, `D`, `W`, `4H`) |
| Create alert on current instrument | `Alt+A` |
| Add text note | `Alt+N` |
| Take chart snapshot | `Alt+S` |

**Zoom/navigation:**
| Action | Hotkey |
|---|---|
| Zoom in | scroll up, or drag price axis left |
| Zoom out | scroll down, or drag price axis right |
| Reset bar spacing | double-click time axis |
| Move 1 bar left/right | `←` / `→` |
| Move further left/right | `Ctrl+←` / `Ctrl+→` |
| Go to specific date | `Alt+G` |
| Pan | click-drag on chart |

**Chart trading:**
| Action | Hotkey |
|---|---|
| Place market buy order | `Shift+B` |
| Place market sell order | `Shift+S` |

**Watchlist:**
| Action | Hotkey |
|---|---|
| Next/previous symbol | `↓`/`Space` or `↑`/`Shift+Space` |
| Flag/unflag symbol | `Alt+Enter` |
| Select all / next / previous | `Ctrl+A`, `Shift+↓`, `Shift+↑` |

**Screener:** same next/prev/flag/select pattern as watchlist, applied to Stock/Forex/Crypto Screener windows.

**Indicator/strategy scripts:** `Ctrl+C` copy script, `Ctrl+V` paste script, `Delete` remove selected script.

**Desktop app window/tab management** (from official Help Center "Hotkeys" article — distinct set, OS-scoped):
| Action | Windows/Linux | macOS |
|---|---|---|
| Open Settings | `Ctrl+,` | `Cmd+,` |
| New tab | `Ctrl+T` | `Cmd+T` |
| Duplicate tab | `Ctrl+U` | `Cmd+U` |
| New window | `Ctrl+N` | `Cmd+N` |
| Reload tab | `Ctrl+R` / `F5` | `Cmd+R` |
| Close window | `Ctrl+W` | `Cmd+W` |
| Reopen closed window/tab | `Shift+Ctrl+T` | `Shift+Cmd+T` |
| Next/prev tab | `Ctrl+PgDn/PgUp` or `Ctrl+Tab`/`Ctrl+Shift+Tab` | `Cmd+PgDn/PgUp` or `Ctrl+Tab`/`Ctrl+Shift+Tab` |
| Go to tab N (1–8) | `Ctrl+<N>` | `Cmd+<N>` |
| Go to rightmost tab | `Ctrl+9` | `Cmd+9` |
| Quit, keep windows | `Shift+Ctrl+Q` | `Cmd+Q` |

### 6.5 Alerts
- **Price alerts** and **technical alerts** (indicator/drawing-based conditions) are tracked as separate quotas: e.g. Essential 20/20, Plus 100/100, Premium 400/400, Ultimate 1,000/1,000 (Basic/free: 3 price alerts total, no technical alerts per third-party plan summaries).
- **Watchlist alerts** quota is separate again (Section 6.2).
- **Second-based alerts**: paid-tier-gated row (fires on second-level condition checks, tied to second-based interval availability).
- **Alerts that don't expire**: gated feature (default alerts on lower tiers auto-expire after a period; higher tiers can set alerts with no expiry) — per a secondary source (xn--4kqz9dx34aeea.net mirror of TradingView's own pricing copy); re-verify on canonical tradingview.com/pricing.
- Alerts can be created on: price conditions, any built-in or Pine indicator's output condition, and directly on drawing tools (e.g., alert when price crosses a trendline or Fibonacci level) — accessible via the Alt+A hotkey or the alarm-clock icon in the toolbar.

#### 6.5.1 Alert condition taxonomy (gap-fill)
Per Help Center "Alerts separation by type" (support/solutions/43000696403) and related alert-configuration guides, TradingView alert conditions fall into three broad categories, each with its own condition-type dropdown:
| Category | What it watches | Example condition types |
|---|---|---|
| **Price alerts** | Raw price action on the primary series | Crossing, Crossing Up, Crossing Down, Greater Than, Less Than, Entering/Exiting Channel |
| **Indicator alerts** | Any built-in or Pine-scripted indicator's output value, including cross-indicator conditions | Same crossing/greater-than/less-than vocabulary applied to indicator values (e.g., MA(50) crossing MA(200); RSI crossing 70/30) |
| **Drawing-tool alerts** | Chart drawing objects (trendlines, horizontal lines/rays, Fibonacci levels, channels, etc.) | Price touching/crossing the drawn object — e.g., alert when price crosses an ascending trendline |
- Trigger frequency options: **Once**, **Once Per Bar**, **Once Per Bar Close** (applies across all three categories).
- Right-click a price level/indicator/drawing → "Add Alert", or use the alarm-clock toolbar icon / `Alt+A` hotkey.
- Editing the underlying indicator or drawing after alert creation does **not** retroactively update the alert's stored parameters — must be manually recreated/edited.
- Source: [TradingView Help Center — Alerts separation by type](https://www.tradingview.com/support/solutions/43000696403-alerts-separation-by-type/)

#### 6.5.2 Webhook alerts and notification channels (gap-fill)
Per official Help Center "How to configure webhook alerts" (support/solutions/43000529348) and the "Webhooks usage" folder (support/folders/43000560150):
- A webhook alert sends an **HTTP POST request** to a user-specified URL, entered in the "Webhook URL" field of the alert creation/edit dialog, at the moment the alert condition fires.
- The **alert message body becomes the POST payload**. If the message is valid JSON, TradingView sets `Content-Type: application/json`; otherwise it falls back to `text/plain` — enabling integration with services expecting structured JSON (e.g., custom trading bots, Discord/Slack relays, or — relevant to CandleViewer — a self-hosted rule-engine endpoint for auto-executing stops/exits).
- **Restrictions**: only ports **80** and **443** are allowed as webhook destinations; **IPv6 destinations are not supported**; a webhook delivery has a **3-second timeout**; **two-factor authentication (2FA) must be enabled** on the TradingView account before webhooks can be configured; TradingView explicitly advises against embedding secrets/passwords in the webhook body.
- **Other non-webhook notification channels** (per the broader Alerts feature set, corroborating the pricing-table "Notifications" rows): in-app popup, browser/desktop push notification, mobile app push notification, email, and SMS (SMS availability has historically been tier/region-gated — not independently re-confirmed in this pass, flagged as unresolved below).
- Relevance to CandleViewer: webhook-based alert delivery is the closest analogue to what CandleViewer's own "custom rule-based stops/exits" requirement needs internally (an alert/condition engine posting to an internal endpoint) — useful as an architecture reference even though CandleViewer will not depend on TradingView's webhook delivery itself.
- Sources: [How to configure webhook alerts](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/), [Webhooks usage folder](https://www.tradingview.com/support/folders/43000560150-webhooks-usage/)

### 6.6 Screenshots / publishing / data export (expanded — was thin per critic feedback)
- **Alt+S** takes an in-app snapshot of the current chart.
- Snapshots/ideas can be published to the TradingView community (Minds, public ideas, comments — social features listed in pricing table under "Social").
- Publishing gated capabilities that scale by tier: "Publish invite-only indicators," "Publish protected scripts" (protecting Pine source from public view), and community contest participation counts (Basic 0 active contests allowed → Ultimate 25) plus "Ability to create public contests."

#### 6.6.1 Chart image export (gap-fill)
- Click the **camera icon** in the chart's top-right toolbar → **"Download Image"** (saves PNG) or **"Copy image"** (to clipboard).
- **No native custom-resolution/DPI export option**: the exported PNG resolution simply matches whatever is currently rendered on-screen at export time (i.e., tied to browser window size / display resolution / browser zoom level) — there is no "export at 2x/4x" setting. To get a higher-resolution image, users must maximize the browser window, use a higher-resolution display, zoom in before exporting, or use full-screen chart mode; TradingView provides no built-in upscaling.
- Source (secondary, cross-checked against the Help Center's general "Download Image / Copy Image" menu behavior — official Help Center article for this specific menu was not independently re-fetched in this pass): [Kotak Neo — Share & Analyse TradingView Charts Like a Pro](https://www.kotakneo.com/stockshaala/trading-view/exporting-charts-for-sharing-analysis/).

#### 6.6.2 Chart data (CSV/OHLCV) export (gap-fill)
- Official feature, announced via TradingView Blog: ["You can now export & download data into a CSV file"](https://www.tradingview.com/blog/en/export-chart-data-in-csv-14395/), documented at Help Center ["How to export chart data"](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/).
- **Requires Pro+/Premium-tier or higher** — not available on Basic/Essential/Plus per the third-party guides cross-checked (exact lowest qualifying tier not independently re-confirmed against the live pricing grid in this pass — flagged below).
- **Workflow**: load symbol/timeframe → add any indicators to be included → scroll/pan to load all desired historical bars (export only includes bars currently loaded into the chart, not the full available history) → open the chart's "⋮"/export menu → "Export chart data..." → choose which series/indicators to include and timestamp format (**ISO** human-readable or **Unix** timestamp) → Export downloads a `.csv`.
- **Contents**: OHLCV (Open/High/Low/Close/Volume) per bar plus values of any visible indicators; drawings/annotations are **not** included in the export — pure tabular price/indicator data only.
- Separately, **Pine Strategy backtest reports** have their own CSV/XLSX export capability (Section 3.4), gated at a different (higher) tier than plain chart-data export.
- Relevance to CandleViewer: confirms TradingView's own OHLCV export is bar-window-limited and indicator-only (no raw tick/order-book export) — reinforcing that CandleViewer's own Bybit-tick-level data pipeline is a genuine differentiator vs. what TradingView itself offers for data portability.

### 6.7 Screener and screener-to-chart integration (gap-fill, new section)
- TradingView's Screener (Stock, Forex, Crypto, ETF, Bond screeners) is presented as a first-party, chart-adjacent feature: clicking any row in a screener result table opens/updates a live chart for that symbol in the same workspace, with full drawing/indicator/style capability retained — no separate app or reload required. Source: [TradingView Screeners walkthrough](https://www.tradingview.com/support/solutions/43000718885-tradingview-screeners-walkthrough/).
- Screener panels are accessible from the top navigation menu and from a right-sidebar widget while a chart is open, letting users filter (e.g., by volume, market cap, technical-rating columns) and click through to chart the filtered symbol without leaving the charting view.
- Custom/user-defined columns (adding indicator values, fundamentals, or Pine-based custom screener columns) are supported, though exact column-count limits per pricing tier were **not confirmed** in this pass (flagged below).
- For developers: TradingView's **Charting Library** (Advanced Charts / embeddable product) documents APIs for building similar screener-to-chart linkage in a custom app, and a community/official-adjacent Python package (`tradingview-screener` on PyPI) exposes TradingView's screener data via its API for programmatic use outside the web UI.
- Scoping note for CandleViewer: since CandleViewer is crypto-only, single-user/small-account-manager-team, and Bybit-only for now, a full multi-asset screener is likely out of scope, but the **click-through-from-filtered-list-to-chart** interaction pattern itself is a reusable, low-cost UX pattern (e.g., filtering the user's own watchlist/open-positions list by a simple metric and clicking through to load a chart).
- Sources: [TradingView Screeners walkthrough](https://www.tradingview.com/support/solutions/43000718885-tradingview-screeners-walkthrough/), [Charting Library integration examples (GitHub)](https://github.com/tradingview/charting-library-examples), [tradingview-screener (PyPI)](https://pypi.org/project/tradingview-screener/)

### 6.7 Templates
- **Chart layout templates**: full saved workspace state (symbols, intervals, indicators, drawings) — count gated per tier (Section 6.1).
- **Indicator templates / custom indicator templates**: save a specific indicator's input+style configuration as a reusable default, gated pricing-table row ("Custom indicator templates").
- **Drawing templates**: save a drawing tool's style as default or named template, and apply in bulk (Section 2.11); Advanced Charts developer docs has a dedicated "Templates" page under the Drawings section confirming this is a first-class, documented capability.

---

## 7. Per-tier limits table (consolidated)

Reconstructed primarily from tradingview.com/pricing "Compare plans" grid (fetched directly) plus corroborating third-party plan-comparison writeups (Pineify, Supa.is, MatchMyBroker, FinancialTechWiz — cross-checked against each other and against the official page where rows overlapped). **Treat this table as approximate** — TradingView revises pricing/limits periodically and third-party sources disagreed on some minor figures (e.g., watchlist alert counts, exact Bar Replay minute-data depth per tier). Always confirm live at https://www.tradingview.com/pricing before relying on any single number.

| Limit / Feature | Basic (Free) | Essential | Plus | Premium | Ultimate |
|---|---|---|---|---|---|
| Monthly price (annual billing) | $0 | ~$12.95 | ~$29.95 | ~$59.95 | ~$199.95 |
| Charts per tab | 1 | 2 | 4 | 8 | 16 |
| Saved chart layouts | 1 | 5 | 10 | unlimited **[verified: blank cell on official pricing grid confirmed via direct re-fetch = no cap shown for Premium/Ultimate, consistent with "unlimited" framing]** | unlimited **[verified, same basis]** |
| Indicators per chart | 2 | 5 | 10 | 25 | 50 |
| Indicator-on-indicator | 1 | 1 | 9 | 24 | 49 |
| Financials per chart | 1 | 4 | 7 | 10 | 25 |
| Simultaneous/parallel chart (data) connections | 2 | 10 | 20 | 50 | 200 |
| Historical bars (intraday) | 5K | 10K | 10K | 20K | 40K |
| Historical intraday data — by minute | none (no minute Bar Replay) | formula: 6 × interval(min) months (e.g. 1-min→6mo, 15-min→90mo) — *corrected from flat "180 days"* | formula: 1 × interval(min) years (e.g. 1-min→1yr, 15-min→15yr) — *corrected from flat "365 days"* | all stored data | all stored data |
| Historical intraday data — by second | — | — | — | all | all |
| Historical intraday data — by tick | — | — | — | — | 7 days |
| Price alerts | 3 | 20 | 100 | 400 | 1,000 |
| Technical alerts | 0 | 20 | 100 | 400 | 1,000 |
| Active watchlist alerts | 0 | 0 | 0 | 2 | 15 |
| Number of watchlists | 1 **[verified]** | "Multiple watchlists" flag shown ✓ but exact count not itemized as a number anywhere on the official pricing page's "Watchlists" row group — the row is a checkmark/blank ("Multiple watchlists") not a count **[verified checkmark-only pattern via direct re-fetch of tradingview.com/pricing]**; third-party sources (MatchMyBroker) independently confirm Basic = exactly 1 watchlist capped at 30 symbols, but no third-party or official source gives an exact numeric cap for paid tiers — **[inferred: likely a high/soft cap, not literally "unlimited," given TradingView caps almost every other quota]** | same as Essential | same as Essential | same as Essential |
| Number of portfolios | 1 | 3 | 4 | 5 | 7 |
| Flagged symbol colors | 1 | 7 | 7 | 7 | 7 |
| Active community contests | 0 | 3 | 5 | 10 | 25 |
| Volume Profile indicators | — | ✓ | ✓ | ✓ | ✓ |
| Volume footprint | — | — | — | ✓ | ✓ |
| Time Price Opportunities (TPO) | — | — | ✓ | ✓ | ✓ |
| Volume candles | ✓ | ✓ | ✓ | ✓ | ✓ |
| Bar Replay | — (per secondary sources; official grid row present but tier cutoff not independently confirmed) | ✓ | ✓ | ✓ | ✓ |
| Trading in Bar Replay | — | — | — | ✓ (inferred) | ✓ |
| Custom time intervals | — | ✓ | ✓ | ✓ | ✓ |
| Second-based intervals | — | — | — | ✓ | ✓ |
| Tick-based intervals | — | — | — | — | ✓ |
| Intraday Renko/Kagi/Line Break/P&F | — | — | ✓ | ✓ | ✓ |
| Customizable chart types (count) | 17 | 17 | 17 | 21 | 21 |
| Extended trading hours | — | ✓ | ✓ | ✓ | ✓ |
| Auto chart patterns | — | — | ✓ (inferred) | ✓ | ✓ |
| Candlestick pattern recognition | — | ✓ (inferred) | ✓ | ✓ | ✓ |
| Deep backtesting | — | — | — | — | ✓ (Ultimate-exclusive per pricing-page ordering) |
| Max market-data subscriptions (paid real-time feeds) | — | 2 | 4 | 6 | more (row truncated in fetch) |
| Ads | shown | none | none | none | none |
| Mobile + desktop apps | ✓ | ✓ | ✓ | ✓ | ✓ |

Where a cell says "inferred," the fetched pricing-page markdown rendered the checkmark/blank ambiguously (checkmarks often render as blank cells when scraped as text) and the value is our best reconstruction from row ordering and third-party corroboration, not a directly confirmed checkmark. See Open Questions.

---

## 8. Mobile parity

No official TradingView Help Center article enumerating an explicit mobile-vs-desktop feature-parity matrix was found even after a further search pass — this remains a genuine documentation gap on TradingView's side, not just a research gap. What **is** confirmed:
- **[verified]** TradingView markets "Web, desktop and mobile apps" as included at every paid tier (pricing page plan summaries), plus Android/iOS home-screen widgets as a separately gated pricing-table row (implying widgets are a paid-tier-only mobile feature, though the exact tier cutoff for widgets specifically was not isolated).
- **[inferred, third-party]** Per a third-party comparison (Supa.is, "TradingView Desktop App vs Web Browser," 2026-04-13): core charting engine, Pine Script editor, alerts, and broker integrations are described as "Identical" across desktop-app vs. web-browser (both are the same underlying web app; the desktop app is an Electron wrapper), and cross-device sync (layouts, watchlists, indicators) is confirmed via account sync. This source only compares **desktop app vs. web**, not **mobile app vs. web/desktop** — mobile parity itself is still unaddressed.
- **[inferred, third-party — user reviews, not authoritative]** Apple App Store reviews for the TradingView iOS app (apps.apple.com/gb/app/tradingview-track-all-markets) describe real limitations: watchlist UI reported as slow (one reviewer: 20–30s load even for a 10-symbol list on a recent iPhone); inability to add/remove a symbol across multiple watchlists from the chart screen (can only manage the watchlist currently open); users request a checkbox-list view to add a symbol to several watchlists at once. These are user complaints, not documented parity gaps, and may be stale/fixed by the time of implementation — treat as anecdotal signal only, not a spec.
- **[inferred, third-party]** MasterTrust's mobile guide (non-official) describes TradingView Mobile as supporting advanced charting (zoom/scroll/multiple indicators), custom watchlists synced across devices, and Paper Trading on mobile — consistent with "most desktop features are present," but again not an official parity matrix.
- **Net assessment for CandleViewer**: since CandleViewer is a from-scratch build (not reusing TradingView's stack), the practical takeaway is to design the React frontend mobile-responsively from day one rather than trying to replicate a specific TradingView mobile/desktop split — TradingView itself doesn't appear to formally document or guarantee an exact parity contract between its own mobile and desktop products.

---

## 9. Key third-party/community context (not official TradingView claims, included for engineering context only)
- Community Pine scripts attempt to approximate footprint/order-flow analytics (e.g., `ta.requestVolumeDelta()`-based scripts) because, per one community source (toolkit4trading.digitalpress.blog), TradingView historically restricted true tick-level order-flow analysis in Pine Script, pushing script authors toward Volume-Profile-style intrabar reconstruction approximations rather than genuine bid/ask tape data. TradingView's own native "Volume footprint" chart type (Section 1.3/1.4), shipped May 2024, is a first-party answer to this gap, built on tradeable/quoted intrabar data rather than raw tick-level bid/ask feed reconstruction — still distinct from a true DOM-based order-flow footprint (e.g., what DeepCharts/Volumetrica or Bookmap provide from raw exchange order-book/tape data). This is directly relevant to CandleViewer's goal of replicating DeepCharts' footprint/Deep Print fidelity — TradingView's footprint chart is not a like-for-like technical benchmark for a from-scratch Bybit-order-book-driven footprint implementation.

---

## 10. TradingView vs. DeepCharts — explicit gap comparison (new section, per critic feedback)
This section exists specifically to baseline TradingView's order-flow/regime capabilities against the DeepCharts feature set named in CandleViewer's project scope (Deepchart, DeepDOM, DeepGamma, footprint/Deep Print, Deep Profile, Deep Stats, Big Trades, imbalance tracker, speed of tape, VWAPs, liquidity heatmap/tracker, stoprun/iceberg detector, market regime, tick replay/backtester). Findings are necessarily asymmetric — this pass researched TradingView in depth, not DeepCharts itself (a dedicated DeepCharts-side research doc would be needed for a full side-by-side; see Open Questions).

| DeepCharts feature (project scope) | TradingView equivalent found | Verdict |
|---|---|---|
| Footprint / Deep Print | Volume footprint chart type (Section 1.3–1.4), Premium+ | Partial — bar/price-level bid-ask distribution exists, but built from *reconstructed intrabar volume*, not raw exchange tape/order-book data (Section 9) |
| DeepDOM (liquidity heatmap on the order book) | No dedicated liquidity-heatmap feature found; TradingView's pricing table has a gated "Depth of Market (DOM) trading" row (basic DOM ladder for supported brokers) but no heatmap-style visualization was located in this pass | **Gap** — TradingView lacks a DOM heatmap; flagged as a dedicated follow-up topic (Open Q #4, pre-existing) |
| DeepGamma (options gamma exposure view) | Not found; TradingView's product is not options-order-flow-focused, and no gamma-exposure-specific built-in was located | **Gap** — not researched further as CandleViewer is crypto-only (options gamma out of scope), but noted for completeness |
| Deep Profile / Deep Stats | Volume Profile family (Fixed Range, Session, Session HD, Periodic, Visible Range, Auto Anchored — Section 3.3) covers profile-style analysis; no equivalent to a dedicated "Deep Stats" summary panel was found | Partial — profile visualization parity plausible, statistics-panel parity unconfirmed |
| Big Trades / large-print detection | Not found as a discrete built-in; closest analogues are Volume footprint's per-level volume display and community "big trades"/whale-alert-style Pine scripts | **Gap** |
| Imbalance tracker | Volume footprint has built-in imbalance-line highlighting *within* the footprint chart (Section 1.4) | Partial — imbalance detection exists but scoped to the footprint chart type, not a standalone tracker/scanner |
| Speed of tape | Not found | **Gap** |
| VWAPs | Anchored VWAP (drawing tool) and Session VWAP (built-in indicator) both confirmed (Section 3.3) | **Covered** — TradingView has solid VWAP parity |
| Stoprun / iceberg detector | Not found as built-ins; only community Pine scripts attempt these heuristically | **Gap** |
| Market regime | No official built-in "market regime" indicator; only community scripts combining ADX + volatility measures (VIX/ATR) or composite tools like Hurst-exponent/Choppiness-Index classifiers (e.g., "VIX + ADX - Trend or Mean Reversion," "Volatility Regime Classifier [QuantRegime]," "Market Regime Lite" — all community Pine scripts, not first-party) | **Gap** — TradingView provides the *building blocks* (ADX, ATR, Bollinger/Keltner volatility indicators) but no first-party regime classifier; CandleViewer would need to build its own regime logic regardless of TradingView as a reference |
| Tick replay / backtester | Tick Replay exists (Ultimate-only, up to 7 days back, Section 5/7) and Pine Strategy backtesting exists (Section 3.4) — but these are two separate features, not a unified tick-level backtester | Partial |
| Trading terminal | TradingView has broker-integrated trading (chart trading hotkeys, DOM trading row) but this doc did not deep-dive execution/order-management UX | Not assessed in this pass |
| Auto-tracker journal | Not found as a TradingView feature; no automated trade-journal product located | **Gap** |

**Summary**: TradingView's order-flow feature set (Volume footprint, Volume Profile family, VWAP, CVD/Volume Delta) provides a *reasonable baseline* for price/volume-distribution-style analysis, but has **no native equivalents** for DOM heatmaps, speed-of-tape, stoprun/iceberg detection, a first-party market-regime classifier, big-trade/whale detection, or an auto-tracking trade journal — all of which the community fills only partially via Pine Script heuristics built on reconstructed (not raw tape/order-book) data. This confirms the premise behind CandleViewer's scope: replicating DeepCharts' order-flow depth requires building directly against Bybit's own WebSocket trade/order-book feeds rather than using TradingView (even at Ultimate tier) as a feature or data-fidelity benchmark for the order-flow-specific parts of the app. TradingView remains a useful reference for charting UX conventions (layouts, drawing tools, alerts, VWAP/Volume-Profile presentation) but not for the DOM/tape/regime layer.

---

## Sources

- https://www.tradingview.com/pricing/ — official plan comparison grid (Basic/Essential/Plus/Premium/Ultimate), fetched directly
- https://www.tradingview.com/gopro — mirror of pricing/plan comparison content
- https://www.tradingview.com/support/solutions/43000703407-chart-types-available-on-tradingview — official chart types list and categorization, fetched directly
- https://www.tradingview.com/support/solutions/43000726164-volume-footprint-charts-a-complete-guide/ — official Volume footprint chart settings guide
- https://www.tradingview.com/support/folders/43000547460-learn-more-about-chart-types — Help Center folder index of all per-chart-type articles
- https://www.tradingview.com/blog/en/new-chart-type-volume-footprint-44399 — official blog post announcing Volume footprint chart type, May 14, 2024
- https://www.tradingview.com/support/solutions/43000703396-drawing-tools-available-on-tradingview/ — official drawing tools categorization (trend, channels, Gann/Fib, patterns, forecasting, shapes, annotations)
- https://www.tradingview.com/charting-library-docs/latest/ui_elements/drawings/Drawings-List/ — Advanced Charts developer docs, complete drawings list (mirrors web product's tool set)
- https://www.tradingview.com/charting-library-docs/latest/ui_elements/drawings — Advanced Charts docs, drawing feature set overview (style customization, toolbar, favorite tools, custom restrictions, templates, Drawing API)
- https://in.tradingview.com/support/folders/43000547459-how-to-use-various-drawing-tools — Help Center India mirror, exhaustive list of every individual drawing-tool help article (confirms full tool roster)
- https://www.tradingview.com/support/folders/43000587408-volume-profiles — Help Center folder: Volume Profile family (Fixed Range, Session, Session HD, Periodic, Visible Range, Auto Anchored)
- https://www.tradingview.com/support/solutions/43000712747-bar-replay-how-and-why-to-test-a-strategy-in-the-past — official Bar Replay guide: multi-chart mode, session restore, historical depth rules, hotkeys
- https://optimusfutures.com/blog/tradingview-synchronized-bar-replay-new-feature-alert — third-party coverage confirming Sept 2024 Synchronized Bar Replay launch date and mechanics
- https://www.tradingview.com/charting-library-docs/latest/trading_terminal — Advanced Charts "Trading Platform" docs: multi-chart layout (up to 8 in that library), sync axes, watchlist widget
- https://www.tradingview.com/support/solutions/43000761094-how-to-sync-selected-charts — official guide to emoji-tag chart grouping/sync
- https://www.tradingview.com/support/solutions/43000629992-how-to-sync-the-charts-of-my-layout — official guide to global layout sync (symbol/crosshair/interval/time/date range)
- https://www.tradingcode.net/tradingview/keyboard-hotkeys — third-party but detailed hotkey reference (general chart, zoom, chart trading, drawing, indicator/script, watchlist, screener, Pine editor)
- https://www.tradingview.com/support/solutions/43000623399-hotkeys — official Help Center hotkeys article (desktop app window/tab management scope)
- http://tradingview.com/support/solutions/43000480679-historical-intraday-data-bars-and-limits-explained — official explanation of historical intraday bar limits by tier (5K/10K/20K/25K/40K)
- https://pineify.app/resources/blog/compare-tradingview-plans — third-party plan comparison (2026), cross-checked against official pricing page
- https://supa.is/article/tradingview-essential-vs-plus-vs-premium-which-plan-2026 — third-party plan comparison with more granular free-tier and Bar-Replay-by-minute-depth breakdown
- https://www.matchmybroker.com/tools/tradingview-review — third-party review citing official pricing page limits (Basic tier detail: 1 watchlist/30 symbols, 1 portfolio/20 holdings)
- https://www.financialtechwiz.com/post/how-much-is-tradingview — third-party 2026 pricing roundup, cross-checked
- https://github.com/akmoy655/tradingview — third-party 2026 pricing summary (used only for cross-checking numeric limits, not as primary source)
- http://www.xn--4kqz9dx34aeea.net/indexb842.html — appears to be a mirror/scrape of TradingView's own pricing page copy; used only to cross-check specific feature-flag wording (e.g., "alerts that don't expire," "second-based intervals") not fully visible in the primary fetch
- https://www.tradingview.com/support/solutions/43000725058-cumulative-volume-delta/ — official Help Center article confirming CVD is a built-in, first-party indicator (resolves prior Open Q #2's CVD ambiguity)
- https://www.tradingview.com/blog/en/second-based-timeframes-are-now-supported-13588/ — official blog post launching seconds-based intervals (1/5/10/15/30/45s), gated to Premium+
- https://www.redditmedia.com/r/TradingView/comments/1k4inrn/does_the_plus_plan_include_the_30_second_timeframe/ — user-confirmed that Plus plan lacks seconds intervals (corroborates Premium+ gating)
- https://in.tradingview.com/support/solutions/43000543053-how-to-use-the-compare-tool/ — official guide to the Compare tool vs. Add Symbol/Overlay distinction
- https://www.tradingview.com/support/solutions/43000692816-how-much-data-is-available-for-bar-replay/ — official Help Center article with exact Bar Replay minute-data depth formulas by tier (corrects prior flat 180/365-day figures)
- https://www.tradingview.com/support/solutions/43000718885-tradingview-screeners-walkthrough/ — official Screeners walkthrough (screener-to-chart integration)
- https://github.com/tradingview/charting-library-examples — official Charting Library integration examples (screener/table + chart sync patterns for embeddable product)
- https://pypi.org/project/tradingview-screener/ — third-party Python package for programmatic screener data access via TradingView's API
- https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/ — official Help Center guide to CSV/OHLCV chart data export
- https://www.tradingview.com/blog/en/export-chart-data-in-csv-14395/ — official blog post announcing CSV chart-data export feature
- https://www.kotakneo.com/stockshaala/trading-view/exporting-charts-for-sharing-analysis/ — third-party guide on PNG chart image export/resolution behavior (no official Help Center article specifically on export-resolution limits was located)
- https://www.tradingview.com/support/solutions/43000696403-alerts-separation-by-type/ — official Help Center article on the three alert-condition categories (price/indicator/drawing) and their condition-type vocabulary
- https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/ — official Help Center guide to webhook alert configuration, restrictions (ports 80/443 only, no IPv6, 3s timeout, 2FA required)
- https://www.tradingview.com/support/folders/43000560150-webhooks-usage/ — official Help Center folder, webhook usage/troubleshooting
- https://fxnewsgroup.com/forex-news/platforms/tradingview-introduces-volume-footprint-chart-type/ — third-party news coverage corroborating the May 14, 2024 Volume footprint release date
- https://www.tradingview.com/script/CtXh25MQ/ ("VIX + ADX - Trend or Mean Reversion"), https://www.tradingview.com/script/zagpmoKH-Volatility-Regime-Classifier-QuantRegime/, https://in.tradingview.com/script/YRDJGi8r-Market-Regime-Lite/ — community (non-official) Pine Script examples cited only to establish that TradingView has no first-party market-regime classifier (Section 10)
- https://www.tradingview.com/support/folders/43000587405-built-in-indicators — official Help Center folder, full_content fetch, itemized list of all ~195+ built-in indicator article titles (resolves Open Q #2 — full catalog now compiled in Section 3.2)
- https://www.tradingview.com/support/categories/indicators/ — official Help Center category page confirming folder article counts ("Built-in Indicators 209 articles")
- https://www.tradingview.com/pricing — re-fetched directly (full_content) to re-verify charts-per-tab, watchlist-count row structure ("Multiple watchlists" flag not a number), and saved-layout counts (Section 7)
- https://supa.is/article/tradingview-desktop-app-vs-web-browser-which-version-2026 — third-party 2026 desktop-vs-web comparison (used only for the desktop/web parity claim in Section 8; does not cover mobile)
- https://apps.apple.com/gb/app/tradingview-track-all-markets/id1205990992 — official iOS App Store listing; used only for user-review-sourced anecdotal mobile watchlist-performance complaints (Section 8), not as an authoritative spec
- https://www.mastertrust.co.in/blog/tradingview-mobile-secrets — third-party mobile feature overview, low authority, corroborating only

---

## Open questions

1. **Exact tier cutoffs for several gated rows** (Bar Replay availability on Basic/free plan; "Trading in Bar Replay"; "Auto chart patterns"; "Candlestick patterns recognition"; "Custom indicator templates"; watchlist count per paid tier) were ambiguous in the scraped markdown of tradingview.com/pricing, where checkmarks often render as blank table cells rather than explicit "yes"/"no" text. Needs a follow-up fetch that either renders the page visually (screenshot) or targets TradingView's structured pricing API/JSON if one is publicly inspectable, to get unambiguous per-row, per-tier checkmarks.
2. ~~Full built-in indicator catalog with exact count~~ — **resolved this pass**: fetched the official Help Center "Built-in Indicators" folder directly (full_content) and compiled the complete itemized list (~195 titles, grouped by category) in Section 3.2. The "400+ pre-built" marketing figure is not fully reconciled to this exact count (likely counts sub-variants/aliases not separately titled) — noted as a residual minor discrepancy, not a gap.
3. ~~Mobile app feature parity~~ — **partially resolved this pass**: still no official TradingView Help Center parity matrix found (confirmed absent after a dedicated follow-up search). Section 8 now documents what corroborating third-party/anecdotal evidence exists (desktop-vs-web parity claims, App Store review complaints about mobile watchlist performance) but a true official parity matrix does not appear to exist publicly — treat this as resolved-as-a-genuine-gap rather than an open research task.
4. **DOM / Depth of Market feature depth** — the pricing table confirms "Depth of Market (DOM) trading" exists as a gated feature; Section 10's gap comparison confirms no DeepDOM-style heatmap was found, but a dedicated DOM/order-book feature deep-dive (ladder trading controls, exact heatmap depth if any) remains a follow-up research topic (separate doc).
5. ~~Historical minute-data replay depth per tier~~ — **resolved**: official Help Center article (support/solutions/43000692816) gives exact formulas (Essential: 6× interval-minutes = months; Plus: 1× interval-minutes = years; Premium/Ultimate: all stored data; Ultimate tick replay: 7 days). Section 5 and the Section 7 table corrected accordingly.
6. **Advanced Charts "8 charts per layout" vs. main web app "16 charts per tab" discrepancy** — confirmed these are different products (embeddable/white-label charting library vs. the consumer web app), but the exact relationship/version parity between them was not fully explored; worth clarifying for CandleViewer since Advanced Charts / Charting Library concepts (Drawings API, multi-pane, etc.) may be more directly relevant as an *architecture reference* than the consumer product limits.
7. **Legacy/older chart types possibly deprecated** (e.g., "Equivolume," seen in an unrelated third-party open-source project's chart-type list, not confirmed as ever offered by TradingView itself) — should not be assumed part of TradingView's feature set; flagged to avoid false attribution.
8. **Indicators-per-chart and indicator-on-indicator exact figures (2/5/10/25/50 and 1/1/9/24/49)** — re-searched; multiple independent third-party 2026 sources (PineScripter, TradeProperly, ImpactWealth) still converge on the same 2/5/10/25/50 figures, which corroborates but does not constitute a direct official-page citation; treat as **highly likely correct but still not a primary-source screenshot/quote** — unresolved in the strict sense requested.
9. **Exact "number of watchlists" per tier** — **re-confirmed still unresolved this pass** (re-fetched tradingview.com/pricing directly): the official grid only shows a "Multiple watchlists" checkmark row, never a numeric count for any paid tier. This is a genuine gap on TradingView's own public page, not a research-tooling limitation — no further official source exists to resolve it short of an authenticated account test. Basic = exactly 1 watchlist (confirmed), symbols-per-watchlist and watchlist-alert quotas remain as previously corroborated.
10. **Screener column-count limits per tier, and SMS notification channel availability/region-gating** — not confirmed in this pass; flagged as new unresolved items from the screener and alerts gap-fill work.
11. **DeepCharts' own feature depth (Section 10 comparison)** — this pass only re-verified the TradingView side; a dedicated DeepCharts-focused research document (per the project's own multi-doc research plan) would be needed to make Section 10's "Gap" verdicts fully rigorous rather than "not found on TradingView's side in this pass."
