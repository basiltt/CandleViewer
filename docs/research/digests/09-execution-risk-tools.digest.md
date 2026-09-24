## Digest: 09-execution-risk-tools.md (source: research date 2026-09-13, Bybit-first execution/risk automation)

### §1 Order entry UX
- DOM/ladder click trading — click price cell to buy/sell/stop, drag to reprice — Bookmap, Jigsaw daytradr, Sierra Chart, Quantower.
- Chart click trading — Ctrl/Shift+click chart axis for market/limit/stop — Sierra Chart, Bookmap.
- Hotkeys — configurable keybinds (buy/sell mkt, bid/ask, flatten, reverse, cancel-all, qty presets) — Sierra Chart, Bookmap.
- One-click trading — explicit arm/lock toggle before live orders fire — Bookmap (off by default), Bybit one-click mode.
- Quantity presets — %/fixed size buttons — Bookmap, Tealstreet, Altrady.
- Risk-based sizing — position size from %equity / $risk / ATR-stop distance — not native to Bybit UI, must be app-side.
- Order templates — saved order+bracket+size combos — Jigsaw daytradr, Quantower.
- **Design implication:** CandleViewer needs client-side arm toggle, hotkeys, DOM-ladder+chart-click entry, risk-based sizing computed client-side (Bybit has none natively).

### §2 Scale-in/out, chase, conditional mechanics
- Scaled orders (ladder distribution) — split size across N orders/price range (equal/linear/geometric) — Insilico, Tealstreet, Altrady, Quantower. Not native Bybit primitive — emulate as N individual limit orders.
- Chase/pegged limit — repeatedly cancel/replace to stay near best bid/ask — **Native on Bybit** via Iceberg-ticket sub-algo (Chase Limit Taker/Maker/Offset); also Insilico "Limit Chase", Tealstreet "Chaser".
- TWAP — equal slices over time window — **not a native Bybit REST orderType**, UI/bot-suite only; must emulate via timed repeated `/v5/order/create` calls.
- Iceberg — visible small qty, hidden reserve refreshed on fill — **Native, confirmed standalone "Iceberg Order" ticket** on Bybit (spot+derivatives) BUT re-verified: no `orderType=Iceberg` or `displayQty` field exists on public `/v5/order/create` (only Market/Limit) — likely Bybit frontend-side slicing; CandleViewer must build as emulated client-side slicing.
- MIT/LIT (market/limit-if-touched) — conditional, no margin reserved until trigger — Quantower; ≈ Bybit "Conditional Order".
- OCO/OTOCO brackets — one-cancels-other or entry-triggers-OCO — TradingView, 3Commas; **Bybit OCO is spot/spot-margin UI-only, explicitly NOT available via API** → CandleViewer must emulate true OCO (race 2 orders, cancel loser on fill notice via WS/REST).
- Break-even automation — move SL to entry(+fees) after configured favorable move (e.g. 1R) — not native, emulate via poll+resubmit SL.
- Partial TP ladders — multiple % TP levels (25%@1R/25%@2R/50%@3R) — 3Commas, Cornix, Altrady.
- Time stops — force-close after max hold duration — Hummingbot Triple Barrier `time_limit`, Freqtrade custom logic.
- Max loss/day lockout — circuit breaker halting orders on daily loss/losing streak — Freqtrade Protections (`StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`).
- Flatten/reverse/cancel-all panic buttons — Sierra Chart Trade Menu, Jigsaw daytradr.

### §3 Trailing stop variants
- Fixed-offset trailing — constant $ distance — Bybit native.
- Percentage trailing — % of price — Bybit native; 3Commas trailing TP deviation %.
- ATR-based trailing — distance = ATR(n)×multiple, recalced per bar — not native anywhere reviewed; Freqtrade `custom_stoploss` — strong CandleViewer candidate.
- Structure-based (swing hi/lo, "chandelier") trailing — not offered natively anywhere — candidate differentiator.
- MA-based trailing (e.g. 20 EMA) — no native product reference — custom only.
- Time-based tightening (stop tightens over time regardless of price) — not found natively — open design question.
- Activation-delta trailing (Hummingbot Triple Barrier) — arms only after `trailing_stop_activation_price_delta`, then trails by `trailing_stop_trailing_delta` — clean reusable schema.
- DCA-bot trailing TP — waits for reversal by deviation % after reaching TP before market-closing — 3Commas.

### §4 Rule-automation engines (ECA/IFTTT)
| Product | Model | Notes |
|---|---|---|
| Coinrule | Visual IF/THEN, AND/OR | Price%, indicators (RSI/vol vs MA), time; actions: buy/sell/TP/SL/trailing; templates + backtest; logs every execution |
| Kryll/KryllOS | Drag-drop block editor, 30+ block types, IF/AND/OR/ELSE + variables | Indicator/price/time/calendar/portfolio condition blocks; buy/sell/TP/SL/Trailing Stop(%) action blocks; **KryllOS = self-hosted engine option** |
| Cornix | Signal-parser bound to Telegram/TradingView, not general condition builder | Multi-level TP, SL, trailing SL, dynamic TP split, exposure caps |
| 3Commas SmartTrade/DCA | Config-driven (safety-order ladder+TP/trailing) | Price-deviation steps, TV webhook signals |
| Freqtrade | Python strategy class, declarative config + imperative callbacks (`custom_stoploss`, `confirm_trade_exit`) + Protections | Most expressive/best-documented — closest analog for CandleViewer rule engine |
| Hummingbot Strategy V2 | Executor+Controller, `TripleBarrierConf` per executor (stop_loss/take_profit/time_limit/trailing deltas) | Cleanest machine-readable schema — basis for §7 sketch |
- **Common pattern:** all separate condition/trigger layer from action layer; log every rule firing — CandleViewer should adopt ECA structure.

### §5 DCA/safety-order/martingale mechanics
- 3Commas DCA safety orders: config "Max Safety Orders" total, but separate "Limit avg. orders placed on exchange" caps **~10 simultaneously active** on book even if total configured higher; remainder queued. API: `POST /ver1/deals/:deal_id/update_max_safety_orders?max_safety_orders=X`.
- 3Commas Trailing TP: waits for deviation-% reversal after TP hit, then market exit; liquid pairs only recommended.
- Cornix Trailing TP: Advanced Settings → Take-Profits → "Leveraged Trailing" → "Personal"; deviation % configurable (e.g. 2%); tracks post-TP peak, market-sells on retrace by deviation%; **leverage divides the trailing %** (2% trail at 5x → effective 0.4%); default activates at every TP level, toggle to restrict to last target only; merges amounts into existing trail if a later TP fires while trailing active.
- Bybit Martingale bot: doubles/increases size after losing step; params = initial size, multiplier, max steps, SL; flagged high-risk by Bybit. **No canonical numeric cap for max steps/leverage found in Bybit help center.**
- Bybit Grid bot: buy/sell limits at fixed intervals across range; Spot (range-bound) vs Futures (+leverage, long/short/neutral). Official examples as low as 5 levels; **no single universal grid-count/leverage-cap number published**; 3rd-party self-hosted bots commonly use `GRID_LEVELS`≈20, `LEVERAGE`≈10x, bounded by Bybit's general leverage ceiling (up to 100x some pairs).
- Bybit Combo bot (Futures): auto-rebalancing multi-position portfolio per user allocation targets/rebalance thresholds.
- Cornix signal execution: reads Telegram/TradingView signals, entries (mkt/limit), multi-TP, SL, trailing SL, dynamic TP split, auto scale in/out, max-exposure caps, 10+ exchanges, trade-only API keys.

### §6 Bybit native vs. emulated (feasibility table)
| Feature | Native? | Key detail |
|---|---|---|
| Market / Limit (incl. Post-Only) | Native | — |
| Conditional order (trigger→mkt/limit) | Native | `/v5/order/create`: `orderType`+`triggerPrice`+`triggerBy`(Last/Mark/Index)+`triggerDirection`; funds not reserved until trigger |
| TP/SL position bracket | Native | `/v5/position/trading-stop` endpoint (not `/order/create`); needs `positionIdx`; fields `takeProfit`,`stopLoss`,`trailingStop`,`tpslMode`(Full/Partial); spot locks assets immediately |
| Trailing stop | Native | server-side via `/v5/position/trading-stop` `trailingStop` field — lower latency than emulation |
| Chase (limit) order | Native | part of Iceberg ticket: 4 sub-algos — Chase Limit(Taker), Chase Limit(maker,dynamic), Chase Limit(Offset), Fixed Price |
| OCO (bare pair) | UI-only, NOT available via API | Bybit help center explicit; CandleViewer must emulate (race+cancel-loser) |
| Scaled/laddered order | Not native | emulate: N individual limit orders |
| TWAP | Not native REST orderType | UI/bot-suite only; emulate via timed repeated order calls |
| Iceberg | "Native" ticket exists but **no `orderType=Iceberg`/`displayQty` field on public REST** (verified against pybit/bybit-exchange/skills/ccxt) | Treat as emulated client-side slicing |
| Break-even automation | Not native | poll P&L, resubmit SL amend |
| ATR/structure/MA trailing | Not native (Bybit trailing = fixed-% or fixed-amount only) | fully client-side, bar-by-bar recompute + resubmit |
| Time stop / daily-loss lockout | Not native | fully client-side circuit breaker |
| Position mode (One-Way/Hedge) | Native | `positionIdx`: 0=one-way, 1=hedge-long, 2=hedge-short; query `/v5/position/list` to confirm mode; TP/SL per-side in hedge mode |
| MMR/liquidation | Native | tiered Risk Limit system per contract; MMR%/leverage-cap rise with notional tier; margin owed cumulative across all tiers spanned; numbers pair-specific & revised periodically (e.g. USDT tier update 2026-05-13) — fetch live via API, don't hardcode |
| Auto-Deleveraging (ADL) | Native, last-resort | ranking = unrealized PnL% × effective leverage (higher both → higher ADL priority); 5-bar/light UI indicator per position; executes at counterparty bankruptcy price, not market; mitigations: lower leverage, partial profit-taking, monitor indicator |
| Grid/DCA/Martingale/Combo bots | Native (Bybit bot products) | Spot Grid: 2–200 levels (upper 0.8x–3x mkt, lower 0.3x–1.2x mkt); Futures Grid: 2–400 levels (upper 1.005x–999999, lower 10%–999999 of mkt), Neutral/Long/Short modes; up to 50 Spot Grid bots concurrently (also cap of 50 total DCA+SpotGrid bots/account); DCA Bot: spot-only, ≤5 coins/bot, interval presets (10min;1/4/8/12hr;1day;1/2/4wk), investment bounded by spot min/max order value, 3 params live-editable on running bot; **no canonical Futures Martingale numeric cap found** |
- **Architectural takeaway:** favor exchange-native (trailing stop, TP/SL bracket, conditional, ADL/MMR) for latency+disconnect survival; reserve client emulation for ATR/structure/MA trailing, BE-after-1R, time stops, daily-loss lockout, true OCO, scaled/laddered/iceberg/TWAP slicing. **Emulated stops = failover risk** if backend down/disconnected/lagging — mitigate via (a) always-on native hard SL floor, (b) reconciliation/heartbeat monitoring w/ alerts.

### §6b DeepCharts/Volumetrica order-flow signals → rule engine
- Deep Iceberg/Iceberg Detector — MBO (per-order-ID) data spots repeated refills at same price (native icebergs = exchange-matched, high confidence; synthetic = algo-sliced, lower confidence) — feeds metrics `iceberg_present_at_level`, `iceberg_executed_volume`; used to avoid placing stops at heavy-iceberg levels or to trigger tightening on exhaustion.
- Stop-run/stop-hunt detection — MBO burst of aggressive orders sweeping a level consuming clustered resting liquidity, classified breakout vs sweep-reverse by follow-through — not a Bybit feature, Volumetrica/DeepCharts-side analytics only — feeds `distance_to_liquidity_cluster`/`in_stop_hunt_zone`; recommend placing structural stops beyond cluster or using wider ATR-multiple.
- DeepDOM liquidity heatmap — resting order-book depth/density by price/time (MBO-driven) — feeds same cluster metric + informs sizing/slippage estimate.
- **Not resolved:** exact proprietary refill-count/liquidity-consumption thresholds for confirmed iceberg / stop-run classification — not published; CandleViewer must tune its own heuristics.

### §7 Rule DSL sketch (design recommendation)
- ECA structure: `rule.id`, `enabled`, `scope`{symbol, account, applies_to: open_positions|pending_orders|account}, `trigger`{type: on_price_update|on_bar_close|on_order_fill|on_timer|on_indicator, timeframe}, `conditions`[] (implicit AND; `any_of` for OR), `actions`[].
- Worked YAML examples given: move-SL-to-BE-after-1R (once:true), ATR trailing stop (only_tighten:true, ratchet), cancel-if-spread-too-wide (spread_bps>5 → cancel all working orders), daily-loss-lockout (realized_pnl_today<=-200 → halt_new_orders until_next_utc_day + flatten_all_positions).
- **Metric vocabulary:** `price`, `unrealized_r_multiple`, `unrealized_pnl_pct`, `realized_pnl_today`, `position_side`, `position_open`, `atr(n)`, `ema(n)`, `swing_low(n)`/`swing_high(n)`, `cvd_divergence`, `spread_bps`, `time_in_trade`, `orderbook_imbalance`, `funding_rate`, `iceberg_present_at_level`, `iceberg_executed_volume`, `distance_to_liquidity_cluster`, `in_stop_hunt_zone`, `stop_run_detected`, `big_trade_notional`, `tape_speed_zscore`, `market_regime`(trend/range/volatile), `queue_position_estimate`, `dom_imbalance_ratio`, `open_interest_delta`.
- **Action vocabulary:** `place_order`, `modify_stop_loss`, `modify_take_profit`, `cancel_order`, `move_to_breakeven`, `scale_out`, `scale_in`, `flatten_all_positions`, `halt_new_orders`, `resume_new_orders`, `send_notification`, `log_journal_tag`, `reduce_leverage`, `widen_stop`, `arm_chase_limit`, `start_iceberg_slice`.
- 18 additional example rules (id — trigger — condition — action):
  1. `avoid-stop-at-iceberg-level` — on_bar_close — iceberg present within N ticks of proposed stop — relocate stop beyond level (emulated).
  2. `tighten-stop-on-iceberg-exhaustion` — on_order_fill — iceberg refill volume plateaus M prints — tighten-only SL (emulated).
  3. `widen-stop-beyond-stop-cluster` — on_position_open — in_stop_hunt_zone at naive stop — move stop beyond cluster / wider ATR (emulated).
  4. `fade-stop-run-reversal` — on_indicator — stop_run_detected + price reclaims level within X bars — native limit counter-entry + journal tag.
  5. `pause-on-big-trade-imbalance` — on_price_update — big_trade_notional > threshold opposing position — halt_new_orders (short, emulated) + notify.
  6. `speed-of-tape-breakout-confirm` — on_bar_close — tape_speed_zscore>2.0 + swing_high break — native breakout entry.
  7. `regime-gate-trend-only-entries` — pre-trade check — market_regime != trend — cancel/block entries.
  8. `dom-imbalance-scale-in` — on_price_update — position_open + dom_imbalance_ratio favors direction — scale_in (native/emulated hybrid, risk-sized).
  9. `funding-rate-flip-flatten` — on_timer 1h — funding_rate flips vs position beyond bps threshold + min hold — flatten_all_positions (native) + tag.
  10. `open-interest-divergence-warning` — on_bar_close — OI diverges from price — notify + tag only (no action).
  11. `max-concurrent-positions-guard` — pre-trade check — open positions ≥ max — reject new entries.
  12. `per-symbol-exposure-cap` — on_order_fill — symbol notional > %equity — halt_new_orders (symbol scope).
  13. `time-stop-flatten-if-no-progress` — on_timer 5m — time_in_trade>max + unrealized_r<0.2 — flatten_all_positions + tag.
  14. `weekend-low-liquidity-lockout` — cron schedule — UTC within low-liq window — halt_new_orders until window end.
  15. `cvd-divergence-early-warning-trim` — on_bar_close — cvd_divergence against position beyond bar-count — scale_out (native partial reduce-only) + tag.
  16. `chase-limit-arm-on-thin-book` — on_order_fill (partial) — spread widening + leaves_qty>0 — arm_chase_limit (native, Iceberg-ticket style).
  17. `iceberg-slice-large-entry` — pre-submit intercept — notional > slippage/impact threshold vs book depth — start_iceberg_slice (emulated).
  18. `reduce-leverage-near-adl-zone` — on_price_update — PnL%×leverage proxy crosses danger threshold — reduce_leverage (native) + notify.
- Every rule firing must be journaled (rule id, timestamp, trigger snapshot, condition values, action result).

### §8 Server-side vs client-side execution / failover
- Native execution survives backend/network/browser disconnect (hard SL, TP bracket, trailing stop, ADL, liquidation all run in Bybit's matching engine).
- Emulated rules depend on backend alive + WS connected + current data; can silently fail on crash/disconnect/stale snapshot.
- **Mitigations:** (1) always place native hard SL floor even with smarter emulated trailing on top; (2) heartbeat/watchdog detecting backend/WS disconnect → alert; (3) on reconnect, reconcile local rule/position state vs Bybit actual before resuming; (4) idempotent actions (`once:true`, dedupe) to avoid double-fire on reconnect replay; (5) log every emulated-rule evaluation (even no-op) for audit.

### §9 Paper trading realism
- Dimensions to simulate: queue position (order arrival vs L2/tape flow), partial fills (incremental vs real trade prints), slippage (walk simulated book, don't single-price fill), fees (real maker/taker schedule), funding (apply real funding-rate payments on perp positions).
- **No single reviewed product fully documented queue-position/partial-fill mechanics** (Bookmap/Jigsaw simulation engines) — flagged open question.
- **NautilusTrader FillModel — strongest confirmed blueprint:**
  - `prob_fill_on_limit` (0.0–1.0): probability a limit order fills on touch (not cross) — crossing = always-fill separately.
  - `prob_slippage` (L1-book mode): probabilistic 1-tick adverse slippage add for coarse book data.
  - Queue-position tracking (`queue_position=True`): snapshots same-side size ahead at acceptance; decremented by same-side trade prints; fill-eligible only once queue clears to 0; only volume beyond cleared queue fills that tick; price move away clears estimate, move toward preserves progress, return to prior level re-caps at new displayed size.
  - `liquidity_consumption` flag: True = tracks consumption by earlier simulated fills same tick (prevents double-counting finite liquidity across multiple paper orders) — recommend **default ON** for multi-strategy/multi-account paper trading.
  - Tiered/size-aware fill models (`TwoTierFillModel`,`ThreeTierFillModel`,`SizeAwareFillModel`,`LimitOrderPartialFillModel`): synthetic depth split (e.g. 50/30/20 across 3 levels) for L1-only symbols/timeframes — use as "light mode" fallback.
  - Fill-price/qty rule by order type: MARKET walks crossed levels as taker; LIMIT uses crossed price as taker or own limit as maker; STOP_MARKET/STOP_LIMIT/MIT/TRAILING_STOP apply market/limit rule post-trigger; trade-driven fill capped at `min(order.leaves_qty, trade.size)`, priced at order's limit not trade price.
- **Freqtrade fallback (simpler, candle-based):** order filled once configured rate falls within candle high/low; stop-loss worst-case = open price adjusted by SL% (leverage-adjusted), floored at candle low — good cheap baseline for 1m+ timeframe paper fills where L2 replay unjustified; use NautilusTrader model for faster/DOM-level paper trading.
- Not covered with primary-source depth: Bookmap/Jigsaw/Sierra Chart proprietary sim engines, Hummingbot, backtesting.py/vectorbt fill assumptions.

### §10 Multi-account management
- 3Commas/Cornix/Tealstreet/Altrady all support multi-exchange/sub-account connections + cross-account signal/bot execution from one dashboard.
- Trade-copier pattern: one signal replicated proportionally (fixed size/%equity/multiplier) across N accounts — recommended for CandleViewer's multi-manager use case: scoped trade-only API keys (no withdrawal) + per-account risk limits (max position size, max daily loss, max concurrent positions) enforced server-side regardless of manager action.
- **No retail bot platform documents fine-grained RBAC** — gap CandleViewer must design custom.
- Adjacent confirmed precedents: Deribit API scopes (`:read`/`:read_write` per functional area: account/trade/wallet; `mainaccount` scope flag) + subaccounts (shared KYC, independent trading/positions/wallet, `subaccount_id` param); Bybit `pybit` sub-UID model (`readOnly` flag 0/1 + `permissions` object selecting categories e.g. trade/contract/wallet); Kraken key-permission matrix (Query Funds / Create&Modify Orders / Withdraw Funds toggles).
- **Recommended design:** one Bybit sub-UID per account manager, trade+read-only, Withdraw disabled (per bybit-exchange/skills guidance: "never enable Withdraw for AI/automation"), layered under CandleViewer app-level RBAC (per-manager symbol/account visibility+trade scope, per-account risk limits). Flagged partially resolved — UI/workflow layer (approval flows, per-manager dashboards) is bespoke design work, no product precedent found.

### §11 Trade journaling / auto-tracker & analytics
- Per-trade record: entry/exit time+price, size, side, fees, funding paid/received, realized P&L, R-multiple, tags (setup type/session/symbol regime).
- MAE/MFE tracked per trade (max adverse/favorable excursion before exit) — evaluates stop-placement/TP-target quality.
- Replay: step back through trade against recorded chart/DOM/footprint state for post-mortem.
- Auto-tagging: rules/signals that managed the trade auto-attach as tags, traceable to rule DSL (§7) — closes loop rule-fired↔trade-outcome.
- P&L/analytics dashboards: win rate, expectancy, R-distribution, equity curve, drawdown, by symbol/session/setup-tag.
- **Not resolved:** no single product's journal documented at full schema depth — synthesized from brief + Cornix/3Commas tracking + Freqtrade `trades` table. Flag follow-up: dedicated journal tool (Edgewonk, TraderSync) for deeper schema.

### Open questions (carried forward)
1. Bybit true standalone Iceberg REST field — resolved this pass: no native `orderType=Iceberg`/`displayQty` field exists; must emulate client-side.
2. Bybit true standalone OCO — resolved: UI-only (spot/spot-margin), explicitly unavailable via API.
3. Kryll rule builder — resolved via blog/docs; still open: exact per-block parameter ranges (max variable count, calendar/DCA cron-like syntax) needs dedicated help-center pass.
4. Paper-trading fill-sim engines — resolved for NautilusTrader & Freqtrade; still open: Bookmap/Jigsaw/Sierra Chart proprietary engines, Hummingbot, backtesting.py/vectorbt fill assumptions — no public spec found.
5. Role-based multi-account access — partially resolved (Deribit scopes/subaccounts, Bybit sub-UID perms confirmed as design primitives); still open: no product documents UI/workflow layer (approval flows, per-manager dashboards) — bespoke CandleViewer design task.
6. Trade-journal schema depth (MAE/MFE, replay) — **not resolved**; synthesized only, no single authoritative spec — follow-up vs Edgewonk/TraderSync recommended.
7. Bybit "Chase Limit Order" exact mechanics — partially resolved: confirmed as 1 of 4 Iceberg-ticket sub-algos (Chase Limit Taker/Maker/Offset, Fixed Price); still open: whether Chase Limit exists as independent order type outside Iceberg ticket, exact numeric params (max chase distance, refresh interval ms/s) — not found.
8. Exact numeric caps for Bybit Grid/DCA bots — resolved for Spot/Futures Grid (2–200/2–400 levels, price-range bounds, ≤50 concurrent bots) and DCA (≤5 coins, fixed interval presets); still open: no canonical Futures Martingale Bot cap (max steps/multiplier/leverage) found — check live bot creation panel directly.
9. DeepCharts/Volumetrica exact internal iceberg/stop-run classification thresholds (min refill count, min liquidity-consumption window) — **not resolved**, proprietary/unpublished; treat methodology as design pattern, tune own thresholds independently.
10. Research budget note: Parallel-Search-MCP hit free-tier rate limit mid-session (twice); all queries successfully re-run via fallback WebSearch — no queries went unanswered.
