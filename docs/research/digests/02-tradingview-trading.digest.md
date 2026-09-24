# Digest: 02-tradingview-trading.md

## 1. Trading Panel / broker integration
- Trading Panel — chart-side broker UI; appears on Trade or Paper Trading — TV not in execution path (browser↔broker direct), only `/permissions` server-to-server.
- Broker integration = public REST API contract TV defines; informal tiers: (1) directory listing, (2) Trading Platform, (3) full white-labeled TV terminal.
- Broker directory — 100+ partner brokers, filterable by asset class.
- Order ticket contents/types — entirely broker-dependent (TV's own help docs state this explicitly).

## 2. Bybit integration
- Supported products via TV↔Bybit: Spot, Inverse Perp, USDT Perp, USDC Perp (no options).
- Connect flow: TV Trading Panel → Bybit → OAuth-style login/authorize → Main/Sub-account linked.
- Session limit: **24h** max before re-auth (TV-wide policy, not Bybit-specific).
- Actions once connected: select pair, place orders, view positions/orders/history, modify/cancel, close positions.
- Bybit implements TV Broker API endpoints itself (`/orders`,`/positions`,`/accountManager`,`/quotes`,`/state`,`/mapping`) — useful reference shape only; CandleViewer doesn't need this protocol.
- Not confirmed: whether Bybit's native order types map 1:1 into TV's generic order ticket (open, §18).

### 2.1 Bybit native order types — verified
- Basic (all markets): Market, Limit, Conditional.
- Advanced: TP/SL, Iceberg, Post-Only, TIF (GTC/IOC/FOK), Trailing Stop, TWAP, Scaled, Chase Limit, RPI.
- Spot-only: OCO.
- Derivatives-only: Reduce-Only, Close On Trigger, POV.

### 2.2 Bybit TP/SL mechanics — verified
- Two scope modes: Entire Position (single TP/SL, market close) vs Current Order/Partial Position (multiple concurrent TP/SL, market or limit close, native OCO between legs).
- Upgraded TP/SL: trigger-by {ROI%, Change%, P&L} vs legacy {Price, ROI%}; ref price = Last/Mark/Index.
- Spot TP/SL distinct: dedicated OCO order type; margin occupied differently per order type.

### 2.3 Bybit position mode — verified
- One-Way mode vs Hedge mode (user-configurable); Hedge allows simultaneous long+short same symbol.
- Maps to `positionIdx` (0=one-way,1=hedge-buy,2=hedge-sell) — should inform CandleViewer's Bybit position-mode data model.

## 3. Order ticket features
- Order types (paper baseline): Market, Limit, Stop (stop-market), Stop-limit, Trailing stop.
- Order size: units/contracts field; some risk-based sizing via separate tool (below), not ticket itself.
- **Long/Short Position drawing tool** — risk-based position sizing: set Account Size + Risk (abs or %), tool computes qty from entry/stop distance; drag handles for entry/TP/SL; shows live R:R, P&L $/%, qty overlay. Planning-only — no auto-send to broker.
- **OCO** — not a separate order-type label; implemented via bracket mechanism (TP+SL linked, one fill cancels other).
- **Order brackets**: TP/SL attached at placement or after; one-leg-fill auto-cancels other leg; broker-dependent support for one vs both legs.
- **Position brackets**: TP/SL applied to whole position (possibly multi-fill), distinct from per-order brackets.
- Advanced Charts/Trading Terminal spec: buy bracketed by sell-limit(TP)/sell-stop(SL), vice versa for sell; default 1 TP + 1 SL per side; `supportOrderBrackets` config flag; values via `PreOrder` object (`stopLoss`/`takeProfit`/`limitPrice`/`stopPrice`).
- Other order/position features: Order history, execution marks on chart, partial close, reverse position, Level 2 data, ad-free trading chart perk, unified positions/orders list.
- Order-from-chart: click price scale to place order; drag order/TP-SL lines to reprice (live-order dragging behavior lacks single dedicated citation — open item).
- Risk/Reward drawing tool — Style tab (colors/line thickness/displayed stats) + Visibility tab (per-timeframe show/hide).

## 4. Paper trading
- Built-in simulated trading, no real broker needed; standard order ticket against live real-time data (per user's data plan).
- Virtual balance, resettable.
- Fill model: idealized (market fills at market price, limit/stop fill on price cross) — no order-book/slippage simulation.
- Distinct from Strategy Tester (automated Pine backtesting) — similar but separate fill logic.
- Reset control: gear icon in Paper Trading settings (only when paper account active) — set new starting balance, account currency (USD/EUR/BTC/etc.), leverage; reset deletes all positions/orders/history irreversibly.
- No official cap found on max virtual starting balance (open).

## 5. DOM panel
- DOM = broker-dependent order-book ladder; click to place at price level; availability/depth broker-dependent, requires Level 2 data support.
- **Bybit confirmed on official TV Level-2/DOM broker list** (also: Alor, AMP, Binance, Bitget, Coinbase Advanced, HTX, IBKR, NinjaTrader, OKX, Phemex, Tradovate, Whitebit, etc. — 37 brokers total).
- DOM depth (# price levels) — NOT documented anywhere; dynamically whatever broker feed provides (no TV-imposed cap); confirmed via Advanced Charts docs (`DOMData`/`subscribeDepth`/`getDepth`, no fixed count).
- Ladder controls (verified): click cell = limit order (left=buy,right=sell); Ctrl-click = stop order; right-click = order-type picker; Buy Mkt/Sell Mkt buttons; drag order to new row = reprice; Flatten/Reverse buttons; per-side cancel-all + global CXL ALL; centering button. Colors: green=Limit, red=Stop, yellow=StopLimit (limit leg duller).
- Bybit trailing-stop/TP-on-position exist on Bybit's own platform (fixed distance or %, attached to position) but NOT confirmed whether TV's first-party Bybit order ticket exposes these 1:1 — open, needs live test.
- Bybit WS orderbook depth tiers: 1/50/200/500 (Bybit-side ceiling is high).
- **Recommendation**: build CandleViewer's own order ticket + DOM directly against Bybit REST/WS API rather than relying on TV's generic broker schema.

## 6. Account Manager panel
- Tabs: Positions (size, avg price, uPnL, bracket info), Orders (from `/orders`, lifecycle placed→working→filled/cancelled/rejected), Order History, Notifications (confirmed real named tab per UI-elements doc, but NO dedicated `/notifications` endpoint — rides general `/state` streaming).
- Edit order (e.g. change SL/TP) = PUT request with updated fields.
- Update cadence: quotes/orders default 500ms/max 1000ms; positions/accountManager/balances default 500ms/max 1500ms.

## 7. Alerts
- Types table: Generic/price (no Pine), Drawing alerts (no Pine), Strategy order-fill alerts (auto, needs `{{strategy.order.alert_message}}` placeholder), `alert()` function-call alerts (Pine required), `alertcondition()` alerts (Pine required).
- Alerts trigger only on realtime bars, not historical; snapshot of script/inputs/context frozen at creation time; repainting is main cause of "wrong time/price" fires; mitigate via "Once Per Bar Close".
- Frequency options: Once Per Bar, Once Per Bar Close, Once Per Minute.
- 3 independent quota categories: Price alerts (Crossing/Up/Down/GT/LT, works on Renko/PnF/spread), Technical alerts (indicator/overlay/drawing/strategy or channel conditions or combined conditions), Watchlist alerts (small quota, e.g. 2). Quotas don't share pool (e.g. 400+400+2=802 total).
- **Plan limits** (mixed confidence, needs live pricing-page reconfirm):
  | Plan | Price alerts | Technical alerts | Webhooks | Expiry |
  |---|---|---|---|---|
  | Basic/Free | ~1–3 | 0 | No | — |
  | Essential | 20 | 20 | Yes | ~2 months |
  | Plus | 100 | 100 | Yes | ~2 months |
  | Premium | 400 | 400 | Yes | Never expires |
  | Expert (legacy?) | 600 | 600 | Yes | — |
  | Ultimate | 1000 | 1000 | Yes | — |
- Notification channels: App push, Pop-up, Email, SMS (paid, unverified), Webhook URL (Essential+), Sound.
- Webhook payload = raw Message field string (supports placeholders like `{{ticker}}`,`{{close}}`,`{{strategy.order.action}}` etc.); Pine has **no JSON serialization** — must hand-build strings.
- **Size limits**: name ≤300 chars; message ≤4000 chars (typed in dialog); message ≤40,960 chars (from Pine `alert()`/`alert_message`, same cap applies to webhook body). Emojis = multi-byte, reduce budget.
- Expiration: paid-tier "Open-ended" option exists; exact defaults/caps per tier not fully confirmed (open).

## 8. Pine Script
- Current version: **v6** (`//@version=6`); v4/v5 scripts still run.
- Script types: Indicator (`indicator()`), Strategy (`strategy()` — entry/exit/close/order calls, generates Strategy Tester report + fill alerts), Library (reusable, importable, public or private).
- `request.security()` / data-access: **hard cap ~40 unique `request.*()` calls per script**, budget shared with imported libraries.
- Limits table:
  | Limit | Value |
  |---|---|
  | Compile time | ~2 min; repeated fails → 1h compile ban |
  | Execution time (all bars) | 20s free/Basic, 40s paid Premium+ |
  | Per-bar loop | 500ms max (slowest nested loop triggers first) |
  | Max plots | 64 |
  | Max drawing objects (default) | 50 (raisable) |
  | Max drawing objects (hard cap) | 500 lines/boxes/labels, 100 polylines |
  | Max compiled size (main+libs) | <1,000,000 tokens |
  | Max main script size | 80,000 tokens |
- Architectural constraints: no external network/WebSocket calls; no persistent storage across sessions (only `var`/`varip` in-session); no custom UI beyond overlays/plots/tables/labels; single main-symbol execution (other symbols read-only via `request.security()`, not tradable).
- Alerts from Pine: `alert()` + `alertcondition()`; order-fill via `alert_message` param; no built-in JSON — must hand-build strings.

## 9. Strategy Tester
- Strategy properties: initial capital, base currency, order size (fixed or % equity), pyramiding, commission (%/fixed/per-contract), slippage (ticks), margin (long/short %), recalc options (every tick vs bar-close; `calc_on_order_fills`), Bar Magnifier toggle (`use_bar_magnifier`), Verify Price for Limit Orders.
- **Bar Magnifier**: uses lower-timeframe intrabar feed to simulate real stop/limit/trailing fill timing; auto-selects intrabar resolution; capped ~**200,000 lower-TF bars** per run, precision degrades beyond.
- **Deep Backtesting** — Premium plan+; confirmed hard caps: **2,000,000 bars / 1,000,000 trades** per calculation; auto-engages (pink/magenta icon) when requested range > loaded bars; results only in Strategy Report tab, never chart-overlaid; "Reset to chart session" exits; "Update report" refreshes after strategy edits.
- Strategy Report tabs:
  - Overview: equity chart, date range selector, total P&L ($/%), max drawdown, % profitable, profit factor, buy&hold overlay, gross profit/loss breakdown, periodical P&L, benchmarking chart, margin usage chart.
  - Performance (All/Long/Short): open P&L, net profit, gross profit/loss, commission paid, buy&hold return, max equity run-up/drawdown, max contracts held.
  - Trades analysis (Long/Short): total/open trades, win/loss counts, % profitable, avg P&L, avg win/loss, win/loss ratio, largest win/loss ($/%), avg bars in trade/win/loss.
- **Bar Replay**: manual bar-by-bar or auto-play replay from earliest/chosen/random date; multi-chart support; drawings persist; session state (symbol/interval/bar/replay state) restorable per chart.

## 10. Screener
- Built-in Stock/Crypto/Forex screeners — filterable columns (price, volume, mkt cap, tech rating, %perf, etc.), asset-class-siloed.
- Built-in screener does **NOT** support custom Pine code — built-in filters/columns only.
- **Pine Screener** (verified) — DOES run Pine: Source (user watchlist incl. colored, or major index; one source at a time, replaceable not clearable) × Indicator (any favorited: custom Pine, built-in, or community) → filter → Scan; rescan required on Source/Studies/inputs/timeframe/filter change.
- Pine Screener can scan **mixed-asset-class** watchlist in one pass (unlike siloed built-in screeners).
- Symbol cap: third-party-only claim "25,000 symbols on Premium" — unverified.
- Net take: source×indicator×scan model is simple, directly reproducible for CandleViewer's own crypto/Bybit screener without needing Pine itself.

## 11. Watchlist features
- Sections/folders — custom named grouping within a watchlist.
- Flagged colors — tier-gated (verified via pricing grid): Basic=1 color, Essential/Plus/Premium/Ultimate=7 colors.
- Import/export — tier-gated row (exact cutoff ambiguous, likely Essential+).
- Custom columns and sorting — tier-gated row, confirmed.
- Multiple watchlists — gated Essential+; Basic capped at 1 watchlist / 30 symbols max (from doc 01). No official cap on watchlist count per paid tier (open).
- Watchlist scan filter — colored/custom watchlists selectable in built-in (non-Pine) Screener too; mismatched asset class → empty table, no error.
- Alerts integration — watchlist alerts = distinct small quota (~2), per §7.
- Net take: CandleViewer (single-owner+few managers) likely needs no tiered cap — simple unlimited named watchlists w/ colors+custom columns suffices.

## 12. News, calendar, ideas, social
- News tab — aggregated feed, filterable by symbol.
- Economic calendar — macro events widget; crypto-specific equivalents (unlocks/halvings) not confirmed.
- Ideas — community trading analyses tied to symbol.
- Minds — short-form social posting, chart-attached.
- Social — follow/comment/reputation badges.
- Low priority for CandleViewer per project scope (trading/DOM/order-flow focused).

## 13. Desktop app / mobile / shortcuts / multi-monitor
- Desktop app (Electron): same feature set as web + multi-monitor/multi-window pop-out support.
- Mobile app (iOS/Android): charting, alerts (push), watchlists, broker-dependent trading.
- Keyboard shortcuts (representative, verify live): Alt+W (add to watchlist), Down/Up (next/prev symbol), Ctrl+A (select all), Alt+Enter (fullscreen), Shift+Down/Up (extend selection), type ticker or Shift-Shift (quick search), type number+Enter (change interval), Tab (switch charts), Alt+S (snapshot), Alt+R (reset chart), Alt+A (create alert).

## 14. Chart sharing & data export
- Share toolbar: snapshot image/link, or publish as Idea.
- CSV export: OHLCV bar export, Premium+/higher tier perk (third-party sourced); Strategy Tester trade lists also CSV-exportable.
- **No fixed row cap** — export captures whatever bars are currently loaded in browser; more history requires scrolling/zooming to force-load more bars first; ceiling = chart bar-loading limits (plan/resolution-dependent) + browser memory, not a CSV-specific number.

## 15. Broker REST API (build-your-own-broker reference)
- Purpose: lets any broker connect backend to TV UI so clients trade inside TV chart (Bybit-style).
- Architecture: client-server, browser↔broker direct; TV server only in path via `/permissions`.
- Doc sections: Integration overview, Endpoint requirements, Trading integration, Trading tests, Data integration, Data integration tests, Glossary, API Reference.
- Core concepts: Auth (multiple types incl. JWT Bearer Flow — client signs JWT, POSTs as `assertion`, gets token back), Symbol mapping (`/mapping`), Permissions (restrict/hide symbols per user), Automated sandbox tests before going live.
- Trading concepts: Orders tab reflects `/orders` endpoint; edit order = PUT with updated fields (e.g. stopLoss/takeProfit).
- Update cadence: default 500ms/max 1000ms (quotes/orders); default 500ms/max 1500ms (positions/accountManager/balances).
- Environments: Localhost↔Staging, Staging↔Staging, Production↔Staging.
- Market data integration skippable if broker sources prices from elsewhere — only `/mapping` needed then.
- Endpoint shape reference: `/orders`,`/positions`,`/accountManager`,`/quotes`,`/state`,`/mapping`,`/permissions` — useful architectural benchmark (500ms typical / 1.5s worst-case "real-time enough" target) for CandleViewer's own broker abstraction layer.

## 16. Charting Library / Advanced Charts / Lightweight Charts licensing — CRITICAL
- **Advanced Charts ("Charting Library")**: free, proprietary, not open-source, not on public registries — obtained via signed license/GitHub grant.
  - Free license intended for **public-facing, freely-accessible** projects only.
  - **Prohibited under free license**: internal/private tools, unpublished hobby projects, paywalled/monetized products, hidden/stripped branding.
  - Required if free-licensed: visible TV branding + backlink; historically a public launch announcement.
  - No redistribution of source.
  - Self-hosted; licensee supplies own market data feed.
  - Commercial/private use requires separate negotiated commercial license.
- **Decision**: CandleViewer is private/self-hosted/non-public → falls outside free license terms → free Advanced Charts likely **cannot legally be used** without a separate commercial license (uncertain if TV even offers this for private/unmonetized use). **Hard legal constraint — do not embed without written TV confirmation.**
- **Lightweight Charts**: genuinely open-source (Apache 2.0) — free for private/internal/commercial use, no branding/public-access constraints. Lighter-weight: single-pane, no built-in trading-terminal/order-ticket/DOM — would need custom order-flow layer (footprint, DOM heatmap, etc.) on top.
- **Recommendation**: build CandleViewer's charting layer independently — Lightweight Charts (OSS) as base for OHLC candlesticks, or fully custom canvas/WebGL for order-flow-specific views (DeepDOM/footprint/liquidity heatmap) — safer licensing + matches project's order-flow requirements that neither TV library natively provides anyway.

## 17. Sources
- ~60 sources cited (TV Help Center primary docs, Bybit Help Center, Broker Integration Manual sub-pages, Pine Script docs v6, third-party trackers/guides for unverified numeric figures). See original doc §17 for full list.

## 18. Open questions
1. Exact per-plan alert quotas — 2 third-party 2026 sources agree (Essential 20/20, Plus 100/100, Premium 400/400) but not confirmed against TV's own pricing page (fetch failed).
2. Alert expiration/duration per plan — Essential/Plus ~2mo expiry, Premium open-ended per third-party; not TV-primary-confirmed.
3. Bybit DOM/Level-2 availability — CONFIRMED (Bybit named on official list); exact # of price levels/rows delivered — still unresolved, needs live test.
4. Exact Bybit-native order types surfaced 1:1 in TV's first-party order ticket (vs full native catalog) — unconfirmed, needs live test. Recommendation: build directly against Bybit API regardless.
5. Account Manager "Notifications" tab — CONFIRMED to exist as named UI tab; no dedicated `/notifications` endpoint (rides `/state` stream).
6. Full Pine Screener scope — CONFIRMED (source/indicator/scan model); "25,000 symbols on Premium" ceiling still uncited/third-party only.
7. Exact CSV export limits — partially resolved: no separate fixed row cap exists; governed by chart bar-loading limits instead (not independently re-quantified).
8. Drag-orders/TP-SL live-order-modification citation — RR drawing tool now confirmed via 2 Help Center articles; but "drag an existing LIVE order's line to modify it" (distinct from planning tool) still has no dedicated citation — open.
9. Watchlist folder deep-dive — mostly resolved (flags/import/custom columns confirmed tier-gated); exact numeric cap on # of watchlists per paid tier still not published by TV — open.
10. Whether TV would grant a commercial Advanced Charts license for a private/non-public/unmonetized internal tool at all — unconfirmed, requires direct vendor contact; building independently recommended regardless.
11. Deep Backtesting exact caps — RESOLVED (2M bars/1M trades, Premium+, TV-primary-confirmed).
12. Bybit's 24h TV broker-session re-auth — confirmed but explicitly NOT APPLICABLE to CandleViewer (which should talk to Bybit's exchange API directly, bypassing TV's broker-session layer).
13. Whether OCO is its own labeled order-type in TV UI — not found; treated as resolved-by-equivalence (bracket = functional OCO). Low priority to re-verify.
14. Tooling limitation: several direct web-fetches (pricing page, export-data article, UI-elements page) failed due to a tool error (`output_config.effort` incompatibility) — several "partially resolved" items should be re-fetched to upgrade confidence.
