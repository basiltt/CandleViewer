# DeepCharts — Deepchart platform full feature & indicator inventory

## 1. Overview

DeepCharts (deepcharts.com) is a Windows-based order-flow / volumetric trading platform built on **Volumetrica** technology, offering three product lines: **Deepchart** (charting + order flow indicators), **DeepDOM** (liquidity heatmap + DOM trading), and **DeepGamma** (options gamma exposure, not covered here). This report inventories **Deepchart** features and indicators as documented on deepcharts.com, helpdesk.deepcharts.com, and the Volumetrica help center (help.volumetricatrading.com), which is the underlying engine vendor.

Research conducted 2026-09-14 via web search against official DeepCharts help center, pricing, and feature pages (search-snippet based; original pages were not directly fetched in full due to search-tool constraints — see Open Questions).

## 2. Pricing Tiers (Deepchart / DeepDOM)

| Plan | Price (billed annually) | Includes |
|---|---|---|
| DeepCharts Orderflow | $59/month ($708/yr) | Essential volume & orderflow tools: Big Trades, Deep Print, Deep Profile, Cumulative Volume Delta, Deep Stats, Imbalance Tracker, Speed of Tape |
| DeepCharts Full Advanced | $79/month | Adds premium studies |
| DeepCharts Pro | $100/month | Full premium bundle incl. Deep-M Effort, Deep-M IVB, Deep V-Tracker, Deep Pattern Builder, Deep Swing Profile |
| DeepDOM standalone | $39/month (~$468/yr) | Heatmap Liquidity Tracker, DOM trading tools |
| DeepChart + DeepDOM Bundle | $1,599/year | Both products + Orderflow Mastery Course + VIP Discord + Liquidity Bootcamp; Windows only |

Sources: deepcharts.com/pricing/deepchart, deepcharts.com/pricing/deepdom.

[Verified via direct fetch 2026-09-14: deepcharts.com/pricing/deepchart confirms $59/mo ($708/yr, "Orderflow" tier), $79/mo ($948/yr, "Full Advanced" tier), and $100/mo (list $125, -20% promo, $1200/yr, "Pro" tier) as live prices, matching this table. corrected: the Pro tier's premium bundle is explicitly named on-site as including "DeepGamma Pro/Classic, Deep Effort (by Fabervaale), Deep Trades, Deep V-Tracker, Pattern Builder & Auto-Backtester, DeepDom (3-month trial for new users)" — Deep Swing Profile and Deep-M IVB are listed separately in the site's "Deep Models & Proprietary Tech" feature grid (available across paid tiers) rather than being Pro-exclusive line items as this table implies.]

## 3. Price Chart Settings

- Chart types: Candlestick, Bar (OHLC), Line, Equi-Volume Bars (width scales with volume), Delta-Volume Bars (color intensity = delta).
- Bar formation modes: Time-based (sec/min/day/week/month), Range (fixed tick move), Volume (fixed traded volume), Tick/Trades (fixed number of prints), Renko (brick size fixed or ATR-based, ignores time), Point & Figure (target/reversal size).
- General params: Days to Load, Continuous Contract + Rollover Basis (date/volume/price-adjusted, futures-only — N/A for crypto spot/perp), ETH session toggle, Countdown Timer to bar close.
- Delta Bars: new bar prints once cumulative delta threshold is hit.

Source: deepcharts.com/helpcenter/article/price-chart-settings, /price-settings.

## 4. Deep Print (Footprint®)

Core volumetric candle showing price/volume/order-flow fused into a grid per price level per bar.

**Type (per-cell data):** Volume, Ask/Bid Split, Delta, Delta + Total Volume.
**Mode:** Profile (histogram-style) or Box (compact numeric).
**Data Settings — Input Type:** Volume, Aggregate Volume, Order (order-book volume), Num Trades.
**Filters:** Min/Max value filter to suppress noise.
**Coloring:** background/text coloring driven by Delta or Imbalance thresholds.
**Diagonal imbalance detection:** aggressive buyers at ask vs. aggressive sellers one tick below at bid, colored green/red.

Bybit feasibility: Bybit v5 public trade stream provides trade side (Buy/Sell) and price/qty — sufficient for Bid/Ask split, Delta, Volume modes. "Order" input type (raw order-book resting volume per price) requires L2 order-book snapshots (available via orderbook.50/orderbook.200 websocket) but is NOT the same as executed footprint volume — DeepCharts' "Order" input likely refers to counting discrete order arrivals, which needs a incremental order-book diff feed; Bybit's L2 book gives depth snapshots/deltas but not per-order granularity (no L3/MBO), so true "Num Trades"/aggregate-trade counting is replicable, but order-count-based footprint variants are approximate at best.

Source: deepcharts.com/helpcenter/article/deep-print-(footprint®), helpdesk.deepcharts.com/portal/en/kb/articles/order-flow-bid-and-ask-footprint.

[Verified via direct fetch 2026-09-14: the live help-center article confirms Type options (Volume, Ask/Bid Split, Delta, Delta + Total Volume) and Input Type/Data Source options (Volume, Aggregate Volume, Order, Num Trades) exactly as listed above. Background coloration by Delta is confirmed. No changes needed.]

## 5. Deep Stats

Per-bar statistic rows/overlay (documented in indicator index as "On Candle Stats" / "Market Statistics"). Typical published stat set (per DeepCharts marketing copy): Total Volume, Bid Volume, Ask Volume, Delta, Max Delta, Min Delta, Delta %, Cumulative Delta, Number of Trades.

Bybit feasibility: fully derivable from the public trade stream (side + size), aggregated per bar.

## 6. Deep Profile (Volume/Delta Profile)

Also called "Deep Profile Values" (a lightweight variant plotting only key levels rather than the full histogram).

**VBP Period:** Composite (all loaded data), Multiples (recurring day/hour periods), Visible (chart viewport only), Personalized (manual date/time range).
**Length Type/Value:** minutes, days, weeks, months, or volume-based unit count.
**Input Data Types:** Volume, Order, Aggregate Trades, Number of Trades.
**Plotted values:** Volume POC, Value Area (~70% of volume), VWAP + standard deviations, Peaks/Valleys (HVN/LVN proxies).
**Splitting:** composite vs. session vs. custom period profiles.

Naked POC / prior-session POC persistence is implied by "Peaks and Valleys" + composite mode but not explicitly itemized in the retrieved snippets — flagged as open question.

Bybit feasibility: fully computable client-side from aggregated trade history (price/size/side); no L3 needed. Historical trade backfill depth is the limiting factor (Bybit REST recent-trades endpoint has limited lookback; needs local tick database for multi-day composite profiles).

Source: deepcharts.com/helpcenter/article/deep-profile-values.

## 7. Big Trades

Bubble/marker overlay for large aggressive executions.

**Data Settings:** Days to Load (historical depth), Input Type (which order-flow data feeds it — see "Different Types of Input Data for Indicators" cross-reference article), Filter Mode: Manual (Min/Max trade-size thresholds) or Automatic ("Big Trades Analysis" algorithm auto-determines optimal size threshold via Intensity Level: Low/Medium/Strong, acting like automatically-calculated Min/Max filters).
**Zones Settings (verified addition):** Body Mode (All / Reverse Only / Trend Only / None) controls whether zones are plotted for aggressive-buyer/aggressive-seller trades relative to candle direction; Bid Color/Ask Color/Opacity for zone rendering.
**Premium add-ons (per pricing page):** MBO data, iceberg detection, aggregation technology (i.e., stitching together rapid consecutive same-side prints into one "iceberg" execution).

Bybit feasibility: trade size + side directly available via public trade stream — bubble overlay fully replicable. Iceberg/MBO-dependent aggregation requires knowing individual resting order identity (L3), which Bybit does not expose; can approximate icebergs only via repeated same-price/same-side prints heuristics, not true iceberg detection.

Source: deepcharts.com/helpcenter/article/big-trades, helpdesk.deepcharts.com/portal/en/kb/articles/deep-trades.

[Verified via direct fetch 2026-09-14: help-center article confirms "Big Trades Analysis" as "a DeepCharts algorithm that dynamically calculates optimal large-trade thresholds based on price behavior and volatility," with Filter Mode → Automatic → Intensity Level (Low/Medium/Strong), matching the "statistical outlier detection" characterization above. corrected: added the previously-unlisted Zones Settings (Body Mode, Bid/Ask Color, Opacity) confirmed in the same article.]

## 8. Imbalance Tracker

Detects/plots aggressive one-sided (bid vs ask) clusters without needing to zoom into footprint cells.

**Settings:** Minimum % imbalance, Minimum volume difference, Number of consecutive imbalances (persistence threshold), Display duration for detected imbalance markers, Coloring.
**"Virgin Zone" feature:** highlights untouched high-imbalance price zones that may act as a future price magnet (akin to unfilled liquidity voids).

Source: help.volumetricatrading.com Imbalance Tracker article; deepcharts.com/helpcenter/indicators.

[Verified via direct fetch 2026-09-14 of help.volumetricatrading.com/en/support/solutions/articles/204000012056-imbalance-tracker: confirms Imbalance-minimum %, Minimum volume-difference, Include zero on imbalance, Min. no. of consecutive imbalances, Number bars-extension, Line thickness, and a "Virgin Zone" concept (imbalance area not yet retraced) with buy/sell colors, plus a separate "Zone Crossed" state (Show zone-crossed, Signal-only-touch) once price retests the zone. corrected: "Include zero on imbalance" was missing from the original settings list — added. Also note the article cross-references two related-but-distinct indicators not previously mentioned in this doc: "Imbalance Rejector" and "Session Imbalance" — worth a follow-up look since they may overlap with or replace some of the imbalance-tracking scope assumed here.]

## 9. Unfinished Auction

Flags a bar's high/low where the auction wasn't "finished" (i.e., the extreme print wasn't met with full opposing aggression — e.g., volume appears at the Bid on a new high tick instead of purely at the Ask).

**Settings:** color, rectangle display toggle, background opacity, volume filter threshold.
Marked with a rectangle on the chart; used as a target/magnet reference for future price revisits.

Source: deepcharts.com/helpcenter/article/unfinished-auction.

## 10. Bar POC

Point of Control within a single footprint bar — the price level with the most volume traded in that bar. Marked distinctly on the footprint cell grid; used for intrabar support/resistance.

## 11. Speed of Tape (incl. "Instant" variant)

Measures market activity velocity within a rolling time window.

**Input Data:** Volume, Order (order count), Trades (trade count).
**Filters:** Filter Min/Max (only flag bars beyond threshold), Number of Seconds (rolling window length, e.g. 10s), Std Dev Per Filter (statistical spike filter to suppress noise).
**Style:** Bull Border/Fill, Bear Border/Fill colors, Line style & width (candlestick vs. line rendering), Short Name label.

Two variants exist: standard "Speed of Tape" and "Speed of Tape (Instant)" — likely differing in whether it uses a rolling window vs. tick-by-tick instantaneous rate; exact distinction not confirmed from snippets (open question).

Source: deepcharts.com/helpcenter/article/speed-of-tape, /speed-of-tape-(instant).

[Verified via direct fetch 2026-09-14: the live Speed of Tape article confirms Input Data options as "Volume" and "Order" (order count) — it does NOT show a third "Trades" input type in the fetched content; only two Input Data options were found (Volume, Order). corrected: "Trades" as a third Input Data option is unconfirmed — flag as unverified rather than stated fact until the Instant variant page is checked directly. Number Seconds parameter (rolling window length, e.g. 60s) confirmed. Subgraph settings (Subgraph Style: candlesticks, Line Style, Line Width, Short Name) confirmed, matching "Style" bullet above.]

## 12. VWAP & Envelopes

**Period Mode:** Day, Minutes, Seconds, Orders (defines the VWAP anchor/reset window) — implies anchored VWAP support (custom start point) in addition to session VWAP.
**Envelope Mode:** Standard Deviation (statistical, calculated from price dispersion around VWAP) or Percentage (fixed % offset).
**Envelope Parameters:** configurable multipliers for 1st/2nd/3rd bands (≈68%/95%/99.7% coverage under normal-distribution assumption), or fixed percentage values per band.
**Display:** per-band color, width, show/hide toggles.

Source: deepcharts.com/helpcenter/article/vwap-envelopes, /helpcenter/deepdom/article/vwap-envelopes.

[Verified via direct fetch 2026-09-14: confirms 1st/2nd/3rd Standard Deviation Value bands (1UP/1DW, 2UP/2DW, 3UP/3DW) with ~68%/95%/99.7% normal-distribution coverage language matching this doc's characterization exactly, plus per-band color/line-style/width subgraph settings. corrected: "Period Mode: Day, Minutes, Seconds, Orders" — the "Orders" period-mode option was NOT found in the fetched article content (which only showed Envelope Parameters and Subgraph sections); this should be treated as unverified rather than confirmed until the top-of-article "General" settings section is directly checked.]

**Anchors/bands — GAP PARTIALLY RESOLVED** [verified: help.volumetricatrading.com/en/support/solutions/articles/204000014225-vwap]: the base VWAP article confirms Band Calculation Mode = **Standard Deviation** or **Percentage change in price** (matching the Envelope Mode already documented above), plus Display Settings (Line Color, Line Thickness, Bandwidth, Band Style). This is a separate, simpler "VWAP" article distinct from "VWAP Envelopes" — the two appear to be a base indicator (single VWAP line + basic bands) and an enhanced variant (multi-band 1/2/3 STD envelope), consistent with a "VWAP" + "VWAP Envelopes" pairing seen elsewhere in the indicator index. Anchor/period-reset options beyond session-based VWAP (e.g., true user-click "Anchored VWAP" from an arbitrary bar, as popularized by TradingView) were **not confirmed** in either article — still open whether DeepCharts supports an anchor-from-any-point-on-chart mode vs. only fixed period-based resets (Day/Minutes/Seconds/session).

## 13. Cumulative Volume Delta (CVD)

Documented display modes: Candlestick, Histogram, or Line. Related indicators in the index: "Delta Cumulative Candlestick", "Delta Cumulative Histogram" (tracks cumulative buy/sell pressure difference over a period), "Delta Bar" (single-bar delta), "Delta % Highlight" (colors bars by delta as % of volume), "Divergence Detector" (flags price/volume or price/delta divergence via on-chart labels).

## 14. Market Profile (TPO) — GAP RESOLVED

[Verified: deepcharts.com/helpcenter/article/market-profile, help.volumetricatrading.com/en/support/solutions/articles/204000011846-tpo-time-price-opportunity-aka-market-profile-]

The TPO (Time Price Opportunity), aka Market Profile®, visualizes price/time/volume distribution. Market is divided into "periods" (default 30 minutes), each represented by a sequential alphabetical letter (A→Z) marking price evolution through the session. Displayed alongside Volume Profile for combined structure analysis.

**Typology settings:**
| Parameter | Meaning | Options |
|---|---|---|
| TPO Base Minute | Duration of one TPO period/letter | Default 30 min, user-customizable |
| TPO Type | Rendering style | Blocks (discrete letter blocks per interval) / Profile (continuous histogram of time-at-price) |
| Period TPO | Reference period grouping | Composite (whole loaded range → one profile) / Multiples (separate profile per session) / Custom (user-defined range) |
| Length Type / Length Value | Unit + count for the period (when Multiples/Custom) | minutes/days/weeks/months; e.g. Length Type=Days, Length Value=2 → new profile every 2 days |
| Split TPO | Separates TPO into individual base-minute periods with distinct settings | None / Last (only most recent shown separately) / Every (all periods split) |
| Custom Date/Time | Manual start point when Period TPO = Custom | date/time picker |
| Background → "Third Range" | Highlights the "C period" range (i.e., end of Initial Balance-equivalent window) | toggle |

Data required: trade prints with timestamp + price (no side/volume needed for pure TPO letters, since TPO measures *time* spent at price, not volume — a key structural distinction vs. Deep Profile/Volume Profile). A 30-min "period" naturally maps to Bybit's continuous trade websocket feed bucketed by wall-clock time; crypto's 24/7 session means "day" boundaries must be redefined (see Deep-M IVB note below) — no natural RTH open/close exists, so Composite/Custom period definitions (e.g., UTC 00:00 rollover) will matter more than for TradingView-style single-session RTH markets.

Standard Market Profile concepts (industry-standard, not deepcharts-specific) also relevant for a CandleViewer implementation: POC (letter-count mode, distinguished from Volume POC), Value Area (default ~70% of TPO count, mirroring the Deep Profile Value Area %), Initial Balance (first N periods, typically first hour = periods A+B), single prints (naked/thin letters, potential support/resistance), and D-profile / P-profile / b-profile shape classification for balanced vs. trending sessions [inferred; general Market Profile theory, e.g. crosstrade.io/learn/technical-indicators/market-profile-tpo].

## 15. Deep-M Effort

Proprietary trend/order-flow-bias model, marketed as pre-optimized for NQ futures on a 40-Range chart (by "Fabervaale" / Fabio Valentini). [Verified: attribution to Fabio Valentini ("Fabervaale") confirmed directly on deepcharts.com/pricing/deepchart ("DeepM Effort NQ - By Fabervaale... A proprietary study by Fabio Valentini on paths of least orderflow resistance") and via helpdesk.deepcharts.com/portal/en/kb/articles/deep-m-effort-nq.]
- Colored directional-bias zones: green = bullish path of least resistance, purple = bearish.
- Includes a dynamic chart-specific moving average for confirmation.
- Alert system on directional-bias shift.
- Marketed as "ready to use" with minimal user-configurable core settings.

Note: instrument-specific tuning (NQ, 40-range) means direct portability to crypto (BTC/ETH perps) would need re-calibration; the underlying method (order-flow path-of-least-resistance) is conceptually replicable from trade-and-book data but the specific algorithm is proprietary/undocumented.

## 16. Deep-M IVB

Algorithmic Opening-Range-Breakout (ORB) tool ("Instrumented" ORB) using historical statistics to auto-plot projection/protection/exit levels for the RTH opening range.
- Plots high/mid/low reference lines and statistically-derived breakout target zones.
- Reaction zones mark likely price-response areas.
- Minimal setup; customizable line/zone visualization.

Crypto relevance: since crypto markets trade 24/7, the concept of a single daily "RTH opening range" doesn't map cleanly — would need redefinition (e.g., UTC daily open, or exchange-specific session) for a Bybit implementation.

[Verified via direct fetch 2026-09-14: help-center article confirms Deep-M IVB is "an algorithmic indicator developed by the Deepcharts team to simplify trading the Opening Range Breakout (ORB) structure," providing "Automated opening range calculation, Predefined projection and protection levels, Reaction zones during breakouts, Clear daily bias summary." corrected: pricing-page copy attributes it to "Fabervaale" ("DeepM IVB - By Fabervaale"), i.e. also a Fabio Valentini product, not a generic in-house Deepcharts team tool as this doc's phrasing implied — added for accuracy.]

## 17. Deep V-Tracker

Order-flow tool for volumetric imbalance/pattern detection.
- **Patterns Module:** detects Acceleration, Exhaustion, Slowdown within candle sequences.
- **Absorption & Pressure Module:** color-coded horizontal lines marking where buyers/sellers absorb or exert pressure, with "control"/"extreme" labels.
- Configurable noise filtering and visual markers.

[Verified via direct fetch 2026-09-14: help-center article confirms Deep V-Tracker has exactly two modules — "Patterns" (Acceleration/Exhaustion/Slowdown, with Pattern Mode strength levels Strong/Medium/Weak) and "Absorption & Pressure" — matching this section. No changes needed.]

## 18. Deep Pattern Builder

Visual rule-builder / custom-indicator-construction tool, described as DeepCharts' most advanced feature.
- Supports up to 4 inputs referencing OHLCV data, Delta, or outputs of other indicators.
- Logical operators (AND/OR) and math operators to combine conditions.
- Automatic backtesting/simulation of the built rule set against historical data.

This is conceptually the closest DeepCharts analog to a "custom rule-based stop/exit" builder that CandleViewer's spec requires — worth studying further as a UX reference (open question: exact condition-editor UI/serialization format not retrieved).

[Verified via direct fetch 2026-09-14: help-center article confirms condition inputs can reference candle data ("Reference"), "Indicator" outputs (e.g. Delta from Deep Stats), or a fixed "Constant" value, plus an "Unused" disable state; conditions combine via OR, AND, or "AND + OR (Advanced)" up to four conditions, matching the up-to-4-inputs / AND-OR claim. corrected: no explicit confirmation of "math operators" (e.g. +/-/*) beyond logical combination was found in the fetched excerpt — soften to "logical combination of up to 4 conditions" rather than asserting general math-operator support; also the workflow example applies Deep Pattern Builder on top of a "Deep Trades" indicator already on the chart, i.e. it appears designed to reference other indicator outputs, not just raw OHLCV/Delta.]

## 19. Deep Profile Swing (a.k.a. "Deep Swing Profile") — GAP RESOLVED

[Verified: deepcharts.com/helpcenter/article/deep-profile-swing]

The real help-center name is **"Deep Profile Swing"** ("Deep Swing Profile" in marketing/pricing copy is the same feature, informally reordered). It automatically plots a Volume Profile keyed to detected price swings rather than fixed time windows.

**General settings:**
| Parameter | Meaning | Options |
|---|---|---|
| Vbp Type | Which profile metric to plot per swing | Volume / Ask-Bid split (implied) / Delta and Total Volumes / Delta Percentage / VWAP (profile calculated relative to swing VWAP) |
| Include Reversal Bar | Whether the bar that starts a new swing counts toward the just-closed swing's profile | on/off |
| Display Mode | Rendering | Profile And Lines (full histogram + key level lines) / Lines Only (just POC/VA lines, no histogram) |

**Main Swing Settings (defines what counts as a "swing"):**
| Swing Type | Definition |
|---|---|
| Left Right Bar | Fixed bar-count pivot detection (N bars left/right must be lower/higher) |
| Highest Lowest | New swing starts on a new high or new low vs. prior extreme |
| Reversal Absolute | Swing ends only after a fixed absolute price reversal ("Abs. Rev" param) — filters out small retracements |
| Reversal Tick | Swing ends after a fixed number of ticks of reversal ("Tick Rev." param) — for short-timeframe precision |

Additional params: **Right Bar** (bars-to-the-right required to confirm a Left-Right-Bar swing pivot), **Swing Stop Settings** (mirror of Main Swing Settings but governing when the *current* swing is considered ended — "Enable Stop Swing" toggle), and a **VWAP Swing** sub-mode with **Swing Max Ticks** (forces a new swing after a max tick excursion, preventing one profile from spanning an excessively long move) and **VWAP Break Ticks** (ticks required to confirm a break of the swing's VWAP, which can end/start a swing).

Data required: OHLCV + trade prints with side (for Delta/Delta% variants) — same as Deep Profile; swing-detection logic runs on price only, so it's a pure price-swing overlay conceptually similar to ZigZag + Volume Profile combined. Fully replicable from Bybit trade data with no additional feed requirements.

## 20. Deep Trades vs. Big Trades — GAP RESOLVED

[Verified: helpdesk.deepcharts.com/portal/en/kb/articles/deep-trades, www.deepcharts.com/helpcenter/article/deep-trades, www.deepcharts.com/helpcenter/article/big-trades]

**Finding: "Deep Trades" and "Big Trades" are the same underlying indicator/settings schema, documented under two article titles/URLs that largely mirror each other verbatim** (both articles' fetched excerpts contain byte-for-byte identical section headers: "1.1 Data Settings > Filter Mode" with Manual/Automatic, "1.2 Plot Settings > Size" with Standard Deviation/Min/Max Size, "1.2 Plot Settings > Color" with Min/Max Opacity + Ask/Bid Color, and a "1.4 Big Trades Analysis" sub-article reference in both). The help center's own site search / knowledge-base URL (`helpdesk.deepcharts.com/.../deep-trades`) actually renders with the page title "Big Trades," confirming these are the same feature — "Deep Trades" is simply an older/alternate naming (article dated Jun 2, 2026 vs. Big Trades article dated Aug 18/Sep 7, 2026, suggesting Big Trades is the current canonical name and Deep Trades is a legacy alias kept for SEO/old-link continuity). There is **no evidence of two functionally distinct indicators** — treat "Deep Trades" and "Big Trades" as one feature in CandleViewer's spec.

**Full confirmed parameter set (Big Trades / Deep Trades):**
| Section | Parameter | Meaning / Options |
|---|---|---|
| Data Settings | Days to Load | Historical depth of large-trade data loaded |
| Data Settings | Input Type | Volume / Order / Aggregate Volume / Num Trades (see §Different Types of Input Data) |
| Data Settings | Filter Mode | Manual (user Min/Max) or Automatic (Big Trades Analysis algorithm) |
| Data Settings | Manual Filter Min/Max | e.g. Min=30 → only trades ≥30 contracts plotted |
| Data Settings | Automatic → Intensity Level | Low / Medium / Strong — auto-computed thresholds refreshed via a one-off "Big Trades Analysis" run (Options → Tools → Big Trades Analysis), results cached, no need to rerun each session |
| Plot Settings — General | Marker Type | Circle / Square / Diamond / Text |
| Plot Settings — General | Hollow Fill | outline-only markers |
| Plot Settings — Size | Standard Deviation | controls marker size scaling (keep default recommended) |
| Plot Settings — Size | Minimum/Maximum Size | marker px bounds |
| Plot Settings — Color | Min/Max Opacity, Ask Color (aggressive buyers), Bid Color (aggressive sellers) | |
| Plot Settings — Text | Plot Only Inside Bar, Text Size, Text Color | only when Marker Type=Text |
| Zones Settings — General | Biggest Only | zones plotted only for the largest trades |
| Zones Settings — Shadow Mode (wick trades) | All / Reverse Only (bearish→buyers, bullish→sellers) / Trend Only (bearish→sellers, bullish→buyers) / None | |
| Zones Settings — Body Mode (body trades) | same 4 options as Shadow Mode, applied to candle-body trades instead of wick trades | |
| Zones — Color | Bid Color, Ask Color, Opacity | |
| Alert Settings | Enable Alert Sound, Bid Alert (sound on aggressive sell), Ask Alert (sound on aggressive buy) | |

Data required: trade prints with side + size — fully available on Bybit's public trade websocket stream. No L2/L3 dependency for the core marker/zone logic; only the "Order" Input Type variant (see §4) is L2-approximate.

## 21. Deep Replay (Tick Replay / Backtester)

Tick-level (Market-By-Order/MBO) historical replay engine, distinct from a live data feed.

- **Setup:** Options → Replay Tick Data → Manage Settings → select symbol + date range via calendar → open new chart → Play.
- Requires disconnecting from any live feed and closing open charts first (replay ≠ live-feed overlay).
- **Speed control:** presets or scroll bar to slow down/fast-forward.
- **Simulated trading:** place trades via chart or DOM during replay in sim mode.
- Footprint/order-flow visuals update live during replay exactly as historically occurred, including Big Trades markers.

Bybit feasibility: fully replicable if CandleViewer stores raw historical trade+book-delta data locally (tick database) — no dependency on proprietary MBO from the exchange since Bybit trade stream already includes side; true book-replay would need locally stored L2 diffs snapshotted over time.

Source: deepcharts.com/helpcenter/deepdom/article/replay-tick-data, helpdesk.deepcharts.com/portal/en/kb/articles/replay-data.

## 22. Trading Terminal / Trading From The Chart

- **Enable trading:** Dollar icon (top-left of chart) or right-click → "Trading enabled."
- **Trading Panel:** toggle via checkbox or right-click → "Show trading panel."
- **Order placement:** Market/Limit/Stop via panel buttons or by clicking directly on the chart at a price.
- **Order management:** left-click an order line to move/reprice it; right-click to cancel.
- **Flat button:** closes open position and cancels all pending orders in one action.
- **OCO (Order-Cancel-Order) strategies:**
  - **SL/TP mode:** simple one Stop-Loss + one Target-Price OCO pair; size settable in ticks or money.
  - **Multi mode:** advanced — multiple contracts, move-to-breakeven, multiple scaled targets.
  - **Server OCO:** managed broker-side (survives disconnect); supported with Rithmic and DXFeed (futures-specific — Bybit equivalent would be its own conditional/OCO order types via REST/WS, need to verify Bybit v5 API OCO support).
  - **Client OCO:** managed locally by the platform; requires the platform to stay connected.
  - Quick ad-hoc OCO: click the "SL"/"TP" squares that appear on any open trade to fast-create an exit pair.
- **Trade Copier:** DeepCharts help center has a dedicated article "How to Setup DeepCharts Trade Copier" (multi-account order mirroring) — relevant to CandleViewer's "few account managers" requirement.
- **Risk Manager:** dedicated help-center article exists; likely account-level max-loss/position-size guardrails — details not retrieved (open question).
- **Strategy Reports:** Trading menu → Strategy Report → choose Broker/Account → generates a performance report.
- **Orders Window:** dedicated management view for all open/working orders.

## 23. Keyboard Shortcuts (Hotkeys) — GAP RESOLVED

[Verified: deepcharts.com/helpcenter/article/configure-keyboard-shortcuts]

Configured via **Options → Settings → Shortcuts column**.

**Category (functional grouping):**
- General — general platform functionality
- Chart — chart-related functions

**Type of Shortcut (action grouping):**
- Action — execute specific functions
- Control — control platform behavior
- Drawing and Annotation — drawing tools and annotations
- Scroll — navigation and scrolling functions
- Trading — trading-related operations

**Shortcut table columns:** Category, Type, Description, configured key-combination.

**To create a new shortcut:** click **Register** → physically press the desired key combination on the keyboard → click **Save Settings** to activate.

No specific default key-bindings (e.g. which key = Buy Market) were enumerated in the fetched article — the platform appears to ship with user-assignable slots per category/type rather than a fixed documented default map; open question if a full default hotkey table is needed for CandleViewer UX parity (would require a deeper fetch of a "default shortcuts list" if one exists, not found in this pass).

## 24. DeepDOM (Liquidity Heatmap + DOM) — Context for Deepchart Integration

Although DeepDOM is a separate product/bundle, it's tightly integrated with Deepchart and directly relevant to CandleViewer's "DeepDOM liquidity heatmap" requirement:

- **Heatmap:** color-coded real-time visualization of resting limit-order liquidity concentration per price level (dark/warm = high concentration).
- **Data streams fused:** live limit-order book (DOM) + executed trades (Time & Sales) shown together.
- **Historical playback:** records order-book evolution over time so a liquidity zone's formation (gradual build vs. sudden appearance) can be reviewed.
- **MBO vs. MBP modes:** Market-By-Order (individual order-level detail — needs L3) vs. Market-By-Price (aggregated per-level volume — L2 sufficient). Enables iceberg/absorption-wall detection when MBO is available.
- **DOM panel:** live bid/ask size ladder alongside heatmap; place/manage/modify limit & stop orders directly from DOM or chart.
- **Stop-run tracker / iceberg tracker:** flagged as premium/advanced features.
- Designed to be resource-light vs. legacy heatmap tools.

Bybit feasibility: Bybit provides L2 order-book (orderbook.1/50/200 depth websocket streams with incremental updates) — sufficient for an MBP-style heatmap and DOM ladder. True MBO (per-order granularity, individual order IDs) is **not available** from Bybit's public API (no L3 feed), so genuine iceberg/order-level absorption-wall detection is **not possible**; only trade-print-based heuristic approximations (e.g., repeated fills at a price without visible book depletion) are feasible.

Source: deepcharts.com/helpcenter/deepdom/article/heatmap, deepcharts.com/features/deepdom.

## 25. Data Feeds & Brokers Supported (Deepchart, futures/legacy context)

DeepCharts targets futures traders; supported feeds/brokers per help center: dxFeed (primary, both desktop & web), CQG, Rithmic, IQFeed, MetaTrader 5, Interactive Brokers (TWS/IB Gateway — aggregated data only, not suitable for full order flow), Quote Media, Trading Technologies, plus direct brokerage integrations (Directa, Sella, IWBank, WeBank). Exchanges covered: CME, CBOT, COMEX, NYMEX, EUREX, NASDAQ, and Italian markets (MTA, IDEM, MOT). Platform: Windows standalone (full features) + web version (dxFeed-based, some feature/broker limits) + Mac via Parallels/VMWare or web/Safari.

This confirms DeepCharts has **no native crypto-exchange integration** (no Bybit, Binance, etc. listed) — CandleViewer would need to build its own Bybit v5 WebSocket/REST connector from scratch; there is no DeepCharts crypto adapter to reference architecturally beyond general design patterns (feed abstraction, symbol manager/entitlements concept).

## 26. Templates, Workspaces, Compact View, Screenshot Workflow — GAP PARTIALLY RESOLVED

[Verified: deepcharts.com/helpcenter/article/templates-and-workspaces]

- **Templates** store a single chart's current setup — indicators, styles, settings. Saved/loaded via right-click on chart → Load/Save Template.
- **Workspaces** store the entire layout — multiple charts, indicators, and profiles together (i.e., a workspace = a saved arrangement of N chart windows, each potentially with its own template applied). Saved/loaded via a dedicated workspace management panel.
- Both Templates and Workspaces can be saved **locally or to the cloud**, enabling config restore across machines/reinstalls.
- Related: help desk references "Orderflow Templates and Workspaces - DeepChart" — ready-made (pre-built) Orderflow templates/workspaces ship with the platform so users don't have to build from scratch [inferred from related-article teaser text; full article not fetched].

Compact/group multi-chart view and screenshot workflow specifics remain unretrieved — still an open question requiring a further targeted fetch.

## 27. Performance Analysis / Strategy Reports (closest match to "Auto-Tracker Journal") — GAP RESOLVED (naming)

[Verified: deepcharts.com/helpcenter/article/performance-analysis]

No feature literally named "Auto-Tracker" or "Auto-Tracker Journal" was found anywhere on deepcharts.com, helpdesk.deepcharts.com, or help.volumetricatrading.com in this research pass — **the project brief's "Auto-Tracker" appears to be a mislabeling of DeepCharts' "Performance Analysis" / "Strategy Reports" feature** (or possibly conflated with the unrelated third-party "TradesViz" auto-import journal service some DeepCharts users pair with the platform, or with "Big Trades Analysis" — the auto-threshold-tuning routine described in §20 — whose name is superficially similar to "Auto-Tracker"). Treat as resolved-as-non-existent; document the actual feature instead:

**Strategy Reports workflow:**
1. Trading menu → Strategy Report.
2. Choose Broker + Account to analyze.
3. Scroll-wheel date-range/symbol picker (top-right) to scope the report.
4. Click Generate Report.

**Report sections:**
| Section | Contents |
|---|---|
| Strategy Performance | Balance, Profit, Losses, Number of trades executed, Commissions (optional), DrawDown, Run-up, % winning trades — split by period |
| Trade List | Per-trade: entry/exit time, entry/exit price, quantity, Profit, DrawDown, Run-up |
| Symbol Performance | Balance per symbol traded — identifies best/worst instruments |
| Chart | Equity curve, drawdown chart, per-trade visual breakdown |
| Time Analysis | Profitability by hour of day (best/worst trading hours), plus daily/monthly/annual aggregation views |

Data required: full closed-trade execution history (fills, timestamps, fees) — this is a pure post-trade analytics feature, not a market-data indicator; fully buildable in CandleViewer from its own order/fill database once paper + live trading are implemented. No exchange-side dependency beyond normal fill reporting.

## 29. Stop-Run & Iceberg Detector Confirmation — GAP RESOLVED

[Verified: helpdesk.deepcharts.com/portal/en/kb/articles/stop-run, help.volumetricatrading.com/.../204000013234-stop-run, deepcharts.com/helpcenter/article/deep-wall, helpdesk.deepcharts.com/portal/en/kb/articles/deep-wall]

DeepCharts documents **two separate, confirmed indicators** covering this ground — a **Stop Run** detector and a **Deep Wall** iceberg-signature detector — plus a **Divergence Detector** for delta/price divergence (see §13) and an **Imbalance Rejector** (reversal-pattern, §30). No single unified "stoprun/iceberg detector" exists; CandleViewer's spec item maps to these two:

### Stop Run
Detects when a large cluster of resting stop orders is triggered simultaneously (a fast, non-organic price move caused by stop-loss cascades rather than fresh directional conviction), which frequently reverses shortly after.
| Parameter | Meaning |
|---|---|
| Minimum Tick | Minimum number of ticks price must move (as a result of triggered stops) before the move qualifies as a Stop Run — filters noise from ordinary small moves |
| Min. Stop Run Vol | Minimum volume required during the triggering window to qualify — small stop clusters that can't move the market are excluded |
| (Volumetrica-side additional fields, per help.volumetricatrading.com) Max number of orders, Max MS (max milliseconds — i.e. the triggering cascade must complete within this time window to count as "simultaneous"), Display Mode, Ask/Bid Color, Marker Thickness, Text Settings | plot/visual customization |

Confirmation logic (descriptive, not exact algorithm): flags a level as a Stop Run when (a) price moves ≥ Minimum Tick within a short time window (≤ Max MS), (b) the move is driven by a burst of order execution ≥ Min. Stop Run Vol, and (c) it typically occurs at an "obvious" prior high/low/support/resistance level where many traders' stops would cluster. This is conceptually **derivable from Bybit's public trade stream alone** (price + size + timestamp, no L2/L3 required) — a burst-detection heuristic (N contracts within M milliseconds moving price by K ticks, historically likely at a "test of prior extreme" level) is directly implementable; DeepCharts does not appear to use L3 stop-order visibility (retail platforms never see the resting stop book) so this is pure trade-tape pattern recognition, fully replicable.

### Deep Wall (iceberg confirmation signal)
- Specialized indicator (documented as ES-futures-tuned by DeepCharts) that monitors price behavior at key levels to detect **passive order walls that absorb aggressive orders**, causing price rejection — this absorption pattern is DeepCharts' stated signature of a **hidden (iceberg) order**.
- Explicitly described as **rare** — appears only a few times per week/month, mostly in low-liquidity sessions (e.g. London session for ES).
- Settings are minimal/pre-tuned: Alert Sound (Options → Settings → Add Alert) and Message Popup on trigger; no manual threshold parameters are exposed to the user (a "recommended general settings" preset is used internally).
- Use case: detect hidden liquidity / high-probability price reversals from repeated absorption at a level.

Bybit feasibility: since Bybit exposes no true iceberg/hidden-order flag and no L3 per-order visibility, an iceberg-confirmation heuristic in CandleViewer would have to replicate Deep Wall's *behavioral* definition — repeated aggressive prints at/near one price level failing to move price further (i.e., large executed volume absorbed with minimal price progress, followed by rejection) — using trade-tape + L2 book-depth-refill patterns (does resting size at that price level keep refreshing after being hit?) as a proxy. This is an approximation of iceberg presence, not a direct confirmation, consistent with the general L3 gap noted throughout this doc.

## 30. Additional Confirmed Indicators (Imbalance Rejector, Deep Delta, Confluence Identifier, Auction Gap Tracker) — market-regime-adjacent tools

[Verified: deepcharts.com/helpcenter/article/{imbalance-rejector, deep-delta, confluence-identifier, auction-gap-tracker}]

No indicator literally named "Market Regime" was found on DeepCharts. The project brief's "market regime indicator" likely maps loosely to a combination of **Deep-M Effort** (directional-bias/path-of-least-resistance zones, §15), **Confluence Identifier** (structural S/R strength), and general trend/oscillator indicators (Super Trend, ADX, Aroon) listed in the indicator index — DeepCharts does not appear to have a single dedicated regime-classification (trending vs. ranging) study. Flag as **resolved-as-non-existent**; recommend CandleViewer design its own regime classifier (e.g. ADX + realized-volatility-based) rather than porting a DeepCharts feature.

**Imbalance Rejector** (reversal-pattern detector distinct from Imbalance Tracker, §8):
| Parameter | Meaning |
|---|---|
| % Min. Imbalance | Minimum imbalance % required at the candle's high (bearish candle) or low (bullish candle) to flag a rejection setup |
| Minimum Diagonal Comparison | How many diagonal tick-levels back to compare when searching for the imbalance (1 = compare last Ask tick vs. 2nd-to-last Bid tick, etc.; higher = deeper diagonal search) |
| Lookback Period | Bars to the left required to qualify a high/low as a valid "swing point" candidate — shorter = more (less reliable) signals, longer = fewer (more reliable) signals |
| Tick Offset | Ticks away from the swing high/low where the marker is actually plotted |

**Deep Delta** (advanced evolution of classic Delta Bars):
| Parameter | Meaning |
|---|---|
| Input Data | Volume / Aggregate Trades / Trades (transaction count) |
| Delta Mode | Classic (standard unfiltered Delta Bars) / Multi-Range (activates "Delta Filter Bars" — up to 4 separately filterable delta ranges) |
| Range 1–4 Min/Max | Per-range filter bounds (max=0 disables max filter) — lets a trader isolate e.g. only "extreme" delta pushes vs. "moderate" ones in separate visual bands |
| Threshold → Level Settings | Up to 2 horizontal reference lines at user-defined positive/negative delta levels |
| Threshold → Marker | Vertical marker when both min and max delta in a bar cross set thresholds — flags absorption (push then reversal within the same bar) or acceleration patterns |

**Confluence Identifier** (automated multi-source S/R zone detector):
| Parameter | Meaning |
|---|---|
| Tick Sensitivity | Price range (in ticks) within which separate elements must align to count as one confluence zone; smaller=more precise zones, larger=broader zones |
| Minimum Number of Confluences | How many elements must align to generate a zone; higher=fewer/stronger zones |
| Starting Mode | Zig Zag (calculation start determined by swing-based Zig Zag) or Date (manual start) |
| Zig Zag Swing Settings — % Absolute Variation | Two-stage ZigZag: a coarser % reversal picks the calculation start date, a finer % reversal identifies the actual swings used for confluence |
| First/Second/Third VBP (Volume-By-Price) | Up to 3 separate Volume Profiles (Daily/Weekly/Monthly/Composite) can each contribute Enablements: POC, Value Area, Peaks, Valleys, Delta Imbalances — any combination feeds into the confluence scoring |
| Support & Resistance Colors | Color intensity scaled by confluence-count (stronger zones visually emphasized) |

**Auction Gap Tracker** (a.k.a. "Unfinished"/zero-print detector, related to §9 Unfinished Auction):
| Parameter | Meaning |
|---|---|
| Minimum Tick Vol | Minimum volume the tick where a "0" (unfinished print) occurs must have to qualify |
| Threshold-max. unfinished | Ceiling defining what counts as "unfinished": 0 = only true zero-prints tracked; 1 = also tracks 1-contract-only prints on Ask/Bid, etc. |
| Include Mode | Intrabar (only unfinished prints inside the bar, excluding the bar's high/low) or All (tracks all qualifying unfinished prints including at the extremes) |
| Min. Num. of Consecutive Zero | Minimum consecutive zero/thin price levels required to trigger a highlight (e.g. 5 → only flags runs of ≥5 consecutive thin levels) |

All four indicators above require only trade prints with price/size/side (Bybit-sufficient); Confluence Identifier additionally needs multi-timeframe Volume Profile computation (derivable from the same trade-tape data, just aggregated over longer/multiple periods).

## 28. Full Feature Table — Summary

| Feature | Category | Bybit Data Sufficiency |
|---|---|---|
| Deep Print (Footprint) | Volumetric candle | Yes (trade+side); "Order" input type approximate |
| Deep Stats | Per-bar stats | Yes (trade+side) |
| Deep Profile | Volume/Delta profile | Yes, given local tick DB |
| Big Trades | Large-trade bubbles | Yes; iceberg/MBO features not possible |
| Imbalance Tracker | Aggressive-cluster detector | Yes |
| Unfinished Auction | Bar-extreme auction flag | Yes |
| Bar POC | Intrabar volume node | Yes |
| Speed of Tape | Tape-velocity meter | Yes |
| VWAP + Envelopes | Anchored VWAP/bands | Yes |
| CVD (candlestick/histogram/line) | Cumulative delta | Yes |
| Market Profile (TPO) | Time-based profile | Yes (time-in-price, no volume needed) |
| Deep-M Effort | Proprietary bias model | Conceptually yes; exact algorithm proprietary |
| Deep-M IVB | ORB statistical model | Needs "session" redefinition for 24/7 crypto |
| Deep V-Tracker | Absorption/pattern detector | Yes, approximate (algorithm undocumented) |
| Deep Pattern Builder | Custom rule/backtest builder | Yes — good UX reference for CandleViewer's custom stop/exit rules |
| Deep Swing Profile | Swing-anchored profile | Yes, conceptually |
| Deep Replay | Tick replay/backtester | Yes, given local tick+book-delta storage |
| Trading Terminal / OCO / Trade Copier | Execution | Partial — Bybit lacks server-side OCO/bracket identical to futures brokers; must implement client-side or via Bybit conditional orders |
| DeepDOM Heatmap + DOM | Liquidity depth | Yes via L2 (MBP); true MBO/iceberg not possible |
| Data Feeds | Broker/feed integration | No crypto feeds exist in DeepCharts; build custom Bybit connector |
| Deep Trades / Big Trades (confirmed same feature) | Large-trade markers + zones | Yes (trade+side); iceberg/MBO-aggregation not possible |
| Deep Profile Swing | Swing-anchored volume profile | Yes, from trade tape + swing-detection on price |
| Stop Run | Stop-cascade / liquidity-sweep detector | Yes — pure trade-tape burst heuristic, no L2/L3 needed |
| Deep Wall | Iceberg/absorption-wall signal | Approximate only — no true iceberg detection possible without L3 |
| Imbalance Rejector | Reversal-pattern marker | Yes |
| Deep Delta | Multi-range filtered delta bars | Yes |
| Confluence Identifier | Automated S/R zone scorer | Yes, given multi-period Volume Profile computation |
| Auction Gap Tracker | Zero/thin-print (unfinished) detector | Yes |
| Market Profile (TPO) | Time-based letter profile | Yes (needs only trade timestamps, not volume) |
| Performance Analysis / Strategy Reports | Post-trade analytics (closest match to "Auto-Tracker Journal") | Yes — pure internal fills database, no exchange dependency |
| Templates & Workspaces | Layout/config persistence | Yes — standard app-state save/load feature |
| Market Regime indicator | — | **Not a real DeepCharts feature** — recommend building CandleViewer's own regime classifier |

## Open Questions — Status After This Pass

Resolved in this update: Deep Trades vs. Big Trades distinction (§20, same feature/legacy alias), Deep Profile Swing full parameter set (§19), TPO/Market Profile settings (§14), Stop Run + Deep Wall as the iceberg/stop-sweep detectors (§29), "Market Regime" confirmed non-existent as a named feature (§30), Deep-M IVB/Effort attribution correction (Fabervaale for both), Auto-Tracker Journal resolved as a mislabeling of Performance Analysis/Strategy Reports (§27), keyboard-shortcut category/type taxonomy (§23), VWAP band-calculation-mode confirmation (Standard Deviation / Percentage), Templates vs. Workspaces distinction (§26).

Still open (needs a further targeted research pass):
1. Exact default hotkey-to-action mapping (if any ships pre-configured) — not found; platform may ship with no defaults, only user-assignable slots.
2. Whether DeepCharts VWAP supports true click-to-anchor (arbitrary bar) VWAP vs. only fixed period/session resets — unconfirmed either way.
3. Numeric limits (max chart count per workspace, max indicators per chart, max historical days loadable, max symbols per Big Trades Analysis run, etc.) — no numeric ceilings were surfaced in any fetched article.
4. Compact/group multi-chart view UI and screenshot/export workflow — no dedicated article found.
5. Whether "Order" input type across indicators (Deep Print, Deep Stats, Deep Profile, Speed of Tape, Deep Delta, Deep Trades) is genuinely per-order-arrival counting (needing L2 incremental diffs) vs. a relabeled aggregate — still ambiguous; the recurring "Different Types of Input Data for Indicators" cross-reference article (referenced by nearly every indicator page) was never itself successfully fetched in full — a direct fetch of `deepcharts.com/helpcenter/article/different-types-of-input` should be the top priority for any follow-up pass, since it would resolve this ambiguity platform-wide in one shot.
6. Bar-count/pricing/version differences between "Deepchart Full Advanced" ($79/mo) vs. "Deepchart Pro" ($100/mo) beyond the headline feature list in §2 — not itemized further.

## Sources

- https://www.deepcharts.com/features/deepchart
- https://www.deepcharts.com/pricing/deepchart
- https://www.deepcharts.com/pricing/deepdom
- https://www.deepcharts.com/features/deepdom
- https://www.deepcharts.com/helpcenter
- https://www.deepcharts.com/helpcenter/indicators
- https://www.deepcharts.com/helpcenter/deepindicators
- https://www.deepcharts.com/helpcenter/trading
- https://www.deepcharts.com/helpcenter/article/deep-print-(footprint%C2%AE)
- https://helpdesk.deepcharts.com/portal/en/kb/articles/order-flow-bid-and-ask-footprint
- https://www.deepcharts.com/helpcenter/article/big-trades
- https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-trades
- https://helpdesk.deepcharts.com/portal/en/kb/deepcharts1/trading
- https://www.deepcharts.com/helpcenter/article/deep-profile-values
- https://www.deepcharts.com/helpcenter/article/speed-of-tape
- https://www.deepcharts.com/helpcenter/article/speed-of-tape-(instant)
- https://www.deepcharts.com/helpcenter/article/vwap-envelopes
- https://www.deepcharts.com/helpcenter/deepdom/article/vwap-envelopes
- https://www.deepcharts.com/helpcenter/article/price-chart-settings
- https://www.deepcharts.com/helpcenter/article/price-settings
- https://www.deepcharts.com/helpcenter/deepdom/article/replay-tick-data
- https://helpdesk.deepcharts.com/portal/en/kb/articles/replay-data
- https://www.deepcharts.com/helpcenter/deepdom/article/heatmap
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/trading
- https://www.deepcharts.com/helpcenter/article/how-to-connect-deepcharts-dxfeed-datafeed
- https://helpdesk.deepcharts.com/portal/en/kb/articles/how-to-connect-interactive-brokers-ib-with-deepchart
- https://www.deepcharts.com/helpcenter/article/unfinished-auction
- https://help.volumetricatrading.com/en/support/solutions/articles/204000012056-imbalance-tracker
- https://www.deepcharts.com/helpcenter/article/deep-m-effort-(nq)
- https://www.deepcharts.com/helpcenter/article/deep-m-ivb
- https://www.deepcharts.com/helpcenter/article/deep-v-tracker
- https://www.deepcharts.com/helpcenter/article/deep-pattern-builder
- https://www.deepcharts.com/helpcenter/article/order-cancel-order
- https://www.deepcharts.com/helpcenter/article/trading-from-the-chart
- https://www.deepcharts.com/helpcenter/article/configure-keyboard-shortcuts
- https://orderflowfutures.com/en/deepcharts/deep-replay
- https://orderflowfutures.com/en/deepcharts/deep-m-effort
- https://orderflowfutures.com/en/deepcharts/deep-m-ivb
- https://orderflowfutures.com/en/deepcharts-promo-code
- https://pinescriptforge.com/deepcharts/plans/bundle
- https://pinescriptforge.com/deepcharts/plans/deepdom
- https://proptradingvibes.com/blog/deepcharts-trading-platform
- https://www.deepcharts.com/blog/everything-you-need-to-know-about-footprint-charts-in-trading
- https://www.deepcharts.com/helpcenter/article/deep-trades
- https://www.deepcharts.com/helpcenter/article/performance-analysis
- https://www.deepcharts.com/helpcenter/article/deep-stats
- https://www.deepcharts.com/helpcenter/article/deep-profile
- https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-profile-volume-delta-profile
- https://helpdesk.deepcharts.com/portal/en/kb/articles/volume-by-price
- https://www.deepcharts.com/helpcenter/deepdom/article/volume-profile
- https://www.deepcharts.com/helpcenter/deepindicators
- https://www.deepcharts.com/helpcenter/article/deep-profile-swing
- https://www.deepcharts.com/helpcenter/article/deep-delta
- https://www.deepcharts.com/helpcenter/article/confluence-identifier
- https://www.deepcharts.com/helpcenter/article/imbalance-rejector
- https://www.deepcharts.com/helpcenter/article/auction-gap-tracker
- https://www.deepcharts.com/helpcenter/article/market-profile
- https://help.volumetricatrading.com/en/support/solutions/articles/204000011846-tpo-time-price-opportunity-aka-market-profile-
- https://help.volumetricatrading.com/en/support/solutions/articles/204000013234-stop-run
- https://helpdesk.deepcharts.com/portal/en/kb/articles/stop-run
- https://www.deepcharts.com/helpcenter/article/deep-wall
- https://helpdesk.deepcharts.com/portal/en/kb/articles/deep-wall
- https://www.deepcharts.com/helpcenter/article/templates-and-workspaces
- https://helpdesk.deepcharts.com/portal/en/kb/articles/templates-and-workspaces
- https://www.deepcharts.com/helpcenter/trading
- https://www.deepcharts.com/helpcenter/article/speed-of-tape
- https://helpdesk.deepcharts.com/portal/en/kb/articles/speed-of-tape-instant
- https://help.volumetricatrading.com/en/support/solutions/articles/204000014225-vwap
- https://www.deepcharts.com/helpcenter/indicators
- https://www.deepcharts.com/helpcenter/deepdom/article/general-settings
- https://helpdesk.deepcharts.com/portal/en/kb/deepdom/features

## Notes on Methodology (this pass)

Research conducted 2026-09-14 via a combination of targeted `web_fetch` on specific help-center URLs (guessed and confirmed via search-result URL discovery, since no sitemap.xml or full site crawl was retrievable in this tool environment) and `web_search` across deepcharts.com, helpdesk.deepcharts.com (Freshdesk-hosted), and help.volumetricatrading.com (the underlying Volumetrica engine vendor's own knowledge base, which frequently has parallel/more-detailed articles for the same indicators, e.g. Imbalance Tracker, Stop Run, VWAP). Where helpdesk.deepcharts.com and deepcharts.com/helpcenter host near-duplicate content for the same feature, both URLs are cited; where volumetricatrading.com adds parameters not found on the deepcharts.com side (e.g. Stop Run's Max MS, Max number of orders), those are flagged as sourced from the Volumetrica side specifically.

