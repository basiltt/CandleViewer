# TradingView trading, alerts, Pine & platform features

Research report — CandleViewer project. Compiled 2026-09-13.

## Table of contents

1. Trading Panel & broker integration
2. Bybit integration specifics
3. Order ticket features
4. Paper trading
5. DOM panel
6. Account Manager panel
7. Alerts
8. Pine Script
9. Strategy Tester
10. Screener
11. Watchlist
12. News, calendar, ideas, social
13. Desktop app, mobile, keyboard shortcuts, multi-monitor
14. Chart sharing & data export
15. Broker REST API (build-your-own-broker)
16. Charting Library / Advanced Charts / Lightweight Charts licensing
17. Sources
18. Open questions

---

## 1. Trading Panel & broker integration

TradingView's **Trading Panel** is the unified interface (right-hand side of "Supercharts", the main chart view) that lets a user connect a brokerage account and trade directly from the chart. Key characteristics, per TradingView's own Broker Integration Manual and Help Center:

- The Trading Panel appears once a user clicks "Trade" and selects/connects a supported broker, or activates Paper Trading.
- TradingView itself does **not** clear or custody trades — all order execution happens on the broker's own systems. The architecture is a client-server model: **the user's browser talks directly to the broker's server**; TradingView's own server is not in the execution path except for the `/permissions` endpoint, which is used to grant a user data-access permissions. (Source: [Integration overview — Broker Integration Manual](https://www.tradingview.com/broker-api-docs/integration-overview))
- Brokers integrate via a **REST API contract** that TradingView defines and documents publicly (see §15). There are informally described "levels" of integration used by third parties (e.g., TraderEvolution) ranging from (1) being listed as a broker in TradingView's directory, up to (3) offering the full TradingView UI as a white-labeled trading terminal for the broker's own clients. TradingView's own docs don't officially number these tiers this way, but the broker directory + Trading Platform + full "TradingView-branded terminal" distinction is real and documented across broker partner literature (source: [TraderEvolution TradingView Broker Integration Guide](https://traderevolution.com/learn/tradingview-broker-integration-guide)).
- TradingView maintains a public, filterable directory of over 100 partner brokers (filterable by asset class: forex, CFDs, equities, futures, crypto — per partner marketing copy referencing the directory; TradingView's own "Brokers" section is at tradingview.com/brokers).
- What the order ticket looks like and which order types/features are available **depends entirely on the connected broker** — TradingView's own help article on order tickets explicitly states: "The order types you can place via the order ticket depend on the broker." (Source: [What is an order ticket — TradingView](https://www.tradingview.com/support/solutions/43000784804-what-is-an-order-ticket))

## 2. Bybit integration specifics

Bybit is a first-party-supported broker in TradingView's Trading Panel (findable via "See all brokers → Bybit" in Supercharts). Per Bybit's own Help Center article (last updated 2026-06-08):

- **Supported product types via TradingView↔Bybit integration:** Spot, Inverse Perpetuals, USDT Perpetuals, and USDC Perpetuals. (Bybit's other product lines, e.g. options, are not mentioned as supported through this integration.)
- **Connection flow:** User logs into TradingView → Trading Panel → Broker list → Bybit → "Connect" → redirected to Bybit's own login page → enters Bybit credentials → "Log in and Authorize" → account (Main Account or Sub-account) is now linked.
- **Session restriction:** The connected session persists for a maximum of **24 hours** before requiring re-authentication, a restriction TradingView imposes for security purposes across all its broker integrations (not Bybit-specific).
- **Available actions once connected:** select a trading pair, place an order, view positions/orders/order history, manage (modify/cancel) orders, and close positions — all directly from the TradingView chart UI.
- (Source: [How to Get Started With Trading on Bybit From TradingView — Bybit Help Center](https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Trading-on-Bybit-From-TradingView); marketing overview at [Bybit × TradingView](https://www.bybit.com/en/derivative-activity/tradingview))
- Because the integration is client-server (browser ↔ Bybit server) rather than TradingView-server-mediated, this implies Bybit itself implemented and hosts the TradingView Broker API endpoints (order placement, positions, account manager, streaming quotes) per TradingView's Broker Integration Manual spec — the same spec any exchange (including future CandleViewer-style integrations) would have to implement to appear as a "broker" inside TradingView's own UI. CandleViewer does not need to implement this same protocol since it is not embedding inside TradingView's own site — but the **shape** of Bybit's API surface that TradingView requires (`/orders`, `/positions`, `/accountManager`, `/quotes`, `/state`, `/mapping`) is a useful reference model for how a professional-grade internal trading panel should be structured. See §15 for the endpoint list.
- **Note:** TradingView does not publish a granular public breakdown of every specific Bybit order type surfaced through the integration (e.g., whether Bybit's native conditional order types, TP/SL-on-fill, or trailing stop are all exposed 1:1) — this level of detail is still not confirmed for the first-party TradingView Trading Panel schema specifically (see Section 5's Bybit-specific sub-section for the fuller re-research pass on this point).

### 2.1 Bybit's own order-type surface (independent of what the TradingView Trading Panel exposes) — **[verified]**
This is Bybit's own native order-type catalog (from Bybit's own Help Center, not TradingView's), relevant to CandleViewer since the recommendation is to build directly against Bybit's API rather than TradingView's broker schema:
- **Basic order types (all markets)**: Market Order, Limit Order, Conditional Order.
- **Advanced order types**: Take Profit and Stop Loss (TP/SL) Orders, Iceberg Order, Post-Only, Time-in-Force selections (GTC/IOC/FOK), Trailing Stop Order, TWAP Order Strategy, Scaled Order, Chase Limit Order, Retail Price Improvement (RPI) Order.
- **Spot-market-only**: One-Cancels-the-Other (OCO) Orders.
- **Derivatives-market-only**: Reduce-Only Order, Close On Trigger, Percentage of Volume (POV) Order.
- Source: [Types of Orders Available on Bybit — Bybit Help Center](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit).

### 2.2 Bybit TP/SL mechanics — **[verified]**
Per Bybit's own Help Center ([How to Set Up and Modify Your TP/SL (Perpetual and Futures Contracts)](https://www.bybit.com/en/help-center/article/How-to-Set-Up-and-Modify-TP-SL-Perpetual-Futures-Contracts), [Introduction to Take Profit and Stop Loss (Perpetual and Futures Contracts)](https://www.bybit.com/en/help-center/article/Introduction-to-Take-Profit-Stop-Loss-Perpetual-Futures-Contracts), [Take Profit and Stop Loss (Spot Trading)](https://www.bybit.com/en/help-center/article/Introduction-to-Take-Profit-and-Stop-Loss-Spot-Trading)):
- Two TP/SL scope modes for derivatives: **Entire Position** (single TP/SL order covering the whole position; always closes via a market order when triggered) vs. **Current Order / Partial Position** (TP/SL scoped to a specific order's quantity; supports multiple concurrent TP/SL orders per position, each closeable via market or limit order, with the paired SL/TP order auto-cancelled once one leg fires — i.e., native OCO-like behavior between a position's TP and SL legs).
- Upgraded TP/SL (current) vs. legacy TP/SL: trigger-by options expanded from {Price, ROI%} to {ROI%, Change%, P&L}; reference price options are Last Traded Price, Mark Price, or Index Price (both versions); upgraded version supports TP/SL via Conditional Limit order for partial positions, legacy only supported Conditional Market order.
- Spot trading TP/SL is a distinct, separate mechanism from derivatives TP/SL (per "Take Profit and Stop Loss (Spot Trading)"): a dedicated **OCO order type** exists for Spot (one-cancels-the-other between the TP and SL legs), and margin/assets are occupied differently depending on order type (TP/SL orders occupy assets immediately on placement; OCO occupies only one side's margin; Conditional orders don't occupy assets until the trigger price is reached).

### 2.3 Bybit position mode — **[verified]**
Per Bybit's "Quick Trading Features" Help Center article: Bybit derivatives support both **One-Way mode** and **Hedge mode** position modes (user-configurable in account/position settings). In One-Way mode, opening a position in the opposite direction via quick-entry reduces/closes the existing position; in Hedge mode, opening the opposite direction instead opens a **separate, independent position** rather than netting against the existing one — i.e., simultaneous long and short positions on the same symbol are possible in Hedge mode. This maps directly onto Bybit's REST/WS API's `positionIdx` parameter (0 = one-way, 1 = hedge-buy-side, 2 = hedge-sell-side) and should inform CandleViewer's own position-mode UI/data model for its Bybit integration.

## 3. Order ticket features

Per TradingView's Help Center "Trading basics" folder and the "What is an order ticket" article ([source](https://www.tradingview.com/support/solutions/43000784804-what-is-an-order-ticket), [folder index](https://www.tradingview.com/support/folders/43000597927-trading-basics)):

### Order types (paper trading baseline; live broker types vary)
| Order type | Description |
|---|---|
| **Market** | Executes immediately at best available price; only quantity needed. |
| **Limit** | Executes only at specified price or better; may not fill if price/liquidity not reached. |
| **Stop (stop-market)** | Pending order that becomes a market order once the stop price is touched; may not execute if price never reaches the level. |
| **Stop-limit** | Combines stop trigger with a limit execution price once triggered (documented under "Understanding stop-limit orders" in the Trading basics folder). |
| **Trailing stop** | A dynamic stop that follows price by a fixed distance/percentage once price moves favorably (documented under "Introduction to trailing stops"). |

### Order size / units
- Order size can be specified in units/contracts or, depending on the ticket, in risk-based terms.
- TradingView's order ticket supports "Price" entry fields for entry, and separate fields depending on order type (limit price, stop price).

### Risk-based position sizing — confirmed via the Long/Short Position drawing tool
- TradingView does **not** appear to expose a risk-based/units-based sizing calculator as a field inside the order ticket itself (order-ticket quantity remains a plain units/contracts field per broker schema). However, TradingView's **Long Position / Short Position drawing tool** (Drawing Tools panel → "Forecasting & Measurement Tools" → Long Position / Short Position) does provide exactly this capability as a charting/planning feature:
  - User sets an **Account Size** and a **Risk** amount (either an absolute currency value or a % of account size).
  - The tool auto-calculates **position size (units/contracts)** from account size, risk %, and the distance between entry and stop-loss.
  - Entry, take-profit, and stop-loss levels are set by dragging handles directly on the chart; the tool displays a live **risk/reward ratio**, potential P&L in currency and %, and the calculated quantity, all as an overlay.
  - It is a **planning/visualization tool only** — it does not place a live order; a user must still transfer the calculated quantity into the order ticket manually (no confirmed one-click "send to broker" integration between the RR tool and the order ticket was found in this pass).
  - (Source: [Long position drawing tool — TradingView Help Center](https://www.tradingview.com/support/solutions/43000517002-long-position-drawing-tool/); [How to use long and short position drawing tools — TradingView Help Center](https://www.tradingview.com/support/solutions/43000475660-how-to-use-long-and-short-position-drawing-tools/).)
- *Gap closed*: this resolves the open question about risk/units-based sizing — it exists, but as a **drawing-tool feature**, not an order-ticket field. CandleViewer should treat these as two separate design surfaces: (1) an order ticket with a plain quantity field (broker-schema-driven, matches Bybit's own qty/leverage model), and (2) an optional chart-overlay RR/position-sizing planning tool that computes suggested quantity but requires manual transfer to the ticket — matching TradingView's own separation of concerns.

### OCO (One-Cancels-Other) orders — confirmed
- TradingView **does** support OCO-style order relationships, but not as a separately named "OCO order type" in the order-ticket dropdown — instead, OCO behavior is implemented via the **bracket mechanism** described below: attaching a take-profit and a stop-loss to the same entry order (or to an existing position) creates a linked pair where filling one leg automatically cancels the other. TradingView's own order-ticket UI exposes this as enabling both "Take Profit" and "Stop Loss" fields on the order ticket, or via right-click on an open position/chart-dragged TP-SL lines to attach brackets after entry. (Source: [What is an order ticket — TradingView](https://in.tradingview.com/support/solutions/43000784804-what-is-an-order-ticket/); corroborated by third-party walkthroughs — [Optimus Futures: TradingView OCO Orders on Futures Instruments](https://community.optimusfutures.com/t/tradingview-oco-orders-on-futures-instruments/5648).)
- **Correction/clarification (added in this pass):** the report's brief specifically asked whether "OCO" is supported — confirmed **yes**, functionally, via Order Brackets/Position Brackets (§3 below), not as a distinct order-type label. TradingView's own Help Center articles use the terms "Order brackets" and "Position brackets" rather than "OCO"; the OCO terminology is standard industry shorthand for the same one-cancels-other relationship and is used informally by TradingView's own community/support content and third parties.

### Brackets (TP/SL)
- **Order brackets**: a broker can support attaching take-profit and/or stop-loss to an order at placement time; when one bracket leg fills, the other auto-cancels (an OCO-style relationship between TP and SL legs). Support for one leg only, or both, is broker-dependent. ([Order brackets — TradingView](https://www.tradingview.com/support/solutions/43000754951-order-brackets))
- Brackets can also be **added after the fact** to an existing order ("Add brackets to the existing order") or modified ("Order brackets modification").
- **Position brackets**: distinct from order brackets — apply TP/SL to an entire open position (which may have been built from multiple fills/entries) rather than to a single order. Also modifiable and addable after the position exists. ([Position brackets — TradingView](https://www.tradingview.com/support/solutions/43000754954-position-brackets))
- In the Advanced Charts / Trading Terminal library docs (used by broker integration partners), brackets are formally defined: a buy order is bracketed by a sell-limit (TP) or sell-stop (SL); a sell order by a buy-stop or buy-limit. By default only one TP and one SL bracket per side is supported unless the integrator's config allows more. The `supportOrderBrackets` config flag enables the UI bracket controls, and bracket values are passed via a `PreOrder` object with `stopLoss`/`takeProfit` fields (plus `limitPrice` / `stopPrice` for limit/stop entry orders). ([Bracket orders — Advanced Charts docs](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/trading-concepts/brackets))

### Other documented order/position features (from the Trading basics folder index)
- **Order history** — log of past orders.
- **Execution history on the chart** — fills marked directly on the price chart.
- **Partial position close** — close only part of an open position.
- **Reverse position** — flip a long to short (or vice versa) in one action.
- **Level 2 data** — order book depth data availability (ties into DOM, §5).
- **AD-free trading on the chart** — a paid-plan perk removing ads from the trading chart view.
- **Positions and orders** — unified list view.
- **Execution marks** — visual fill markers on the chart.

### Order-from-chart / drag orders / RR tools — Help Center citation added (gap closed)
TradingView is widely known (via UI/marketing, not always separately help-documented) for:
- Placing orders directly by clicking on the chart's price scale ("order from chart").
- **Dragging** pending order lines and open position TP/SL lines directly on the chart to modify price levels.
- A built-in **Risk/Reward (long/short position) drawing tool** that overlays entry/target/stop zones with computed R:R ratio, potential profit/loss in currency and %, directly as a chart drawing tool (found under Drawing Tools → "Long/Short Position").
- These are UI/drawing-tool level features rather than separate broker-API endpoints — they translate into the same underlying order/bracket calls described above.
- **Confirmed primary-source citations found in this pass** (previously flagged as uncited, open question §18 item 8, now resolved): [Long position drawing tool — TradingView Help Center](https://www.tradingview.com/support/solutions/43000517002-long-position-drawing-tool/) and [How to use long and short position drawing tools — TradingView Help Center](https://www.tradingview.com/support/solutions/43000475660-how-to-use-long-and-short-position-drawing-tools/) directly document: entry price set by clicking the chart; green (profit) and red (loss) zones with draggable handles; live-updating R:R ratio, P&L in currency/%, and position-size stats; a Style tab (colors/line thickness/which stats to display) and a Visibility tab (which timeframes show the tool). Dragging existing order/TP-SL lines directly on the chart to modify a **live order** (as opposed to the planning-only drawing tool) remains sourced only to general product/UI knowledge — TradingView's Trading-basics folder references "Order brackets modification" and "Position brackets" as the underlying mechanism, but no single Help Center article was found that explicitly documents "drag the line to modify" as its own titled topic. This narrower point remains an open item (§18).

*(Note: the RR/Long-Position drawing tool is now sourced; the narrower "drag an existing live order's line to modify it" UI behavior is still not tied to one authoritative citation — see §18.)*

## 4. Paper trading

Per the Trading basics folder ("Demo features on TradingView") and general TradingView product documentation:
- Paper trading is TradingView's built-in **simulated trading** mode, available without connecting any real broker.
- It uses the standard order ticket (market/limit/stop as described in §3) against **live real-time market data** (subject to the user's data plan/exchange data permissions) so fills approximate real market conditions.
- Paper trading accounts have a **virtual balance** that can be reset by the user (exact default balance and reset mechanics are configured in "Paper Trading" account settings inside the Trading Panel; TradingView's UI provides an option to reset the paper account to its starting balance and/or adjust the starting equity value).
- Fill model: for a simulated/paper account, TradingView fills market orders at the prevailing market price and limit/stop orders when the market price crosses the specified level, similar to a live broker but without slippage/liquidity modeling from a real order book (i.e., it is a idealized/simplified fill assumption, not a full order-book simulation).
- Distinct from Pine Script's **Strategy Tester** broker emulator (§9) — paper trading is a manual, chart-based simulated trading account for discretionary trading; the Strategy Tester is for **automated backtesting** of Pine strategy code. They use conceptually similar but implementation-distinct fill logic.
- (Source: [Trading basics folder — TradingView Help Center](https://www.tradingview.com/support/folders/43000597927-trading-basics), listing "Demo features on TradingView" among its articles — full article body not independently re-fetched in this pass; treat granular reset/limit mechanics as **needing direct verification**, §18.)

### Reset mechanics — additional detail (partial gap closure)
Corroborating third-party walkthroughs consistent with TradingView's own Trading Panel UI (no single dedicated primary Help Center article body was retrievable in full text during this pass, so this remains partially unconfirmed against TradingView's own wording — flagged in §18):
- The "Reset" control lives in Paper Trading account settings (gear icon in the Trading Panel, only available while the Paper Trading account — not a live broker — is the active connection).
- Reset lets the user set a **new starting balance**, choose an **account currency** (USD, EUR, BTC, and others), and adjust **leverage** for the simulated account.
- Resetting **deletes all open positions, working orders, and historical paper-trading records** for that paper account — described as irreversible.
- No official numeric cap on paper-trading virtual balance (i.e., no confirmed maximum starting balance a user can set) was found; this remains unresolved (§18).
- (Corroborating, non-primary sources: [Pineify — How to Reset Paper Trading TradingView](https://pineify.app/resources/blog/how-to-reset-paper-trading-tradingview); [Aron Groups — TradingView Paper Trading Guide](https://arongroups.co/forex-articles/tradingview-paper-trading-guide/).)

## 5. DOM panel

- "DOM" = Depth of Market — TradingView's DOM panel is a broker-dependent, order-book-driven trading panel showing bid/ask price ladders with size at each level, and letting users click to place orders directly at a price level in the ladder.
- Availability of the DOM panel, and how deep the book is shown, is **broker-dependent** — not all TradingView-supported brokers/exchanges expose sufficient Level 2 data for a DOM ladder. TradingView's Trading basics folder references "Level 2 data" as its own documented concept, implying DOM ladder functionality requires Level 2 (order book) market data support from the connected broker.
- **[verified this pass] Bybit is on TradingView's official Level 2/DOM-supported broker list.** Per the official Help Center article "How do I get level 2 data?" (support/solutions/43000480004), the full list of brokers TradingView names as providing Level 2 data in the DOM window is: **Alor, AMP, AVAFutures, Binance, Bitazza, Bitget, Bybit, CapTrader, Coinbase Advanced, Colmex Pro, CFI, Dorman Trading, DNSE, EdgeClear, FXOpen, GBE Brokers, Herenya, HTX, IBKR, iBroker, Interactive IL, InnovestX, Ironbeam, Mexem, NinjaTrader, OKX, Optimus Futures, Phemex, Plus500US, Samuel Sekuritas, StoneX, Tokenize, TradeStation, Tradier Futures, Tradovate, Velocity, Whitebit, WH SelfInvest Futures.** This directly resolves the prior open question about whether Bybit's DOM is enabled through the first-party TradingView integration — **it is listed by name**, alongside other crypto exchanges (Binance, Bitget, Coinbase Advanced, HTX, OKX, Phemex, Whitebit).
- **DOM depth (number of price levels) — [unresolved, still]**: neither this article nor the companion "Depth of market (DOM): what it is and how traders can use it" article (support/solutions/43000516459) or the "Level 2 data" glossary article (support/solutions/43000754967) states an exact number of price levels/rows shown in TradingView's DOM ladder. The DOM article describes the *mechanics* (static price-series display, centering button, click/drag to place orders) but not a fixed row count — TradingView's DOM appears to show as many levels as the broker feed provides, dynamically, rather than a fixed TradingView-imposed cap. This is consistent with the Advanced Charts / Charting Library documentation (`charting_library-docs/trading_terminal/depth-of-market`), which describes the DOM widget as sourced from a `DOMData` object populated via `subscribeDepth`/`getDepth`-style Datafeed methods with no documented fixed level count — the depth is whatever the datafeed/broker chooses to push.
- **Ladder trading controls — [verified]**: from the official DOM Help Center article, the ladder supports: click a cell next to a price to place a limit order (left column = buy, right column = sell); Ctrl-click (Cmd-click on Mac) a cell to place a stop order; right-click (Ctrl+right-click on Mac) a price cell to get an order-type picker (market/limit/stop); Buy Mkt / Sell Mkt buttons for market orders at a set quantity; drag an existing order to a different price row to reprice it (opens the same modify dialog as clicking the order); Flatten and Reverse buttons to close/flip the current position; a per-side cancel-all control (cancel all buys, cancel all sells) plus a global "CXL ALL" button; and a centering button to re-center the static price ladder on the current market price. Color coding: green = active Limit Buy/Sell, red = active Stop Buy/Sell, yellow = active StopLimit Buy/Sell (limit leg shown duller than the stop leg).
- Given Bybit is confirmed on the Level-2/DOM broker list, the first-party TradingView↔Bybit DOM should in principle be available live, though the **exact depth (number of rows) delivered for Bybit specifically** is not stated anywhere in official docs and would need direct live testing to confirm (Bybit's own WebSocket order-book topics support `orderbook.1/50/200/500` depth tiers per Bybit's own API docs, so the ceiling on Bybit's side is high — what TradingView's DOM widget actually surfaces from that feed is the remaining unknown).

### Bybit-specific order types & DOM depth via TradingView (re-researched this pass — partial gap closure)
- **Order types confirmed as broadly supported for Bybit via TradingView/automation tooling:** Market, Limit, Conditional (stop) orders, Take Profit, Stop Loss, and **Trailing Stop**. Per Bybit's own Help Center ([Trailing Stop Order (Perpetual and Futures Trading) — Bybit](https://www.bybit.com/en/help-center/article/Trailing-Stop-Order-Perpetual-and-Futures-Trading); [Types of Orders Available on Bybit — Bybit Help Center](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit)), Bybit's native trailing stop can be set by fixed distance or percentage/rate, and is available for Perpetual/Futures positions (attached to an open position rather than a pending order — i.e., a "TP/SL/Trailing-on-position" model, distinct from "TP/SL-on-order").
- **Important caveat (unresolved — still an open question):** the sources found confirm Bybit's own native order types (including trailing stop) exist on Bybit's platform/API, and third-party automation tools (e.g., AutoView, which relays TradingView alerts to Bybit via webhook) can address these order types by API parameter. However, **no primary source was found confirming that TradingView's own first-party Trading Panel↔Bybit broker integration (the built-in "Connect to Bybit" flow, not a third-party webhook relay) exposes Bybit's native trailing-stop or TP/SL-on-position UI 1:1** inside TradingView's own order ticket. TradingView's order-ticket UI is broker-schema-driven and generic (§3); whether Bybit's specific broker-integration schema (as implemented by Bybit for the TradingView Broker API) surfaces trailing-stop as a first-class order-ticket option, versus only Market/Limit/Stop with basic TP/SL brackets, remains **unconfirmed** and should be verified by directly testing a live Bybit↔TradingView connection. This narrows but does not fully close the original open question (§18).
- **DOM/Level-2 depth:** **[verified this pass]** Bybit is confirmed by name on TradingView's official Level-2-data broker list (Section 5), so the DOM panel is enabled for Bybit-connected accounts on the first-party integration. The **exact number of price levels/rows** shown for Bybit specifically is still not stated in any official source — this narrower depth-count question remains open (§18) pending direct live testing.
- Given both caveats, this report's existing recommendation stands and is reinforced: **CandleViewer should build its own order ticket and DOM directly against Bybit's REST/WebSocket API** (which does confirm full trailing-stop, TP/SL-on-position, and 50/500-level order-book depth — per Bybit's own API docs) rather than assume feature parity with whatever subset TradingView's generic broker-integration schema happens to expose for Bybit.

## 6. Account Manager panel

The **Account Manager** is the tabbed panel (typically bottom of the Trading Panel area) showing, per the Broker Integration Manual's "Trading concepts" documentation:
- **Positions** — open positions with size, average price, unrealized P&L, and (if supported) bracket/TP-SL info.
- **Orders** — working/pending orders; the manual notes the UI's "Orders" tab displays all orders received in response to the broker's `/orders` endpoint, and that placing an order triggers a lifecycle of order-state events (e.g., placed → working → filled/cancelled/rejected) that the broker's backend must report.
- **Order history** — historical/closed orders.
- **Notifications** — broker-originated messages/events surfaced to the user (e.g., fills, margin calls) — implied by the account-manager streaming/update architecture in the integration manual, though a dedicated "Notifications" tab is not separately named in the excerpts retrieved; this is an area to verify directly against the live product (§18).
- **Gap closed (partially) — Notifications tab confirmed to exist as a documented UI element:** re-researched this pass against [UI elements — Broker Integration Manual](https://www.tradingview.com/broker-api-docs/trading/ui-elements/). The Account Manager panel is explicitly documented as being able to host **multiple tabs**, and "Notifications" is named among the possible tabs alongside Positions, Orders, Order History, and Account Info — so a Notifications tab **is** a real, named first-class UI element in the Broker Integration Manual, not merely inferred. However, unlike Orders/Positions, there is **no dedicated `/notifications` REST endpoint** in the documented Broker API — notification content is instead pushed to the front end via the Trading Host's general real-time update/state mechanism (the same `/state` and streaming architecture that drives Positions/Orders), rather than a distinct notifications data model. *Correction: previously the report treated this as unconfirmed/implied only; it is now confirmed as a named tab, with the caveat that its backing data model is not a separate endpoint.*
- Editing an order (e.g., changing stopLoss/takeProfit on an existing order) is implemented as a PUT request to the broker's server carrying the updated order parameters, including `stopLoss`/`takeProfit` fields.
- Update/streaming cadence per the integration FAQ: **default 500ms / max 1000ms** for quotes and order updates; **default 500ms / max 1500ms** for positions, accountManager, and balances. (Source: [FAQ — Broker Integration Manual](https://tr.tradingview.com/broker-api-docs/faq))
- (Sources: [Concepts — Broker Integration Manual, Trading](https://in.tradingview.com/broker-api-docs/trading/concepts); [UI elements — Broker Integration Manual](https://www.tradingview.com/broker-api-docs/trading/ui-elements/))

## 7. Alerts

### Alert types
Per TradingView's "Concepts / Alerts" doc and "Introduction to TradingView alerts":
| Type | How it's created | Requires Pine code? |
|---|---|---|
| **Generic / price alerts** | From the chart UI on a plain symbol + price + condition (crossing, crossing up/down, greater than, less than) | No |
| **Drawing alerts** | Right-click a drawn line/channel/shape → add alert | No |
| **Script/indicator alerts on order-fill events** | Created from a strategy's order-fill events in the UI | No (auto-generated by strategy engine), but requires the placeholder `{{strategy.order.alert_message}}` in the message field to see the custom message |
| **Script alerts triggered by `alert()` function calls** | Requires the script itself to contain `alert()` calls; users then pick "Any alert() function call" as the trigger condition | **Yes** |
| **`alertcondition()` alerts** | Requires the script to declare `alertcondition(condition, title, message)`; users then select that named condition from the Create Alert dialog | **Yes** |

Key semantics (from [Concepts / Alerts](https://www.tradingview.com/pine-script-docs/concepts/alerts) and the [Alerts FAQ](https://www.tradingview.com/pine-script-docs/faq/alerts)):
- No Pine alert code can create a "running" alert on its own — Pine merely defines *alert events*; the user must still create the actual running alert via the Create Alert dialog in the chart UI.
- Alerts **only trigger on realtime bars** — not on historical/backtest bars.
- When an alert is created, TradingView saves a **snapshot** of the script, its input values, and the chart's symbol/timeframe/context, and runs that frozen version server-side — so subsequent changes to the indicator's inputs on the visible chart do NOT affect an already-created alert.
- **Repainting** is called out as the typical root cause of "alert fired at an unexpected time/price" complaints, because realtime-bar values can differ from the final confirmed bar value; setting alert frequency to "Once Per Bar Close" mitigates this.
- Alert trigger frequency options include (at least): Once Per Bar, Once Per Bar Close, Once Per Minute.

### Trigger condition categories ("Alerts separation by type")
TradingView classifies every alert into exactly one of three types for quota purposes ([Alerts separation by type](https://www.tradingview.com/support/solutions/43000696403-alerts-separation-by-type)):
- **Price alerts**: symbol + price value only, with condition ∈ {Crossing, Crossing Up, Crossing Down, Greater Than, Less Than}. Applies even on Renko/PnF/spread charts.
- **Technical alerts**: any alert on an overlay/indicator/drawing/strategy, OR any alert using condition ∈ {Entering Channel, Exiting Channel, Inside Channel, Outside Channel, Moving Up, Moving Down, Moving Up %, Moving Down %}, OR any alert combining multiple conditions.
- **Watchlist alerts**: a separate, much smaller quota (e.g. 2 on many plans) — for alerts scoped across an entire watchlist rather than one symbol/script.
- Each category has an **independent** active-alert quota, e.g. with 400 price + 400 technical + 2 watchlist you can run 802 alerts total simultaneously — quotas do not share a pool.

### Alert limits by plan (values found across TradingView blog + third-party trackers — verify current figures directly against tradingview.com/gopro before relying on them, as TradingView has changed these multiple times, most recently referenced doubling in 2023 and again per 2026 third-party trackers)
| Plan | Active alerts (approx., per most recent sources found) | Webhooks | Notes |
|---|---|---|---|
| Basic / Free | ~1–3 active alerts, 0 technical alerts | No | Free plan cannot use technical/indicator-based alerts or webhooks; price alerts only, deliverable by email/app. |
| Essential | Higher tier cap (third-party trackers cite ~20) | **Yes** (Essential is the minimum plan with webhook support) | |
| Plus | Higher again (~100 cited) | Yes | |
| Premium | 800 total (400 price + 400 technical) per TradingView's own 2023 blog post; other trackers cite same figure in 2026 | Yes | Also unlocks 2 watchlist alerts on some tier breakdowns |
| Expert (non-public/legacy tier referenced in one source) | 1200 total (600+600) | Yes | |
| Ultimate | 2000 total (1000 price + 1000 technical) | Yes | |

⚠️ These numbers come from a mix of TradingView's own blog ([It's doubled now: more alerts for each plan!](https://www.tradingview.com/blog/en/more-alerts-for-each-plan-31701/), 2023) and third-party trackers (tv-hub.org, clearedge.trading, pickmytrade) whose 2026 figures don't perfectly agree with each other on Essential/Plus caps — **treat exact per-plan numeric caps as needing live verification against TradingView's current pricing page** before being used for any product decision (§18). The category-split mechanism (price/technical/watchlist as independent quotas) is solidly documented directly by TradingView and can be trusted.

### Alert limits — additional 2026 figures found this pass (partial gap closure, still not TradingView-primary-sourced)
Two more recent (2026) third-party plan-comparison sources were located and are broadly consistent with each other and with the Premium figure already cited above from TradingView's own 2023 blog post:

| Plan | Active price alerts | Active technical alerts | Alert expiry | Monthly cost (billed annually) |
|---|---|---|---|---|
| Essential | 20 | 20 | ~2 months (fixed expiration) | $12.95 |
| Plus | 100 | 100 | ~2 months (fixed expiration) | $29.95 |
| Premium | 400 | 400 | **Never expires (open-ended)** | $59.95 |

- (Sources: [Tickerly.net — Which TradingView Plan Should I Get? (2026 Guide)](https://tickerly.net/best-tradingview-plan/); [FinancialTechWiz — TradingView Pricing 2026](https://www.financialtechwiz.com/post/how-much-is-tradingview/).)
- This directly resolves open question §18 item 2 (alert expiration/duration per plan) to the extent these third-party figures are accurate: **lower/mid tiers (Essential, Plus) get alerts that expire after roughly 2 months and must be recreated; Premium alerts are open-ended/never expire.** This is still **not independently confirmed against TradingView's own pricing page or Help Center article body** in this pass (attempts to fetch tradingview.com/pricing directly failed due to a tool error — see note below), so item 1 (exact numeric caps) remains formally unresolved at "TradingView-primary-source" confidence, though corroboration across two independent third-party 2026 sources raises confidence the Essential=20/Plus=100/Premium=400 figures are currently accurate.
- **Tooling note:** a direct fetch of `tradingview.com/pricing` was attempted in this research pass to verify these numbers against TradingView's own page but failed due to a web-fetch tool error unrelated to content availability; this should be retried.

### Notification channels
Per [Introduction to TradingView alerts](https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts):
- **App notification** (TradingView mobile app push)
- **Pop-up** (in-browser/desktop-app dialog)
- **Email** (including to an alternate address)
- **SMS** (per third-party trackers; likely a paid-plan feature — not independently re-verified against TradingView's own current article body in this pass)
- **Webhook URL** (POST request with the alert's message as the JSON/text body) — requires Essential plan or higher
- **Sound alert**

### Webhook payload
- The webhook POST body is simply whatever string was placed in the alert's "Message" field (which can itself embed placeholders like `{{ticker}}`, `{{close}}`, `{{strategy.order.action}}`, `{{strategy.position_size}}`, `{{strategy.order.price}}`, or the raw text passed to a Pine `alert()`/`alert_message` argument).
- Pine has **no built-in JSON-encoding function**, per the Alerts FAQ — if a script wants to emit valid JSON to a webhook, the script author must hand-construct the JSON string themselves (e.g., via `str.format()`/string concatenation).
- A very common pattern (seen across third-party automation vendors like CrossTrade, PickMyTrade, Stocks Developer's "AutoTrader") is constructing a delimited key=value or JSON string inside Pine via `alert_message` on `strategy.entry()`/`strategy.close()`/`strategy.exit()` calls, then having the TradingView alert's Message field just be `{{strategy.order.alert_message}}`.

### Alert size/name limits
Per [Alert name and message size limits](https://www.tradingview.com/support/solutions/43000773947-alert-name-and-message-size-limits/):
- **300 characters** max alert name.
- **4000 characters** max message length when typed directly into the alert-creation dialog's "Message" field.
- **40,960 characters** max message length when the message comes from Pine's `alert()` function or the `alert_message` argument of a `strategy.*()` call (same limit applies to webhook request body size).
- Emojis count as multiple characters (multi-byte encoding), reducing effective character budget.

### Expiration
- TradingView alerts historically had a fixed maximum lifetime for non-webhook (browser-triggered / "open-ended") alerts; current TradingView docs/UI expose an alert "Expiration" date field in the Create Alert dialog allowing indefinite ("Open-ended") alerts on paid plans vs. a capped duration on lower tiers. Exact current defaults/caps were not independently confirmed to a specific number of days in this research pass — flagged as an open question (§18).

## 8. Pine Script

### Versions
- Current version is **Pine Script v6** ([Welcome to Pine Script v6](https://www.tradingview.com/pine-script-docs/welcome)). Prior versions (v5, v4, etc.) remain usable on existing scripts but new script templates default to v6. Version is declared via `//@version=6` (or similar) at the top of a script.

### Script types
- **Indicators** — `indicator()` declaration; display data/plots/shapes on the chart, do not place trades.
- **Strategies** — `strategy()` declaration; can call `strategy.entry()`, `strategy.exit()`, `strategy.close()`, `strategy.order()` to simulate/backtest trades and generate the Strategy Tester report (§9); can also generate real order-fill alerts to drive live automation via alerts + webhooks.
- **Libraries** — reusable function collections importable by other scripts via `import` statements; can be published publicly or kept private/for-personal-use.

### Key data-access function: `request.security()`
- Pulls data from another symbol, timeframe, or context (e.g., higher timeframe aggregation, extended-session data) into the current script.
- **Hard resource limit: ~40 unique `request.*()` calls per script** (covers `request.security()`, `request.currency_rate()`, `request.dividends()`, etc.), and this budget is shared with any imported libraries' own `request.*()` calls. (Source: TradingView's official Pine Script Limitations doc plus corroborating community references — [QuantNomad](https://quantnomad.com/the-main-limitations-of-pine-script-on-tradingview/), [Pineify](https://pineify.app/pine-script/guides/pine-script-limitations).)

### Other documented Pine execution/resource limits
| Limit | Value |
|---|---|
| Script compile time | ~2 minutes; repeated failures trigger a temporary 1-hour compile ban |
| Script execution time across all bars | 20s (Basic/free-tier), 40s (paid/Premium+ tiers) |
| Per-bar loop execution | 500ms max per single bar's loop execution (slowest nested loop triggers timeout first) |
| Max plots per script | 64 |
| Max drawing objects (lines/boxes/labels) default | 50 (can be raised) |
| Max drawing objects hard cap | 500 lines/boxes/labels, 100 polylines |
| Max compiled script size (main + all imported libraries) | under 1,000,000 tokens total |
| Max main script size alone | 80,000 tokens |

### Architectural constraints
- No external network/API calls or WebSocket support from within Pine — Pine cannot call arbitrary outside services; all data must come through TradingView's own `request.*()` data model or built-ins.
- No persistent database/storage across sessions — script state is scoped to script execution and does not persist arbitrarily between reloads outside of `var`/`varip` in-session state.
- No custom interactive UI beyond chart overlays/plots/tables/labels — no arbitrary HTML/JS UI.
- Single main-symbol execution model — one primary chart symbol per script instance; other symbols can only be *read* via `request.security()`, not traded directly (a strategy always trades the chart's own symbol).

### Alerts from Pine (see also §7)
- `alert()` function calls and `alertcondition()` declarations are the two Pine-code paths to create alert-eligible events; order-fill alert messages use the `alert_message` parameter on `strategy.entry()`/`strategy.exit()`/`strategy.close()`/`strategy.order()`, surfaced in the Create Alert dialog via the `{{strategy.order.alert_message}}` placeholder.
- Pine has no built-in JSON serialization — JSON payloads for webhooks must be hand-built as strings.

## 9. Strategy Tester

### Strategy properties (configurable via `strategy()` args or the Strategy Tester's Properties tab)
Per [Strategy properties — TradingView](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/):
- Initial capital
- Base currency
- Order size (fixed contracts/shares, or % of equity)
- Pyramiding (number of same-direction entries allowed to stack)
- Commission (percent, fixed per order, or per contract)
- Slippage (in ticks)
- Margin (long/short margin %, for leveraged instruments)
- Recalculate options: recalculate on every tick vs. only on bar close; recalculate after order is filled (`calc_on_order_fills`)
- Bar Magnifier toggle (`use_bar_magnifier`)
- Verify Price for Limit Orders (only fill a limit order if the historical bar's range plausibly reached that price, accounting for realistic fill assumptions)

### Bar Magnifier
Per [What is bar magnifier backtesting mode](https://www.tradingview.com/support/solutions/43000669285-what-is-bar-magnifier-backtesting-mode/):
- Uses a **lower ("intrabar") timeframe** feed to simulate whether/when a stop, limit, or trailing order would actually have triggered within a higher-timeframe bar, instead of assuming worst/best-case OHLC ordering.
- Automatically selects an appropriate intrabar resolution based on the chart's timeframe (e.g., a 1D chart may magnify with 1H intrabars).
- Capped at roughly **200,000 lower-timeframe bars** loaded per strategy run; precision degrades for periods beyond that cap.
- Enabled via `use_bar_magnifier=true` in the `strategy()` declaration, or the Properties tab toggle.

### Deep Backtesting
- A paid-plan (**Premium tier and above, now confirmed directly against TradingView's own Help Center**, not just third-party trackers — see below) feature that extends backtesting far beyond the bars currently rendered/loaded on the visible chart.
- **Gap closed — the "up to 2 million bars / 1 million trades" figures are confirmed by TradingView's own Help Center, not merely third-party trackers.** Re-researched this pass against TradingView's own Help Center folder ["I'd like to learn more about Deep Backtesting"](https://www.tradingview.com/support/folders/43000584695-i-d-like-to-learn-more-about-deep-backtesting/), which contains the primary articles [How Deep Backtesting works](https://www.tradingview.com/support/solutions/43000666265-how-deep-backtesting-works/), [How much data is available for Deep Backtesting?](https://in.tradingview.com/support/solutions/43000668210-how-much-data-is-available-for-deep-backtesting/), and [Why are the results of Deep Backtesting not shown on the chart?](https://in.tradingview.com/support/solutions/43000670566-why-are-the-results-of-deep-backtesting-not-shown-on-the-chart/). These TradingView-owned articles corroborate: a hard cap of **2 million bars** and **1 million trades** per calculation; eligibility limited to **Premium plan and above**; Deep Backtesting engages automatically (indicated by a pink/magenta icon) when the selected backtest date range exceeds the bars currently loaded on the chart; results appear only in the **Strategy Report tab**, never overlaid on the chart itself (because the chart only ever renders the bars physically loaded in the browser, while Deep Backtesting queries TradingView's full server-side historical dataset); a "Reset to chart session" control exits Deep Backtesting mode back to ordinary viewport-limited testing; and an "Update report" action is needed to refresh results after editing the strategy. *(No footnote correction needed — the original figure was accurate; confidence upgraded from "third-party only" to "TradingView Help Center confirmed.")*
- Actual historical coverage still depends on the asset and timeframe selected (daily charts can span much longer real-world periods within the 2M-bar cap than intraday charts).
- Gives a materially better long-horizon view of drawdown/robustness than a default, viewport-limited backtest.

### Strategy Report structure
Per [TradingView Strategy Report: How to start](https://ru.tradingview.com/support/solutions/43000764138/) and the India-locale mirror ([in.tradingview.com](https://in.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)):

**Overview tab**
- Equity chart (equity over time)
- Date range selector for the tested window
- Total P&L (currency + %)
- Max drawdown
- Profitable trades (%)
- Profit factor (gross profit ÷ gross loss)
- Buy & hold comparison overlay
- Breakdown: gross profit vs. gross loss per signal/side, with net result
- Periodical: P&L broken down by period (daily/weekly/monthly/yearly), with favorable/adverse excursion detail on hover
- Benchmarking: strategy PnL vs. buy-and-hold bar chart across chosen period granularity
- Margin usage: line chart of % margin usage over time, trade count and exact usage on hover

**Performance tab** (separate metrics for All/Long/Short):
- Open P&L
- Net profit
- Gross profit
- Gross loss
- Commission paid
- Buy & hold return
- Max equity run-up
- Max equity drawdown
- Max contracts held

**Trades analysis tab** (separate for Long/Short):
- Total trades
- Total open trades
- Winning trades / Losing trades
- Percent profitable
- Avg P&L
- Avg winning trade / Avg losing trade
- Ratio avg win / avg loss
- Largest winning trade (currency + %)
- Largest losing trade (currency + %)
- Avg # bars in trades / in winning trades / in losing trades

### Bar Replay
Per [Bar Replay: how and why to test a strategy in the past](https://www.tradingview.com/support/solutions/43000712747-bar-replay-how-and-why-to-test-a-strategy-in-the-past):
- Lets a user manually "replay" historical price bar-by-bar (or via auto-play at adjustable speed) to practice discretionary decisions or watch how an indicator/strategy would have reacted in real time, without financial exposure.
- Supports starting from the earliest available day, a chosen date, or a random bar.
- Works across single or multiple charts in a layout simultaneously; drawings persist after exiting replay, chart type/style settings are not preserved on resume for chart types that don't support replay.
- Session state (symbol, interval, last-viewed bar, replay state) can be restored when reopening a workspace, per-chart.

## 10. Screener

- TradingView provides Stock, Crypto, and Forex screeners (separate URLs/sections: tradingview.com/screener/ variants) with built-in filterable columns (price, volume, market cap, technical rating, performance %, etc.).
- **Crypto screener** specifically covers exchange-listed crypto pairs with filters for market cap, volume, price change, and technical indicator-based columns (e.g., RSI, Moving Averages rating).
- **Important architectural limitation:** the built-in screener does **not** support arbitrary custom Pine Script code — it only supports TradingView's own built-in filter/column set. (Corroborated directly inside TradingView's own Pine docs Alerts FAQ content: "the TradingView screener uses built-in filters and does not support custom Pine Script code.")

### 10.1 Pine Screener scope — **[verified this pass]**
Per the official Help Center article [TradingView Pine Screener: key features and requirements](https://www.tradingview.com/support/solutions/43000742436-tradingview-pine-screener-key-features-and-requirements) (fetched directly):
- The Pine Screener **does** run Pine Script logic (unlike the main built-in screener) — it scans a chosen **Source** against a chosen **Indicator**:
  - **Sources**: the user's own custom/curated watchlists (including colored lists), or a major market index. Only one source can be scanned at a time; source selection cannot be cleared, only replaced; the last-used source is remembered and re-selected on next open (falling back to the default watchlist if the prior source was deleted or access was lost).
  - **Indicators**: any indicator saved to the user's favorites — this includes the user's own custom Pine scripts, TradingView's built-in technical indicators, or community-published scripts from the public library.
- Workflow: select source → select indicator → set filter criteria on that indicator's outputs → Scan. A rescan is required if the user changes Source, Studies (indicators), current study inputs, study timeframe, or the filter set after a run — a "Rescan" prompt appears when this happens.
- The Pine Screener can scan a **mixed-asset-class watchlist simultaneously** — e.g., a single watchlist containing stocks, crypto, bonds, and other asset types together — since it scans whatever the selected source contains, unconstrained by a single-asset-class screener view (unlike the dedicated Stock/Crypto/Forex screeners in Section 10's main paragraph, which are asset-class-siloed).
- **Symbol scope limit — [inferred, third-party, not TradingView-primary]**: a third-party guide (Pineify) states the Pine Screener "supports up to 25,000 symbols on Premium" — this specific numeric ceiling was not found in TradingView's own Help Center article and should be treated as unverified/third-party until corroborated by an official source.
- **Net assessment for CandleViewer**: Pine Screener's "watchlist × indicator → scan" model is architecturally simple and directly reproducible — CandleViewer's own screener (crypto-only, Bybit-first) could adopt the same source/indicator/scan mental model without needing Pine Script itself, since the underlying computation (apply an indicator function to each symbol in a list, filter/sort the outputs) is generic.

## 11. Watchlist features

Based on TradingView's general watchlist product documentation, UI behavior, and the official pricing grid's Watchlist row group (fetched directly):
- **Sections**: symbols can be grouped into custom named sections/folders within a single watchlist.
- **Flags/colored lists — [verified, tier-gated]**: per the official pricing grid, "Flagged symbols colors" is an explicit gated row: **Basic = 1** color, **Essential/Plus/Premium/Ultimate = 7** colors each. The Pine Screener docs (Section 10.1) independently corroborate that "colored lists" are a real, named watchlist concept (selectable as a Pine Screener source), consistent with this flagging mechanism.
- **Import/export — [verified, tier-gated]**: the official pricing grid has a dedicated "Import/export" row under Watchlists, present as a gated checkmark feature (exact tier cutoff rendered ambiguously in the scraped grid — likely Essential+ given the pattern of other Basic-excluded rows, but not independently confirmed with a clean checkmark read).
- **Custom columns and sorting — [verified, tier-gated]**: separate gated row on the same grid ("Custom columns and sorting"), confirming watchlists support user-configurable columns (e.g., price, %change, custom indicator values) and sort order, beyond the default view.
- **Multiple watchlists**: users can maintain several named watchlists and switch between them — gated flag present from Essential upward (Section 7 of doc 01); Basic is capped at exactly 1 watchlist (30 symbols max, per third-party corroboration in doc 01). No official exact numeric cap was found for how many watchlists a paid-tier user may create (doc 01 Open Question #9 — still unresolved after this pass's re-fetch).
- **Watchlist scan filter**: per [How to scan watchlist or flagged list?](https://www.tradingview.com/support/solutions/43000724549-how-to-scan-watchlist-or-flagged-list) — colored/custom watchlists are directly selectable as a filter inside the (non-Pine) built-in Screener too, not just the Pine Screener; the filter menu auto-updates as watchlists are created/deleted, and if a selected watchlist's symbols don't match the active screener's asset class (e.g., a watchlist with stocks opened inside the ETF Screener), the table renders empty rather than showing an error.
- **Alerts integration**: watchlist-level alerts are a distinct alert category with their own (typically very small, e.g. 2) quota, as covered in §7.
- **Net assessment for CandleViewer**: sections/flags/colors/import are all real, officially-gated TradingView watchlist features (not just inferred), but the exact watchlist-count cap per tier remains genuinely undocumented by TradingView itself — CandleViewer, being single-owner + a few account managers with unlimited internal access, likely doesn't need to replicate a tiered-cap model at all; a simple "unlimited named watchlists with color flags and custom columns" design covers everything confirmed above.

## 12. News, calendar, ideas, social, minds

- **News tab**: aggregated news feed (from partnered providers) filterable by symbol, on the chart's News panel.
- **Economic calendar**: macro event calendar (rates decisions, CPI releases, etc.) available as a widget/panel; scope for crypto-specific "calendar" equivalents (e.g., token unlocks, halving dates) was not confirmed in this pass.
- **Ideas**: community-published trading ideas/analyses tied to a symbol, publicly browsable per-symbol or platform-wide.
- **Minds**: a shorter-form, feed-style social posting feature (similar to a micro-blog) distinct from full "Ideas" posts, allowing quick chart-attached commentary.
- **Social features**: follow other users, comment on ideas, reputation/badge system for top authors.
- (These are standard, well-known TradingView platform features; a dedicated Help Center citation pass for each was not completed in this research session — flagged §18 for direct verification if any of these matter for CandleViewer's scope, though per the project brief CandleViewer is trading/DOM/order-flow focused and these social/news features are likely low priority.)

## 13. Desktop app, mobile features, keyboard shortcuts, multi-monitor

- **Desktop app**: a native (Electron-based) TradingView Desktop application exists for Windows/macOS, offering the same charting/trading feature set as the web app plus **multi-monitor / multi-window support** — letting a user pop individual charts or panels out into separate OS-level windows across multiple monitors, which the browser-only version supports more limited by comparison.
- **Mobile app**: iOS/Android apps supporting charting, alerts (including push "App notification" delivery), watchlists, and (broker-dependent) trading from mobile.
- **Keyboard shortcuts**: TradingView provides an extensive, remappable keyboard shortcut system, documented at the official [Shortcuts and tips folder](https://www.tradingview.com/support/folders/43000561752-hotkeys-and-tips/). Representative shortcuts (compiled from third-party cheat sheets referencing the official docs):

| Action | Shortcut |
|---|---|
| Add symbol to watchlist | Alt + W |
| Next / previous symbol | Down / Up Arrow |
| Select all symbols (in a list) | Ctrl + A |
| Toggle fullscreen / maximize chart | Alt + Enter |
| Extend selection | Shift + Down/Up |
| Quick symbol search | Type ticker, or press Shift twice |
| Change interval | Type number then Enter |
| Switch charts in multi-chart layout | Tab |
| Take snapshot | Alt + S |
| Reset chart | Alt + R |
| Create alert | Alt + A |

⚠️ The exact shortcut list should be pulled live from the official folder (linked above) rather than relied upon from this table alone, since third-party cheat-sheets may drift from the current, user-customizable default bindings.

## 14. Chart sharing & data export

- **Chart sharing**: a "Share" toolbar action can produce a shareable snapshot image/link of the current chart state (symbol, indicators, drawings), or publish a full "Idea" post.
- **CSV data export**: TradingView supports exporting chart bar data (OHLCV) to CSV from paid plans (documented as a Premium+/higher-tier perk in third-party plan-comparison sources, e.g., "supa.is" plan breakdown referenced in this research: Premium includes "Chart data export"). Strategy Tester trade lists can likewise be exported to CSV for external analysis (a workflow explicitly referenced by third-party analytics tools like Pineify, which ingest TradingView's exported Strategy Tester CSV for deeper reporting).
- **Gap re-researched — no fixed numeric row cap found; the constraint is architectural, not a stated limit.** Per TradingView's own Help Center article [How to export chart data — TradingView](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/) (title confirmed via search; full body not independently re-fetched due to a tool error this pass, see note below) and corroborating third-party guides, chart-data CSV export captures only the OHLCV bars **currently loaded into the chart in the browser** at the moment of export — there is no documented fixed "row limit" as such. To get more historical rows, the user must first scroll back/zoom out to force TradingView to load more bars into memory, then export; the practical ceiling is therefore governed by how much history TradingView will load into a chart session (which is itself resolution- and plan-dependent) plus browser memory, not a stated CSV-specific cap. **This resolves the open question to the extent that "there is no separate, documented numeric CSV row limit distinct from ordinary chart bar-loading limits"** — but the underlying chart bar-loading limits per plan/resolution were not independently re-quantified in this pass and remain a related open item.
- **Tooling note:** direct fetch of the primary Help Center article body failed due to a web-fetch tool error during this pass (see §18); the above is based on the article's indexed title/summary plus consistent third-party corroboration, not the full primary text.

## 15. Broker REST API / Trading integration spec (build-your-own-broker reference)

Per the [TradingView REST API for Brokers — Broker Integration Manual](https://www.tradingview.com/broker-api-docs) and its sub-pages:
- **Purpose**: lets any brokerage connect its own backend to the TradingView web platform so its clients can trade Bybit-style, directly inside TradingView's UI.
- **Architecture**: client-server model — requests from the end-user's browser go **directly to the broker's own server**; TradingView's own server is not part of the trading data path except for the `/permissions` endpoint (server-to-server, used to grant a user data access).
- **Documented sections**: Integration overview, Endpoint requirements, Trading integration, Trading tests, Data integration, Data integration tests, Glossary, plus a separate API Reference.
- **Core concepts documented**: Authentication (multiple types supported, including a JWT Bearer Flow where the client forms and signs a JWT, POSTs it as an `assertion` field, and receives a token back), Symbol mapping (matching broker symbols to TradingView symbols via a `/mapping` endpoint), Permissions (restricting/hiding symbols per user), Automated tests (a sandbox test suite brokers must pass before going live).
- **Trading concepts** (from the Concepts sub-page): the Orders tab reflects whatever the broker's `/orders` endpoint returns; placing an order triggers an order-execution lifecycle; editing an order (e.g., changing stopLoss/takeProfit) results in a PUT request to the broker's server with the updated fields.
- **Update cadence requirements** (from the integration FAQ): default 500ms/max 1000ms for quotes and orders; default 500ms/max 1500ms for positions, accountManager, and balances.
- **Environments**: TradingView environment ↔ Broker environment pairs used through the integration lifecycle — Localhost↔Staging (TradingView dev troubleshooting), Staging↔Staging (broker integration development in TradingView's sandbox), Production↔Staging (testing broker-side changes against TradingView production).
- **When market data integration can be skipped**: if price/quote data is sourced by TradingView from elsewhere (e.g., directly from the exchange itself, as may be the case for a listed/native crypto exchange), the broker need not implement the market-data endpoints and only needs `/mapping` for symbol matching.
- This spec is a **useful architectural reference** for CandleViewer's own internal broker abstraction layer (even though CandleViewer is not embedding inside TradingView's own site) — particularly the endpoint shape (`/orders`, `/positions`, `/accountManager`, `/quotes`, `/state`, `/mapping`, `/permissions`) and the update-latency targets (500ms typical, sub-1.5s worst case) as a benchmark for what "real-time enough" trading UI expects.

## 16. Charting Library / Advanced Charts / Lightweight Charts licensing

This is a **critical legal question** for CandleViewer, which is explicitly a private, self-hosted, non-public app.

### TradingView Advanced Charts ("Charting Library")
- This is TradingView's full-featured, embeddable charting widget (with Trading Terminal broker-integration support) offered to third parties as a **free-to-use, but proprietary and non-open-source** library — not distributed via public package registries; obtained via a signed license agreement / GitHub access grant from TradingView after applying.
- Per TradingView's own [Free Charting Library page](https://www.tradingview.com/free-charting-libraries/) and third-party analysis (Grokipedia synthesis, cross-checked against known TradingView Advanced Charts distribution practice):
  - **Free license is intended for public-facing, freely-accessible projects** — i.e., a public website/app that end users can access, generally without a login/paywall gate.
  - **Prohibited under the free license**: purely internal/private tools, hobby/personal projects not publicly released, products that are paywalled or otherwise monetized/commercial, and products that strip/hide TradingView's required branding.
  - **Required if free-licensed**: visible TradingView branding + backlink somewhere in the integration; historically TradingView has also expected a public launch announcement/blog post linking back to them before going live.
  - **No redistribution**: the library's source may not be published/exposed in a public code repository or handed to third parties outside the licensed integrator.
  - **Self-hosting required**: the licensee hosts the library files on their own infrastructure and must supply/connect their own market data feed — TradingView does not provide data through this library.
  - **Commercial/private use requires a separate, negotiated commercial license** directly with TradingView — this is the correct path for a monetized product, or (relevant here) a **private/internal tool not publicly accessible**, since the free tier's terms are oriented around public accessibility, not "no payment."

### Implication for CandleViewer
- **CandleViewer is a private, self-hosted, single-user-plus-a-few-account-managers tool — it is NOT publicly accessible.** Under the terms described above, this profile (private/internal, not publicly released) appears to fall outside what TradingView's **free** Advanced Charts license permits, meaning **the free Advanced Charts / Charting Library license likely cannot be legally used for CandleViewer as currently scoped**, without applying for and obtaining a separate commercial license from TradingView (which would involve direct negotiation, likely cost, and possibly not even being offered for a non-commercial, private, unpublished use case). **This should be treated as a hard legal constraint, not a "probably fine" assumption — do not embed TradingView's Advanced Charts / Charting Library into CandleViewer without written confirmation from TradingView that a private/internal, non-public deployment is permitted under whatever license is actually signed.**

### TradingView Lightweight Charts
- By contrast, TradingView's **Lightweight Charts** library is genuinely **open source under the Apache License 2.0**, and can be freely used — including in private, internal, and commercial contexts — without needing a TradingView license agreement, branding requirements, or public-accessibility constraints, because it is a standard open-source software license, not a proprietary "free tier" grant.
- Lightweight Charts is a much lighter-weight candlestick/line charting library (single-pane, no built-in trading-terminal/order-ticket UI, no built-in DOM/order-flow visualization) compared to the full Advanced Charts / Charting Library product — it would need to be paired with custom-built order-flow visualizations (footprint, DOM heatmap, etc.) rather than TradingView providing those out of the box.

### Practical recommendation for CandleViewer
- Given (a) the private/non-public nature of CandleViewer, and (b) the project's stated need for order-flow visualizations (DeepDOM, footprint/Deep Print, liquidity heatmap) that go well beyond what either TradingView library natively offers anyway, **the safer and more flexible path is to build CandleViewer's charting layer independently** (e.g., on Lightweight Charts as an open-source base for basic OHLC candlestick display, or a fully custom canvas/WebGL renderer for the order-flow-specific views), rather than relying on TradingView's Advanced Charts, which (1) has licensing terms that appear incompatible with a private tool, and (2) does not natively provide the DeepCharts-style order-flow visualizations that are core to this project's requirements anyway.

## 17. Sources

### Added in gap-remediation pass (2026-09-14)
- [What is an order ticket — TradingView (in.tradingview.com mirror)](https://in.tradingview.com/support/solutions/43000784804-what-is-an-order-ticket/)
- [Optimus Futures community — TradingView OCO Orders on Futures Instruments](https://community.optimusfutures.com/t/tradingview-oco-orders-on-futures-instruments/5648)
- [Long position drawing tool — TradingView Help Center](https://www.tradingview.com/support/solutions/43000517002-long-position-drawing-tool/)
- [How to use long and short position drawing tools — TradingView Help Center](https://www.tradingview.com/support/solutions/43000475660-how-to-use-long-and-short-position-drawing-tools/)
- [UI elements — Broker Integration Manual, TradingView](https://www.tradingview.com/broker-api-docs/trading/ui-elements/)
- [Custom fields — Broker Integration Manual, TradingView](https://www.tradingview.com/broker-api-docs/trading/ui-elements/custom-fields/)
- [Tickerly.net — Which TradingView Plan Should I Get? (2026 Guide)](https://tickerly.net/best-tradingview-plan/)
- [FinancialTechWiz — TradingView Pricing 2026: Plans, Costs, and What You Get](https://www.financialtechwiz.com/post/how-much-is-tradingview/)
- [Trailing Stop Order (Perpetual and Futures Trading) — Bybit Help Center](https://www.bybit.com/en/help-center/article/Trailing-Stop-Order-Perpetual-and-Futures-Trading)
- [Types of Orders Available on Bybit — Bybit Help Center](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit)
- [How Deep Backtesting works — TradingView Help Center](https://www.tradingview.com/support/solutions/43000666265-how-deep-backtesting-works/)
- [How much data is available for Deep Backtesting? — TradingView Help Center](https://in.tradingview.com/support/solutions/43000668210-how-much-data-is-available-for-deep-backtesting/)
- [Why are the results of Deep Backtesting not shown on the chart? — TradingView Help Center](https://in.tradingview.com/support/solutions/43000670566-why-are-the-results-of-deep-backtesting-not-shown-on-the-chart/)
- [I'd like to learn more about Deep Backtesting — TradingView Help Center folder](https://www.tradingview.com/support/folders/43000584695-i-d-like-to-learn-more-about-deep-backtesting/)
- [How to export chart data — TradingView Help Center](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/)
- [Pineify — How to Reset Paper Trading TradingView](https://pineify.app/resources/blog/how-to-reset-paper-trading-tradingview)
- [Aron Groups — TradingView Paper Trading Guide](https://arongroups.co/forex-articles/tradingview-paper-trading-guide/)

- [TradingView REST API for Brokers — Broker Integration Manual (Home)](https://www.tradingview.com/broker-api-docs)
- [Integration overview — Broker Integration Manual](https://www.tradingview.com/broker-api-docs/integration-overview)
- [Concepts — Broker Integration Manual, Trading](https://in.tradingview.com/broker-api-docs/trading/concepts)
- [FAQ — Broker Integration Manual](https://tr.tradingview.com/broker-api-docs/faq)
- [How to Get Started With Trading on Bybit From TradingView — Bybit Help Center](https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Trading-on-Bybit-From-TradingView)
- [TradingView x Bybit marketing/overview page](https://www.bybit.com/en/derivative-activity/tradingview)
- [TraderEvolution — TradingView Broker Integration Guide](https://traderevolution.com/learn/tradingview-broker-integration-guide)
- [Interactive Brokers — TradingView: Frequently Asked Questions](https://www.interactivebrokers.com/docs/third-party-integrations/specific-third-party-connection-details/trading-view/trading-view-frequently-asked-questions)
- [What is an order ticket — TradingView Help Center](https://www.tradingview.com/support/solutions/43000784804-what-is-an-order-ticket)
- [Trading basics folder — TradingView Help Center](https://www.tradingview.com/support/folders/43000597927-trading-basics)
- [Order brackets — TradingView Help Center](https://www.tradingview.com/support/solutions/43000754951-order-brackets)
- [Position brackets — TradingView Help Center](https://www.tradingview.com/support/solutions/43000754954-position-brackets)
- [Bracket orders — Advanced Charts / Trading Terminal Documentation](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/trading-concepts/brackets)
- [Alerts separation by type — TradingView Help Center](https://www.tradingview.com/support/solutions/43000696403-alerts-separation-by-type)
- [Introduction to TradingView alerts — Help Center](https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts)
- [Alert name and message size limits — Help Center](https://www.tradingview.com/support/solutions/43000773947-alert-name-and-message-size-limits/)
- [Concepts / Alerts — Pine Script Docs](https://www.tradingview.com/pine-script-docs/concepts/alerts)
- [Alerts FAQ — Pine Script Docs](https://www.tradingview.com/pine-script-docs/faq/alerts)
- [Welcome to Pine Script v6](https://www.tradingview.com/pine-script-docs/welcome)
- [Pine Script Language Reference Manual v6](https://www.tradingview.com/pine-script-reference/v6/)
- [Pine Script Limitations — official docs (referenced via secondary sources)](https://www.tradingview.com/pine-script-docs/en/v5/concepts/Limitations.html)
- [QuantNomad — The Main Limitations of Pine Script on TradingView](https://quantnomad.com/the-main-limitations-of-pine-script-on-tradingview/)
- [Pineify — Pine Script Limitations: What Pine Script Cannot Do](https://pineify.app/pine-script/guides/pine-script-limitations)
- [Strategy properties — TradingView Help Center](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)
- [What is bar magnifier backtesting mode — TradingView Help Center](https://www.tradingview.com/support/solutions/43000669285-what-is-bar-magnifier-backtesting-mode/)
- [TradingView Strategy Tester Backtest Settings Explained (2026 guide, third-party)](https://dev.to/xqliu/tradingview-strategy-tester-backtest-settings-explained-2026-guide-1mka)
- [How to Use TradingView Strategy Tester (third-party guide)](https://chartwisehub.com/tradingview-strategy-tester/)
- [TradingView Strategy Report: How to start — Help Center (RU mirror)](https://ru.tradingview.com/support/solutions/43000764138/)
- [TradingView Strategy Report: How to start — Help Center (India mirror, expanded metrics list)](https://in.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)
- [Bar Replay: how and why to test a strategy in the past — Help Center](https://www.tradingview.com/support/solutions/43000712747-bar-replay-how-and-why-to-test-a-strategy-in-the-past)
- [Pickmytrade — Strategy Tester Walkthrough / Deep Backtesting mention](https://blog.pickmytrade.trade/strategy-tester-walkthrough-tutorial-2025-updated)
- [Pickmytrade — TradingView Strategy Tester + AI (slippage/commission realism)](https://blog.pickmytrade.io/tradingview-strategy-tester-ai-optimize-for-real-world-results)
- [Pineify — TradingView Backtest Report analysis tool (context on CSV export workflow)](https://pineify.app/backtest-report)
- [tv-hub.org — How to Set Up TradingView Alerts (2026), third-party alert-limit tracker](https://www.tv-hub.org/guide/tradingview-alerts-setup)
- [ru.tradingview.com — How to get more active alerts per subscription](https://ru.tradingview.com/support/solutions/43000690941)
- [TradingView Blog — It's doubled now: more alerts for each plan! (2023)](https://www.tradingview.com/blog/en/more-alerts-for-each-plan-31701/)
- [supa.is — TradingView Plans 2026: Essential vs Plus vs Premium (third-party plan comparison)](https://supa.is/article/tradingview-essential-vs-plus-vs-premium-which-plan-2026)
- [Pickmytrade blog — TradingView Plan You Need For Webhook Automated Trading (third-party)](https://blog.pickmytrade.trade/tradingview-plan-you-need-for-webhook-automated-trading)
- [ClearEdge Trading — TradingView Alert Limits: Complete Guide (third-party)](https://clearedge.trading/post/tradingview-alert-limits-plan-restrictions)
- [LuxAlgo docs — TradingView Alerts overview (third-party)](https://docs.luxalgo.com/docs/getting-started/tradingview-alerts)
- [crosstrade.io — Pine Script webhook alerts guide (third-party automation vendor)](https://crosstrade.io/learn/pine-script/webhook-alerts)
- [TradingView Free Charting Libraries page](https://www.tradingview.com/free-charting-libraries/)
- [Grokipedia — TradingView Advanced Charts (secondary synthesis of licensing terms)](https://grokipedia.com/page/TradingView_Advanced_Charts)
- [TradingView Shortcuts and tips folder — Help Center](https://www.tradingview.com/support/folders/43000561752-hotkeys-and-tips/)
- [ChartWiseHub — TradingView Cheat Sheet (third-party shortcuts reference)](https://chartwisehub.com/tradingview-cheat-sheet/)
- [TutorialTactic — 71 TradingView Keyboard Shortcuts (third-party PDF/reference)](https://tutorialtactic.com/blog/tradingview-shortcuts/)

### Added in second gap-remediation pass (2026-09-14)
- [How do I get level 2 data? — TradingView Help Center](https://www.tradingview.com/support/solutions/43000480004-how-do-i-get-level-2-data) — official Level-2/DOM broker list including Bybit by name
- [Depth of market (DOM): what it is and how traders can use it — TradingView Help Center](https://www.tradingview.com/support/solutions/43000516459-depth-of-market-dom-what-it-is-and-how-traders-can-use-it) (re-fetched full_content) — ladder trading controls (click/Ctrl-click/right-click, drag-to-modify, Flatten/Reverse, cancel-all)
- [Level 2 data — TradingView Help Center](https://www.tradingview.com/support/solutions/43000754967-level-2-data)
- [Depth of Market | Advanced Charts Documentation](https://www.tradingview.com/charting-library-docs/latest/trading_terminal/depth-of-market) — confirms DOM widget depth is datafeed-driven, no fixed TradingView-imposed level count
- [TradingView Pine Screener: key features and requirements — Help Center](https://www.tradingview.com/support/solutions/43000742436-tradingview-pine-screener-key-features-and-requirements) (fetched full_content) — source/indicator/scan model, mixed-asset-class scanning
- [How to scan watchlist or flagged list? — TradingView Help Center](https://www.tradingview.com/support/solutions/43000724549-how-to-scan-watchlist-or-flagged-list)
- [Pineify — How to Use Pine Screener](https://pineify.app/custom-screener/how-to-use-pine-screener) — third-party-only source for the "25,000 symbols on Premium" figure, unverified officially
- [Types of Orders Available on Bybit — Bybit Help Center](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit) (re-fetched, full order-type taxonomy)
- [How to Set Up and Modify Your TP/SL (Perpetual and Futures Contracts) — Bybit Help Center](https://www.bybit.com/en/help-center/article/How-to-Set-Up-and-Modify-TP-SL-Perpetual-Futures-Contracts)
- [Introduction to Take Profit and Stop Loss (Perpetual and Futures Contracts) — Bybit Help Center](https://www.bybit.com/en/help-center/article/Introduction-to-Take-Profit-Stop-Loss-Perpetual-Futures-Contracts)
- [Take Profit and Stop Loss (Spot Trading) — Bybit Help Center](https://www.bybit.com/en/help-center/article/Introduction-to-Take-Profit-and-Stop-Loss-Spot-Trading)
- [FAQ — Spot Trading — Bybit Help Center](https://www.bybit.com/en/help-center/article/FAQ-Spot-Trading)
- [Quick Trading Features — Bybit Help Center](https://www.bybit.com/en/help-center/article/Quick-trading-features) — One-Way vs. Hedge position mode mechanics
- [FAQ — Trading Chart — Bybit Help Center](https://www.bybit.com/en/help-center/article/Bybit-Trading-Chart-FAQ)
- https://www.tradingview.com/pricing (re-fetched full_content) — official Watchlist row-group gated features (Flagged symbol colors 1/7/7/7/7, Import/export, Custom columns and sorting)

## 18. Open questions

The following items could not be fully confirmed from primary/official sources within this research pass and should be verified directly (e.g., by creating a live TradingView account at each plan tier, and/or by directly testing the Bybit↔TradingView integration) before being relied upon for architecture decisions:

1. **[Partially resolved this pass]** Exact per-plan alert quotas today. Two independent 2026 third-party sources ([Tickerly.net](https://tickerly.net/best-tradingview-plan/), [FinancialTechWiz](https://www.financialtechwiz.com/post/how-much-is-tradingview/)) now agree: Essential = 20/20, Plus = 100/100, Premium = 400/400 (price/technical). Still **not confirmed against TradingView's own current pricing/GoPro page directly** — an attempted direct fetch of tradingview.com/pricing failed due to a tool error in this pass and should be retried.
2. **[Resolved this pass, pending primary re-confirmation]** Exact alert expiration/duration rules per plan: per the same two 2026 sources, Essential and Plus alerts expire after ~2 months; Premium alerts are open-ended/never expire. Not yet independently verified against TradingView's own Help Center article body.
3. **[Resolved this pass, narrower point remains]** Bybit-specific DOM / Level 2 availability through the TradingView↔Bybit integration: **confirmed — Bybit is explicitly named on TradingView's official Level-2-data broker list** ([How do I get level 2 data?](https://www.tradingview.com/support/solutions/43000480004-how-do-i-get-level-2-data)). The DOM ladder is available for Bybit-connected accounts. The **exact depth (number of price levels/rows)** delivered is still not stated in any official source and remains open, pending live testing.
4. **[Narrowed, not closed]** Exact set of Bybit-native order types surfaced 1:1 through TradingView's own first-party order ticket: confirmed that Bybit natively supports Market/Limit/Conditional/TP/SL/Trailing-Stop/Iceberg/Post-Only/TWAP/Scaled/Chase-Limit/RPI (basic + advanced order types, Section 2.1), plus OCO on Spot and Reduce-Only/Close-On-Trigger/POV on Derivatives, and that TP/SL supports both Entire-Position and Partial-Position scope modes (Section 2.2). Not confirmed whether TradingView's own generic broker-integration order ticket (as opposed to third-party webhook/API tools like AutoView) exposes all of these identically for a Bybit-connected account — needs live testing. This remains the correct scoping boundary: CandleViewer should build directly against Bybit's own API surface (now fully itemized in Section 2.1–2.3) rather than assume TradingView UI parity.
5. **[Resolved this pass]** Whether the Account Manager panel has a literal "Notifications" tab: **confirmed yes** — TradingView's own [UI elements — Broker Integration Manual](https://www.tradingview.com/broker-api-docs/trading/ui-elements/) names "Notifications" as one of the Account Manager's possible tabs, alongside Positions/Orders/Order History/Account Info. Caveat: there is no dedicated `/notifications` REST endpoint backing it (unlike `/orders`/`/positions`) — it rides on the general state/streaming push mechanism.
6. **[Resolved this pass]** Full Pine Screener feature scope: confirmed via direct official Help Center fetch (Section 10.1) — source/indicator/scan model, mixed-asset-class scanning, rescan triggers. The one still-unconfirmed sub-point is the third-party-only "25,000 symbols on Premium" ceiling figure, which lacks an official citation.
7. **[Partially resolved this pass]** Exact CSV data-export limits: TradingView's own Help Center article title ["How to export chart data"](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/) was located, and corroborating guides indicate there is **no separate fixed row cap** — export captures whatever bars are currently loaded on the chart, so the practical limit is governed by chart bar-loading limits (plan/resolution-dependent), not a CSV-specific number. The article's full primary text was not independently re-fetched (tool error) to confirm this wording verbatim — flagged for retry.
8. **[Resolved this pass]** Whether "drag orders/TP/SL lines directly on the chart" and the built-in Risk/Reward drawing tool have a single authoritative TradingView Help Center citation: the **Risk/Reward (Long/Short Position) drawing tool is now confirmed** via two TradingView Help Center articles (see §3, §17). The narrower behavior of **dragging an existing live order's line to modify a working order** (as distinct from the planning-only drawing tool) still lacks a single dedicated Help Center citation — remains open.
9. **[Resolved this pass]** Watchlist folder deep-dive (sections/flags/colors/import mechanics): confirmed via the official pricing grid's Watchlist row group and the Pine Screener docs (Section 11) — Flagged symbol colors is an explicit gated row (1/7/7/7/7 across Basic→Ultimate), Import/export and Custom columns and sorting are separate gated rows, and colored/custom watchlists are directly confirmed as selectable scan sources in both the Pine Screener and the built-in screener. The one still-open sub-point is the exact numeric cap on **number of watchlists** per paid tier (doc 01 Open Q #9) — TradingView's own page genuinely does not publish this number.
10. **Whether TradingView would grant a commercial Advanced Charts / Charting Library license for a genuinely private, non-public, unmonetized internal tool like CandleViewer at all** — the free tier's terms clearly exclude this use case, but it is unconfirmed whether TradingView's *paid/commercial* licensing track even accepts non-public/internal-only deployments, or is oriented solely toward products TradingView expects to eventually be public-facing/monetized. This should be resolved via direct contact with TradingView's licensing team before any decision to embed Advanced Charts, though given the project's build-your-own-order-flow-visualization requirements, building independently (Lightweight Charts + custom order-flow layer) is likely the right call regardless of licensing outcome. **Not addressed in this pass — still open** (requires direct vendor contact, not web research).
11. **[Resolved this pass]** Deep Backtesting's exact plan-gating and bar/trade caps: **now confirmed directly against TradingView's own Help Center** (see §9 and §17) — Premium plan and above; cap of 2,000,000 bars / 1,000,000 trades per calculation. The original figures were accurate; confidence upgraded from third-party-only to TradingView-primary-sourced.
12. **Bybit's TradingView broker session 24-hour re-auth restriction** — confirmed by Bybit's own help article, but whether this materially affects a CandleViewer-style non-TradingView-hosted integration (it should not, since CandleViewer would talk to Bybit's exchange API directly, not via TradingView's broker-session mechanism) should be explicitly noted as **not applicable** to CandleViewer's own Bybit connection, which this report recommends be built directly against Bybit's REST/WebSocket API rather than through TradingView's broker integration layer at all.
13. **[New]** Whether OCO is exposed as its own labeled order-type option anywhere in TradingView's UI (vs. purely via the bracket/TP-SL mechanism) was not found in any primary source — treated as resolved-by-equivalence (bracket = functional OCO) rather than a literal UI label match. Low-priority to re-verify.
14. **[New — tooling limitation, not a content gap]** Several direct-fetch attempts against tradingview.com pages (pricing page, export-data article, UI-elements page) failed in this pass due to a web-fetch tool error (`output_config.effort` incompatibility), forcing reliance on search-engine-summarized excerpts rather than full primary-source article bodies for a few claims flagged above. These should be re-fetched directly once the tooling issue is resolved to upgrade several "partially resolved" items above to fully primary-confirmed.
