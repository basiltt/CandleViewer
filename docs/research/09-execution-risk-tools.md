# Fast execution, custom rule-based stops & risk automation — best practice inventory

Research date: 2026-09-13. Scope: crypto/futures execution & risk-automation UX across professional order-flow platforms, crypto-native terminals/bots, and open-source algo frameworks, to define CandleViewer's trading feature set (Bybit-first, demo + live).

---

## 1. Order entry UX patterns

| Pattern | Description | Seen in |
|---|---|---|
| DOM/ladder click trading | Click a price cell on the vertical price ladder to place buy/sell/stop orders; drag working orders to reprice; click order to cancel | Bookmap, Jigsaw daytradr, Sierra Chart Trade DOM, Quantower DOM Trader |
| Chart click trading | Ctrl/Shift + click on the chart price axis to buy/sell, with modifier keys distinguishing market/limit/stop | Sierra Chart ("Extend Chart DOM Across Entire Chart"), Bookmap (Shift+click = stop) |
| Hotkeys | Configurable keybindings for buy/sell market, buy bid/sell ask, flatten, reverse, cancel-all, quantity presets | Sierra Chart (`Global Settings → Customize Keyboard Shortcuts`), Bookmap (`Settings → Configure shortcuts`) |
| One-click trading | A toggle/lock that must be explicitly enabled before DOM/chart clicks fire live orders (safety gate) | Bookmap (off by default, lock icon in Trading Control Panel), Bybit web/app "one-click" mode |
| Quantity presets | Preset order-size buttons (e.g., 25%/50%/100% of max, or fixed contract counts) settable in a config panel | Bookmap Trading Configuration Panel, most crypto terminals (Tealstreet, Altrady) |
| Risk-based sizing | Position size computed from % of equity, fixed $ risk, or ATR-multiple stop distance rather than fixed quantity | Common pattern in retail futures platforms (NinjaTrader/Sierra Chart plugins) and DIY crypto bots; not natively built into Bybit UI — must be app-side |
| Order templates | Saved combinations of order type + bracket (SL/TP) + size that can be re-applied instantly | Jigsaw daytradr ("define and store custom order entry strategies"), Quantower Order Placing Strategies |

**Design implication for CandleViewer:** implement a client-side "arm" toggle (one-click gate), configurable hotkeys, and an order-entry panel that supports DOM-ladder clicks and chart-click trading, with quantity computed either as fixed size or risk-based (% equity / $ risk / ATR-stop-distance) — since Bybit itself does not expose risk-based sizing, this must be computed client-side before submitting the order.

---

## 2. Scale-in/out, chase, and conditional order mechanics

| Mechanism | Description | Reference implementation |
|---|---|---|
| Scaled orders (ladder distribution) | Split a total order size into N orders across a price range; distribution can be equal, linear (increasing/decreasing size toward one end), or geometric | Insilico Terminal, Tealstreet ("scaled order system... multiple staggered orders across a price range"), Altrady ladder orders, Quantower "Time-split" placing strategy |
| Chase / pegged limit order | Client-side or exchange-side logic that repeatedly cancels/replaces a limit order to keep it pegged near the best bid/ask (to improve fill probability without crossing the spread) | Bybit "Chase Limit Order" (per Bybit help center summaries: "adjusts your limit order price closer to the market in small increments"); Insilico Terminal "Limit Chase"; Tealstreet "Chaser" |
| TWAP | Breaks a large order into equal-sized slices executed over a fixed time window to approximate the time-weighted average price | Bybit trading bots include TWAP-style execution (per Bybit bot tutorials); Insilico Terminal offers TWAP explicitly |
| Iceberg | Displays only a small visible quantity while holding a larger hidden reserve, refreshing the visible slice as it fills | Referenced generically across execution-algo literature; Quantower explicitly lists "Iceberg" as an order-placing strategy; **Bybit has a dedicated, standalone "Iceberg Order" ticket** (confirmed via primary source, see §6) *(corrected: earlier draft treated this as an unverified "institutional flow" generality — it is a documented, named, user-facing order type)* |
| Market-if-touched (MIT) / Limit-if-touched (LIT) | Conditional order that becomes a market/limit order only once a trigger price is touched, without reserving margin until triggered | Quantower "Limit If Touched / Market If Touched"; conceptually equivalent to Bybit's "Conditional Order" (funds not occupied until trigger fires) |
| OCO / OTOCO brackets | One-Cancels-Other (a stop and a limit, whichever fills cancels the other) or One-Triggers-OCO (entry order triggers a paired SL+TP OCO pair) | TradingView Broker Integration Manual explicitly supports bracket orders (SL/TP OCO pairs attached to entry); 3Commas SmartTrade uses OCO-style TP/SL; Bybit offers OCO **only as a spot/spot-margin UI feature and explicitly states it is "Not Available for API Usage"** — API users must emulate OCO client-side ([Bybit Help Center — One-Cancels-the-Other (OCO) Orders](https://www.bybit.com/en/help-center/article/One-Cancels-the-Other-OCO-Orders)) *(corrected: earlier draft only said Bybit "attaches TP/SL brackets directly to a position," which understated that Bybit does have a genuine UI-level OCO concept for spot — it's the API that lacks it)* |
| Break-even automation | Automatically moves the stop-loss to the entry price (or entry + fees) once price has moved a configured distance in favor (e.g., 1R) | Common DIY rule in 3Commas/Cornix advanced settings and Freqtrade `custom_stoploss`; not a native Bybit order type — must be emulated by a bot polling position P&L and re-submitting the SL order |
| Partial TP ladders | Multiple take-profit levels each closing a percentage of the position (e.g., 25% at 1R, 25% at 2R, 50% at 3R) | 3Commas DCA bot multi-target TP; Cornix "multi-level order execution... multiple take-profit targets"; Altrady multi-exit |
| Trailing stops | See §3 below | — |
| Time stops | Force-close a position after a maximum holding duration regardless of P&L | Hummingbot Triple Barrier `time_limit` parameter; Freqtrade can approximate via custom logic |
| Max loss per day / lockout | Circuit breaker that halts new order placement (or forces flatten) once daily loss or a losing-trade streak threshold is hit | Freqtrade "Protections" (`StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`) is the clearest reference implementation of this pattern |
| Flatten / reverse / cancel-all panic buttons | Single-click actions: close all positions, close-and-reverse, or cancel all working orders | Sierra Chart Trade Menu (Flatten, Reverse hotkeys); Jigsaw daytradr auto-tracks and can clear stale orders |

---

## 3. Trailing stop variants

| Variant | Trigger logic | Reference |
|---|---|---|
| Fixed-offset trailing stop | Stop trails price by a constant absolute price distance | Bybit native trailing stop (percentage or amount) |
| Percentage trailing stop | Stop trails by a % of price | Bybit native trailing stop; 3Commas Trailing Take Profit ("trailing deviation" %) |
| ATR-based trailing stop | Stop distance recalculated each bar/tick as a multiple of Average True Range, adapting to volatility | Not native to Bybit or 3Commas; implemented via `custom_stoploss` in Freqtrade or custom scripts — a strong candidate for CandleViewer's rule engine |
| Structure-based (swing low/high) trailing stop | Stop moves to the most recent confirmed swing low (long) / swing high (short), i.e., "chandelier"-style logic | Not offered by any reviewed native exchange/bot UI — a DIY rule pattern (candidate CandleViewer differentiator, ties into order-flow / footprint analysis) |
| MA-based trailing stop | Stop trails a moving average (e.g., 20 EMA) | Common discretionary-trader rule, implementable only via custom rule engine (no native product reference found) |
| Time-based tightening | Stop distance progressively tightens the longer a trade is open (independent of price), forcing exit if the market doesn't move as expected within a time budget | Not found as a native product feature in this research pass — flagged as open question / custom design |
| Activation-delta trailing stop (Hummingbot Triple Barrier) | Trailing only "arms" once price has moved favorably by `trailing_stop_activation_price_delta`; then trails by `trailing_stop_trailing_delta` | Hummingbot `PositionExecutor` — a clean, directly reusable config schema (see §7) |
| DCA-bot trailing TP | Instead of closing at a fixed take-profit price, waits for price to reverse by a configured deviation % after reaching TP, then closes via market order | 3Commas ("How Take Profit Works... Trailing feature explained") |

---

## 4. Rule-based automation engines (ECA / IFTTT style)

| Product | Model | Condition vocabulary | Action vocabulary | Notes |
|---|---|---|---|---|
| Coinrule | Visual no-code IF/THEN builder with AND/OR chaining | Price % move over a time window, technical indicators (RSI, volume vs. moving average), time-based triggers | Buy/sell, set TP/SL, set trailing stop, chain multiple actions | Includes templates (DCA, grid, dip-buying) and backtesting against historical data; every rule execution is logged (help.coinrule.com/articles/247956-build-a-rule) |
| Kryll (KryllOS) | Visual, no-code, drag-and-drop "block" strategy editor with 30+ documented block types (indicator, price, time, logic, order/action, notification) chained on a canvas; supports `IF`/`AND`/`OR`/`ELSE` conditional branching and user-defined **variables** for reusable strategy state | Indicator blocks (RSI/MA/MACD/etc.), price/candle blocks, time & calendar blocks (recurring/scheduled DCA-style entries), portfolio/balance blocks | Buy/sell/order blocks, **Take Profit**, **Stop Loss**, and **Trailing Stop** blocks (trailing distance set as %, arms after entry and ratchets the exit level as price moves favorably — same mechanic class as Bybit's native trailing stop, see §3), notification blocks (Telegram/email) | Kryll additionally offers **KryllOS**, a self-hosted/on-premise version of the strategy engine for running strategies outside Kryll's own cloud infrastructure. Full block reference: ["The Blocks Bible" — Kryll Strategy Editor Blocks](https://blog.kryll.io/the-blocks-bible/); trailing/TP/SL mechanics: ["The secrets of Take Profit, Stop Loss & Trailing Stop with Kryll.io"](https://blog.kryll.io/the-secrets-of-take-profit-stop-loss-trailing-stop-with-kryll-io/) *(corrected: earlier draft deprioritized Kryll entirely as an "open question"; it is now covered with primary blog/docs sources — a deeper pass against Kryll's own in-app help center is still recommended if exact per-block parameter ranges are needed for 1:1 DSL parity)* |
| Cornix | Signal-parser + rule engine bound to Telegram/TradingView alerts rather than a general condition builder | Structured signal fields (entry, multiple TP targets, SL) parsed from text; TradingView/Pine alerts | Multi-level TP execution, SL placement, trailing SL, dynamic TP splitting, position-size/exposure caps, per-pair/portfolio trade limits | Signals-first design: the "IF" is an inbound message rather than a live market condition (help.cornix.io) |
| 3Commas SmartTrade / DCA bot | Configuration-driven (safety-order ladder + TP/trailing), not a general rule DSL | Price deviation steps (safety order triggers), TradingView webhook signals | Averaging safety orders, trailing TP, stop loss, TradingView-bot bridge | See §5 for safety-order mechanics |
| Freqtrade | Python strategy class with declarative config (`minimal_roi`, `stoploss`, `trailing_stop`) plus imperative callbacks (`custom_stoploss`, `confirm_trade_exit`, etc.) and a declarative "Protections" system | Any Python-computable condition (indicators via `populate_indicators`), time-in-trade, drawdown, stoploss frequency | Custom stoploss return value (negative float distance), ROI-table exits, ProtectionsSystem-level trading halts | Most expressive and best-documented of the reviewed tools — closest analog to what CandleViewer's rule engine should support (docs.freqtrade.io) |
| Hummingbot Strategy V2 | Executor + Controller architecture; each Executor (Position Executor, Grid Executor, etc.) is configured with a `TripleBarrierConf` | Declarative stop_loss / take_profit / time_limit / trailing deltas per executor | Executor manages its own order lifecycle | Cleanest machine-readable schema found (see §7 sketch) |

**Common pattern across all of the above:** every engine separates (a) a **condition/trigger layer** (price, indicator, signal, time, drawdown) from (b) an **action layer** (place/modify/cancel order, resize position, halt trading), and most persist an execution log per rule firing for audit/journaling. CandleViewer's rule engine should adopt the same ECA (event-condition-action) separation.

---

## 5. DCA / safety-order & martingale mechanics (3Commas / Cornix / Bybit bots)

- **Safety orders (3Commas DCA bot):** additional buy (long) / sell (short) orders placed as price moves against the initial entry, each configurable with its own volume, price-step, and deviation, to average the position's entry price down (or up). **Concrete limits (confirmed):** the bot config sets a "Max Safety Orders" count for the whole deal, but a separate "Limit avg. orders placed on exchange" setting commonly caps *simultaneously active* safety orders on the exchange order book at around **10 active at once**, even when the total configured max is higher — remaining orders are queued and placed progressively as earlier ones fill. Max safety orders can also be adjusted on an already-open deal via the API: `POST /ver1/deals/:deal_id/update_max_safety_orders?max_safety_orders=X`. ([3Commas Help Center — DCA Bot: Interface and Main Settings](https://help.3commas.io/en/articles/3108940-dca-bot-interface-and-main-settings); [3Commas Help Center — Understanding the DCA Bot Summary box](https://help.3commas.io/en/articles/16666593-understanding-the-dca-bot-summary-box); [3Commas API — Modify maximum safety orders count](https://developers.3commas.io/dca-bot/deals/modify-maximum-safety-orders-count/)) *(corrected: earlier draft described safety orders only qualitatively without citing the ~10-active-order exchange cap or the API endpoint for adjusting the limit)*
- **Trailing Take Profit (3Commas):** once the take-profit % is reached, the bot does not immediately close — it waits for a configured trailing deviation reversal, then exits via market order. Recommended only on liquid pairs to avoid slippage. (help.3commas.io/en/articles/3108981)
- **Trailing Take-Profit (Cornix) — concrete mechanics (confirmed):** configured under Advanced Settings → Take-Profits → "Leveraged Trailing" → "Personal," with a user-set trailing **deviation percent** (e.g. 2%). The bot tracks the post-TP peak price and executes a market sell once price retraces by the deviation % from that peak. **Leverage adjustment:** Cornix divides the configured trailing % by the leverage multiplier to keep the effective trailing distance sane — e.g., a 2% trailing setting at 5x leverage effectively trails at **0.4%** from the peak. By default trailing activates at every TP level reached; an "only use for the last target" toggle restricts it to the final TP only. If a later TP target triggers while a trailing TP is already active, Cornix merges the position amounts into the existing trail rather than starting a second one. ([Cornix Help Center — Trailing Take-Profit](https://help.cornix.io/en/articles/5814862-trailing-take-profit); [Cornix Help Center — Signals Bot Advanced Settings: Take-Profit Strategy](https://help.cornix.io/en/articles/8976604-signals-bot-advanced-settings-take-profit-strategy)) *(new: earlier draft did not cite Cornix's exact trailing-deviation/leverage-division mechanics with numbers)*
- **Martingale bot (Bybit):** doubles/increases position size after a losing step to average down/recover on rebound; explicitly flagged by Bybit as high risk. Parameters: initial order size, multiplier, max steps, stop loss. (bybit.com/en/learn/bybit-trading-bot)
- **Grid bot (Bybit):** places buy/sell limit orders at fixed intervals across a price range; Spot Grid for range-bound markets, Futures Grid adds leverage + long/short/neutral modes. Official examples show configurations with as few as 5 grid levels; per-pair/UI-version grid-count ceilings and exact leverage caps are **not published as a single fixed universal number** in Bybit's own docs reviewed this pass — third-party/self-hosted implementations (e.g., the open-source `Cikle/bybit-dca-trading-bot`) commonly expose `GRID_LEVELS` (e.g., 20) and `LEVERAGE` (e.g., 10x) as free-form config values bounded only by what the account/contract allows (up to Bybit's general leverage ceiling, which reaches 100x on some pairs). ([Bybit Help Center — Introduction to Spot Grid Bot](https://www.bybit.com/en/help-center/article/Introduction-to-Spot-Grid-Bot); [Bybit Grid Trading Bot Help Center section](https://help.bybit.com/hc/en-us/sections/7880580863385-Grid-Trading-Bot); [Cikle/bybit-dca-trading-bot — GitHub](https://github.com/Cikle/bybit-dca-trading-bot)) *(corrected: earlier draft summarized grid/DCA bots without noting that Bybit does not publish one canonical max-grid-count number — this gap could not be fully closed and is carried to Open Questions)*
- **Combo bot (Bybit, Futures):** auto-rebalancing portfolio of multiple long/short positions per user-defined allocation targets and rebalance thresholds.
- **Cornix signal execution:** reads structured signals from Telegram/TradingView, places entries (market/limit), multiple TP targets, and SL exactly as specified; supports trailing SL, dynamic TP splitting, auto scale-in/out, and max-exposure caps, across 10+ exchanges from one dashboard, with trade-only (non-withdrawal) API key permissions. (cornix.io; help.cornix.io/en/collections/8561509-signals)

---

## 6. Bybit native vs. emulated order/stop types

| Feature | Native on Bybit? | Notes / emulation approach |
|---|---|---|
| Market order | Native | — |
| Limit order (incl. Post-Only) | Native | — |
| Conditional order (trigger → market/limit) | Native | Confirmed via `/v5/order/create`: standard `orderType` (`Limit`/`Market`) plus `triggerPrice`, `triggerBy` (`LastPrice`/`MarkPrice`/`IndexPrice`), and `triggerDirection`; funds not reserved until trigger fires ([Bybit V5 API — Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order); bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit) |
| Take Profit / Stop Loss (position-attached bracket) | Native | Set/amended via the dedicated `/v5/position/trading-stop` endpoint, not `/order/create`; requires `positionIdx` (0 = one-way, 1 = hedge-long, 2 = hedge-short — see Position mode row below); supports `takeProfit`, `stopLoss`, `trailingStop`, and `tpslMode` (`Full` vs `Partial`) ([Bybit V5 API — Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)). On spot, assets are locked immediately once TP/SL is set (unlike a bare conditional order) |
| Trailing stop | Native | Bybit computes and manages the trailing distance server-side once armed (also set via `/v5/position/trading-stop`, `trailingStop` field) — lower latency/more reliable than client-side emulation |
| Chase (limit) order | Native — confirmed as part of Bybit's **Iceberg Order** ticket (see Iceberg row below), which exposes four sub-order placement algorithms: **Chase Limit (Taker)**, **Chase Limit (maker, dynamic)**, **Chase Limit (Offset)** (fixed distance from best price), and **Fixed Price** | *(corrected: earlier draft treated Chase Limit mechanics as unverified help-center/community synthesis with an explicit open question; a direct Bybit Help Center article ("Iceberg Order") now confirms these four placement modes as a documented sub-feature of the Iceberg order type, not a separate standalone order)* — availability may still vary by product/account tier; verify current app version before implementation |
| OCO (as a bare pair, not bracket) | **UI-only; explicitly NOT available via API** | Bybit's own Help Center states: *"Not Available for API Usage: API users won't have access to OCO orders, as they can design strategies to replicate similar functionality."* ([Bybit Help Center — One-Cancels-the-Other (OCO) Orders](https://www.bybit.com/en/help-center/article/One-Cancels-the-Other-OCO-Orders)). Since CandleViewer is API-driven, it must emulate true independent OCO (race two orders, cancel the loser on fill notification via WS/REST) regardless of what the consumer web UI offers *(corrected: earlier draft was uncertain whether OCO existed at all on Bybit; it does exist in the UI for spot/spot-margin, but is confirmed unavailable to API integrations like CandleViewer)* |
| Scaled/laddered order (multiple orders across a price range) | Not native as a single order primitive | Must be emulated client-side: submit N individual limit orders per a configured distribution |
| TWAP | **Not a native REST `orderType`** — confirmed no dedicated TWAP order type exists on `/v5/order/create`; only available as an algo/bot-suite product in the UI | Must emulate via client-side chunking: repeated `/v5/order/create` calls at timed intervals ([Bybit V5 API docs](https://bybit-exchange.github.io/docs/v5/intro); DeepWiki bybit-exchange/api-usage-examples order management) *(corrected: earlier draft flagged this as an open question needing direct API verification — now confirmed: no native TWAP order-type primitive)* |
| Iceberg | **Native — confirmed standalone order type**, "Iceberg Order," documented in Bybit's Help Center for both spot and derivatives ([Bybit Help Center — Iceberg Order](https://www.bybit.com/en/help-center/article/Iceberg-Order); [Bybit Learn — How to use iceberg orders](https://www.bybit.com/en/learn/bybit-guide/how-to-use-iceberg-orders)) | Configurable: total quantity/value, split by qty-per-suborder or total suborder count, upper/lower price limits, and one of four placement algorithms (Chase Limit Taker, Chase Limit maker, Chase Limit Offset, Fixed Price) — only one visible suborder rests on the book at a time, refreshed automatically as each fills, until the full size completes or is cancelled. *(corrected: earlier draft said this was "not documented as a consumer order-ticket feature" and flagged it for API-doc verification — a direct Bybit Help Center article confirms it is a real, named, standalone order-ticket feature; exact REST field names for `orderType`/display-qty were not confirmed as a single canonical spec across all market categories, so implementers should still check the live `/v5/order/create` parameter reference for the current field name before coding)* **Re-verified this pass against the live `/v5/order/create` field reference (pybit `_v5_trade.py` wrapper, `bybit-exchange/skills` derivatives module, and third-party `bybit-api`/ccxt client source):** the documented `orderType` enum on `/v5/order/create` is only `Market`/`Limit` — no `orderType=Iceberg` value and no `displayQty`/hidden-size field appear anywhere in the current parameter surface (`category`, `symbol`, `side`, `orderType`, `qty`, `price`, `timeInForce`, `orderLinkId`, `triggerPrice`, `takeProfit`, `stopLoss`, `tpslMode`, `reduceOnly`, `positionIdx`, `marketUnit`, `rpiTakerAccess`, etc.). This means Bybit's consumer-UI "Iceberg Order" ticket is very likely **client-side order-slicing built by Bybit's own web/app frontend on top of ordinary repeated `Limit`/`Market` calls (with `orderLinkId`-tracked sub-orders), not a distinct exchange-native order primitive exposed over the public REST API** — i.e., functionally it may already be exactly what §6's "emulated" column describes CandleViewer building itself. **Action item / still open:** no Bybit V5 API reference page (`bybit-exchange.github.io/docs/v5/order/*`) was found in this pass documenting an iceberg-specific endpoint or field, so CandleViewer should plan to build iceberg slicing as client-side emulation (per the Chase-Limit/Fixed-Price sub-order logic in the Help Center article) rather than searching for a native passthrough field. |
| Break-even automation ("move SL to BE after 1R") | Not native | Must emulate: poll position P&L / price, then submit an amend to the existing SL trigger price |
| ATR-based / structure-based / MA-based trailing stop | Not native (Bybit trailing stop is fixed-% or fixed-amount only) | Fully client-side/emulated: CandleViewer's own bot process must compute the dynamic stop level bar-by-bar and re-submit stop-order amendments |
| Time stop / max-loss-per-day lockout | Not native | Fully client-side: application-level circuit breaker that halts new order submission and/or flattens positions |
| Position mode (One-Way vs. Hedge) | Native | **Confirmed mechanics:** controlled by the `positionIdx` field on every order/position-management call. `positionIdx=0` = One-Way mode (single net position per symbol, long or short). Hedge Mode uses `positionIdx=1` for the long side and `positionIdx=2` for the short side of the same symbol simultaneously. Callers should query `/v5/position/list` to confirm the account's current mode/valid `positionIdx` values before submitting orders rather than assuming. TP/SL attachment via `/v5/position/trading-stop` requires the matching `positionIdx` — in Hedge Mode, TP/SL must be set per-side (long and short brackets are independent); in One-Way Mode there is only one bracket per symbol. ([Bybit Help Center — Difference Between Position Modes](https://www.bybit.com/en/help-center/article/Difference-Between-Position-Modes-One-Way-Mode-and-Hedge-Mode); [Bybit V5 API — Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)) *(new: earlier draft only referenced this generically; mechanics now confirmed against primary API docs)* |
| Maintenance Margin Ratio (MMR) / liquidation | Native, exchange-computed | Bybit uses a **tiered Risk Limit system per contract**: as position (notional) value increases, it crosses into higher tiers that carry a higher Maintenance Margin Rate and a lower maximum allowed leverage; margin owed is calculated cumulatively across every tier the position spans (not just the top tier). Exact MMR%/leverage-cap numbers are pair-specific and are periodically revised by Bybit (e.g., an announced USDT-margin tier update effective 2026-05-13), so CandleViewer's risk engine should fetch the live tier table per-symbol via the risk-limit API/UI rather than hard-coding values. ([Bybit Help Center — Risk Limit (Perpetual and Expiry Contracts)](https://www.bybit.com/en/help-center/article/Risk-Limit-Perpetual-and-Expiry-Contracts); [Bybit Announcement — USDT margin tiers update, 2026-05-13](https://announcements.bybit.com/en/article/usdt-margin-tiers-update-on-may-13-2026-blt8ba149984d899879/)) Laddered/partial liquidation is used in some cases to avoid full-position liquidation |
| Auto-Deleveraging (ADL) | Native, last-resort risk mechanism | Triggered when the insurance fund can't cover a counterparty's liquidation loss. **Ranking formula (confirmed):** positions are ranked by a combination of **unrealized PnL % × effective leverage** — the more profitable AND the more highly leveraged a position is, the higher its priority for forced deleveraging. Bybit surfaces this as a **5-bar/light ADL indicator** on each open position (more bars lit = higher risk of being selected); deleveraging executes at the counterparty's bankruptcy price, not the live market price, which can cap a winning trade's realized profit earlier than the trader would like. Mitigation levers: lower effective leverage, take partial profits to reduce PnL%/size, monitor the indicator during high volatility. ([Bybit Help Center — Auto-Deleveraging (ADL) Mechanism](https://www.bybit.com/en/help-center/article/Auto-Deleveraging-ADL)) *(corrected: earlier draft referenced ADL only generically as "ranks and deleverages the highest-leverage, highest-profit opposite-side positions first" without the concrete PnL%×leverage ranking formula or the 5-bar indicator mechanic — now confirmed)* |
| Grid / DCA / Martingale / Combo bots | Native (Bybit's own bot products) | CandleViewer could either integrate with these via API or fully reimplement equivalent logic client-side for tighter integration with the custom rule engine. **Concrete numeric caps confirmed (help center, consumer bot UI — not a documented REST/bot-API limit, so treat as UI reference points for CandleViewer's own reimplementation ceilings):** Spot Grid Bot — grid count 2–200 (upper price range 0.8×–3× market, lower 0.3×–1.2× market; system narrows the max grid count for a tighter price range to keep grid profit > fees); Futures Grid Bot — grid count 2–400 (upper 1.005×–999,999, lower 10%–999,999 of market), Neutral/Long/Short modes; up to 50 Spot Grid Bots (and separately, up to 50 total DCA+Spot-Grid bots) running simultaneously per account; DCA Bot — Spot-only, up to 5 coins per bot, time interval presets (10 min; 1/4/8/12 hr; 1 day; 1/2/4 wk), investment amount bounded by Spot per-transaction min/max order value, three params (investment amount, frequency, max orders) can be live-edited on a running bot. ([FAQ — Spot Grid Bot](https://www.bybit.com/en/help-center/article/FAQ-Spot-Grid-Bot); [FAQ — Futures Grid Bot](https://www.bybit.com/en/help-center/article/FAQ-Futures-Grid-Bot); [FAQ — DCA Bot](https://www.bybit.com/en/help-center/article/FAQ-DCA-Bot)) No canonical martingale-specific numeric cap (max steps/leverage) was found in Bybit's own help-center FAQ set for Futures Martingale Bot in this pass — see Open Questions. |

**Key architectural takeaway:** favor **exchange-native execution** (trailing stop, TP/SL bracket, conditional orders, ADL/MMR) wherever Bybit supports it server-side — this reduces latency and survives client disconnects. Reserve **client-side emulation** for the genuinely custom logic Bybit doesn't offer (ATR/structure/MA-based trailing, break-even-after-1R, time stops, daily-loss lockouts, true OCO pairs, scaled/laddered/iceberg/TWAP order slicing). Emulated stops carry a **failover risk**: if CandleViewer's backend process is down, disconnected, or lagging, an emulated stop will not fire — this must be mitigated by (a) always placing a native "hard" stop-loss on the exchange as a safety net even when a smarter client-side trailing/rule-based stop is also running, and (b) reconciliation/heartbeat monitoring with alerting on backend downtime.

---

## 6b. DeepCharts/Volumetrica order-flow signals as inputs to the stop/execution rule engine (new)

The brief requires CandleViewer to replicate DeepCharts' order-flow views (iceberg detector, stop-run detection, etc.) — this section connects those signals to the execution/risk rule engine defined in §7, closing the design-linkage gap between "detect X" and "act on X."

| DeepCharts/Volumetrica feature | Detection methodology (confirmed) | How it should feed CandleViewer's stop/execution rules |
|---|---|---|
| Deep Iceberg / Iceberg Detector | Uses **Market-By-Order (MBO)** data (per-order IDs, not just aggregated volume) to spot orders that repeatedly refill at the same price — i.e., executed volume at a price level far exceeds the largest visible order size ever shown there. Distinguishes **native icebergs** (exchange-matched, high detection confidence from true MBO) from **synthetic icebergs** (built by algos slicing orders client-side, lower detection confidence). ([DeepCharts Help Center — Deep Iceberg (Iceberg Detector)](https://www.deepcharts.com/helpcenter/deepdom/article/deep-iceberg-(iceberg-detector)); [Volumetrica Support — Stop Iceberg](https://help.volumetricatrading.com/en/support/solutions/articles/204000012605-stop-iceberg)) | A detected iceberg at/near a level should be surfaced as a `metric` in the rule DSL (e.g. `iceberg_present_at_level`, `iceberg_executed_volume`) so a stop-placement rule can **avoid placing a stop exactly at a level with heavy iceberg absorption** (likely to see continued defense/support) or, conversely, treat iceberg exhaustion (refill stops) as a trigger to tighten/move a stop. |
| Stop-run / stop-hunt detection | Identified via MBO by detecting a burst of aggressive market orders sweeping through a price level in a short window, consuming clustered resting liquidity (the classic "stop cluster" signature), then classifying the move as a genuine breakout vs. a sweep-and-reverse based on whether follow-through or exhaustion/reversal occurs immediately after. Bybit itself does not publish a stop-run detector — this is Volumetrica/DeepCharts-side analytics on order-flow data, not an exchange feature. | This is the most direct DeepCharts→risk-engine linkage requested in the brief: CandleViewer's stop-placement/trailing rules should treat **known stop-cluster zones (areas of visible resting stop-order density inferred from liquidity heatmap/DOM clustering)** as a factor to place structural stops *beyond* the cluster (or use a wider ATR-multiple) rather than exactly at an obvious round-number/swing level, reducing the odds of being run and reversed against. A rule metric such as `distance_to_liquidity_cluster` or `in_stop_hunt_zone` (boolean, computed from the DOM/heatmap module) is recommended as a new condition type in the §7 DSL. |
| DeepDOM liquidity heatmap / liquidity tracker | Visualizes resting order-book liquidity depth/density by price over time (built on the same MBO-driven Volumetrica tech). | Feeds the same `distance_to_liquidity_cluster` metric above; can also inform position sizing (avoid oversized orders directly into thin liquidity, which the order-entry module in §1 should account for via a slippage/impact estimate). |

**Design takeaway:** CandleViewer's rule engine (§7) should treat DeepCharts-style order-flow analytics (iceberg presence, stop-cluster proximity, liquidity thinness) as **first-class condition metrics** alongside price/indicator/time metrics, not just as passive chart overlays — this is what actually fulfills the brief's requirement that DeepCharts visibility "inform CandleViewer's rule engine." Exact internal Volumetrica/DeepCharts algorithmic thresholds (e.g., how many refills constitute a confirmed iceberg, or the exact liquidity-consumption threshold for a "stop-run" classification) are proprietary and not published in primary docs — treat this as informing CandleViewer's *own* independently-tuned heuristics rather than a spec to replicate exactly (see Open Questions).

---

## 7. Recommended rule DSL sketch

Design goals: ECA (event-condition-action) structure, mirrors Freqtrade's expressiveness + Hummingbot's declarative Triple-Barrier config + Coinrule's readable IF/THEN chaining, while explicitly modeling which actions are exchange-native vs. must be emulated by CandleViewer's own execution engine.

```yaml
rule:
  id: "move-sl-to-be-after-1r"
  enabled: true
  scope:
    symbol: "BTCUSDT"
    account: "bybit-live-1"
    applies_to: "open_positions"     # open_positions | pending_orders | account
  trigger:
    type: "on_price_update"          # on_price_update | on_bar_close | on_order_fill | on_timer | on_indicator
    timeframe: null                  # e.g. "1m" if type == on_bar_close
  conditions:                        # all must be true (implicit AND); use "any_of" for OR
    - metric: "unrealized_r_multiple"
      op: ">="
      value: 1.0
    - metric: "position_side"
      op: "=="
      value: "long"
  actions:
    - type: "modify_stop_loss"
      mode: "emulated"               # native | emulated  (native = exchange-side order amend; emulated = CandleViewer computes + resubmits)
      target_price: "entry_price + fees"
      once: true                    # fire once per position lifecycle, then disable

---
rule:
  id: "atr-trailing-stop"
  enabled: true
  scope: { symbol: "ETHUSDT", account: "bybit-live-1", applies_to: "open_positions" }
  trigger: { type: "on_bar_close", timeframe: "5m" }
  conditions:
    - metric: "position_open"
      op: "=="
      value: true
  actions:
    - type: "modify_stop_loss"
      mode: "emulated"
      target_price: "close - 3 * atr(14)"   # long-side example; mirrored for shorts
      only_tighten: true                    # never loosen the stop (ratchet behavior)

---
rule:
  id: "cancel-if-spread-too-wide"
  enabled: true
  scope: { symbol: "BTCUSDT", account: "bybit-live-1", applies_to: "pending_orders" }
  trigger: { type: "on_price_update" }
  conditions:
    - metric: "spread_bps"
      op: ">"
      value: 5
  actions:
    - type: "cancel_order"
      mode: "native"
      target: "all_working_orders_for_symbol"

---
rule:
  id: "daily-loss-lockout"
  enabled: true
  scope: { account: "bybit-live-1", applies_to: "account" }
  trigger: { type: "on_timer", interval: "1m" }
  conditions:
    - metric: "realized_pnl_today"
      op: "<="
      value: -200            # absolute currency amount; % of equity also supported
  actions:
    - type: "halt_new_orders"
      mode: "emulated"
      duration: "until_next_utc_day"
    - type: "flatten_all_positions"
      mode: "native"
      confirm_required: false
```

Supported `metric` vocabulary (initial set, extensible): `price`, `unrealized_r_multiple`, `unrealized_pnl_pct`, `realized_pnl_today`, `position_side`, `position_open`, `atr(n)`, `ema(n)`, `swing_low(n)` / `swing_high(n)`, `cvd_divergence`, `spread_bps`, `time_in_trade`, `orderbook_imbalance`, `funding_rate`, `iceberg_present_at_level`, `iceberg_executed_volume`, `distance_to_liquidity_cluster`, `in_stop_hunt_zone`, `stop_run_detected`, `big_trade_notional`, `tape_speed_zscore`, `market_regime` (`trend`/`range`/`volatile`), `queue_position_estimate`, `dom_imbalance_ratio`, `open_interest_delta`.

Supported `action.type` vocabulary: `place_order`, `modify_stop_loss`, `modify_take_profit`, `cancel_order`, `move_to_breakeven`, `scale_out`, `scale_in`, `flatten_all_positions`, `halt_new_orders`, `resume_new_orders`, `send_notification`, `log_journal_tag`, `reduce_leverage`, `widen_stop`, `arm_chase_limit`, `start_iceberg_slice`.

**Additional concrete example rules (15+, crypto/order-flow context)** — sketched at `trigger`/`conditions`/`actions` summary level rather than full YAML, following the same schema as the four worked examples above:

| # | Rule id | Trigger | Conditions (summary) | Actions (summary) |
|---|---|---|---|---|
| 1 | `avoid-stop-at-iceberg-level` | `on_bar_close` | `iceberg_present_at_level` == true AND proposed stop within N ticks of that level | `modify_stop_loss` (emulated) — relocate stop beyond the iceberg-defended level rather than at it |
| 2 | `tighten-stop-on-iceberg-exhaustion` | `on_order_fill` (iceberg refill count metric updates) | `iceberg_executed_volume` stops increasing for M consecutive prints (exhaustion signature) | `modify_stop_loss` (emulated), `only_tighten: true` |
| 3 | `widen-stop-beyond-stop-cluster` | `on_position_open` | `in_stop_hunt_zone` == true at the naive structural stop level | `modify_stop_loss` (emulated) — place stop beyond the detected liquidity cluster, or switch to a wider ATR-multiple |
| 4 | `fade-stop-run-reversal` | `on_indicator` (`stop_run_detected` fires) | `stop_run_detected` == true AND price reclaims the swept level within X bars | `place_order` (native, limit, counter-trend entry), `log_journal_tag: "stop-run-fade"` |
| 5 | `pause-on-big-trade-imbalance` | `on_price_update` | `big_trade_notional` > configured threshold in the direction opposing an open position | `halt_new_orders` (emulated, short duration), `send_notification` |
| 6 | `speed-of-tape-breakout-confirm` | `on_bar_close` | `tape_speed_zscore` > 2.0 AND price breaks `swing_high(n)` | `place_order` (native, market/limit breakout entry) |
| 7 | `regime-gate-trend-only-entries` | `on_price_update` (pre-trade check) | `market_regime` != `"trend"` | `cancel_order` (native) — block new trend-following entries while regime == range/volatile |
| 8 | `dom-imbalance-scale-in` | `on_price_update` | `position_open` == true AND `dom_imbalance_ratio` favors position direction beyond threshold | `scale_in` (native/emulated hybrid — additional limit order sized by risk-based sizing from §1) |
| 9 | `funding-rate-flip-flatten` | `on_timer`, interval `"1h"` | `funding_rate` crosses against position direction beyond a configured bps threshold AND `time_in_trade` > min hold | `flatten_all_positions` (native), `log_journal_tag: "funding-flip-exit"` |
| 10 | `open-interest-divergence-warning` | `on_bar_close` | `open_interest_delta` diverges from price direction (price up, OI down = weak-hands rally) | `send_notification`, `log_journal_tag: "oi-divergence"` (informational only, no order action) |
| 11 | `max-concurrent-positions-guard` | `on_price_update` (pre-trade check) | count of open positions for `account` >= configured max | `cancel_order` (native) — reject/withhold new entries until a slot frees up |
| 12 | `per-symbol-exposure-cap` | `on_order_fill` | notional exposure for `symbol` exceeds configured % of equity | `halt_new_orders` (emulated, scope: symbol only) |
| 13 | `time-stop-flatten-if-no-progress` | `on_timer`, interval `"5m"` | `time_in_trade` > configured max AND `unrealized_r_multiple` < 0.2 | `flatten_all_positions` (native), `log_journal_tag: "time-stop"` |
| 14 | `weekend-low-liquidity-lockout` | `on_timer` (cron-like schedule) | current UTC time within configured low-liquidity weekend window | `halt_new_orders` (emulated, `duration: "until_window_end"`) |
| 15 | `cvd-divergence-early-warning-trim` | `on_bar_close` | `cvd_divergence` == true against an open position beyond a configured bar-count | `scale_out` (native, partial reduce-only close), `log_journal_tag: "cvd-divergence-trim"` |
| 16 | `chase-limit-arm-on-thin-book` | `on_order_fill` (partial fill of a resting limit) | `spread_bps` widening AND remaining `leaves_qty` > 0 | `arm_chase_limit` (native — Bybit Iceberg-ticket-style Chase Limit sub-order per §6) |
| 17 | `iceberg-slice-large-entry` | `place_order` request intercepted pre-submit | requested order notional > configured slippage/impact threshold vs. current `distance_to_liquidity_cluster`/book depth | `start_iceberg_slice` (emulated per §6 iceberg finding — client-side repeated limit slices, since no native REST iceberg field was confirmed) |
| 18 | `reduce-leverage-near-adl-zone` | `on_price_update` | Bybit ADL indicator proxy (`unrealized_pnl_pct` × effective leverage) crosses a configured danger threshold | `reduce_leverage` (native), `send_notification` |

Every rule firing should be journaled (rule id, timestamp, trigger snapshot, condition values, action result) to support the "auto-tracker journal" requirement (§9) and to debug emulated-stop failover incidents.

---

## 8. Server-side vs. client-side execution, and failover implications

- **Native (exchange-side)** order/stop types execute even if CandleViewer's backend, network, or browser session goes down — critical for anything that must survive a disconnect (hard stop-loss, TP bracket, trailing stop, ADL, liquidation logic all run inside Bybit's matching engine).
- **Emulated (client-side)** rules (ATR/structure/MA-trailing stops, break-even automation, daily-loss lockout, true OCO pairing, scaled/laddered/TWAP/iceberg slicing) depend on CandleViewer's backend process being alive, connected via WebSocket, and current on market data. Any of these can silently fail to fire if the process crashes, the WebSocket disconnects without reconnect, or GC/latency causes a stale market snapshot.
- **Mitigations for emulated logic (best practice pattern derived across Freqtrade/Hummingbot/3Commas/Cornix designs):**
  1. Always place a native "hard" stop-loss at position open as a floor, even when running a smarter emulated trailing/rule-based stop on top.
  2. Heartbeat/watchdog process that detects backend or WS disconnects and pages/alerts the user.
  3. On reconnect, reconcile local rule/position state against Bybit's actual open orders/positions before resuming rule evaluation (avoid duplicate/orphaned orders).
  4. Idempotent action execution (e.g., "once: true" flags, dedupe on rule-firing) so a reconnect-replay doesn't double-fire an action.
  5. Log every emulated-rule evaluation and action for audit, even when no action is taken, to distinguish "rule didn't fire because condition false" from "rule engine wasn't running."

---

## 9. Paper trading realism

Requirements distilled from the brief (fill simulation using live L2 book & trades):

| Realism dimension | What to simulate | Why it matters |
|---|---|---|
| Queue position | Model where a simulated resting limit order sits in the price-level queue based on order arrival time vs. observed L2 size/time-and-sales flow, so it doesn't fill unrealistically early | Prevents paper-trading over-optimism common in naive backtesters/paper modes |
| Partial fills | Simulated orders should fill incrementally as real trades print against that price level, matching observed traded volume rather than filling 100% instantly | Matches real DOM-trading behavior (Bookmap/Jigsaw-style order flow realism) |
| Slippage | Market/stop-triggered orders in paper mode should walk the simulated book (consume L2 levels) rather than fill at a single price | Avoids paper P&L being systematically better than live |
| Fees | Apply the exchange's real maker/taker fee schedule to simulated fills | Needed for realistic net P&L in paper accounts |
| Funding | Apply simulated funding-rate payments/receipts on perpetual positions held across funding intervals, using Bybit's actual published funding rate | Perpetuals-specific realism gap common in naive paper-trading tools |

No single reviewed product's paper-trading engine was documented in enough technical depth in this research pass to serve as a direct blueprint — **flag as open question**: further research (or direct experimentation) needed on exactly how, e.g., Bookmap's/Jigsaw's simulation/replay engines model queue position and partial fills, since this wasn't covered by primary sources surfaced during this pass.

**Update this pass — NautilusTrader's fill-model architecture is now confirmed via primary docs and is the strongest concrete blueprint found for CandleViewer's paper-trading fill engine:**

| NautilusTrader mechanism | Mechanics (confirmed) | Applicability to CandleViewer |
|---|---|---|
| `FillModel` base class, `prob_fill_on_limit` | With L2/L3 book depth, controls whether a limit order fills once price *touches* (but doesn't cross) its level — `0.0` never fills on touch, `1.0` always fills, values between are a per-touch probability draw; crossing the price is a separate, always-fill matching condition | Directly reusable: give paper-trading limit orders a configurable touch-fill probability instead of naive "instant fill on touch," which is the single biggest source of paper-trading over-optimism |
| `prob_slippage` (L1-book mode) | For coarser L1 (quote/trade/bar-derived) books, a probabilistic draw adds one tick of adverse slippage to a fill | Useful fallback for symbols/timeframes where CandleViewer only has L1/trade-tape data rather than full L2 depth |
| Queue-position tracking (`queue_position=True`) | On order acceptance, the order snapshots the same-side displayed size already resting ahead of it at that price; each same-side trade print at that price reduces the "quantity ahead" counter; the order becomes fill-eligible only once the queue ahead clears to zero, and only trade volume *beyond* the cleared queue can fill it that tick. A price move away from the order's level clears its queue estimate; a move toward it preserves progress; return to a previously-visible level re-caps quantity-ahead at the new displayed size | This is the core queue-position algorithm CandleViewer should port: track "size ahead of me at this price," decrement it off real trade prints from the live L2/trade feed, and only allow the simulated order to fill once that reaches zero — much more realistic than fill-on-touch alone |
| `liquidity_consumption` flag | When `True`, tracks how much of the recorded/displayed size at a level has already been consumed by earlier *simulated* fills within the same tick/iteration, preventing multiple simulated orders from all "filling" against the same finite real liquidity; when `False` (default), the same displayed liquidity can be reused by multiple simulated fills in one iteration | CandleViewer should default this to **on** for multi-strategy/multi-account paper trading so two paper orders don't both claim the same real fill event |
| Tiered/size-aware fill models (`TwoTierFillModel`, `ThreeTierFillModel`, `SizeAwareFillModel`, `LimitOrderPartialFillModel`) | Preset models that split an order's fill across synthetic depth tiers (e.g., 50/30/20 across three price levels, or "5 contracts per price touch" for partial-fill queue emulation) or change behavior above/below a size threshold, for venues/timeframes where full L2 depth isn't available | Good template for a "light" mode: when CandleViewer only has L1 book/trade data for a symbol, apply a tiered synthetic-depth model rather than doing naive full-size instant fills |
| Trade-driven fills / fill-price determination by order type | `MARKET` walks crossed levels as taker; `LIMIT` uses crossed-book price as taker or its own limit price as maker; `STOP_MARKET`/`STOP_LIMIT`/`MARKET_IF_TOUCHED`/`TRAILING_STOP_*` apply the market- or limit-style rule *after* trigger/activation; a trade-driven fill (when the book doesn't represent the print) is capped at `min(order.leaves_qty, trade.size)` and priced at the order's limit rather than the (possibly better) trade price | CandleViewer's paper engine should mirror this per-order-type fill-price/quantity-cap table rather than inventing bespoke rules per order type, since it already cleanly covers conditional/trigger/trailing orders too |

([Fill models – NautilusTrader docs](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models); [Fill Prices and Matching – NautilusTrader docs](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/backtesting/fill-prices-and-matching.md); [Trade-Based Execution – NautilusTrader docs](https://nautilustrader.io/docs/latest/concepts/backtesting/trade-execution); [Enhanced order-fill simulation in backtesting — nautechsystems/nautilus_trader#2194](https://github.com/nautechsystems/nautilus_trader/issues/2194))

By contrast, **Freqtrade's dry-run/backtest fill logic is much simpler** (candle-based, not tick/L2-based): `_get_order_filled` treats an order as filled once the configured `rate` falls within the current candle's high/low range, with the stop-loss "worst case" fill modeled as `open price adjusted by the configured stop-loss percentage (leverage-adjusted), floored at the candle low` so a simulated stop can't report an unrealistically better exit than the candle actually offered — a reasonable, cheap baseline for CandleViewer's slower (1m+) timeframe paper fills where full L2 replay isn't justified, while the NautilusTrader queue-position model above should govern faster/DOM-level paper trading. ([Freqtrade `backtesting.py` source](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/optimize/backtesting.py)) Hummingbot's and `backtesting.py`/`vectorbt`'s own fill assumptions were not documented with comparable primary-source technical depth in this pass — see Open Questions.

---

## 10. Multi-account management

- **3Commas / Cornix / Tealstreet / Altrady** all support connecting multiple exchange accounts/sub-accounts and executing signals or bot logic across them from one dashboard (Cornix: "manage and execute signals across multiple exchanges (10+) and accounts from a unified dashboard" — help.cornix.io).
- **Trade copier** pattern: one signal/rule fires and is replicated proportionally (by fixed size, % of equity, or a configured multiplier) across N connected accounts — standard in Cornix/3Commas-style signal bots; recommended pattern for CandleViewer's "a few people managing accounts" requirement: each user/account-manager has scoped, role-based API-key access (trade-only, no withdrawal) and per-account risk limits (max position size, max daily loss, max concurrent positions) enforced by CandleViewer's backend independent of what any individual account manager attempts to execute.
- **Role-based access:** none of the reviewed retail bot platforms document a fine-grained RBAC model in the sources surfaced this pass (most are single-owner-with-shared-login products) — this is a **gap CandleViewer will likely need to design custom**, since the brief calls for a small number of named account managers with scoped permissions rather than a single trader.
- **Adjacent patterns confirmed this pass (from institutional/derivatives-exchange API scoping, not retail terminals):** Deribit's API-key model is the clearest documented precedent for the *scope* axis CandleViewer needs — keys are granted independent `:read` vs `:read_write` scopes per functional area (`account`, `trade`, `wallet`, etc.), so a key can be trade-capable without wallet/withdrawal access, and a `mainaccount` scope is auto-set by the server to distinguish master-account vs subaccount tokens ([Deribit API Access Scopes](https://docs.deribit.com/articles/access-scope)). Deribit also documents **subaccounts** as the isolation primitive for "team access control and portfolio segregation" — subaccounts share the parent's KYC but have independent trading/positions/wallet state, only the main account can create/manage them, and many endpoints accept a `subaccount_id` parameter to query a subaccount's data from the main account's session without re-authenticating as it ([Deribit — Managing Subaccounts](https://docs.deribit.com/articles/managing-subaccounts-api)). Bybit's own `pybit` client exposes an analogous **sub-UID permission-object model**: `create_sub_uid`/related sub-user calls accept a `readOnly` flag (0 = read+write, 1 = read-only) plus a `permissions` object where the master key selects which permission categories (e.g., trade, contract, wallet) to grant a given sub-account ([`pybit/_v5_user.py`](https://github.com/bybit-exchange/pybit/blob/master/pybit/_v5_user.py)), confirming Bybit's own sub-account infrastructure could technically back a CandleViewer per-manager scoping scheme (trade-only sub-UID keys, no withdraw permission, one sub-UID per account manager) instead of a fully custom auth layer built only inside CandleViewer. Kraken's public API-key-permission matrix independently corroborates the same design pattern at a coarser retail level (separate `Query Funds` / `Create & Modify Orders` / `Withdraw Funds` permission toggles per key) ([Kraken — API key permissions](http://docs.kraken.com/exchange/guides/rest/api-keys)).
- **Recommended CandleViewer design (synthesizing the above):** use **Bybit sub-UIDs, one per account manager, each with a trade-and-read-only permission set and Withdraw explicitly disabled** (mirroring the `bybit-exchange/skills` guidance to "Enable Read + Trade permissions only (never enable Withdraw for AI/automation use)" — [`bybit-exchange/skills` README](https://github.com/bybit-exchange/skills)) as the exchange-side isolation boundary, layered underneath CandleViewer's own app-level RBAC (per-manager UI role: which symbols/accounts they can see or trade, per-account risk limits such as max position size/max daily loss/max concurrent positions enforced in CandleViewer's backend independent of what the sub-UID's exchange-side permissions alone would allow). This is a genuine hybrid design, not a single existing product's blueprint — flag as **partially resolved**: the scoping *primitives* (Deribit scopes/subaccounts, Bybit sub-UID permissions, Kraken key permissions) are now confirmed via primary docs, but no reviewed product documents the *UI-level* manager-role workflow (e.g., approval flows, per-manager dashboards) CandleViewer will still need to design from scratch.

---

## 11. Trade journaling / auto-tracker & analytics

Requirement traits (from DeepCharts "auto-tracker journal" and general best practice, cross-referenced against the rule-engine logging pattern in §4/§7):

- Per-trade record: entry/exit time & price, size, side, fees, funding paid/received, realized P&L, R-multiple, tags (setup type, session, symbol regime).
- MAE/MFE (Maximum Adverse Excursion / Maximum Favorable Excursion) tracked per trade — how far price moved against and in favor of the position before exit, to evaluate stop-placement and TP-target quality.
- Replay: ability to step back through the trade against the recorded chart/DOM/footprint state at the time, for post-mortem review.
- Auto-tagging: rules/signals that opened/managed the trade should be auto-attached as tags (traceable back to the rule DSL in §7), giving a closed loop between "rule fired" and "trade outcome."
- P&L/analytics dashboards: aggregate win rate, expectancy, R-distribution, equity curve, drawdown, performance by symbol/session/setup-tag.

No single reviewed product's journal was documented with full technical/schema depth in the primary sources surfaced this pass; this section reflects synthesis of the brief's explicit requirements plus patterns visible in Cornix/3Commas trade tracking and Freqtrade's trade database (`trades` table with a rich set of computed fields) rather than a directly-cited external spec. **Flag for follow-up research** into a dedicated journaling tool (e.g., Edgewonk, TraderSync) if deeper analytics-schema detail is needed later.

---

## Sources

- [Types of Orders Available on Bybit – Help Center](https://www.bybit.com/en/help-center/article/Types-of-Orders-Available-on-Bybit)
- [Types of Orders Available on Bybit (EU)](https://www.bybit.eu/en-EU/help-center/article/Types-of-Orders-Available-on-Bybit)
- [Take Profit and Stop Loss (Spot Trading) – Bybit Help Center](https://www.bybit.com/en/help-center/article/Introduction-to-Take-Profit-and-Stop-Loss-Spot-Trading)
- [Bybit Perpetuals Command Cheat Sheet – autoview.com](https://autoview.com/guides/bybit-commands/)
- [Bybit Perpetuals Command Reference – autoview.com](https://autoview.com/guides/bybit-command-reference/)
- [Trading Stops and Risk Management – DeepWiki (bybit-exchange/docs)](https://deepwiki.com/bybit-exchange/docs/3.3-trading-stops-and-risk-management)
- [What are Bybit Trading Bots? – bybit.com](https://www.bybit.com/en/learn/bybit-trading-bot/what-is-bybit-trading-bot)
- [Differences Between Each Trading Bot on Bybit – Help Center](https://www.bybit.global/en/help-center/article/Difference-between-Bybit-Trading-Bot)
- [Bybit EU Automated Bot](https://www.bybit.eu/en-EU/tradingbot/)
- [Enums Definitions – Bybit V5 API Documentation](https://bybit-exchange.github.io/docs/v5/enum)
- [Auto-Deleveraging (ADL) Mechanism – Bybit Help Center](https://www.bybit.com/en/help-center/article/Auto-Deleveraging-ADL)
- [Position Management API – pybit (DeepWiki)](https://deepwiki.com/bybit-exchange/pybit/5.3-position-management-api)
- [Position Management – bybit.go.api (DeepWiki)](https://deepwiki.com/bybit-exchange/bybit.go.api/3.3-position-management)
- [Stoploss – Freqtrade docs](https://www.freqtrade.io/en/2020.01/stoploss/)
- [Strategy Callbacks (custom_stoploss) – Freqtrade docs](https://docs.freqtrade.io/en/2025.7/strategy-callbacks/)
- [freqtrade/docs/includes/protections.md – GitHub](https://github.com/freqtrade/freqtrade/blob/develop/docs/includes/protections.md)
- [Custom Stoploss Strategies – DeepWiki (freqtrade/freqtrade-strategies)](https://deepwiki.com/freqtrade/freqtrade-strategies/5.1-custom-stoploss-strategies)
- [How Take Profit Works (SmartTrade and DCA Bots): Trailing feature explained – 3Commas Help Center](https://help.3commas.io/en/articles/3108981-how-take-profit-works-smarttrade-and-dca-bots-trailing-feature-explained)
- [DCA Bot | 3Commas API Platform](https://developers.3commas.io/dca-bot/)
- [3Commas DCA Bot for TradingView — Setup & Parameter Guide](https://help.3commas.io/en/articles/16307077-3commas-dca-bot-for-tradingview-setup-parameter-guide)
- [DCA Safety Orders Calculator – 3commas.io blog](https://3commas.io/blog/dca-safety-orders-calculator)
- [Cornix – Automated crypto trading for everyone](https://cornix.io/)
- [Signals | Cornix Help Center](https://help.cornix.io/en/collections/8561509-signals)
- [Signals Bot Advanced Settings – Cornix Help Center](https://help.cornix.io/en/articles/8975701-signals-bot-advanced-settings-advanced-section)
- [Orders Management – Bookmap Knowledge Base](https://bookmap.com/knowledgebase/docs/KB-Trading-Orders-Management)
- [Trading from DOM – Bookmap Knowledge Base](http://docusaurus.bookmap.com/knowledgebase/docs/KB-Trading-From-DOM)
- [Jigsaw Trading – daytradr Order Flow Platform](https://www.jigsawtrading.com/daytradr-professional-order-flow-platform/)
- [Jigsaw Daytradr overview – nexusfi.com](https://nexusfi.com/a/platforms/jigsaw-daytradr)
- [Trade Menu – Sierra Chart](https://www.sierrachart.com/index.php?page=doc/TradeMenu.html)
- [Keyboard Commands – Sierra Chart](https://www.sierrachart.com/index.php?page=doc/KeyboardCommands.html)
- [Chart Trading and the Chart DOM – Sierra Chart](https://www.sierrachart.com/index.php?page=doc/ChartTrading.html)
- [Concepts | Broker Integration Manual – TradingView](https://in.tradingview.com/broker-api-docs/trading/concepts/)
- [Manage Orders | Advanced Charts Documentation – TradingView](https://www.tradingview.com/charting-library-docs/latest/tutorials/implement-broker-api/manage-orders/)
- [Coinrule – Trading Strategy Builder](https://coinrule.com/trading-strategy-builder/)
- [Build A Rule – Coinrule Help Center](https://help.coinrule.com/articles/247956-build-a-rule)
- [Position Executor – Hummingbot docs](https://hummingbot.org/strategies/v2-strategies/executors/positionexecutor/)
- [Risk Management – DeepWiki (hummingbot/deploy)](https://deepwiki.com/hummingbot/deploy/6.1-risk-management)
- [Order Types – Quantower Knowledge Base (GitHub)](https://github.com/Quantower/QuantowerKB/blob/master/trading-panels/order-entry/order-types.md)
- [Order Placing Strategies – Quantower Knowledge Base (GitHub)](https://github.com/Quantower/QuantowerKB/blob/master/trading-panels/order-entry/order-placing-strategies/README.md)
- [Insilico Terminal — Professional Crypto Trading Terminal](https://www.insilicoterminal.com/)
- [Insilico Terminal Review – FINESTEL](https://finestel.com/blog/insilico-terminal-review/)
- [Tealstreet Review 2026 – FINESTEL](https://finestel.com/blog/tealstreet-review/)
- [Tealstreet Crypto Trading Terminal](https://www.tealstreet.io/)
- [Compare Altrady vs. Insilico Terminal – Slashdot](https://slashdot.org/software/comparison/Altrady-vs-Insilico-Terminal/)
- [Kryll Strategy Editor Blocks: Master Automated Trading Strategies ("The Blocks Bible") – Kryll blog](https://blog.kryll.io/the-blocks-bible/)
- [The secrets of Take Profit, Stop Loss & Trailing Stop with Kryll.io – Kryll blog](https://blog.kryll.io/the-secrets-of-take-profit-stop-loss-trailing-stop-with-kryll-io/)
- [Iceberg Order – Bybit Help Center](https://www.bybit.com/en/help-center/article/Iceberg-Order)
- [How to use iceberg orders on Bybit – Bybit Learn](https://www.bybit.com/en/learn/bybit-guide/how-to-use-iceberg-orders)
- [One-Cancels-the-Other (OCO) Orders – Bybit Help Center](https://www.bybit.com/en/help-center/article/One-Cancels-the-Other-OCO-Orders)
- [Place Order (order/create) – Bybit V5 API Docs](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [Set Trading Stop (position/trading-stop) – Bybit V5 API Docs](https://bybit-exchange.github.io/docs/v5/position/trading-stop)
- [Order Management APIs – DeepWiki (bybit-exchange/api-usage-examples)](https://deepwiki.com/bybit-exchange/api-usage-examples/4.2-order-management-apis)
- [Difference Between Position Modes: One-Way Mode and Hedge Mode – Bybit Help Center](https://www.bybit.com/en/help-center/article/Difference-Between-Position-Modes-One-Way-Mode-and-Hedge-Mode)
- [Risk Limit (Perpetual and Expiry Contracts) – Bybit Help Center](https://www.bybit.com/en/help-center/article/Risk-Limit-Perpetual-and-Expiry-Contracts)
- [Margin trading position tiers update on May 13, 2026 – Bybit Announcements](https://announcements.bybit.com/en/article/usdt-margin-tiers-update-on-may-13-2026-blt8ba149984d899879/)
- [Auto-Deleveraging (ADL) Mechanism – Bybit Help Center](https://www.bybit.com/en/help-center/article/Auto-Deleveraging-ADL)
- [Introduction to Spot Grid Bot on Bybit – Bybit Help Center](https://www.bybit.com/en/help-center/article/Introduction-to-Spot-Grid-Bot)
- [Bybit Grid Trading Bot section – Bybit Help Center](https://help.bybit.com/hc/en-us/sections/7880580863385-Grid-Trading-Bot)
- [Cikle/bybit-dca-trading-bot – GitHub (open-source leveraged grid/DCA bot)](https://github.com/Cikle/bybit-dca-trading-bot)
- [DCA Bot: Interface and Main Settings – 3Commas Help Center](https://help.3commas.io/en/articles/3108940-dca-bot-interface-and-main-settings)
- [Understanding the DCA Bot Summary box – 3Commas Help Center](https://help.3commas.io/en/articles/16666593-understanding-the-dca-bot-summary-box)
- [Modify maximum safety orders count – 3Commas API Platform](https://developers.3commas.io/dca-bot/deals/modify-maximum-safety-orders-count/)
- [Trailing Take-Profit – Cornix Help Center](https://help.cornix.io/en/articles/5814862-trailing-take-profit)
- [Signals Bot Advanced Settings – Take-Profit Strategy – Cornix Help Center](https://help.cornix.io/en/articles/8976604-signals-bot-advanced-settings-take-profit-strategy)
- [Deep Iceberg (Iceberg Detector) – DeepCharts Help Center](https://www.deepcharts.com/helpcenter/deepdom/article/deep-iceberg-(iceberg-detector))
- [Stop Iceberg – Volumetrica Support](https://help.volumetricatrading.com/en/support/solutions/articles/204000012605-stop-iceberg)
- [FAQ — Spot Grid Bot – Bybit Help Center](https://www.bybit.com/en/help-center/article/FAQ-Spot-Grid-Bot)
- [FAQ — Futures Grid Bot – Bybit Help Center](https://www.bybit.com/en/help-center/article/FAQ-Futures-Grid-Bot)
- [FAQ — Dollar-Cost-Averaging (DCA) Bot – Bybit Help Center](https://www.bybit.com/en/help-center/article/FAQ-DCA-Bot)
- [pybit `_v5_trade.py` (place_order parameter surface) – GitHub](https://github.com/bybit-exchange/pybit/blob/master/pybit/_v5_trade.py)
- [pybit `_v5_user.py` (sub-UID permission/readOnly model) – GitHub](https://github.com/bybit-exchange/pybit/blob/master/pybit/_v5_user.py)
- [bybit-exchange/skills — derivatives module & README (API key permission guidance)](https://github.com/bybit-exchange/skills)
- [Fill Models – NautilusTrader docs](https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models)
- [Fill Prices and Matching – NautilusTrader docs](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/backtesting/fill-prices-and-matching.md)
- [Trade-Based Execution – NautilusTrader docs](https://nautilustrader.io/docs/latest/concepts/backtesting/trade-execution)
- [Enhanced order-fill simulation in backtesting — nautechsystems/nautilus_trader Issue #2194](https://github.com/nautechsystems/nautilus_trader/issues/2194)
- [Freqtrade `backtesting.py` source (candle-range fill / stop worst-case logic) – GitHub](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/optimize/backtesting.py)
- [Deribit API Access Scopes – Deribit Docs](https://docs.deribit.com/articles/access-scope)
- [Managing Subaccounts – Deribit Docs](https://docs.deribit.com/articles/managing-subaccounts-api)
- [API key permissions – Kraken Docs](http://docs.kraken.com/exchange/guides/rest/api-keys)

---

## Open questions

1. ~~**Bybit iceberg orders / TWAP as raw order-ticket primitives**~~ — **Resolved this pass (revised finding).** TWAP remains confirmed **not** a native REST order type. Iceberg is a real, named, consumer-facing "Iceberg Order" ticket — but this pass's deeper check of the actual `/v5/order/create` parameter surface (pybit source, bybit-exchange/skills derivatives module, third-party client libraries) found **no `orderType=Iceberg` enum value and no `displayQty`/hidden-size field** anywhere in the documented REST parameters. Revised conclusion: Bybit's Iceberg ticket is most likely implemented as client-side order-slicing in Bybit's own frontend, not a distinct exchange-native primitive exposed over the public API — CandleViewer should plan to build iceberg slicing as its own emulated feature (per the Chase-Limit/Fixed-Price sub-order logic in §6) rather than expecting a passthrough field. See §6.
2. ~~**Bybit true standalone OCO**~~ — **Resolved this pass.** Confirmed via Bybit's own Help Center: OCO exists as a UI-only feature (spot/spot-margin) and is explicitly stated as unavailable for API usage — see §2 and §6.
3. ~~**Kryll rule builder**~~ — **Resolved this pass** with primary blog/docs sources (block reference "The Blocks Bible," trailing/TP/SL mechanics article, KryllOS self-hosted mode) — see §4. Still open: exact per-block parameter ranges (e.g., max variable count, calendar/DCA scheduling cron-like syntax) would need a dedicated pass against Kryll's in-app help center/documentation portal rather than its blog.
4. ~~**Paper-trading fill-simulation engines**~~ — **Resolved this pass for NautilusTrader and Freqtrade** (queue-position/`prob_fill_on_limit`/`liquidity_consumption` mechanics for NautilusTrader; candle-range/worst-case stop fill logic for Freqtrade) — see §9. Still open: Bookmap/Jigsaw/Sierra Chart's own proprietary simulation/replay engines were not documented with comparable primary-source technical depth (no public spec found), nor were Hummingbot's or `backtesting.py`/`vectorbt`'s specific fill assumptions — a dedicated deep-dive or hands-on testing of those specific products would still be needed for full coverage.
5. ~~**Role-based multi-account access**~~ — **Partially resolved this pass.** No retail trading-terminal product documents a full RBAC model, but adjacent scoping primitives are now confirmed via primary docs: Deribit's per-functional-area `:read`/`:read_write` API scopes plus its subaccount model, and Bybit's own sub-UID `readOnly`/`permissions` object (per `pybit`). Recommended design: Bybit sub-UIDs per account manager (trade+read only, Withdraw disabled) as the exchange-side isolation layer, with CandleViewer's own app-level RBAC (per-manager scope, per-account risk limits) layered on top — see §10. Still open: no product documents the UI/workflow layer (approval flows, per-manager dashboards) for this pattern; that remains a bespoke CandleViewer design task.
6. **Trade-journal schema depth (MAE/MFE, replay):** the brief's "auto-tracker journal" requirements were synthesized from the request plus adjacent tooling (Freqtrade trade DB, Cornix/3Commas tracking) rather than from a single authoritative journaling-tool spec; a follow-up pass against a dedicated journal product (e.g., Edgewonk, TraderSync) would sharpen the schema. **Not resolved this pass.**
7. ~~**Bybit "Chase Limit Order" exact mechanics and availability**~~ — **Partially resolved this pass.** Confirmed via Bybit Help Center ("Iceberg Order" article) that Chase Limit (Taker), Chase Limit (maker), Chase Limit (Offset), and Fixed Price are the four documented sub-order placement algorithms for the Iceberg order type specifically — see §6. Still open: whether "Chase Limit" is also offered as an independent order type outside the Iceberg ticket, and the exact numeric parameter ranges (max chase distance, refresh interval in ms/seconds) — not found in the sources reviewed this pass.
8. ~~**Exact numeric caps for Bybit's Grid/DCA bots**~~ — **Resolved this pass for Spot/Futures Grid Bot and DCA Bot** (grid count 2–200 spot / 2–400 futures, price-range bounds, up to 50 concurrent bots, DCA up to 5 coins with fixed interval presets) — see §6, confirmed via Bybit's own FAQ help-center articles. **Still not resolved:** a canonical numeric cap for Bybit's own **Futures Martingale Bot** specifically (max steps/multiplier/leverage ceiling) was not found in the help-center FAQ set reviewed this pass — recommend checking the live Futures Martingale Bot creation panel directly.
9. **DeepCharts/Volumetrica exact internal thresholds** for classifying a confirmed iceberg (minimum refill count) or a "stop-run" (minimum liquidity consumed in a time window): **not resolved this pass** — these are proprietary implementation details of Volumetrica's MBO-based analytics and are not published; CandleViewer should treat the *methodology* (MBO-based refill/order-ID tracking, burst-liquidity-consumption detection) as the design pattern to follow, while independently tuning its own detection thresholds. See §6b for the design-linkage recommendation.
10. **Research budget note:** the Parallel-Search-MCP web_search/web_fetch tools hit a free-tier rate limit partway through this session (both in the original pass and again in this and a further revision pass); all queries were re-run successfully via the fallback WebSearch tool, so no queries in this revision went unanswered as a result — the rate limit did not block any of the gap-remediation research above.
