# CandleViewer — Views & Screens Catalogue

> Research phase document. Complete catalogue of views/screens CandleViewer must provide to match DeepCharts' data visibility for crypto trading on Bybit, informed by reports 04 (Deepchart), 05 (DeepDOM/Gamma), 08 (crypto metrics), and 12 (scope/users). No sprint planning — this is a specification of *what screens exist and what they show*, not an implementation plan.

## Conventions used below

- **Purpose** — why the view exists / what decision it supports.
- **Data inputs** — Bybit v5 REST endpoints and/or WebSocket topics (category-qualified where relevant: `spot`/`linear`/`inverse`/`option`), plus whether a value is `REST`, `WS`, `LOCAL` (computed/aggregated by CandleViewer's own recorder), or `HYBRID`.
- **Key settings** — user-configurable parameters.
- **Visual encoding** — color/shape/size conventions.
- **Interactions/hotkeys** — mouse/keyboard behavior.
- **DeepCharts/TradingView equivalent** — nearest analog product/feature.
- **ASCII wireframe** — rough box-layout sketch, not pixel-accurate.

Global caveats carried from prior research (apply to every view below unless noted): Bybit has no L3/MBO (order-level) feed, so true iceberg/order-count footprint and true stop-order visibility are heuristic proxies, not ground truth like DeepDOM's MBO tools; all history beyond Bybit's short REST retention windows depends on CandleViewer's own recorder having been running and storing data locally.

---

## 1. Main Chart (Price + Footprint)

**Purpose:** primary price-action view; the vertical spine every other pane docks to. Supports candlestick/bar/line rendering plus footprint (Deep Print) overlay per bar. Also the host surface for the drawing-tools toolbar (matrix §C: trendline/ray/horizontal line/rectangle/Fibonacci/anchored VWAP/text annotation/undo-redo, etc.) and the classic-TA indicator overlay/subpane system (matrix §D: SMA/EMA/MACD/Bollinger/ATR/ADX/Supertrend/ZigZag/Volume histogram, etc.) — every Must/Should row in those two matrix sections attaches here rather than to a separate dedicated view.

**Data inputs:**
- `kline` REST (`/v5/market/kline`) for historical OHLCV bootstrap — `REST`.
- `kline.{interval}.{symbol}` WS topic for live bar updates — `WS`.
- `publicTrade.{symbol}` WS (all trades, side+price+qty) — `WS`, aggregated `LOCAL` into footprint cells (per price-per-bar bid/ask split, delta, volume, imbalance) since Bybit doesn't expose footprint natively.
- `orderbook.50/200.{symbol}` WS — optional, for "Order" input-type approximation only (heuristic, see report 04 §4 caveat).

**Key settings:**
- Chart type: Candlestick, Bar (OHLC), Line, Equi-Volume, Delta-Volume.
- Bar mode: Time (sec/min/hr/day), Volume, Tick/Trades, Range, Renko (brick size fixed/ATR), Point & Figure.
- Footprint cell type: Volume / Bid-Ask Split / Delta / Delta+Total.
- Footprint display mode: Profile (histogram) vs Box (numeric grid).
- Footprint input source: Aggregated Trades / Num Trades (Order-based input flagged as heuristic-only).
- Min/max value noise filter; diagonal-imbalance threshold (e.g. 300%) and coloring.
- Session toggle (24/7 for crypto — no ETH/RTH split needed, but exchange-maintenance-window markers useful).
- Countdown-to-bar-close timer.

**Visual encoding:** green/red (or configurable) bid/ask cells; delta-weighted background shading; diagonal-imbalance cells highlighted (bright green/red) when ask-vs-bid-one-tick-below ratio exceeds threshold; POC cell per bar optionally bolded.

**Interactions/hotkeys:** scroll/pinch zoom, drag-pan, click-drag horizontal ray/level draw, `Shift+click` = trend line, number-row hotkeys to switch bar-mode presets, right-click cell = "focus imbalance," toggle footprint on/off (e.g. `F`), toggle profile/box mode (`Alt+F`).

**DeepCharts/TV equivalent:** Deepchart's core Price Chart + Deep Print (Footprint®); TradingView has no native equivalent (third-party footprint plugins only).

```
+----------------------------------------------------------------+
| Symbol: BTCUSDT-PERP  Interval:5m  [Candlestick|Footprint|...] |
|------------------------------------------------------------------|
|      |Ask 12| 45              ___                                |
|      |Bid  8| 32             /   \      <- footprint grid        |
|  ____|Ask 30| 10   ___      /     \___                           |
| /    |Bid 22|  5  /   \    /                                     |
|/     +------+    /     \__/                                      |
|                                                                    |
| [ VAH ------ POC ------ VAL ]  (profile overlay, optional)        |
+----------------------------------------------------------------+
```

---

## 2. Deep Stats Rows (Per-Bar Statistics)

**Purpose:** at-a-glance numeric summary of order-flow per bar without reading the full footprint grid — quick scan for delta strength/exhaustion across recent bars.

**Data inputs:** derived entirely `LOCAL` from `publicTrade.{symbol}` WS aggregated per bar: Total Volume, Bid Volume, Ask Volume, Delta, Max Delta, Min Delta, Delta %, Cumulative Delta (running), Number of Trades.

**Key settings:** row selection/order (toggle which stats show), row height/compact mode, color-scale thresholds per stat (e.g. delta % > 60 = strong green), rolling-N-bar mini-sparkline toggle per row.

**Visual encoding:** heat-colored numeric cells (green positive delta, red negative), sparkline strip per stat row optional.

**Interactions/hotkeys:** click a stat row header to sort/pin to top; hover cell → tooltip with raw trade count breakdown; drag to reorder rows.

**DeepCharts/TV equivalent:** Deepchart's "Deep Stats" / On-Candle Stats strip under the main chart.

```
+----------------------------------------------------------------+
| Bar:  09:00  09:05  09:10  09:15  09:20  09:25                   |
| Vol:   1,204  980   2,301  1,050   876   1,900                    |
| Delta: +320   -110  +740   +90    -260   +510                     |
| CumΔ:  +320   +210  +950   +1040  +780   +1290                    |
| #Trd:   412   355    690    401    288    602                     |
+----------------------------------------------------------------+
```

---

## 3. Profile Panel (Volume/Delta Profile + TPO)

**Purpose:** vertical histogram of traded volume (or delta) by price over a configurable period, to find POC / Value Area / balance-imbalance zones — core reference for support/resistance and fair-value judgments.

**Data inputs:** `publicTrade.{symbol}` WS aggregated `LOCAL` by price bucket over the chosen period; bootstrapped from recorder's stored tick history (or `kline` REST as a coarse fallback when no tick history exists yet for older ranges).

**Key settings:**
- Period type: Composite (all loaded), Multiples (recurring session/day/hour), Visible (viewport only), Personalized (manual range), Swing-anchored (Deep Swing Profile analog).
- Input data: Volume / Aggregate Trades / Number of Trades (no true "Order" input possible — Bybit lacks L3).
- Value Area %: default 70%.
- Row size (tick granularity of buckets).
- Show VWAP + σ bands overlay on profile.
- Single-print / low-volume-node highlighting toggle.

**Visual encoding:** horizontal bars keyed by price row; POC row bolded/wide; Value Area shaded band; single-prints marked with thin outline; delta-profile mode splits each row into bid(left)/ask(right) mini-bars.

**Interactions/hotkeys:** click a row to draw horizontal ray at that price on main chart; drag profile boundary handles to resize period; toggle Volume/Delta mode (`Alt+P`); right-click → "anchor VWAP here."

**DeepCharts/TV equivalent:** Deep Profile / Deep Profile Values; TradingView's Volume Profile / Fixed Range Volume Profile (session-based only, no delta-profile mode).

```
      Price   Volume Profile
      69,450  |██                      
      69,400  |█████                   
      69,350  |███████████ POC ------> [bold]
      69,300  |█████████  } Value Area (70%)
      69,250  |███                     
      69,200  |█  <-single print
```

---

## 4. Heatmap + DOM Ladder (DeepDOM analog)

**Purpose:** real-time resting liquidity visualization layered behind a clickable price ladder for reading order-book depth/pressure and executing directly from the book.

**Data inputs:** `orderbook.50/200/500.{symbol}` WS (depth per venue tier) — `WS`, historized `LOCAL` for the fading heatmap trail; `tickers.{symbol}` WS for best bid/ask, mark price; own open orders/positions via private WS (`order`, `position` topics) overlaid on the ladder.

**Key settings:** depth tiers shown (top N levels), heatmap color scale (linear vs log size-to-color), trail/decay duration (how long historical liquidity persists before fading), cell size (price increment), Buy/Sell color assignment (verify against DeepCharts' own inconsistent green/violet vs green/red docs — pick and document CandleViewer's own convention explicitly), show/hide own resting orders, one-click trade size preset.

**Visual encoding:** heatmap gradient (dark→bright) behind each price row scaled to resting size; current best bid/ask highlighted; own working orders shown as bracket markers on their row; large "walls" auto-highlighted with a threshold outline; liquidity/reload/absorption flags shown as tick marks beside the row when a heuristic fires (see report 05 §4.9).

**Interactions/hotkeys:** click a row = limit order at that price; `Ctrl+click` = market order sized per preset; drag order marker up/down on ladder = modify price; `Esc` = cancel-all on symbol; scroll = pan ladder; `+`/`-` = zoom price granularity.

**DeepCharts/TV equivalent:** DeepDOM Heatmap + DOM; TradingView's DOM (order-book ladder without heatmap-trail visualization, Pro/paid feature, no proxy for iceberg/stop-run flags).

```
+------ DOM / Heatmap ------+
| 69,500  ask 42 ▓▓▓▓         |
| 69,480  ask 18 ▓▓           |
| 69,460  ask 65 ▓▓▓▓▓▓▓ WALL |
| ---- 69,450 last ----       |
| 69,440  bid 30 ▓▓▓          |
| 69,420  bid 90 ▓▓▓▓▓▓▓▓ WALL|
| 69,400  bid 22 ▓▓  [MY BUY] |
+------------------------------+
```

---

## 5. Big Trades / Bubbles (Time & Sales overlay)

**Purpose:** surface unusually large individual prints ("smart money" flow) directly on the chart and/or a scrolling tape, filtered by notional size.

**Data inputs:** `publicTrade.{symbol}` WS, filtered `LOCAL` by a notional/qty threshold (absolute or relative, e.g. percentile of trailing N trades).

**Key settings:** size threshold (absolute $ or dynamic percentile), bubble scaling (linear/log by notional), color by side, tape row count, sound/flash alert on trades above a second, higher "whale" threshold, filter by symbol/category.

**Visual encoding:** bubbles overlaid on price chart at execution price/time, radius ∝ notional; scrolling tape list with side-colored rows, timestamp, price, size, notional.

**Interactions/hotkeys:** hover bubble → trade detail tooltip; click tape row → jump chart to that timestamp; `B` toggles bubble overlay; adjustable threshold slider live-updates without reload.

**DeepCharts/TV equivalent:** Big Trades (Deepchart) / Deep Trades (Volume Bubbles, DeepDOM); TradingView has no native large-print bubble overlay (third-party only).

```
Price
69,480 |        o (small)
69,460 |    O         O  <- bubble sized by notional
69,440 |  ⬤ WHALE 2.4M
       +----------------------> time
Tape:  12:03:41  69,441  1.2 BTC  BUY
       12:03:40  69,438  0.3 BTC  SELL
```

---

## 6. CVD / Delta Panes

**Purpose:** sub-chart tracking cumulative volume delta and per-bar delta over time to gauge sustained aggressor pressure vs. exhaustion/divergence against price.

**Data inputs:** `publicTrade.{symbol}` WS aggregated `LOCAL`: per-bar delta = Σ(buy qty) − Σ(sell qty); CVD = running cumulative sum, resettable per session/anchor.

**Key settings:** reset anchor (session/day/never/manual), display as line vs histogram, show per-bar delta as colored histogram beneath CVD line, divergence auto-marking (price higher-high while CVD lower-high, or vice versa), smoothing (SMA/EMA overlay on CVD).

**Visual encoding:** CVD line (single color, slope conveys pressure), per-bar delta histogram green/red, divergence markers (triangle/flag) where detected.

**Interactions/hotkeys:** click-drag to manually re-anchor CVD reset point; `D` toggles delta histogram; sync crosshair with main chart.

**DeepCharts/TV equivalent:** Deepchart's CVD indicator (bundled in Orderflow tier); TradingView has community CVD scripts, not a native pane.

```
+---------------- CVD Pane ----------------+
|        ___/‾‾\___                        |
|      /            \___/‾‾  <- CVD line   |
|  ▂▄▆█▄▂ ▁▂▃ ▆█▇▃ ▁▂  <- per-bar delta hist|
+-------------------------------------------+
```

---

## 7. Open Interest / Funding / Liquidation Panes

**Purpose:** derivatives-specific context absent from spot charting — track positioning buildup/unwind (OI), cost-of-carry pressure (funding), and forced-flow shocks (liquidations) alongside price.

**Data inputs:**
- OI: `tickers.{symbol}` WS (`openInterest` field, linear/inverse only) for live, `/v5/market/open-interest` REST for backfill/cross-check — `HYBRID`.
- Funding: `tickers.{symbol}` WS (`fundingRate`, `nextFundingTime`) live, `/v5/market/funding/history` REST for historical bars — `HYBRID`.
- Liquidations: `allLiquidation.{symbol}` WS, aggregated `LOCAL` into time-bucketed bars/heatmap (long-liq vs short-liq notional, per report 08 §9.2); no REST historical liquidation endpoint exists, so history only as deep as the recorder has been running.
- Mark/Index price & basis: `tickers.{symbol}` WS (`markPrice`, `indexPrice`) for basis/premium sub-pane.

**Key settings:** OI display as absolute or OI-change-per-bar; overlay OI-vs-price quadrant coloring (price↑OI↑ = new longs, price↑OI↓ = short covering, etc.); funding pane as stepped line vs bar-per-interval, annualized-rate toggle; liquidation pane as bars (split long/short) or heatmap grid; liquidation notional threshold to filter noise.

**Visual encoding:** OI line/area, quadrant background tint per report-08 convention; funding rate stepped line with zero-line; liquidation histogram red (short liq) / green (long liq) spikes, or heatmap cells colored by cumulative notional with decay.

**Interactions/hotkeys:** click OI quadrant legend to filter regime; hover funding bar → next-funding countdown tooltip; click liquidation spike → jump tape to that timestamp.

**DeepCharts/TV equivalent:** no direct DeepCharts equivalent (futures-equities platform, no crypto derivatives concepts); closest crypto-market analogs are Coinglass/Hyblock OI-heatmap and liquidation-heatmap dashboards — CandleViewer builds this natively rather than depending on a third party.

```
+---- OI ----+  +---- Funding ----+  +---- Liquidations ----+
| ▁▂▃▅▇█ OI  |  |  0.01%▔▔▁▁▔▔    |  | ▁█▁▁▂▁▇(short) ▁▁▁▂  |
| green=up-  |  | next: 02:14:33  |  | ▁▁▁▂▁▁▁▁(long)  ▁▁▁▁  |
| tint=      |  |                  |                        |
+------------+  +------------------+  +------------------------+
```

---

## 8. Speed of Tape

**Purpose:** instantaneous read of trade-print velocity/acceleration — used to qualify breakouts (fast tape = conviction) vs. chop.

**Data inputs:** `publicTrade.{symbol}` WS, `LOCAL` rolling-window trade-count and notional-per-second computation; optional "instant" variant using a much shorter window (per report 04 §"Speed of Tape (Instant)").

**Key settings:** rolling window length (e.g. 1s/5s/30s), display as gauge vs strip-chart, alert threshold (prints/sec above X), split by side (buy speed vs sell speed).

**Visual encoding:** horizontal gauge/speedometer or scrolling mini strip-chart; color ramps from cool (slow) to hot (fast); optional flash/alert when threshold crossed.

**Interactions/hotkeys:** click gauge to reset baseline; hotkey to toggle instant vs smoothed mode.

**DeepCharts/TV equivalent:** Speed of Tape / Speed of Tape (Instant) (Deepchart); Book Speed (DeepDOM, book-side variant, see view 11).

```
+-- Speed of Tape --+
|   🔥🔥🔥░░░  62/s  |
|   buy:41  sell:21 |
+--------------------+
```

---

## 9. Imbalance Tracker

**Purpose:** flags stacked/diagonal bid-ask imbalances across consecutive price levels within the footprint — a leading signal for absorption or continuation.

**Data inputs:** footprint cell data (`publicTrade.{symbol}` aggregated `LOCAL` per price-per-bar), plus a stacking rule (N consecutive imbalanced cells at threshold ratio).

**Key settings:** imbalance ratio threshold (e.g. 300%), stack depth (min consecutive levels, e.g. 3), diagonal vs vertical (same-price) imbalance mode, per-symbol/per-timeframe independent thresholds, alert on new stack formed.

**Visual encoding:** highlighted footprint cells (bright outline/fill) forming a visible "staircase"; separate summary strip listing active imbalance stacks with direction arrows.

**Interactions/hotkeys:** click a stack marker → scroll main chart to it; toggle imbalance overlay (`I`); adjustable threshold live slider.

**DeepCharts/TV equivalent:** Imbalance Tracker (Deepchart, bundled in Orderflow tier).

```
Footprint column (diagonal imbalance highlighted):
69,420 | 12 x 340  <-- stacked imbalance (bright)
69,410 |  8 x 290  <-- stacked imbalance (bright)
69,400 | 40 x  55
```

---

## 10. Market Regime Panel

**Purpose:** classify current session as trending/ranging/volatile/calm to calibrate strategy choice and risk sizing at a glance.

**Data inputs:** `LOCAL` composite score from L2 book-thickness clustering (`orderbook` WS), realized volatility (ATR/close-to-close from `kline`), and trade-tape speed (`publicTrade` WS) — heuristic proxy, no MBO-based "true" regime signal available (report 05 §4.9).

**Key settings:** lookback window for regime scoring, sensitivity/thresholds for regime-boundary classification, which sub-signals feed the composite (volatility only vs volatility+book+speed), display as label vs continuous gauge/dial.

**Visual encoding:** labeled badge (e.g. "TRENDING ▲", "RANGE ▬", "VOLATILE ⚡") with color coding; optional background tint applied to main chart matching current regime; small history strip showing regime transitions over the session.

**Interactions/hotkeys:** click badge → expand into contributing-signal breakdown; hover history strip → regime-change timestamp tooltip.

**DeepCharts/TV equivalent:** Market Regime (DeepDOM); no TradingView native equivalent.

```
+-- Regime --+
|  TRENDING ▲ |
|  [vol:hi][book:thin][speed:fast]
+-------------+
```

---

## 11. Multi-Chart Layouts

**Purpose:** simultaneous multi-timeframe or multi-symbol context (higher-TF structure alongside execution TF; or watchlist symbols side by side), matching a manager's session-prep workflow (report 12 §3.1).

**Data inputs:** same per-pane feeds as View 1, one subscription set per pane; shared crosshair/level sync layer `LOCAL`.

**Key settings:** grid layout presets (1x1, 2x1, 2x2, 1+3, custom), per-pane symbol/timeframe binding, crosshair-sync toggle, level-sync toggle (drawn levels propagate across panes on same symbol), independent vs linked scaling.

**Visual encoding:** thin divider gutters; active pane highlighted border; synced crosshair drawn as dashed line across all linked panes simultaneously.

**Interactions/hotkeys:** `Ctrl+1..9` = layout presets; click pane to make active (keyboard shortcuts route to active pane); drag pane divider to resize; drag a symbol from watchlist onto a pane to rebind it.

**DeepCharts/TV equivalent:** Deepchart's compact/group multi-chart mode (settings not fully retrieved per report 04 open Q7); TradingView's multi-chart layouts (well established, direct precedent to copy UX from).

```
+------------------+------------------+
| BTCUSDT 4H (ctx) | BTCUSDT 5m (exec)|
|   trend chart     |   footprint      |
+------------------+------------------+
| ETHUSDT 1H        | SOLUSDT 1H       |
+------------------+------------------+
```

---

## 12. Replay Mode

**Purpose:** rehearse historical sessions tick-by-tick (or bar-by-bar) to test rule-based exits/strategies and review journaled trades without live risk.

**Data inputs:** CandleViewer's own recorded tick database (trades + order-book deltas + liquidations) — `LOCAL` only; Bybit provides no historical MBO/tick-replay API, so replay fidelity is capped by however long the recorder has been running for that symbol (report 08 §19, report 04 §21).

**Key settings:** symbol + date/time range picker (calendar), playback speed (0.5x–100x presets, scrub bar), simulated-order mode toggle (paper fills during replay), which panes stay "live" during replay (footprint/DOM/big-trades all update in replay-time), loop/bookmark markers for specific moments (e.g., "replay from journal entry #42").

**Visual encoding:** identical to live views but with a distinct "REPLAY" banner/border color to prevent confusion with live trading; scrub bar with playhead beneath all synced panes.

**Interactions/hotkeys:** space = play/pause, `←/→` = step bar-by-bar, `Shift+←/→` = step tick-by-tick, `R` = jump to real-time/exit replay, click scrub bar = seek.

**DeepCharts/TV equivalent:** Deep Replay / MBO Replay (DeepDOM, "2 weeks and counting" per report 05 — i.e. still in development at DeepCharts too); TradingView's bar replay (bar-level only, no tick/DOM replay).

```
+---------------- REPLAY MODE ----------------+
| [main chart + footprint, replaying]          |
+-----------------------------------------------+
| |◀◀  ▶  ▶▶|  speed: 4x   09:31:04 -> 09:41:04 |
| [============●===========================]    |
+-----------------------------------------------+
```

---

## 13. Trading Terminal / Order Ticket

**Purpose:** primary execution surface — fast order entry with full order-type coverage, bracket attach, and DOM/chart click-to-trade, serving both discretionary managers and quick owner intervention.

**Data inputs:** private WS (`order`, `execution`, `position`, `wallet` topics) for live order/position/fill state; REST `/v5/order/create`, `/order/amend`, `/order/cancel`, `/position/trading-stop` (for attached TP/SL) for placement; `/v5/market/instruments-info` REST for tick size/lot size/leverage tiers.

**Key settings:** default order type (Market/Limit/Conditional), quantity presets (fixed size, % of equity, risk-% based sizing calculator per report 12 §3.1 item 6), default TP/SL attach mode (ticks, %, R-multiple), one-click trading toggle (with confirm-off warning), hotkey order-size ladder, category/leverage selector.

**Visual encoding:** buy/sell buttons color-coded; live bid/ask quote strip; order-preview panel showing estimated liquidation price, margin required, fees; working-order rows inline with countdown/status badges.

**Interactions/hotkeys:** `B`/`S` = buy/sell at market with default size; number keys = size presets; `Ctrl+Enter` = submit ticket; DOM ladder click = price-specific limit (view 4 crossover); `Esc` = cancel ticket; global "flatten all" hotkey/button with confirm.

**DeepCharts/TV equivalent:** Trading From The Chart / DeepDOM Trading Panel; TradingView's Order Panel/Ticket (similar concept, equities/futures-broker-oriented).

```
+------------- Order Ticket -------------+
| Symbol: BTCUSDT-PERP   Lev: 10x         |
| [ BUY ]        [ SELL ]                |
| Qty: [ 0.10 BTC ] [25%][50%][Max]       |
| Type: Market ▾   TP: +50 ticks          |
| Est. Liq: 61,204   Margin: 690 USDT     |
| [ SUBMIT ]        [ FLATTEN ALL ]       |
+------------------------------------------+
```

---

## 14. Positions & Orders

**Purpose:** consolidated live view of all open positions and working orders across symbols/sub-accounts, for monitoring and one-click management.

**Data inputs:** private WS `position`, `order` topics per sub-account; REST `/v5/position/list`, `/v5/order/realtime` for reconciliation/backfill on reconnect.

**Key settings:** group-by (symbol/sub-account/manager), show/hide closed-today, column set (unrealized PnL, entry, mark, liq price, leverage, margin mode), sort order, sub-account filter (owner view across all managers vs manager's own scoped view per report 12 §3.2 personas).

**Visual encoding:** PnL cells green/red with magnitude shading; liq-price proximity warning (amber/red row highlight as price approaches liquidation); order rows show fill-progress bar for partials.

**Interactions/hotkeys:** click position row → focus that symbol on main chart; inline close/reduce buttons; multi-select + "close selected"; right-click order → amend/cancel context menu.

**DeepCharts/TV equivalent:** no direct DeepCharts equivalent (single-account futures platform); TradingView's Positions/Orders panel in its broker-integrated trading panel is the closer analog.

```
+---------------------------- Positions ----------------------------+
| Sub-acct | Symbol    | Side | Size | Entry  | Mark   | PnL   | Liq |
| mgr_alex | BTCUSDT   | Long | 0.5  | 69,200 | 69,450 | +125  | 61k |
| mgr_bea  | ETHUSDT   | Short| 3.0  | 3,410  | 3,395  | +45   | 3.9k|
+-----------------------------------------------------------------------+
```

---

## 15. Risk Dashboard

**Purpose:** owner-level aggregate risk oversight across all managers/sub-accounts — daily loss limits, drawdown, exposure concentration — with kill-switch authority (report 12 §3.2 Owner persona).

**Data inputs:** aggregated `LOCAL` from private WS across all sub-account connections (positions, PnL, wallet balances); `/v5/account/wallet-balance` REST for periodic reconciliation.

**Key settings:** per-manager max-daily-loss / max-drawdown thresholds with auto-flatten-and-lockout action, aggregate exposure caps (per symbol, per manager, portfolio-wide), alert routing (push/email/in-app) on breach, lockout override control (owner-only).

**Visual encoding:** traffic-light per-manager status (green/amber/red vs limits); aggregate exposure heatmap by symbol/manager; daily PnL bar chart across managers; drawdown line vs limit threshold line.

**Interactions/hotkeys:** click manager row → drill into their Positions & Orders view (owner-as-reviewer, read-only per persona table); big "FREEZE" button per manager (immediately revokes trading, per report 12 §1 sub-account isolation model); acknowledge/mute alert.

**DeepCharts/TV equivalent:** no DeepCharts/TradingView equivalent (single-user retail platforms) — this view is CandleViewer-original, closest conceptual analog is a prop-firm risk-management dashboard.

```
+---------------------- Risk Dashboard ----------------------+
| Manager  | Daily PnL | DD vs Limit | Exposure | Status      |
| alex     | +210      | 40%         | 2.1 BTC  | ● green     |
| bea      | -480      | 92%         | 0.8 BTC  | ● red [FREEZE]|
+----------------------------------------------------------------+
```

---

## 16. Rule Builder (Custom Stops/Exits)

**Purpose:** construct and backtest custom rule-based stop/exit logic without code — the CandleViewer analog to DeepCharts' Deep Pattern Builder, extended to actually place/manage live stop-management orders, not just visual pattern flags.

**Data inputs:** consumes any derived series available elsewhere in the app (OHLCV, delta, CVD, OI, funding, regime score, indicator outputs) as rule inputs `LOCAL`; executes via same order-management REST/WS path as View 13 (`/v5/order/amend`, `/position/trading-stop`) once a rule fires live.

**Key settings:** condition editor (up to N inputs, AND/OR/NOT logic, comparison/math operators — mirroring Deep Pattern Builder's 4-input model per report 04 §18); action type (move SL to breakeven, trail by N ticks, partial close %, time-based exit, full flatten); trigger mode (live-armed vs simulate-only); auto-backtest-on-save against recorder's stored history.

**Visual encoding:** node/block rule-graph or structured form (open question in report 04 — exact DeepCharts UI not confirmed, so CandleViewer should default to a clear structured-form editor rather than a freeform visual graph until validated); backtest result summary (equity curve, hit rate, avg R) shown inline after each edit.

**Interactions/hotkeys:** drag to reorder condition blocks; toggle rule active/inactive; "Test against last 30 days" button; clone existing rule as template; per-rule audit log of every time it fired.

**DeepCharts/TV equivalent:** Deep Pattern Builder (Deepchart); TradingView's Strategy Tester + Pine condition scripting (code-based, not visual/no-code).

```
+------------------- Rule Builder -------------------+
| IF   [Delta] [<] [-500]                              |
| AND  [Price] [below] [VWAP]                          |
| THEN [Move SL to] [Breakeven]                         |
|                                                        |
| [ Backtest last 30d ]  Result: 62% hit, +0.8R avg     |
| [ Arm Live ]   [ Simulate Only ]                      |
+---------------------------------------------------------+
```

---

## 17. Journal / Auto-Tracker

**Purpose:** automatic trade logging with post-session performance review — every fill captured with context (chart snapshot/replay link) and manual annotation, per report 12 §3.1 item 8.

**Data inputs:** private WS `execution` topic auto-logs every fill `LOCAL`; linked to Replay Mode (View 12) via timestamp for "view this trade in context"; manual tags/notes stored `LOCAL`.

**Key settings:** auto-tag rules (by symbol/strategy/rule-builder-source), review-period filters (day/week/custom), stat set shown (win rate, expectancy, R-multiple distribution, avg hold time), export (CSV/PDF).

**Visual encoding:** trade list with side-colored rows; R-multiple distribution histogram; equity curve; calendar heatmap of daily PnL.

**Interactions/hotkeys:** click trade row → opens Replay Mode seeked to that trade's entry; inline tag/note editor; filter chips for strategy/rule/manager.

**DeepCharts/TV equivalent:** DeepDOM's "Backtester and Journal" bundle item; report 04 flags uncertainty whether a DeepCharts feature is literally branded "Auto-Tracker" — treat CandleViewer's Journal as this project's own spec regardless of exact DeepCharts naming.

```
+----------------- Journal -----------------+
| Date  | Sym  | Side | R    | Tags          |
| 09/13 | BTC  | Long | +1.4 | breakout,rule1|
| 09/13 | ETH  | Short| -0.6 | fade           |
+-----------------------------------------------+
| Win rate: 58%   Avg R: +0.32   [Equity curve] |
+-----------------------------------------------+
```

---

## 18. Watchlist / Symbol Search

**Purpose:** entry point for symbol selection and pre-session screening across the tradeable Bybit universe.

**Data inputs:** `/v5/market/instruments-info` REST (symbol list, tick/lot size, category); `tickers.{symbol}` WS batch-subscribed for live price/%change/volume/funding/OI-change columns for scanner sort.

**Key settings:** column set (price, %chg, rel-vol, funding rate, OI Δ, distance-to-key-level), sort/filter rules, saved watchlist groups, category filter (spot/linear/inverse), search-by-name/fuzzy match.

**Visual encoding:** sortable table, sparkline mini-chart per row, color-coded %change and funding rate.

**Interactions/hotkeys:** type-to-search; `Enter` loads symbol into active chart pane; drag row onto a multi-chart pane (View 11) to bind it; star/pin favorites.

**DeepCharts/TV equivalent:** TradingView's Watchlist (direct precedent); DeepCharts has no native crypto watchlist (futures/equities focus).

```
+---------------- Watchlist ----------------+
| Symbol   | Price   | %chg | RelVol | Fund |
| BTCUSDT  | 69,450  | +1.2%| 1.8x   | 0.01%|
| ETHUSDT  | 3,410   | -0.4%| 0.9x   | -0.02%|
+------------------------------------------------+
```

---

## 19. Alerts

**Purpose:** notify on price/indicator/level/risk conditions without requiring the screen to be watched continuously.

**Data inputs:** evaluated `LOCAL` against any live feed already consumed elsewhere (kline, tickers, footprint-derived stats, risk-dashboard breaches); delivery via in-app toast + optional push/email (external integration, out of Bybit's scope).

**Key settings:** condition builder (reuses Rule Builder's condition editor, View 16, but without an execution action — alert-only), delivery channel selection, snooze/mute, one-shot vs recurring, per-symbol vs global.

**Visual encoding:** alert list with status (armed/fired/snoozed), fired alerts shown as markers on the relevant chart at trigger time/price.

**Interactions/hotkeys:** right-click chart level → "alert me here"; click armed alert → edit/delete; fired-alert toast with jump-to-chart action.

**DeepCharts/TV equivalent:** TradingView's Alerts (direct precedent, well-established UX to copy); DeepCharts has no strongly documented alert-center equivalent in retrieved research.

```
+------------------ Alerts ------------------+
| [armed] BTCUSDT > 70,000            [x]     |
| [fired] ETHUSDT Delta < -1000 @12:04 [view] |
| [ + New Alert ]                              |
+------------------------------------------------+
```

---

## 20. Account / Environment Switcher (Demo/Live)

**Purpose:** unambiguous, hard-to-mistake switch between Bybit demo-trading and live-trading environments per symbol/sub-account, given the brief's requirement to support both modes safely.

**Data inputs:** REST/WS host selection per report 08 §1.1 (`api-demo.bybit.com` for demo order/position/wallet calls, shared mainnet market-data host); per-environment API key storage/management.

**Key settings:** active environment per session (Demo/Live), per-sub-account environment binding, confirmation-required toggle when switching into Live, visually distinct theme accent per environment (e.g. live = red-accented chrome) to prevent accidental live orders.

**Visual encoding:** persistent top-bar badge (e.g. "LIVE" red pill vs "DEMO" blue pill); environment-colored border around the entire trading terminal (View 13) as a strong visual guard.

**Interactions/hotkeys:** explicit confirm dialog on Demo→Live switch (typed confirmation or held-button); global hotkey disabled for switching (must be deliberate click, no accidental keyboard toggle).

**DeepCharts/TV equivalent:** no direct analog (DeepCharts/TradingView don't have a demo-vs-live broker-mode concept baked into the charting UI itself); closest precedent is standard broker-terminal paper/live toggles (e.g. NinjaTrader Sim vs Live).

```
+--------------------------------------------------+
|  [ DEMO ] BTCUSDT-PERP        <-- badge, blue     |
|  (switch to LIVE requires typed confirmation)     |
+--------------------------------------------------+
```

---

## 21. Admin / Users

**Purpose:** owner-only screen to manage manager accounts, permissions, API-key bindings, and audit trail — reflecting the sub-account-per-manager model and its numeric cap constraints (report 12 §1.1).

**Data inputs:** CandleViewer's own user/auth store (`LOCAL`, not a Bybit concept) mapped to Bybit sub-account IDs; Bybit sub-account creation/API-key endpoints (`create_sub_uid`, API key management) invoked by the owner's Main-account credentials.

**Key settings:** add/remove manager (bounded by Bybit's 5/20 sub-account cap per report 12 §1.1 — CandleViewer should surface this cap explicitly in the UI so the owner doesn't attempt to onboard more managers than Bybit allows), per-manager permission scope (read-only viewer vs full trading), risk-limit assignment (feeds Risk Dashboard, View 15), API key rotation/IP-whitelist management, audit log viewer (every order/config change, who/when).

**Visual encoding:** user table with role badges, sub-account cap usage meter (e.g. "4/5 sub-accounts used"), audit log as a reverse-chronological event stream.

**Interactions/hotkeys:** invite/deactivate manager; per-manager "view as" (owner impersonates read-only to sanity-check their view); export audit log.

**DeepCharts/TV equivalent:** no analog (both are single-user retail platforms); closest conceptual precedent is a prop-firm/brokerage back-office user-admin panel.

```
+-------------------- Admin / Users --------------------+
| Manager | Sub-Acct | Role       | Risk Limit | Status  |
| alex    | sub_001  | Trader     | -500/day   | active  |
| bea     | sub_002  | Trader     | -300/day   | active  |
| Sub-accounts used: 2/5 (regular tier)                   |
| [ Audit Log ]  [ + Invite Manager ]                     |
+------------------------------------------------------------+
```

---

## Cross-cutting notes

- **Global hotkey layer:** a single configurable keymap (per report 04 §"Configure Keyboard Shortcuts") should span all views consistently rather than each view inventing its own scheme — flag as a design requirement, not yet detailed here.
- **Demo/Live isolation (View 20) must gate every trading-capable view** (13 Trading Terminal, 14 Positions & Orders, 4 DOM click-to-trade, 16 Rule Builder's "Arm Live" action) — none of those views should be able to place a live order while the environment badge reads Demo, and vice versa.
- **Heuristic-vs-true-MBO labeling:** any view surfacing Iceberg/Stop-Run/true-order-count footprint (Views 1, 4, 9, 10) must visibly flag itself as a heuristic proxy in its own UI (e.g. an "(estimated)" badge), not just in this document, since Bybit has no L3 feed to ground-truth these signals (report 05 §4.9, report 04 §4).
- **Recorder dependency:** Views 3 (Profile), 12 (Replay), 17 (Journal) and any "Composite"/long-lookback mode of Views 6–10 are only as deep as CandleViewer's own tick recorder has been running (report 08 §19) — each such view's empty/partial-history state should be an explicit, designed UI state, not an afterthought.

## Open questions

1. Exact DeepCharts UI paradigm for its rule-builder (node-graph vs structured form) remains unconfirmed (report 04 open Q — carried into View 16); CandleViewer's structured-form default should be validated against a live DeepCharts trial if access is ever obtained.
2. DeepCharts' own default Buy/Sell heatmap color convention is internally inconsistent between its own help articles (report 05 open Q3); View 4's color convention is therefore CandleViewer's own choice, not a confirmed DeepCharts match, and should be explicitly decided (not just inherited) before implementation.
3. No primary-source confirmation was found for a literally "Auto-Tracker"-branded DeepCharts journal feature (report 04 open Q4); View 17 is specified from the project brief's own requirement rather than a verified DeepCharts feature-parity target.
4. Legal/regulatory questions around multi-manager sub-account arrangements (report 12 §7) affect Views 15/21's assumed multi-manager scale but are out of scope for this document — revisit onboarding-capacity assumptions in Views 15/21 once counsel weighs in.
5. This document is a screen/view catalogue only; visual design system, exact color tokens, and responsive/window-management behavior (single-window multi-pane vs multiple OS windows) are not yet specified and should be a follow-up research/design pass.
