# DeepCharts — DeepDOM, DeepGamma, and helpdesk deep-crawl

> Research artifact for CandleViewer (research phase only). Crypto-only, Bybit-first, self-hosted TradingView/DeepCharts alternative for one user plus a few account managers.

Crawl date: 2026-09-13/14. DeepCharts marketing pages carry auto-generated "published" timestamps (Sep 1-12, 2026) that update on every render; treat as "live", not a real version date.

## 1. Company / product structure

- DeepCharts (deepcharts.com) is a white-label front end built on Volumetrica technology (volumetricatrading.com). The Volumetrica homepage explicitly lists "Deepchart" and "DeepDom" as two of its own product lines, confirming DeepCharts licenses/rebrands the Volumetrica engine (the VolBook/DOM family) rather than building an independent stack. Source: https://volumetricatrading.com/en/index
- DeepCharts is split into three commercial products:
  1. Deepchart - footprint/orderflow charting (candlesticks, footprint, Delta Profile, TPO) - the base platform.
  2. DeepDOM ("DeepDom") - the liquidity-heatmap / DOM / MBO-indicator product, sold standalone or bundled.
  3. DeepGamma - options gamma-exposure (GEX) overlay, native to Deepchart, SPX/CBOE-data specific.
- Underlying data plumbing distinguishes MBP (Market By Price - aggregated depth per level) from MBO (Market By Order - individual order-level data with persistent order IDs), fed via dxFeed and Rithmic for futures brokers. MBO is required for the Iceberg Detector, Stop Run Detector, and other "smart money" tools. Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/heatmap
- Desktop app, Windows only per the DeepDOM pricing page. No web/Mac/Linux client identified for DeepDOM specifically.

## 2. DeepDOM pricing (at crawl date)

Source: https://www.deepcharts.com/pricing/deepdom

| Plan | Price | Billing | Notes |
|---|---|---|---|
| DeepDom | $39/month | Also quoted as "$468/Yearly" | Terms offered: 1 Month, 3 Months, 6 Months, 1 Year, Lifetime Addon. Windows only. |

Included in the DeepDom plan (single bundle, no internal feature tiers found):
- DeepDom Heatmap
- Liquidity Tracker
- Stopruns (Stop Run Detector)
- Iceberg Detector
- Market Regime
- Deep Reload
- MBO Indicators (bundle)
- Backtester and Journal
- Bonus extras: Orderflow Mastery Course, VIP Discord Chat

DeepGamma pricing (from https://www.deepcharts.com/features/deepgamma): the marketing page renders as a comparison ladder against "Other GEX Solutions" and "Other Orderflow Platforms"; the only clearly DeepCharts-attributable figure is "From $46/month" for Cboe 1-minute data with native orderflow-chart integration and orderflow+options backtesting. Rows citing "$250/month" and "third-party tools only" read as competitor-comparison rows in the copy, not confirmed DeepCharts price points - see Open Questions.

## 3. DeepDOM feature grid overview (from pricing/deepdom feature list)

The DeepDOM pricing page (https://www.deepcharts.com/pricing/deepdom) lays out its features in five groups. Reproduced and organized below (marketing copy, lightly cleaned):

### 3.1 MBO Features (require the MBO add-on/feed)

- Iceberg Detector (onchart) - automatically spots when a Native Iceberg is being loaded on the book to absorb aggressors.
- Stoprun Detector (onchart) - automatically spots when a stop run is happening in the market and stop orders are sweeping the book.
- Stop/Iceberg Tracker (cumulative) - a cumulative line chart with one line dedicated to stop activity and one to iceberg activity.
- MBO Replay ("2 weeks and counting", i.e. in development) - replay with MBO data to backtest the most granular orderflow details.
- Big Passive Trade - filters and highlights the biggest trades in the book on an order-by-order basis.

### 3.2 DeepDom Indicators

- Deep Reload - automatically detects if the book is being reloaded with fresh directional liquidity to support the current move.
- Market Regime - analyses the current clustering of liquidity to assess the potential volatility regime of the current session.
- Deep Liquidity Scan - tracks the cumulative level and variation in book thickness for both Bid, Ask, and their Delta.
- Deep Trades - Volume Bubbles filtered by size, to spot only the biggest orders from "smart money".
- Book Speed - tracks the speed of the book to assess the current market regime (calm or nervous); used for qualifying breakouts and volatility.
- Absorption - (marketing copy duplicates the Book Speed description verbatim: "Tracks the speed of the book to assess the current market regime (calm or nervous). Use it for qualifying breakouts and volatility." This looks like a copy/paste error on DeepCharts' own site - the actual Absorption mechanic is not independently described anywhere in the crawled pages. Flagged in Open Questions.) [Verified via direct re-fetch 2026-09-14 of deepcharts.com/pricing/deepdom: the duplication is confirmed still present on the live page as of this crawl — this is not a copy error introduced by the earlier research pass but an actual, ongoing error on DeepCharts' own marketing page. Still unverified what Absorption's real, distinct behavior is.]

### 3.3 Volume Indicators

- Deep Profile - volume profile in all variants (volume, delta, bid/ask) beside the heatmap; resettable, fixed, daily, weekly modes.
- CVD (Cumulative Delta) - cumulative delta of aggressive flow, histogram or line, customizable per metric.
- VWAP and Envelopes - daily/weekly/custom developing VWAP with standard-deviation bands/envelopes.
- Classic Volume - volume-by-time indicator, per tick/time/candle.
- DeepDelta - proprietary "Delta-Filtered Bars" isolating the delta that matters at each price move.

### 3.4 General Features

- DOM Liquidity Heatmap - customizable in color, intensity, contrast, MBO highlights, and market-maker filters.
- Aggressive Orderflow Bubbles - customizable bubbles of aggressive orders (2D/3D, grouping factor, size, etc.).
- Deep Replay (all current contracts) - replay every order (passive and aggressive) tick-by-tick in the past; backtest and auto-track metrics.
- Volumetrica Bridge - same data-feed bridge used for Deepchart; no separate feed needed to connect broker/prop firm to both products.
- Trading Terminal - professional terminal with OCO strategies, trade/manage orders directly on the heatmap.
- Automatic Metrics Journal - tracks SIM/prop/real trading and replay/backtest trades automatically.
- 24-hour Backfill Data - up to 24h of historical DOM data pre-loaded when a chart opens.
- Classic Advanced DOM - traditional price-ladder DOM view for book scalpers who want both views.
- Times & Sales - legacy tape indicator showing every traded volume at time and price.
- Important Levels - daily highs/lows, VWAPs, POCs plotted on-chart.
- Candlesticks - normal candlestick overlay of any timeframe on top of the heatmap.

### 3.5 "Why DeepDom" comparison claims (marketing page, features/deepdom)

DeepCharts markets DeepDOM against "Other Heatmaps" with these bullet claims:
- Easy on the CPU / Easy to use
- Advanced Backtester
- "0.01s Precision" (the pricing/marketing copy states 0.01s in one place and the research brief cites a 0.015s refresh claim seen elsewhere - see 4.1 below for the more precise 0.015s figure found on a third-party review site)
- Stop Run / Market Regime included by default, vs. competitors who gate the MBO Bundle, Iceberg Tracker, and Stop Run Indicator behind extra paid add-ons ("Gotta pay extra $" - explicit dig at competitor pricing, most likely Bookmap, given Bookmap's known add-on pricing model for MBO features).

## 4. Per-feature detail tables (settings, visuals, data requirements, Bybit feasibility)

### 4.1 Heatmap (core DeepDOM feature)

Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/heatmap and https://www.deepcharts.com/helpcenter/deepdom/article/heatmap

**What it is (verbatim synthesis):** "The Heatmap is the core of DeepDom and the reason the platform exists in the first place. Every other tool - the DOM, Bubbles, CVD, VWAP - adds context and confirmation. But the Heatmap is where you see the full picture of market intent laid out visually across both price and time simultaneously." Each horizontal band of color is a concentration of resting limit orders at that price level, recorded and replayable over time.

**How to read the colors:**
- Red = highest liquidity concentration
- Orange = second highest
- Yellow, White, Blue, Black = progressively thinner liquidity
- Colors are **relative/adaptive**: "These colors adjust automatically to current market conditions. If a new large limit order appears, the entire color scale shifts to reflect the new context."
- Separately, **Buy vs Sell limit color-coding**: Green = Buy Limit (bids) below price; Violet = Sell Limit (asks) above price. corrected: re-fetched directly 2026-09-14 — no page could be found stating the reverse ("green = Sell Limit, red = Buy Limit"). The Heatmap article itself, the DeepDOM "Trading from the Chart" article, and the general beginner-guide blog post all consistently state Green = Buy Limit/Bid, Purple/Violet = Sell Limit/Ask. The originally-cited "color-scheme inconsistency" claim appears to have been a fabrication or misreading of the earlier research pass — there is no confirmed discrepancy; the Open Questions entry below should be treated as resolved (no inconsistency found), not as an open item.

**Fresh vs. Persistent liquidity concept** (a key interpretive layer, not a toggle):
- *Fresh liquidity* = orders that just appeared in the book; signals new intent but more likely to be pulled/cancelled before price arrives (potentially "spoof"-like or reactive).
- *Persistent liquidity* = orders resting for a long time without cancellation; signals genuine committed positioning, more likely to produce a strong/sustained reaction when price reaches it.
- Best setup per DeepCharts: persistent + fresh liquidity both building at the same level simultaneously.

**Source Settings (MBP vs MBO):** Right-click chart -> Source Settings lets you choose whether a given chart panel is fed by MBP (Market By Price - standard combined depth per level) or MBO (Market By Order - granular per-order data). This choice **directly gates which DeepDom features are available** on that chart (Iceberg/Stop detection require MBO).

**History depth (resolved 2026-09-14, [verified]):** Direct re-fetch of https://helpdesk.deepcharts.com/portal/en/kb/articles/heatmap confirms explicit wording: "By default, the chart loads with one hour of liquidity history" - i.e. the Heatmap's own default history window is **1 hour**, distinct from (and shorter than) the general "24-hour Backfill Data" feature described in section 3.4. The article also states DeepDom "supports analysis of over 1,000 book levels" (depth, not history) and that Level 2 market depth from the data feed is required to access this at all.

**Refresh rate discrepancy - resolved 2026-09-14 [verified]:** Multiple distinct, non-conflicting figures were found across DeepCharts/Volumetrica-family products, meaning the "0.01s vs 0.015s" tension in the prior research pass was likely a conflation of different settings/products rather than one true number:
- deepcharts.com/pricing/deepdom marketing page: "0.01s Precision" (unqualified, likely a rounded marketing figure for the underlying feed/tick precision, not a UI redraw rate).
- deepcharts.com/helpcenter/deepdom/article/general-settings (DeepDOM's own **Refresh Time (MS)** setting, [verified] via direct fetch): **Chart** refresh default = **50ms** (chart "refreshes 20 times per second"), user-adjustable up/down; **Time & Sales** panel refresh default = **300ms**. Explicitly framed as a responsiveness-vs-CPU/RAM tradeoff.
- deepcharts.com/features/deepchart marketing copy [verified]: DOM/order-book "0.25s refresh rate" is stated for the **DOM scalping** feature specifically ("Our super-fast Orderbook (Depth Of Market) with a 0.25s refresh rate").
- FlowMatriX/DeepWatch (a comparable Volumetrica-family/competitor heatmap product, cross-reference only, [inferred] as directionally similar architecture): "The heatmap is built one column at a time, every 50 milliseconds," matching DeepDOM's own 50ms chart-refresh default almost exactly.
- Conclusion: no single DeepCharts page states "0.015s" verbatim in this crawl; the actual, KB-documented, user-configurable default is **50ms for the chart/heatmap redraw** and **300ms for Time & Sales**, with a separately-marketed "0.25s" figure for DOM/orderbook refresh and an unqualified "0.01s Precision" marketing claim whose exact referent (tick timestamp precision vs. UI redraw) remains unclear. Treat "0.015s" as unconfirmed/likely erroneous going forward.

**Other configurable elements found in the Heatmap KB article (from sliders/settings text captured mid-crawl):**
- Liquidity Contrast slider - adjusts contrast of liquidity colors
- Top Contrast slider - adjusts contrast ceiling
- MBO Filters (when MBO source selected): Filter Volume (min threshold for a bubble to appear), Filter Bubble (min size for individual bubble), Out Std Dev Perc, Std Dev Val (both scale bubble sizing statistically), Volume Mode Color (coloring mode, e.g. "Delta Absolute" and others)
- CVD plot settings embedded in the same panel: Period Value, Show Bid/Ask Volume, Delta Bid/Ask Color, Volume Ask/Bid Color, Line Width
- Resettable Profile (labelled "RES. P." in the settings tree) - lets you start measuring volume distribution from any moment
- "Enable Chart DOM" - overlays a DOM panel directly on the chart; "Clear Recent Filled" - clears recently filled order markers; "Settings Column Order" - configures DOM column layout

| Parameter/Setting | Effect | Data need | Bybit feasibility |
|---|---|---|---|
| Liquidity Contrast / Top Contrast sliders | Visual scaling only | none extra | Trivial - client-side rendering parameter |
| Color scale (Red-Orange-Yellow-White-Blue-Black) | Relative concentration coloring, auto-rescaling to current book | Requires per-price-level resting size history | Feasible - Bybit L2 WS (`orderbook.{depth}.{symbol}`) gives per-level bid/ask sizes; need to persist a rolling history buffer server-side to paint the heatmap over time |
| MBP vs MBO source toggle | Governs which advanced tools are active | MBO feed | Not available from Bybit public API (aggregated MBP only) - CandleViewer's heatmap should always be "MBP-equivalent" mode; iceberg/stop detectors must be built as proxies (see 4.4, 4.5) |
| Fresh vs Persistent liquidity classification | Interpretive overlay distinguishing new vs long-resting orders | Needs per-price-level "time since order first appeared/last changed" tracking | Feasible as a derived metric: track how long a given price level's aggregate size has remained above a threshold using L2 delta stream, without needing per-order IDs |
| 24h Backfill | Preloads up to 24h historical DOM on chart open | Requires storing L2 snapshots/deltas continuously | Feasible - CandleViewer backend can run a persistent WS listener + time-series store (e.g. into a local DB) to reconstruct historical heatmap frames |

### 4.2 DOM ladder / Advanced DOM

Source: https://www.deepcharts.com/helpcenter/article/depth-of-market (Deepchart's "Advanced DOM") and https://www.deepcharts.com/helpcenter/deepdom/article/trading-from-the-chart (DeepDOM's "Chart DOM" - a second, related but distinct ladder embedded directly on the price chart). Both re-fetched directly 2026-09-14, [verified].

**Opening the Advanced DOM:** New -> Book -> ADV DOM -> select subscribed instrument -> Select.

**Advanced DOM default column layout (left to right):** P&L (profit/loss per tick), B (buy order-management column), Bid (limit buy placement), Price (central ladder), Ask (limit sell placement), S (sell order-management column), VP (Daily Volume Profile).

**Chart DOM default column layout (left to right, distinct ladder embedded on-chart) [verified]:** B.PS (Bid Pull/Stack - quantity added/removed at each Bid level), B (buy order-management column), Bid (buy-limit orders per price level), Ask (sell-limit orders per price level), S (sell order-management column), A.PS (Ask Pull/Stack - quantity added/removed at each Ask level).

**Click-trading mechanics on the DOM [verified, from Advanced DOM article]:**
- Top info panel exposes an explicit order-type toggle: **Automatic / Limit / Market / Conditional**.
- In **Automatic** mode, the order type placed is determined by mouse button + click position relative to current price:
  - Right-click Bid -> Buy Market; Right-click Ask -> Sell Market.
  - Left-click Bid below price -> Buy Limit; Left-click Bid above price -> Buy Stop.
  - Left-click Ask above price -> Sell Limit; Left-click Ask below price -> Sell Stop.
- Pending-order management directly on the ladder: Left-click & drag -> move order; Right-click -> delete order; Double left-click -> modify quantity.
- Chart DOM variant restates the same click grammar explicitly per side: Buy Market = right-click Bid column; Sell Market = right-click Ask column; Buy Limit = left-click Bid below price; Buy Stop = left-click Bid above price; Sell Limit = left-click Ask above price; Sell Stop = left-click Ask below price. Modify/cancel: drag with left mouse button on the B/S order-management columns to reprice; right-click to cancel; double left-click to edit quantity.

**Pull/Stack columns (liquidity-change visualization) [verified]:** B.PS/A.PS show changes in resting size at each level as it happens: green = quantity added, red = quantity removed on the Bid side (B.PS); color logic reversed on the Ask side (A.PS) per the Advanced-DOM article's "Pull/Stack Columns" section.

**Trades columns:** BT = volume sold at market (aggressor sell hitting bid), AT = volume bought at market (aggressor buy lifting ask). Offers columns show the number of individual discrete orders resting at each bid/ask level (an MBO-only figure, since MBP by definition aggregates individual orders into one size total).

**Centering / aggregation, Chart DOM settings panel [verified]:** Settings icon opens Font size, Text format, and per-column appearance controls: Bid/Ask Columns (background/text color), Pull Stack Columns (enable, filter mode = average or none, colors), Filled filter (hide small executed quantities), Bid/Ask Filled (B.T/A.T columns showing executed volume, forming a footprint view; auto-reset on price swing or manual reset), Last Filled (last-trade column), Order View (show/hide order-management columns + colors), Price Scale (enable/customize the price-ladder column itself), P/L Column (tick-by-tick unrealized P/L when a position is open), Markers (last-traded-price, open, high, low), Column Order (rearrange DOM columns).

**Top information panel (Advanced DOM):** Selected instrument, connected broker, active trading account, open position quantity, daily P&L; a **Fundamentals Table** below shows % change from previous close, change from session open, total traded volume, number of trades (stocks only), upper/lower suspension prices.

**Order quantity & trading controls (bottom of Advanced DOM):** set order quantity, classic trading buttons (click-to-trade from ladder), OCO (Order Cancels Order) strategy toggle.

**Profiles/Volume configuration (header row):** Add Volume, Delta, or Bid/Ask profile columns. Volume Profile types: Resettable Profile (starts recording when enabled, clearable via eraser icon) and Daily Profile (from start of session).

**Customization (gear icon, top-left):**
- Enable/disable sections to simplify the DOM
- Order Column Settings - reorder columns
- Chart DOM Settings - customize text/colors/background; enable markers for High, Low, Open, Suspension levels
- Number of Levels Show (DOM Settings) - e.g. set to 20 to show only 20 depth levels, or leave unrestricted for full feed depth
- Layout Templates (Model section) - save/load custom DOM layouts
- Vertical Scale (Price column) - right-click for auto-recognition mode / manual scale management (this is DeepDOM's ladder-centering mechanism: auto-recognition re-centers the ladder on the live price; manual mode fixes the visible price range)
- Custom Time Session (Exchange Time Zone) - Enable custom session; Ini Session / End Session times entered in US market time (a futures-market-centric detail that would need adapting for 24/7 crypto - see Open Questions/feasibility)

| Feature | Settings | Data need | Bybit feasibility |
|---|---|---|---|
| Column layout (P&L/B/Bid/Price/Ask/S/VP, or Chart-DOM's B.PS/B/Bid/Ask/S/A.PS) | Reorderable, toggle sections on/off | Position/account data (P&L), L2 book (Bid/Ask/Price), volume profile (VP), per-level size deltas (Pull/Stack) | Fully feasible - Bybit REST/WS gives positions (private WS `position` topic), L2 book, trade history for VP, and per-level delta events natively (Bybit's L2 WS pushes deltas, so add/remove tracking for Pull/Stack coloring is a direct read, not a derived heuristic) |
| Trading from DOM (click-to-trade, Automatic/Limit/Market/Conditional toggle, drag-to-move, double-click-to-modify) | Order qty box, OCO toggle, classic buy/sell buttons, click-position-based order-type inference | Order placement API | Feasible via Bybit REST `/v5/order/create`, `/v5/order/amend`, `/v5/order/cancel`; OCO/conditional via Bybit's native TP/SL and conditional-order (`triggerPrice`/`stopOrderType`) fields on v5 orders. The click-grammar (right-click=market, left-click above/below price=stop/limit) is a pure frontend UX layer with no exchange-specific blocker |
| Offers column (order count per level) | Shows discrete order count per price | MBO (order-level) feed | Not available - Bybit L2 is MBP; CandleViewer cannot show a genuine per-level order count, only aggregate size. Must omit this column or clearly relabel it as unavailable rather than faking a count |
| Centering / auto-scale on price column | Auto-recognition mode (click near current price) vs manual | none extra | Feasible client-side |
| Aggregation / number of levels shown | "Number of Levels Show" setting, e.g. 20 | Full L2 depth then truncate | Feasible - Bybit orderbook WS supports depth tiers 1/50/200/500 (linear) so aggregation-by-truncation is native |
| Custom Time Session | Ini/End session times in US market time | Session config | Needs redesign for 24/7 crypto markets - "session" concept (daily reset time) still useful for daily volume profile resets (e.g. reset at 00:00 UTC) but must not assume a "market open/close" |

### 4.3 Volume Bubbles / Prints on heatmap

Source: https://helpdesk.deepcharts.com/portal/en/kb/deepdom/features (article excerpt) and heatmap-page bubble settings.

**What it is:** Tick-by-tick visual record of every market execution ("print"), plotted directly on the chart at the exact price/time it happened. Color-coded (e.g. blue for market buy, per excerpt fragment "blue for a market buy...").

**Settings captured:**
- Bid Color / Ask Color - colors of bubbles by aggressor side
- Filter Volume - minimum volume threshold for a bubble to appear at all
- Filter Bubble - minimum size for an individual bubble
- Out Std Dev Perc / Std Dev Val - statistical scaling controls for bubble sizing (bubbles sized relative to a rolling standard deviation of trade sizes, so "big" is contextual to recent activity, not an absolute number)
- Volume Mode Color - coloring mode (e.g., "Delta Absolute" and other unspecified modes)
- 2D/3D display, "grouping factors", size scaling (per features/deepdom marketing copy: "Customizable bubbles of aggressive orders. 2D, 3D, groping [sic] factors, size, etc...")

| Data need | Bybit feasibility |
|---|---|
| Tick-level trade prints with aggressor side (buy/sell) and size, nanosecond/millisecond precision claimed by Volumetrica ("nanosecond precision... ideal for HFT analysis") | Feasible at the granularity Bybit provides. Bybit's public trade WS (`publicTrade.{symbol}`) streams each execution with side, price, size, and a timestamp (millisecond resolution) - sufficient for bubble prints, though not nanosecond-precision (Bybit is exchange-side aggregated, not colocated HFT feed) |

### 4.4 Iceberg Detector (Deep Iceberg) - detail

Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-iceberg

Already summarized in section 3.1 table; expanded settings breakdown:

1. **Concept** - an iceberg order is a large limit order where only a small slice is shown in the DOM while the rest stays hidden and auto-replenishes.
2. **Detection method** - Deep Iceberg tracks a resting order's persistent **order ID** across repeated replenishments at the same price, identifying when cumulative traded volume far exceeds the largest single visible slice ever shown.
3. **Visualization** - marker at the traded price; label shows (a) Total executed iceberg volume, (b) Maximum visible size ever shown. An optional horizontal "active iceberg line" persists while the iceberg is still resting.
4. **Data Settings** - Filter min/max (size range to display), Iceberg timeout seconds (max gap before a reload sequence is considered a new/separate iceberg).
5. **Plot Settings** - Marker shape (Circle/Square/Diamond/Triangle/Text), Size unit (Automatic vs Tick), Standard Dev. (selectivity of highlighting), Opacity, Ask/Bid color.
6. **Active Icebergs** - Enable line, Line width, Line style (Solid/Dash/Dot/Dash dot/Dash dot dot), Line remove mode (Stop = freezes the line in place, Disappear = removes it on completion).
7. **Text Settings** - Plot only if inside (view-clipping to reduce overlap), Text size, Text color.
8. **Alert Iceberg** - Enable, Threshold (min iceberg volume to fire an alert).

**Bybit feasibility (expanded):** Genuine iceberg detection as implemented by DeepCharts fundamentally requires knowing that the *same order* keeps reappearing - this needs an order-ID-level (MBO) feed, which no major centralized crypto exchange, including Bybit, exposes publicly for the resting book (exchanges do not reveal counterparty/order identity data for anti-gaming/compliance reasons). A CandleViewer analog could implement a **heuristic reload detector**: track a specific price level's displayed size over time; if it depletes (gets hit by trades) and is repeatedly refreshed back to a similar size within a short window, flag it as a "probable iceberg / persistent replenishment" zone. This is a meaningfully different (weaker) signal than true MBO-based detection and should be labeled as a heuristic/proxy in the UI, not "iceberg detector."

### 4.5 Stop Run Detector - detail

Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/stop-run and https://orderflowfutures.com/en/deepcharts/stop-run-detection (third-party explainer, cross-checked against official KB)

What it is: "The Stop Run indicator shows you on the chart when a large number of stop orders have been triggered in the market. This helps you understand why price suddenly moved fast - and whether that move was real buying or selling, or just a wave of stops being triggered."

When does a Stop Run occur / what to look for (from official KB):
- Sudden volume spike - a big jump in volume with no obvious news reason
- Fast price movement - price moves through a level much faster than a normal move, looking almost like a jump
- Quick reversal after the move - price snaps back shortly after, trapping momentum-chasers
- Order book and Footprint signals - certain price levels suddenly empty out in the DOM as stops get hit; very large aggressive orders appear all at once in the Footprint chart

Third-party (orderflowfutures.com) technical framing: "A stop run is a fast sweep of liquidity beyond an obvious level, triggering the piled-up stops then often reversing. Retail gets stopped out, big players collect the liquidity." "DeepCharts detects it via MBO data: you see orders consumed all at once beyond the level, then the lack of aggressive follow-through - the signature of a sweep rather than a genuine break." Suggested trading approach: "wait for confirmation: sweep then rejection, with no aggressive follow-through. Entry is against the crowd that got stopped out, with a stop on the other side of the sweep. Always with context."

General Settings (official KB):
- Minimum Tick - the minimum number of ticks price must move (as a result of triggered stop orders) before the event is flagged as a Stop Run. Too low means every small move is flagged (noisy); correctly tuned means only meaningful moves get flagged.
- Maximum Ord Num - caps the maximum number of orders the indicator considers during a Stop Run, avoiding over-flagging during extremely busy periods (e.g. right after major news).
- Max MS (milliseconds) - defines how fast the triggered stop orders must fire to be counted as a single Stop Run event; a genuine stop run fires within a tiny fraction of a second, so tightening this (e.g. from 50ms down to 5ms) filters out slower, more organic moves.
- Min. Stop Run Vol. - minimum total volume required to qualify as a Stop Run, filtering out small/insignificant sweep events.

Plot Settings: Ask Color / Bid Color (side-specific coloring), Marker Width (thickness of the marking line).

Text Settings: present in the article but specific sub-options were not fully captured in this crawl (see Open Questions).

Bybit feasibility (expanded): The full MBO-based technique (seeing literal stop-order triggers) is not possible - Bybit does not publish which resting conditional/stop orders exist in the book (they are held server-side and only become visible as market orders once triggered); this is universal across exchanges, not Bybit-specific. However, the externally observable signature DeepCharts itself describes (fast price move plus volume spike plus book level emptying plus quick reversal) is fully constructable from Bybit's public feeds:
- L2 orderbook WS (detect a level's depth vanishing rapidly)
- Public trade WS (detect a burst of market orders within a short window, Max-MS-style bucket)
- Kline/candle data (confirm the fast price move plus reversal pattern)

This proxy (call it "Liquidity Sweep Detector" in CandleViewer to avoid over-claiming "stop order" visibility) is one of the more promising DeepDOM features to replicate with Bybit data, and should be a good candidate for the CandleViewer roadmap.

### 4.6 Market Regime

Source: pricing/deepdom feature description (dedicated helpdesk article did not return usable content during this crawl - see Open Questions).

Description (from pricing page): "Analyses the current clustering of liquidity to assess the potential volatility regime of the current session." Related "Book Speed" feature: "Tracks the speed of the book to assess the current market regime (calm or nervous). Use it for qualifying breakouts and volatility." Note: DeepCharts' own marketing copy repeats this exact sentence for both "Book Speed" and "Absorption," which looks like a copy-paste duplication rather than two genuinely distinct descriptions - flagged in Open Questions. [Resolved 2026-09-14, see 4.6a: a dedicated Absorption KB article exists with a genuinely distinct mechanic, confirming the marketing-copy duplication is indeed just a copy-paste error, not a sign the two indicators are the same thing.]

| Aspect | Detail | Bybit feasibility |
|---|---|---|
| Core signal | Clustering/concentration of resting liquidity across the book, changing over time, used to infer calm-vs-nervous regime | Feasible as a derived metric: compute a rolling measure of book depth dispersion/concentration across price levels, or the rate of book-update messages per second, from Bybit L2 WS |
| Book Speed sub-metric | Rate of order-book change (implied) | Feasible - count L2 delta messages per second as a book-speed score |
| Output | Presumably a discrete regime label/overlay (calm/transitional/volatile) or continuous score - exact visual representation unconfirmed in crawl | Would need original design work for CandleViewer; Bybit data is sufficient input |

### 4.6a Absorption indicator - detail [verified 2026-09-14]

Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/absorption-indicator-deepdom (dedicated Absorption KB article, distinct from the Book Speed/Market Regime duplicated marketing blurb).

**What it is (verbatim):** "The Absorption indicator identifies price areas where the market shows a strong ability to absorb buy or sell orders. This suggests the presence of significant [passive] liquidity that is slowing or temporarily halting price movement." This matches the generic order-flow definition of absorption (aggressive volume executing into a level without moving price, because a passive counterparty is fully matching it) rather than the Book Speed/Market Regime "calm vs nervous" framing - confirming these are genuinely different indicators despite the marketing-page copy duplication.

**General Settings [verified]:**
- **Max Tick** - constrains how many ticks of price movement are allowed while still counting toward the same absorption event (e.g. examples contrast Max Tick=1 vs Max Tick=15, i.e. a tight vs wide price-tolerance window for grouping executions into one absorption reading).
- **Max Orders Number** - caps how many individual orders are included in the absorption calculation, "determines the weight of the trader or traders involved" (i.e. filters for a minimum/maximum count of discrete orders contributing - an MBO-only concept, since MBP has no discrete order count).
- **Max MS** - a time-window filter (milliseconds) for how close together executions must occur to count toward the same absorption event; examples contrast Max MS=2050 vs Max MS=10, with the tighter window filtering out slower/more-spread-out fills.
- **Min. Absorption Vol.** - minimum volume threshold required for a price area to qualify as "absorbed" at all; examples contrast Min Absorption Vol=20 vs =50, with the higher threshold filtering out minor absorption events.

**Plot Settings [verified]:** Display Mode (Text / Diamond / Square marker shapes), Ask Color / Bid Color (side-specific highlighting), Marker Width (thickness/size of the marker).

**Text Settings:** Enable Text toggle present; further sub-options not fully captured in this crawl.

**Bybit feasibility (resolved):** The **Max Orders Number** setting is MBO-dependent (order-count-based weighting) and cannot be replicated on Bybit's MBP-only feed. However, the core absorption concept - aggressive volume (from the public trade tape) executing at a level while that level's L2 resting size holds or refreshes rather than depleting to zero - is fully constructible from Bybit's public trade WS (`publicTrade.{symbol}`) plus L2 orderbook WS (`orderbook.{depth}.{symbol}`), using volume/time-window thresholds directly analogous to Max MS and Min. Absorption Vol. A CandleViewer version should drop the "Max Orders Number" MBO-only knob (or reinterpret it loosely as a cumulative-trade-count proxy, clearly labeled as an approximation) and keep the tick-tolerance, time-window, and minimum-volume filters as-is.

### 4.6b Deep V-Tracker (Deepchart-side, not DeepDom) - Absorption & Pressure module [verified 2026-09-14]

Source: https://www.deepcharts.com/helpcenter/article/deep-v-tracker. Note: Deep V-Tracker lives under the **Deepchart** (footprint/orderflow charting) product, not DeepDom - it is a chart-based indicator, distinct from DeepDom's dedicated "Absorption" indicator (4.6a), though both use the word "absorption." This is a second, independently-confirmed absorption-adjacent feature, not a duplicate of 4.6a.

**What it is:** "A sophisticated Order Flow indicator designed to detect volumetric imbalances and specific price patterns," with two modules:
1. **Patterns module** - detects anomalies in trading speed/candlestick behavior across three pattern types: **Acceleration**, **Exhaustion**, **Slowdown**. DeepCharts' own guidance: "it is recommended to enable only Acceleration to keep the chart clean," implying Exhaustion/Slowdown are noisier or less reliable in practice. Each pattern type has a strength filter (Strong = fewest/highest-confidence markers, Medium, Weak = most markers/highest noise) and a customizable marker color.
2. **Absorption & Pressure module** - "highlights zones where buyers or sellers are exerting force via horizontal lines." Color-coding: Purple = activity on BID (Seller Pressure), Green = activity on ASK (Buyer Pressure) (both customizable). Two label types: **P (Pressure)** - an active zone where one side pushes price with force, shown as Dashed P for strong buying pressure or Solid P for strong selling pressure; **A (Absorption)** - a zone where aggressive orders are blocked by passive limit orders, "often signals potential reversal."

**Bybit feasibility:** The Patterns module (Acceleration/Exhaustion/Slowdown) is a pure price-action + trade-tape-speed derived signal - fully buildable from Bybit's public trade WS and kline data (rate-of-change in trade frequency/size vs. price movement), no MBO dependency. The Absorption & Pressure module's core signal (aggressive flow vs. passive resistance at a level) is the same MBP-compatible mechanic as the DeepDom Absorption indicator (4.6a) and Deep Reload (4.7); the Pressure ("P") half specifically (one side pushing price with force) is essentially a directional-momentum/CVD-slope-at-level signal, also fully constructible from Bybit's trade tape without MBO.

### 4.7 Deep Reload - full write-up

Source: https://www.deepcharts.com/helpcenter/deepdom/article/deep-reload (Fresh Liquidity Detector)

Already detailed in section 3.1 table. Additional detail from the full article text:

- Concept: "Resting liquidity is the visible volume sitting in the order book at each price level. When a big trader or algorithm decides to get involved, they often add size close to the current price rather than chasing the move. Deep Reload focuses on these additions: it detects when a meaningful amount of new volume suddenly appears in a narrow band of prices around the inside market." Fresh liquidity "can act as a buffer (bids stacking below price to support it) or a ceiling (asks stacking above price to slow or reverse a rally)... often related to iceberg or sliced orders."
- How to set up: right-click chart, choose Indicators, find Deep Reload, click plus to add it, click the gear icon to configure.
- Levels Width parameter example: "with a value of 10 the indicator tracks fresh liquidity across the top 10 bids and top 10 asks and aggregates qualifying events into a single zone when they occur within that window."
- Plot Max Ticks: "limits the vertical height of each zone in price ticks. When fresh liquidity is detected at several adjacent levels, Deep Reload groups them into a single band up to this maximum range so you can see the entire defended area at a glance."
- Trend Filter (optional): Enable trend filter; Trend filter lookback in minutes - "sets how many minutes of recent price action are used to estimate trend direction (e.g. via a moving average or VWAP comparison)." With the filter enabled, signals can be restricted to those aligned with the current bias (bid reloads in an uptrend, ask reloads in a downtrend), suppressing counter-trend bands.
- Suggested combined use: "Deep Reload zones with CVD and Deep Trades to build a complete picture of passive vs aggressive participation."

Bybit feasibility: High. This is directly buildable from Bybit's L2 orderbook delta stream (orderbook.{depth}.{symbol}, pushed roughly every 20ms per Bybit's own docs) with a rolling aggregation window near best bid/ask, a configurable size/volume threshold, and an optional trend filter computed from kline/VWAP data already needed elsewhere in CandleViewer.

### 4.8 Deep Liquidity Scan [expanded 2026-09-14, verified]

Source: https://helpdesk.deepcharts.com/portal/en/kb/articles/liquidity-tracker (dedicated KB article, successfully retrieved on re-fetch; the earlier crawl pass's "stub/placeholder" result is superseded).

Description (from pricing page, corroborated by the dedicated article): "Tracks the cumulative level and variation in book thickness for both Bid, Ask and their Delta." The dedicated article frames it as best used "in combination with the Heatmap or the DOM panel" to understand overall order-flow/liquidity-intent context.

**General Settings [verified]:**
- **Num Lev Depth** - how many order-book price levels (from best bid/ask outward) are included in the liquidity calculation; a high value (e.g. 200) captures liquidity sitting far from current price, a low value focuses only on liquidity near the touch.
- **Calc Mode** - options include:
  - **Exponential** - weights levels near current price more heavily than deep levels, with the falloff rate itself configurable (see Exp Half-Weight Lev below).
  - **Last** - compares current liquidity reading against the immediately preceding reading (fast, responsive, noisier).
  - **Peak** - compares current liquidity against the highest liquidity level ever observed (a running-max baseline).
- **Exp Half-Weight Lev** - only active when Calc Mode = Exponential; controls how quickly the weighting decays with depth (i.e. defines the "half-life" level at which a deeper level's contribution drops to half strength).
- **Value Smooth** - applies smoothing to reduce noise/jumpiness in the plotted lines, since raw book data is described as "very noisy."
- A book-freshness filter with at least two modes: **All** (every level within the selected depth regardless of age, the default/broadest view) and **Fresh Only** (restricts to levels that recently appeared in the book, i.e. explicitly excludes long-resting liquidity from the reading - a novelty-only view).

**Delta Settings [verified, partially captured]:** A **Delta Enable** toggle exposes the Bid-minus-Ask liquidity differential as its own plotted series, described as "one of the most important readings the indicator provides ... which side of the market currently has more passive orders sitting in the book, and by how much."

| Aspect | Detail | Bybit feasibility |
|---|---|---|
| Core metric | Cumulative book thickness (total depth) per side plus delta between sides, tracked over time as a line/indicator, over a configurable depth (Num Lev Depth) and weighting scheme (Calc Mode: Exponential/Last/Peak) | Fully feasible - straightforward to compute (sum of bid sizes vs ask sizes across N levels, exponentially weighted or peak-tracked) from Bybit's L2 WS feed, updated on every delta message; no MBO dependency anywhere in this indicator |
| Fresh Only filter | Restrict the calculation to recently-appeared liquidity only | Feasible - requires the same per-level "time since last significant change" tracking already needed for the Heatmap's Fresh vs Persistent classification (section 4.1); reuse that tracking layer |
| Value Smooth | Noise reduction on the plotted line | Trivial - standard smoothing (EMA/SMA) applied client- or server-side to the derived series |

### 4.9 Iceberg / Stop Run / Reload / Regime / Absorption - Bybit feasibility summary

| Feature | MBO required? | Buildable as true MBO feature on Bybit | Buildable as heuristic proxy on Bybit |
|---|---|---|---|
| Iceberg Detector | Yes (order ID tracking) | No | Yes, but must be labeled a heuristic replenishment detector, not true iceberg detection |
| Stop Run Detector | Yes per DeepCharts marketing, but externally observable signature is derivable from MBP-equivalent data | No (true stop-order visibility) | Yes - liquidity-sweep-plus-reversal detector from L2 plus trade tape is a strong analog |
| Deep Reload | Not strictly required (works off level-level size deltas) | N/A (already MBP-compatible) | Yes, directly, no proxy caveat needed |
| Deep Liquidity Scan | No (confirmed [verified] - purely MBP-level aggregate metric, no order-count/order-ID dependency in any setting found) | N/A | Yes, directly, including the Exponential/Last/Peak calc modes and Fresh Only filter |
| Market Regime / Book Speed | No (aggregate, not order-level) | N/A | Yes, directly, as a derived volatility/liquidity-clustering score |
| Absorption | Mostly no ([verified] core mechanic is trade-tape-vs-resting-size, MBP-compatible); Max Orders Number setting specifically is MBO-only | No, for the Max Orders Number weighting specifically | Yes for the core absorption signal (tick tolerance + time window + min volume, all MBP-compatible); Max Orders Number should be dropped or approximated |

## 5. DeepGamma

Source: https://www.deepcharts.com/features/deepgamma

DeepGamma is explicitly SPX/index-options-specific, built on real CBOE market-maker data, and is marketed as "native to Deepchart" (i.e. an overlay module of the Deepchart footprint platform, not a separate app like DeepDOM).

### 5.1 Feature list (marketing copy)

- GEX Profile (Gamma Exposure Profile)
- Heatmap (a gamma-specific heatmap, distinct from the DeepDOM liquidity heatmap)
- Gamma Bands
- Gamma Profile
- Deep Option Trades
- Expected Move
- Total Options Volume
- Net Option Delta

### 5.2 Data/technical claims

- "Real CBOE MM data for SPX" - "No assumption in the calculation. 100% certain if its a market maker or not." (i.e. DeepGamma claims to identify genuine market-maker options flow from CBOE data directly, rather than inferring MM positioning statistically as many retail GEX tools do.)
- Coverage: SPX (primary, CBOE MM data), plus SPY and QQQ, "Gamma exposure assessed with proprietary formulas" (implying SPY/QQQ use a different, non-CBOE-MM-confirmed methodology, likely OPRA-based inference, versus SPX's claimed certainty).
- Resolution: 1-minute resolution for SPX with real-time data.
- Historical backtesting: "Replay up to 9 months of Orderflow and SPX Option flow"; "9 months of CBOE historical data - Backtest through November 2025" (implies the historical window is a fixed lookback anchored near the crawl date, not a rolling window advertised as permanent).
- No third-party tool integration needed - "This is all proprietary tech built in deepchart."
- Beyond Gamma: "Gamma Exposure is only one perspective on option flow. There is more." - Deep Option Trades, Expected Move, Total Options Volume, Net Option Delta are positioned as complementary metrics.
- Pricing: "From $46/month" tied to "Cboe 1-minute data," native orderflow-chart integration, and orderflow+options backtesting (see section 2 for caveats on the comparison-table rendering).

### 5.3 Assessment: could a crypto-analog use Deribit/Bybit options data?

CandleViewer is Bybit-first, crypto-only. DeepGamma's core techniques (GEX profile/heatmap, gamma bands, gamma profile) are standard options-market-maker-hedging-flow analyses; the mechanics (computing dealer gamma exposure by strike from open interest, and inferring hedging flow direction) are transferable in principle to crypto options, but the *specific* claim DeepCharts makes for SPX (deterministic MM identification via CBOE-exclusive data) is not repeatable in crypto because there is no equivalent "MM-tagged" trade feed publicly available from any crypto options venue.

| Requirement | SPX (DeepGamma) | Deribit (crypto options leader) | Bybit options |
|---|---|---|---|
| Options open interest by strike/expiry | Yes, via CBOE feed | Yes, public REST endpoint returns OI per instrument (strike/expiry/type) | Yes, via v5 API: GET /v5/market/open-interest (category=option, per-symbol) and GET /v5/market/instruments-info (category=option) to enumerate all strikes/expiries; WebSocket topic option.open_interest for live updates (per Bybit V5 docs, https://bybit-exchange.github.io/docs/v5/intro) |
| Market-maker-tagged trade flow (deterministic MM identification) | Yes (CBOE MM data, DeepGamma's key differentiator) | No public equivalent | No public equivalent - Bybit does not expose counterparty/market-maker tags on option trades |
| Options trade tape (Deep Option Trades analog) | Yes | Yes - Deribit public trade feeds per instrument | Yes - Bybit provides public trade data per option instrument via REST/WS, though liquidity/volume is far lower than Deribit's |
| Gamma/GEX computation feasibility | Deterministic dealer positioning (CBOE MM data) | Feasible only as an assumption-based GEX estimate: standard retail approach assumes market makers are short gamma (or use OI plus assumed dealer positioning direction) - same limitation most non-CBOE GEX tools operate under | Same assumption-based limitation as Deribit; additionally Bybit's crypto options market has materially lower open interest, tighter strike coverage, and fewer market participants than Deribit, so a GEX signal computed from Bybit alone would likely be noisier and less liquid-market-representative than one computed from Deribit |
| Expected Move / Total Options Volume / Net Option Delta analogs | Yes (native) | Computable from OI, IV (if available), and trade tape | Computable from Bybit's OI, mark IV field (Bybit options tickers expose implied volatility), and trade tape, though again on a much thinner market |

**Recommendation for CandleViewer (research-stage only, not a build decision):** If a crypto-GEX feature is pursued later, **Deribit is architecturally the better primary data source** for options OI/strike/IV (it is the dominant crypto options venue by volume and open interest), with Bybit optionally layered in for BTC/ETH options given the project's Bybit-first broker choice. Neither venue can replicate DeepGamma's "100% certain market maker" claim; any crypto GEX feature would necessarily be an assumption-based dealer-gamma estimate, on par with most non-CBOE GEX tools in the equities/index space (e.g. many free/paid retail SPX GEX trackers that do not have CBOE MM data either).

## 6. Volumetrica Trading platform (the white-label parent)

Source: https://volumetricatrading.com/en/index and https://www.volumetricatrading.com/, plus https://help.volumetricatrading.com/en/support/solutions/204000010703 (Volumetrica's own helpdesk "Deepchart" category, useful for cross-referencing which features DeepCharts inherited)

Volumetrica markets two platform lines that map directly onto DeepCharts' Deepchart and DeepDOM:

### 6.1 Deepchart (Volumetrica's own description)

"Deepchart offers a complete suite for analyzing and trading futures."
- Volume Analysis: unique volume charting tools - Volume Profile, Deep Trades, Delta Profile, TPO, Order Flow Analyzer - and advanced chart types (DeepBars, Range, Renko).
- Essential Data: The Book (DOM) displays market depth (limit orders bid/ask); Time & Sales (T&S) tracks trade execution in real time.
- Execution & Risk: click order execution from Chart, Book, or Panel; advanced risk management with OCO strategies and customizable money-management tools for daily P/L limits.
- Reporting: detailed reports on win rate and risk/return for strategic optimization.
- Data delay/testing: 15-minute data delay and a Sim Account to practice/test strategies on real-time futures markets without risking capital.

### 6.2 DeepDom (Volumetrica's own description, confirms/cross-checks DeepCharts' own copy)

"Deep Dom is the platform for advanced liquidity and market microstructure analysis."
- Liquidity and Flow Analysis: "The Heatmap displays historical order book liquidity, identifying support, resistance, and institutional activity." Volume Bubbles "show tick-by-tick trades directly on the chart, distinguishing aggressive bids and asks with nanosecond precision (ideal for HFT analysis)."
- Indicators: "Advanced tools such as Iceberg, Stop Run, CVD, and Liquidity Tracker allow you to analyze aggressive pressure and hidden liquidity."
- Operational Tools: candles and advanced drawing tools directly on the heatmap, an advanced DOM (details truncated in source fetch).

### 6.3 Volumetrica's own Knowledge Base categories (for the Deepchart product specifically)

Source: https://help.volumetricatrading.com/en/support/solutions/204000010703 - this listing is useful because it enumerates Volumetrica-native indicator names that likely underlie many DeepCharts indicators (DeepCharts appears to have renamed/rebranded a subset with "Deep" prefixes):

- Deepchart category: 7 articles total, sub-split into "Common issues" (4), "Configurations" (8, e.g. Installation and First Configuration, How to create a new Connection, How to connect Symbols to the Data Feed), "Features" (6, e.g. Chart, Adv. Dom, Adv. Time and Sales), "Trading" (6, e.g. Simulation Environment, Trading from the Chart, OCO Strategy), "Indicators - Common" (37 articles, e.g. Absolute Levels, ADX, Annotation Condition Advanced - i.e. a large library of generic technical indicators beyond the orderflow-specific ones), "Indicators - Volume" (31 articles, e.g. Auction Gap Tracker, Bar POC, Big Trades), and "VolAnalyzer" (1 article, VolSwing).
- This confirms DeepCharts' Deepchart product includes a **large generic technical-indicator library** (ADX and dozens of others) in addition to the order-flow-specific tools, which the DeepCharts-branded pages/help center do not foreground as heavily.
- "Big Trades" (Volumetrica's name) appears to correspond to DeepCharts' "Deep Trades" / "Big Passive Trade" concepts.
- "Bar POC" and "Auction Gap Tracker" are Volumetrica-native volume-analysis indicators not explicitly named in the DeepCharts marketing pages crawled - potential additional features DeepCharts may also expose under different names (unconfirmed - flagged in Open Questions).

### 6.4 Volumetrica Heatmap article (VolBook) - additional detail not found on DeepCharts pages

Source: https://help.volumetricatrading.com/en/support/solutions/articles/204000013376-heatmap

"The Heatmap of VolBook represents the most comprehensive tool for analyzing trading volumes and order flow, as it combines the executed market order information (provided by Time and Sales) with the limit order information entered in the Trading Book (DOM)."
- Default view: opens with an hour of history; green = Sell Limit, red = Buy Limit (Note: this directly **contradicts** the DeepCharts helpdesk Heatmap article, which states green = Buy Limit and violet = Sell Limit - see Open Questions for this color-scheme discrepancy between the underlying Volumetrica engine and the DeepCharts-branded documentation).
- **Level 2 depth requirement explicitly stated:** "Please note that in order to have market depth available, it is necessary to have Level 2 of the data feed, in particular VolBook allows you to analyze over 1000 book levels." This is a very deep book (1000+ levels) compared to what most crypto exchange public WS feeds expose (Bybit's public orderbook WS tops out at a fixed depth of 50/200/500 levels depending on tier/category - see feasibility notes).
- Adaptive/relative color scaling confirmed again here: "if a new limit order of larger size than those present up to that point were to be placed in the DOM, the colors will scale. What was previously highlighted in red will most likely become orange and so on" - i.e. the same relative/rescaling heatmap logic described on the DeepCharts side.
- Settings tree includes: Import all annotations, Model, Indicators, Properties, Line Bid/Ask, Heatmap, Color Levels-DOM, Imbalance Book, Cumulative-Delta, Last-Level, Price-Line, Graphic-Settings.
- "Imbalance Book" as a distinct settings section confirms Volumetrica/DeepCharts has an **imbalance-tracking feature** (referenced in the CandleViewer research brief as "imbalance tracker") that lives inside the Heatmap/DOM settings rather than as a standalone marketed product page - full settings for it were not retrieved in this crawl (Open Questions).
- Bubble-mode setting: "Mode de bubbles: Defines whether to display the Delta prevalen[ce]..." (truncated in source fetch; French-language fragment leaked into the English page, indicating this Volumetrica help article is a partial machine/human translation).

## 7. Helpdesk deep-crawl (helpdesk.deepcharts.com/portal/en/kb)

Source: https://helpdesk.deepcharts.com/portal/en/kb

The KB portal reports **"135 Articles; 5 Sections"** across the whole DeepCharts category, and a sub-figure of **"39 Articles; 5 Sections"** shown for the DeepDom sub-portal specifically (Zoho Desk-powered help center). [Correction, 2026-09-14, verified via direct re-fetch of https://helpdesk.deepcharts.com/portal/en/kb: the portal actually renders **"172 Articles; 5 Sections"** for the top-level DeepCharts category and **"39 Articles; 5 Sections"** for the DeepDom sub-category, i.e. the 135 figure used in the original research brief appears to be either stale or a miscount from an earlier crawl; 172 is the freshly confirmed top-level total, with DeepDom's own 39-article sub-portal now fully enumerable (see 7.1a below) via direct fetch of its five section pages, unlike the earlier attempt which returned JS-stub content.]

### 7.1a Full DeepDom KB inventory by section (39 articles, [verified] 2026-09-14 via direct fetch of each section page)

Fetched directly: https://helpdesk.deepcharts.com/portal/en/kb/deepdom (top-level DeepDom portal, showing section article counts and "Popular"/"Recent" lists), https://helpdesk.deepcharts.com/portal/en/kb/deepdom/configurations, https://helpdesk.deepcharts.com/portal/en/kb/deepdom/trading, https://helpdesk.deepcharts.com/portal/en/kb/deepdom/features, https://helpdesk.deepcharts.com/portal/en/kb/deepdom/indicators, https://helpdesk.deepcharts.com/portal/en/kb/deepdom/common-issues.

**Section counts confirmed:** Common Issues (4 articles), Configurations (9 articles), Features (3 articles), Trading (4 articles), Indicators (19 articles). Total = 39, matching the portal's own "39 Articles" figure.

**Common Issues (4)** - titles not individually enumerated by this fetch (the section page returned "No articles found" for an unauthenticated/cached view in one pass); titles referenced elsewhere in the crawl include "Rectangle Drawing Tool Not Working," "Basic Requirements / Installation Problem," "Cache Issues," "Installation Issue," "License Issues" (these last three named explicitly on the DeepDom top-level portal page's Common Issues count-4 listing cross-reference, but not individually opened in this pass - [inferred] titles, not full one-line summaries).

**Configurations (9):**
1. General Settings - central configuration hub: Refresh Time (MS) for Chart/Time&Sales, Trading defaults (Daily/Open P&L display mode), stop-order trigger basis (Last vs Bid/Ask), Alert sounds, keyboard shortcuts. [verified, see 4.1/section text above]
2. How to Manage Symbol Rollover - [inferred from title only; not opened]
3. How to Customize Language and Theme - [inferred from title only]
4. How to Set Up Keyboard Shortcuts - [inferred from title only]
5. How to Enable Sound Notifications - [inferred from title only]
6. User Configuration - Templates, Workspaces, Tool Config - [inferred from title only]
7. How to Add a New Connection - [inferred from title only; likely data-feed/broker connection setup, paralleling Deepchart's own "How to Add a New Connection - VolBook" Volumetrica-side article]
8. How to Add Markets Correctly (Symbol Manage) - [inferred from title only]
9. Installation and First Configuration - listed as a "Popular Article" on the DeepDom portal home page; [inferred summary] first-run setup guide.

**Trading (4):**
1. Orders Window - "gives you a centralized view of all your active and pending orders directly within DeepDom... monitor and manage your orders in real time without leaving the platform." [verified excerpt]
2. Portfolio-Risk Manager - "enables traders to apply professional, automated risk controls directly within the platform. By defining strict risk management rules, traders can enforce discipline in real time. If any predefined rule is [violated, an automated action triggers]." [verified excerpt, truncated]
3. Simulation Environment - "DeepDom includes a built-in simulation environment that lets you practice strategies with SIM accounts using real-time data but without financial risk." [verified excerpt]
4. Trading from the Chart (Deepdom) - full write-up already used in section 4.2 (Chart DOM columns, click-trading grammar). [verified]

**Features (3):**
1. Volume Bubbles - full write-up in section 4.3. [verified]
2. Replay Tick Data - DeepDom - "lets you replay a past trading session as if it were happening in real time, with the option to practice simulated trading alongside it. This feature is especially useful for users who are still learning." [verified excerpt]
3. Heatmap - full write-up in section 4.1. [verified]

**Indicators (19, [verified] full list via direct fetch of /portal/en/kb/deepdom/indicators):**
1. Deep Iceberg (Iceberg Detector) - section 4.4.
2. Spread Bid/Ask - "measures and plots the distance between the best bid and best ask prices (the bid-ask spread) in ticks. It helps you see when liquidity conditions change - for example, when spreads suddenly widen." [verified excerpt]
3. Deep Reload - section 4.7 (retitled here "Fresh Liquidity Detector" in its own subtitle).
4. Stop Run - section 4.5.
5. Deep Liquidity Scan (article URL slug still "liquidity-tracker") - section 4.8, full settings now captured.
6. Cumulative Iceberg/Stop - "monitors and identifies two specific types of market activity - Iceberg orders and Stop orders - using MBO (Market By Order) technology. It tracks the presence and execution of these [patterns as a cumulative line chart]." [verified excerpt] - this is the "Stop/Iceberg Tracker (cumulative)" feature named in the pricing-page grid (section 3.1), now confirmed to have its own dedicated KB article and to be explicitly MBO-based end to end (not just its underlying detectors).
7. Absorption - section 4.6a, full settings now captured [verified].
8. Volume Swing - title only; content not opened in this pass ([inferred] likely a volume-based swing-high/low or reversal marker, analogous to Volumetrica's "VolSwing" article named in section 6.3).
9. POC Dynamic - "displays the Point of Control (POC) - the price level where the highest volume has been traded - calculated on a rolling basis over the last n minutes. In addition to the POC line itself, it allows you to plot [historical POC levels / a POC ribbon]." [verified excerpt, truncated]
10. Volume Profile (URL slug volume-by-price) - section 7.1 above, already fully summarized [verified].
11. Book Speed - title/URL confirmed (https://helpdesk.deepcharts.com/portal/en/kb/articles/book-speed) but the article body returned only the generic help-widget chrome on this fetch pass, not the actual content - settings remain unconfirmed [Open Question, unresolved despite direct fetch attempt].
12. Session Imbalance - "highlights key price levels from the first hour of trading, known as the Initial Balance. These levels are considered significant because the majority of trading volume in any session enters during [that window]." [verified excerpt, truncated] - confirms the Initial-Balance-based mechanic driving this indicator, and confirms it is the "imbalance tracker" referenced elsewhere (see 6.4 Imbalance Book cross-reference) - though note Session Imbalance (Initial Balance breakout levels) and the DOM's separate "Imbalance Book" bid/ask-imbalance setting appear to be two distinct features sharing the word "imbalance," not the same feature - flagged for disambiguation.
13. VWAP + Envelopes - "displays the average price of trades weighted by volume over a chosen time period, along with standard deviation bands above and below it." [verified excerpt]
14. Volume - "displays total traded volume and can color the background according to delta, helping you quickly see where participation increases and which side is more aggressive." [verified excerpt] (Note: a very similarly-described "Volume" article was also captured under the general/Deepchart article set in section 7.1 with sub-modes Volume/Order/Aggregate-Trade - these may be the same underlying indicator documented from two different product contexts, or a DeepDom-specific variant; not fully disambiguated.)
15. Deep Delta - "an advanced version of Delta Bar that lets you apply filters to the delta and highlight up to four configurable ranges, making it easier to focus on significant buying or selling imbalances." [verified excerpt]
16. Delta Bar - "displays the delta (difference between buy-market and sell-market volume) as bars plotted beneath the chart, helping you see where aggressive buyers or sellers dominated each period." [verified excerpt]
17. Cumulative Volume Delta (CVD) - "shows tick-by-tick cumulative delta over a user-defined period, measuring the difference between buy-market and sell-market volume to reveal sustained buying or selling pressure." [verified excerpt]
18. Deep Trades - "highlights aggregated large orders on the chart using visual markers, making it easy to see where the largest buy and sell transactions occurred." [verified excerpt] (A more detailed, dedicated Deepchart-side "Deep Trades" article/blog post is also referenced in section 5/9 with additional detail on Deep-Trades-as-absorption-signal.)
19. Important Levels - title/URL confirmed (https://helpdesk.deepcharts.com/portal/en/kb/articles/im) but content not opened in this pass; per the pricing-page grid (section 3.4) this covers daily highs/lows, VWAPs, and POCs plotted on-chart - [inferred] from marketing copy, not independently confirmed via the dedicated article body.

### 7.1 Articles retrieved and summarized in this crawl

| Article | URL | Summary |
|---|---|---|
| Heatmap | https://helpdesk.deepcharts.com/portal/en/kb/articles/heatmap | Core DeepDom liquidity heatmap; color scale (Red=highest liquidity down to Black=thinnest), Buy(green)/Sell(violet) limit separation, Fresh vs Persistent liquidity concept, MBP vs MBO Source Settings toggle, plus embedded CVD/Volume-Profile/DOM-overlay settings panels. Full detail in section 4.1. |
| Volume Bubbles | https://helpdesk.deepcharts.com/portal/en/kb/articles/volume-bubbles (referenced from Heatmap article) | Tick-by-tick trade prints plotted on chart; color by aggressor side; sizing/filter settings (Filter Volume, Filter Bubble, Std Dev-based scaling). Section 4.3. |
| Replay Tick Data - DeepDom | https://helpdesk.deepcharts.com/portal/en/kb/articles/tick-data-replay-deepdom | Lets users replay a past trading session as if live, with optional simulated trading; useful for learning without a live data feed/subscription, and for pre-purchase evaluation of a new instrument. |
| Deep Iceberg (Iceberg Detector) | https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-iceberg | Full write-up in section 4.4: order-ID-based replenishment tracking, Data/Plot/Active-Icebergs/Text/Alert settings groups. |
| Stop Run | https://helpdesk.deepcharts.com/portal/en/kb/articles/stop-run | Full write-up in section 4.5: General Settings (Minimum Tick, Maximum Ord Num, Max MS, Min. Stop Run Vol.), Plot Settings, Text Settings. |
| Volume Profile (titled "Volume Profile" on-page, URL slug volume-by-price) | https://helpdesk.deepcharts.com/portal/en/kb/articles/volume-by-price | "The Deep Profile displays the volume traded at each price level over a specific period," with POC, Value Area, High Volume Nodes (HVN), Volume/Ask-Bid Volume/Delta/Total Delta+Volume display modes; Grouping (Automatic or Manual Ticks); Color Calculation modes (Volume, Delta, and at least one more truncated in fetch); a "Valley" line setting group (Line Width/Color) and a "Summary" panel group (Enable Summary, Text/Ask/Bid colors); Custom Time Session settings (Ini/End Session in US market time) for session-based profile resets. |
| Volume (generic Volume indicator) | https://helpdesk.deepcharts.com/portal/en/kb/articles/volume | Total volume per bar; sub-modes Volume / Order (number of orders placed) / Aggregate Trade (number of trades executed); Filter Min/Max thresholds; "Calculation Based on Seconds" option (volume-per-second calculation, useful on Range bars to spot acceleration/deceleration); background coloring modes None/Fade/Delta-based (delta-mode name cut off in fetch). |
| Rectangle Drawing Tool Not Working | https://helpdesk.deepcharts.com/portal/en/kb/articles/rectangle-drawing-tool-not-working | Troubleshooting article: fixes a corrupted drawing-tool config file by disabling antivirus (leaving Windows Defender only) and reinstalling; checks for .NET package requirements. Confirms DeepCharts requires specific Windows runtime prerequisites. |
| How to Connect Interactive Brokers (IB) with DeepChart | https://helpdesk.deepcharts.com/portal/en/kb/articles/how-to-connect-interactive-brokers-ib-with-deepchart | DeepChart connects to Interactive Brokers via the TWS (Trader Workstation) API; requires TWS to be running/configured correctly. Confirms DeepCharts supports broker integrations beyond dxFeed/Rithmic for execution (IB is a stocks/futures/options broker, relevant context only, not crypto). |
| Price Chart Settings | https://helpdesk.deepcharts.com/portal/en/kb/articles/price-chart-settings | Describes the Price Chart (candlestick or line) as an "indicator" in DeepCharts' architecture that visualizes historical buyer/seller transactions based on the order book; fully customizable (specific settings truncated in fetch). |
| Deep-M IVB | https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-m-ivb | An algorithmic indicator simplifying Opening-Range-Breakout (ORB) trading; analyzes years of historical data to auto-plot high-probability projection levels. Futures/equities-session-based concept (relies on a defined session open); would need redesign for 24/7 crypto (no single daily "open"). |
| Depth of Market (DOM) | https://www.deepcharts.com/helpcenter/article/depth-of-market | Full write-up in section 4.2: Advanced DOM layout, columns, settings, aggregation, custom session times. |
| Deep Reload | https://www.deepcharts.com/helpcenter/deepdom/article/deep-reload | Full write-up in section 4.7. |
| Stop Run Detection (third-party explainer, orderflowfutures.com, cross-checked) | https://orderflowfutures.com/en/deepcharts/stop-run-detection | Independent community explainer confirming and elaborating on the official Stop Run KB article; includes an FAQ block defining "stop run," DeepCharts' MBO-based detection method, and a suggested trading approach (fade the sweep after confirmation of rejection). |

### 7.2 KB navigation structure observed (categories/sections, from the DeepDom Features sub-portal and the DeepCharts general Help Center sidebar)

From https://www.deepcharts.com/helpcenter/deepdom (DeepDom-specific Help Center sidebar navigation, which mirrors the Zoho KB's section structure):

- **Common Issues** section - e.g. "Cache Issues - DeepDom," "Installation Issues," "Licence Issues" (View All Articles link, full list not enumerated)
- **How To** section - e.g. "General Settings (DeepDOM)," "Installation and First Configuration," "How to Add Markets Correctly"
- **Trading** section - e.g. "Orders Window," "Portfolio-Risk Manager," "Simulation Environment"
- **Indicators** section - e.g. "Spread Bid/Ask," "VWAP + Envelopes," "Session Imbalance" (this "Session Imbalance" name is another confirmation of an imbalance-tracking feature, alongside the "Imbalance Book" setting found in the Volumetrica Heatmap article, section 6.4)
- **Features** section - Volume Bubbles, Heatmap, Replay Tick Data (the three articles most fully retrieved in this crawl, see 7.1)
- **Deep Indicators** section - "Deep Iceberg (Iceberg Detector)," "Deep Reload," "Deep Liquidity Scan" (each has a "View All Articles" link suggesting more members of this category beyond the three named)

This five-section structure (Common Issues / How To / Trading / Indicators / Features, or a similar grouping that also separates out "Deep Indicators") is consistent with the "5 Sections" figure reported by the Zoho KB portal page, giving reasonable confidence the section taxonomy is: Common Issues, How To / Configurations, Trading, Indicators (general/technical), Deep Indicators (or "Features" combined with Deep Indicators depending on how Zoho groups DeepDom vs the general DeepCharts KB) - exact 1:1 mapping to Zoho's "5 Sections" label could not be fully confirmed field-by-field (Open Questions).

### 7.3 What could not be enumerated

Despite repeated fetch attempts, the following remain **not** retrievable within this crawl's tool budget and rate limits, even after the 2026-09-14 follow-up pass that resolved the full DeepDom 39-article list (7.1a):
- A complete, article-by-article list of all **172** top-level DeepCharts KB articles (corrected from the earlier "135" figure - see 7.1a intro). The DeepDom sub-category's 39 articles are now fully enumerated by title with one-line summaries where fetchable (7.1a); the remaining ~133 articles live in other top-level sections (general Deepchart help center, DeepGamma, generic technical-indicator library per the Volumetrica cross-reference in 6.3, installation/licensing/troubleshooting) and were not individually enumerated.
- **Book Speed** and **Important Levels** - both articles' URLs are confirmed to exist and are correctly titled (see 7.1a items 11 and 19), but repeated direct-fetch attempts returned only generic help-widget page chrome rather than article body content on both passes. This is a genuine, reproducible fetch gap, not a rate-limit artifact - both should be retried with a JS-rendering browser tool rather than a static fetch before being considered fully closed.
- The DeepGamma KB/help-center equivalent (a "DeepGamma" section of the helpdesk was referenced in the sidebar navigation dump - "Change to DeepCharts Help Center" - but a DeepGamma-specific set of KB articles analogous to the DeepDom ones was not located/retrieved).
- Full "Text Settings" sub-options for the Absorption indicator (4.6a) beyond the "Enable Text" toggle.
- Full title-by-title content of the 4 Common Issues articles under DeepDom (titles inferred, not opened - see 7.1a).

## 8. Bybit data requirements cheat-sheet (for feasibility assessments above)

Source: https://bybit-exchange.github.io/docs/v5/intro and general knowledge of Bybit's V5 API structure, cross-checked against a WebSearch summary (see Sources).

- **Orderbook (L2 depth) WebSocket:** topic pattern orderbook.{depth}.{symbol}, with depth tiers (e.g. 1/50/200/500 for linear/inverse; smaller tiers for spot and options) pushed as an initial snapshot plus incremental deltas; push frequency is roughly 20ms for the deepest linear/inverse tiers per Bybit's documented behavior referenced in this research (exact millisecond figures should be re-verified directly against the live V5 docs before implementation, since Bybit has changed push intervals across API versions historically).
- **Public trade WebSocket:** topic publicTrade.{symbol} - streams each individual execution (price, size, side, timestamp) in real time; this is the basis for Volume Bubbles/prints, Deep-Trades-style big-print filters, and the trade-tape half of a Stop-Run-sweep proxy.
- **Options-specific:**
  - REST GET /v5/market/open-interest with category=option and a specific symbol (e.g. BTC-30JUN23-60000-C) returns open interest for that single instrument; to build a full strike-by-strike OI curve you must first call GET /v5/market/instruments-info?category=option to enumerate all live instruments (strikes/expiries), then query open interest per symbol (or use the WS topic below for live updates instead of REST polling).
  - WebSocket topic option.open_interest provides live OI updates without REST polling.
  - Bybit option tickers also expose mark implied volatility and other Greeks-adjacent fields (referenced generally; exact field names should be verified against the live options ticker WS/REST schema before implementation).
- **Private/account data:** position WS topic (for DOM P&L-column analogs), order/execution WS topics (for the Trading Terminal / OCO analogs), REST /v5/order/create supporting conditional and TP/SL orders (for OCO-strategy analogs).
- **Kline/candles:** standard REST/WS kline endpoints, needed for VWAP, trend filters (as used by Deep Reload's optional Trend Filter), and volume-profile-by-time-bucket construction.

None of the above give order-ID-level (MBO) visibility into the resting book; Bybit, like essentially all centralized crypto exchanges' public APIs, exposes only Market-By-Price (aggregated) depth publicly. This single fact is the dominant constraint shaping the feasibility column throughout sections 3-6: true Iceberg Detection and true Stop-Order-triggered detection (as DeepCharts defines them via MBO) are not achievable; heuristic/proxy versions built from L2 deltas + trade tape are achievable for most of the rest of the DeepDOM feature set.

## Sources

- https://www.deepcharts.com/features/deepdom
- https://www.deepcharts.com/pricing/deepdom
- https://www.deepcharts.com/features/deepgamma
- https://www.deepcharts.com/helpcenter/deepdom
- https://www.deepcharts.com/helpcenter/deepdom/features
- https://www.deepcharts.com/helpcenter/deepdom/article/heatmap
- https://www.deepcharts.com/helpcenter/deepdom/article/deep-reload
- https://www.deepcharts.com/helpcenter/deepdom/article/deep-liquidity-scan
- https://www.deepcharts.com/helpcenter/deepdom/deepindicators
- https://www.deepcharts.com/helpcenter/article/depth-of-market
- https://www.deepcharts.com/datafeeds
- https://www.deepcharts.com/de/pricing/deepdom
- https://helpdesk.deepcharts.com/portal/en/kb
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/configurations
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/trading
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/features
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/indicators
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/common-issues
- https://helpdesk.deepcharts.com/portal/en/kb/articles/absorption-indicator-deepdom
- https://helpdesk.deepcharts.com/portal/en/kb/articles/liquidity-tracker
- https://helpdesk.deepcharts.com/portal/en/kb/articles/book-speed
- https://www.deepcharts.com/helpcenter/deepdom/article/general-settings
- https://www.deepcharts.com/helpcenter/deepdom/article/trading-from-the-chart
- https://www.deepcharts.com/helpcenter/article/deep-v-tracker
- https://www.deepcharts.com/features/deepchart
- https://orderflowfutures.com/en/tutorials
- https://orderflowfutures.com/en/order-flow
- https://helpdesk.deepcharts.com/portal/en/kb/articles/heatmap
- https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-iceberg
- https://helpdesk.deepcharts.com/portal/en/kb/articles/stop-run
- https://helpdesk.deepcharts.com/portal/en/kb/articles/volume-by-price
- https://helpdesk.deepcharts.com/portal/en/kb/articles/volume
- https://helpdesk.deepcharts.com/portal/en/kb/articles/volume-bubbles
- https://helpdesk.deepcharts.com/portal/en/kb/articles/tick-data-replay-deepdom
- https://helpdesk.deepcharts.com/portal/en/kb/articles/rectangle-drawing-tool-not-working
- https://helpdesk.deepcharts.com/portal/en/kb/articles/how-to-connect-interactive-brokers-ib-with-deepchart
- https://helpdesk.deepcharts.com/portal/en/kb/articles/price-chart-settings
- https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-m-ivb
- https://volumetricatrading.com/en/index
- https://www.volumetricatrading.com/
- https://help.volumetricatrading.com/en/support/home
- https://help.volumetricatrading.com/en/support/solutions/204000010703
- https://help.volumetricatrading.com/en/support/solutions/articles/204000013376-heatmap
- https://orderflowfutures.com/en/deepcharts/stop-run-detection
- https://pinescriptforge.com/deepcharts/plans/deepdom
- https://bybit-exchange.github.io/docs/v5/intro
- https://www.bybit.com/en/help-center/article/How-to-retrieve-API-documentations

## Open questions

1. DeepGamma exact pricing tiers. The features/deepgamma page renders its pricing/comparison section as a flat text block mixing DeepCharts' own tier (From 46 dollars per month, Cboe 1-minute data) with what appear to be competitor-comparison rows (From 250 dollars per month, Third-party tools only). A cleaner source should be checked to confirm whether the DeepGamma price is a standalone add-on price or requires an underlying Deepchart subscription first. **Still unresolved.**
2. ~~0.01s vs 0.015s heatmap refresh-rate claim.~~ **RESOLVED 2026-09-14** (see section 4.1 "Refresh rate discrepancy"): the DeepDOM General Settings article gives explicit, KB-documented defaults - Chart refresh 50ms (20 fps), Time & Sales refresh 300ms; the features/deepchart marketing page separately states a "0.25s refresh rate" for DOM/orderbook scalping; "0.01s Precision" remains an unqualified marketing figure of unclear referent. No page stating "0.015s" verbatim was found; treat that figure as unconfirmed/likely erroneous going forward, superseded by the 50ms/300ms/0.25s figures above.
3. ~~Color-scheme discrepancy for Buy/Sell limits.~~ corrected/RESOLVED 2026-09-14: re-fetched deepcharts.com/helpcenter/deepdom/article/heatmap and deepcharts.com/helpcenter/deepdom/article/trading-from-the-chart directly — both, plus the DeepCharts beginner-guide blog post, consistently state Green = Buy Limit, Purple/Violet = Sell Limit. No page stating the reverse ("green = Sell Limit, red = Buy Limit") was found in this pass; the original claim of a discrepancy appears to have been erroneous/unsubstantiated in the prior research pass. Treat DeepCharts' default as Green=Buy Limit / Violet=Sell Limit with no confirmed inconsistency. Note (2026-09-14 addendum): section 6.4's Volumetrica-side VolBook Heatmap article states the *reverse* mapping (green=Sell Limit, red=Buy Limit) for the underlying white-label engine - this remains a genuine, still-unreconciled discrepancy between the Volumetrica-branded and DeepCharts-branded documentation of what should be the same engine; not re-tested in this pass.
4. ~~Absorption feature - duplicate marketing description.~~ **RESOLVED 2026-09-14** (see sections 4.6/4.6a/4.6b): a dedicated Absorption KB article was located (helpdesk.deepcharts.com/portal/en/kb/articles/absorption-indicator-deepdom) with a genuinely distinct mechanic (aggressive-flow-vs-passive-resistance-at-a-level, with Max Tick/Max Orders Number/Max MS/Min. Absorption Vol. settings) confirming the pricing-page's identical Book-Speed/Absorption sentence was indeed just a marketing copy-paste error, not evidence the two indicators are the same. A second, related but distinct Absorption & Pressure module was also found under Deepchart's Deep V-Tracker indicator (4.6b).
5. Full settings for Market Regime, Book Speed, and Deep Trades. Deep Liquidity Scan and Absorption were fully resolved this pass (4.6a, 4.8); Session Imbalance got a partial (one-sentence, truncated) excerpt (7.1a item 12). Market Regime, Book Speed (article body would not render past generic help-widget chrome on two separate fetch attempts), and Deep Trades (only a short KB excerpt plus a separate Deepchart-side blog post was found, not a full DeepDom-indicator settings tree) remain **only partially documented**. A follow-up crawl using a JS-rendering fetch/browser tool specifically targeting these three would close the remaining gap.
6. ~~Full enumeration of all 135 helpdesk KB articles.~~ **PARTIALLY RESOLVED 2026-09-14** (see section 7.1a): the top-level DeepCharts KB actually totals **172 articles** (corrected from 135), and the DeepDom sub-category's full 39-article inventory is now enumerated by title, section, and one-line summary where fetchable. The remaining ~133 articles (general Deepchart help center, DeepGamma, generic technical-indicator library, installation/licensing content) were not individually enumerated in this pass - see 7.3.
7. Exact Bybit L2 push-frequency and depth-tier figures. This report states roughly 20 milliseconds for Bybit's deepest orderbook WS tier based on general knowledge referenced during research, not a freshly re-verified quote from the live V5 API docs (a direct fetch of the Bybit docs failed mid-session due to a tool error). Before any implementation work, the exact push-interval and depth-tier table for spot, linear, inverse, and option categories should be re-confirmed directly against Bybit's own V5 WebSocket orderbook documentation. **Still unresolved** - not re-attempted in this pass.
8. Tooling note, not a content gap but relevant for reproducibility: mid-session, the Parallel Search MCP web_search and web_fetch tools hit a free-tier rate limit, and a subsequent WebFetch tool call failed with an unrelated internal error. Research for the back half of this report relied on the WebSearch tool plus raw curl and HTML scraping via Bash. A few pages, including the live Bybit V5 docs and a couple of DeepCharts helpdesk articles referenced by URL but not confirmed to load cleanly, should be spot-checked if higher confidence is required.
9. New (2026-09-14): "Session Imbalance" (Initial Balance breakout levels, a DeepDom Indicator) vs. "Imbalance Book" (a Heatmap/DOM settings-tree entry per the Volumetrica VolBook article, section 6.4) vs. the research brief's generic "imbalance tracker" - these may be up to three distinct features sharing the word "imbalance," or two/three names for overlapping functionality. Not disambiguated in this pass; needs a dedicated comparison once/if Book Speed and Important Levels article bodies become fetchable.
10. New (2026-09-14): the "Volume" indicator appears twice in the crawl with near-identical but not-quite-matching descriptions (7.1 general-Deepchart Volume article: sub-modes Volume/Order/Aggregate-Trade; 7.1a item 14, DeepDom Indicators Volume article: total volume + delta-based background coloring). Unclear whether this is the same indicator documented in two product contexts or two separate features. Not disambiguated.
