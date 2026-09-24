# Bybit API v5 — complete capability map for trading & data

Research notes for CandleViewer (crypto-only, Bybit-first trading terminal). Compiled from official Bybit API v5 docs (bybit-exchange.github.io/docs/v5), official SDK source (pybit, bybit-api), and ccxt documentation. Dates/versions noted where available. This is a RESEARCH document only.

## Table of Contents

1. Account architecture (UTA 2.0, margin modes)
2. Environments: Mainnet, Testnet, Demo Trading
3. Product categories
4. REST — Market data endpoints
5. REST — Trade endpoints
6. REST — Position endpoints
7. REST — Account & Asset endpoints
8. REST — User / Sub-account endpoints
9. WebSocket — Public streams
10. WebSocket — Private streams
11. WebSocket — Order Entry (Trade over WS)
12. Authentication & signing
13. Rate limits
14. Heartbeats, reconnects, orderbook sequencing
15. Historical data availability & bulk downloads
16. Python SDKs & libraries
17. Fees
18. API key permissions, IP whitelisting, sub-accounts
19. Pitfalls & operational notes
20. Example payloads
21. Sources
22. Open questions

---

## 1. Account architecture

Source: https://bybit-exchange.github.io/docs/v5/intro , https://bybit-exchange.github.io/docs/v5/acct-mode

The V5 API "brings uniformity and efficiency to Bybit's product lines, unifying Spot, Derivatives, and Options in one set of specifications." A single endpoint (e.g. `POST /v5/order/create`) is parameterised with `category` (`spot`/`linear`/`inverse`/`option`) rather than requiring separate API groups per product, as was the case pre-V5.

**Unified Trading Account (UTA)**
- UTA lets a user share and cross-utilise margin across Spot, USDT Perpetual, USDC Perpetual, and Options — profit/loss can be offset across these instruments from one collateral pool.
- Bybit has iterated the UTA product: UTA 1.0 → UTA 2.0 (Pro) is now the default/target account type referenced throughout the current docs (rate-limit tables reference "UTA2.0" explicitly, see §13). Newer accounts are auto-provisioned as UTA; older "Classic"/"Normal" (non-unified, `CONTRACT`) accounts can be upgraded via `POST /v5/account/upgrade-unified-account` (irreversible — see ccxt's `upgradeUnifiedTradeAccount`, https://bybit-exchange.github.io/docs/v5/account/upgrade-unified-account).
- `accountType` values seen across endpoints: `UNIFIED` (Unified Trading Account) and `CONTRACT` (legacy/normal derivatives account, still used for some older sub-accounts). `SPOT` was a legacy classic-spot wallet type, now folded into UNIFIED for most users.
- Query whether an account is unified: `GET /v5/user/query-api` / `isUnifiedEnabled` helper in ccxt wraps `GET /v5/account/account-info` (https://bybit-exchange.github.io/docs/v5/account/account-info) which returns `unifiedMarginStatus` (margin mode indicator) and `marginMode`.

**Margin modes** (queried/set via `GET/POST /v5/account/set-margin-mode` and position-level endpoints):
- **Cross margin** — all available balance in the unified wallet backs all positions; liquidation risk is shared across positions in that category.
- **Isolated margin** — each position/symbol has a dedicated margin allocation, set via `POST /v5/position/switch-isolated` (`tradeMode`: `0` cross, `1` isolated) and `POST /v5/position/set-leverage`.
- **Portfolio margin** — a UTA-level risk-netting mode that computes margin requirements portfolio-wide (Greeks-aware for options) rather than per-position; enabled via account-level `set-margin-mode` with `PORTFOLIO_MARGIN` (higher capital efficiency, generally requires meeting risk-tier and KYC/asset thresholds set by Bybit).
- Hedge mode vs one-way mode is a **position-mode** setting (separate from margin mode), controlled by `POST /v5/position/switch-mode` with `mode`: `0` = Merged Single (one-way), `3` = Both Sides (hedge). Hedge mode requires order/position calls to pass `positionIdx`: `0` one-way, `1` hedge-Buy, `2` hedge-Sell (seen throughout `/v5/order/create` and `/v5/position/trading-stop`).

## 2. Environments: Mainnet, Testnet, Demo Trading

Source: https://bybit-exchange.github.io/docs/v5/demo , https://bybit-exchange.github.io/docs/v5/ws/connect , tiagosiebler/bybit-api README

| Environment | REST host | WS public | WS private | WS order-entry (trade) |
|---|---|---|---|---|
| Mainnet | `https://api.bybit.com` (also `api.bytick.com` alt domain) | `wss://stream.bybit.com/v5/public/{spot\|linear\|inverse\|option\|spread\|rfq}` | `wss://stream.bybit.com/v5/private` | `wss://stream.bybit.com/v5/trade` |
| Testnet | `https://api-testnet.bybit.com` | `wss://stream-testnet.bybit.com/v5/public/...` | `wss://stream-testnet.bybit.com/v5/private` | `wss://stream-testnet.bybit.com/v5/trade` |
| Demo Trading | `https://api-demo.bybit.com` | **not supported** — use mainnet public streams (`wss://stream.bybit.com/v5/public/...`); market data identical to mainnet | `wss://stream-demo.bybit.com/v5/private` (private only) | **not supported** |

### Demo Trading details (https://bybit-exchange.github.io/docs/v5/demo)
- Basic trading rules mirror real trading; simulated fills against real market data.
- Orders generated in demo trading are retained for **7 days** only.
- Demo trading rate limit is the **default** tier and is **not upgradable** (no VIP-tier boosts).
- **Enable/create a demo account:** `POST /v5/user/create-demo-member` called against `api.bybit.com` (not the demo host) with permission `AccountTransfer`, `SubMemberTransfer`, or `SubMemberTransferList`; rate limit 5 req/s.
- **[CONFIRMED 2026-09-14, resolves prior open question about sub-account/demo interplay]** Source: https://bybit-exchange.github.io/docs/v5/demo (live-fetched). The live docs' own "Create API Key" instructions describe demo trading as tied to the **logged-in mainnet account itself**, not a sub-account concept: "log in to your mainnet account; switch to Demo Trading — please note it is an independent account for demo trading only, and it has its own user ID." *Footnote — corrected/clarified:* this confirms demo trading is architecturally a special linked "shadow" account of the master UID (with its own distinct user ID, separate from ordinary sub-accounts created via `/v5/user/create-sub-member`), rather than a flag or mode settable on an arbitrary sub-account. The docs do not show any sub-account-specific demo-trading creation flow (no `sub-member` or `sub-uid` parameter anywhere on the Demo Trading Service page) — the practical implication for CandleViewer's "per-manager demo mode" UX is that **each account manager would need their own separate mainnet login switched into its own Demo Trading shadow account**, rather than one master UID being able to spin up multiple independent demo sub-accounts under itself. This should still be empirically confirmed against a real multi-user setup before finalizing the UX (the docs describe the single-user flow only and do not explicitly rule out a master account having sub-accounts that each separately switch into their own demo mode), but the balance of evidence from the primary doc favors "demo trading is per-mainnet-login, not a sub-account-assignable mode."
- **Full supported REST/WS endpoint list for demo — [confirmed and expanded from live docs, corrects the previous partial list]:** Market: **all endpoints**. Trade: Place Order (`/v5/order/create`), Amend Order (`/v5/order/amend`), Cancel Order (`/v5/order/cancel`), Get Open Orders (`/v5/order/realtime`), Cancel All Orders (`/v5/order/cancel-all`), Get Order History (`/v5/order/history`), Get Trade History (`/v5/execution/list`), **Batch Place/Amend/Cancel Order** (`/v5/order/create-batch`, `/v5/order/amend-batch`, `/v5/order/cancel-batch` — **linear and option only**). *Footnote — corrected:* the prior revision (§6 pitfall note) stated batch endpoints are "not listed as supported in Demo Trading... treat as mainnet/testnet only until verified otherwise" — the live docs page in fact **does** list batch endpoints as supported on demo, scoped to `linear`/`option` categories only (not spot/inverse). Position: Get Position Info, Set Leverage, Switch Position Mode, Set Trading Stop, Set Auto Add Margin, Add/Reduce Margin, Get Closed PnL. Account: Get Wallet Balance, Get Borrow History, Set Collateral Coin, Get Collateral Info, Get Coin Greeks, Get Account Info, Get Transaction Log, Set Margin Mode, Set Spot Hedging. Asset: Get Delivery Record, Get USDC Session Settlement. Spot Margin Trade: Toggle Margin Trade, Set Leverage, Get Status And Leverage. WS Private: `order`, `execution`, `position`, `wallet`, `greeks` via `/v5/private` (confirmed, matches prior revision).
- **Request demo funds (faucet):** `POST /v5/account/demo-apply-money` against `api-demo.bybit.com`, rate limit **1 request per minute**. Body includes `adjustType` and a `utaDemoApplyMoney` array (per-coin amounts) to top up the simulated UTA wallet.
- *(Stale duplicate line removed 2026-09-14 — corrected: an earlier draft of this line claimed batch order endpoints were "NOT listed as supported on demo," which directly contradicted the corrected/superseding line above (batch Place/Amend/Cancel Order **are** supported on demo, scoped to `linear`/`option`). Removed to eliminate the internal contradiction; see the line above for the current, doc-verified list — verified: https://bybit-exchange.github.io/docs/v5/demo)*
- **Supported WS on demo:** private topics `order`, `execution`, `position`, `wallet`, `greeks` only, via `wss://stream-demo.bybit.com/v5/private`. Public market-data WS is NOT provided under the demo domain — apps must connect to the real mainnet public WS (`stream.bybit.com`) for live order books/trades/klines while trading against the demo REST/private-WS endpoints. WS Trade (order entry over websocket) is **not supported** in demo, per the tiagosiebler/bybit-api README ("as of January 2025, the demo trading environment does not support the WebSocket API [order-entry]").
- Demo API keys are generated separately from live keys in the Bybit UI (demo trading toggle in API management) and only work against `api-demo.bybit.com`; they cannot be reused on mainnet or testnet hosts.
- **Implication for CandleViewer:** architecture should treat "demo trading" as its own connection profile — REST + private WS pinned to `api-demo` / `stream-demo` hosts, but the market-data/charting layer (klines, orderbook, trades, tickers) should reuse the **mainnet public WS connection** even while the account/trading layer is in demo mode. This is a first-class design point, not an edge case.

### Testnet (https://bybit-exchange.github.io/docs/v5/testnet, https://testnet.bybit.com)
- Full separate environment with its own matching engine and thinner liquidity/synthetic order flow — data is not representative of real markets, so it is low priority per project scope (already noted by the user) but useful for order-management smoke testing (including WS Trade, which testnet *does* support unlike demo).
- Testnet API keys are created at `https://testnet.bybit.com/app/user/api-management` and are entirely separate from mainnet/demo keys.
- Testnet supports the WS Order Entry endpoint (`wss://stream-testnet.bybit.com/v5/trade`), useful for testing the low-latency order-entry code path safely before using it on mainnet.

### Domain/network notes
- Alternate hostnames exist for regional routing/regulatory reasons, e.g. `bybit.kz`/`stream.bybit.kz` referenced in the rate-limit docs for Kazakhstan-localized traffic; the SDKs (bybit-api) also reference a `bytick.com` alt domain historically used for GFW-affected regions. CandleViewer should make the REST/WS host configurable rather than hardcoded.

## 3. Product categories

Source: https://bybit-exchange.github.io/docs/v5/intro , https://bybit-exchange.github.io/docs/v5/enum

| `category` value | Meaning | Notes |
|---|---|---|
| `spot` | Spot trading | Margin spot trading supported for UTA (`isLeverage` flag on order create) |
| `linear` | USDT & USDC Perpetual + USDT Futures | Most actively developed category; supports hedge mode, conditional orders, TP/SL, trailing stop |
| `inverse` | Inverse Perpetual & Futures (coin-margined, e.g. BTCUSD) | Same trade/position feature set as linear in most respects |
| `option` | USDC Options | Distinct margin/Greeks model; supports `orderIv` (implied vol) order param; market-maker-protection (`mmp`) |

Nearly every endpoint takes `category` as a required or defaulted parameter; when omitted, several endpoints (e.g. Get Kline) default to `linear`. Always pass `category` explicitly in CandleViewer's client.

## 4. REST — Market data endpoints

Base path prefix: `/v5/market/...` unless noted. All are public (no auth) and are **not** counted against the private API rate limit (though IP-based public limits still apply — prefer WS for market data per Bybit's own FAQ guidance).

### Kline / candles
`GET /v5/market/kline` — https://bybit-exchange.github.io/docs/v5/market/kline
- `category`: `spot`/`linear`/`inverse` (kline not documented for `option` via this endpoint — options use `/v5/market/mark-price-kline` style feeds where relevant).
- `symbol` (required, uppercase), `interval` (required): `1,3,5,15,30,60,120,240,360,720` (minutes), `D`, `W`, `M`.
- `start`/`end`: ms timestamps (optional).
- `limit`: 1–1000 (default `200`, max **1000** per page). To get more history, page backwards using `start`/`end` across repeated calls — Bybit does not offer a single "give me N years of history" call; you must paginate the max-1000-per-request kline endpoint repeatedly, which is the same approach ccxt's `fetchOHLCV` uses internally with `since`/`limit` chunking.
- No documented hard cap on how far back kline history goes for major pairs (varies per symbol's listing date); verify empirically per symbol.

Related kline endpoints (same request/response shape, different price source):
- **Mark price kline:** `GET /v5/market/mark-price-kline` — https://bybit-exchange.github.io/docs/v5/market/mark-kline
- **Index price kline:** `GET /v5/market/index-price-kline` — https://bybit-exchange.github.io/docs/v5/market/index-kline
- **Premium index price kline** (linear/perp funding-basis kline): `GET /v5/market/premium-index-price-kline` — https://bybit-exchange.github.io/docs/v5/market/premium-index-kline

### Orderbook
`GET /v5/market/orderbook` — https://bybit-exchange.github.io/docs/v5/market/orderbook

**[CONFIRMED 2026-09-14, live-fetched from the primary docs page — resolves the gap flagged by the earlier critic pass]** The `limit` parameter's exact documented range per category is:

| Category | `limit` range | Default |
|---|---|---|
| `spot` | `[1, 1000]` | `1` |
| `linear` & `inverse` | `[1, 1000]` | `25` |
| `option` | `[1, 25]` | `1` |

*Footnote — corrected:* the previous revision of this document stated depth levels "1, 50, 200, 500, 1000 depending on category" as an approximation carried over from the WS depth tiers (§9); the REST `GET /v5/market/orderbook` endpoint itself does **not** use fixed tier values — `limit` is a free integer within the ranges above (any value 1–1000 for spot/linear/inverse, 1–25 for option), unlike the WS topic which *is* tiered into fixed depths (1/50/200/1000 for spot & linear/inverse, 25/100 for option — see §9, unchanged). Response fields confirmed unchanged: `s` (symbol), `b`/`a` (bids/asks, `[price, size]`), `ts`, `u` (update id — for contract and spot, corresponds to `u` in the 1000-level WS orderbook stream), `seq` (cross-sequence), `cts` (matching-engine timestamp, correlates with `T` in the public trade channel).

### Recent trades
`GET /v5/market/recent-trade` — https://bybit-exchange.github.io/docs/v5/market/recent-trade
- **[CONFIRMED 2026-09-14]** `category`, `symbol` (required for spot/linear/inverse, optional for option), `baseCoin` (option only, defaults to BTC), `optionType` (option only), `limit`: **spot `[1,60]` default 60**; **linear/inverse/option `[1,1000]` default 500**. *Footnote — corrected:* earlier text said "option max 500" as a special case; the live docs give option the same `[1,1000]`/default-500 range as linear/inverse — only spot is the outlier at max 60. Response now also includes `isBlockTrade` (bool), `isRPITrade` (bool — whether the trade was an RPI-improved fill), and for options: `mP` (mark price), `iP` (index price), `mIv`, `iv`. Bybit does not provide historical trade-by-trade REST beyond this recent window; anything older must be recorded live or pulled from bulk CSV downloads (§15).

### Open interest — confirmed limits (resolves gap: DeepDOM/Big-Trades-adjacent endpoint limits)
`GET /v5/market/open-interest` — https://bybit-exchange.github.io/docs/v5/market/open-interest
- **[CONFIRMED 2026-09-14]** `category`: `linear`/`inverse` only (not spot/option). `intervalTime` (required): `5min`, `15min`, `30min`, `1h`, `4h`, `1d`. `limit`: **`[1,200]`, default 50**, paginated via `cursor`/`nextPageCursor`. Response gives both `openInterest` (sum of both sides) and `singleOpenInterest` (single side) per timestamp — useful for a Big-Trades/imbalance-style OI-delta panel.

### Tickers
`GET /v5/market/tickers` — https://bybit-exchange.github.io/docs/v5/market/tickers
- 24h rolling stats: last price, bid/ask, volume, turnover, high/low, `price24hPcnt`, funding rate + next funding time (linear/inverse), open interest, mark/index price.

### Funding rate history
`GET /v5/market/funding/history` — https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
- `category` (linear/inverse), `symbol`, `startTime`/`endTime`, `limit` (max 200). Funding intervals vary by symbol (commonly 8h, but some symbols use 1h/2h/4h — check `fundingInterval` on `instruments-info`).

### Insurance fund
`GET /v5/market/insurance` — https://bybit-exchange.github.io/docs/v5/market/insurance
- Returns per-coin insurance fund balance and update time; gauges platform-level tail risk.

### Long/short ratio
`GET /v5/market/account-ratio` — https://bybit-exchange.github.io/docs/v5/market/long-short-ratio
- `category` (linear/inverse), `symbol`, `period` (`5min,15min,30min,1h,4h,1d`), `limit` (max 500). Ratio of accounts long vs short.

### Historical volatility (options)
`GET /v5/market/historical-volatility` — https://bybit-exchange.github.io/docs/v5/market/iv
- `category=option`, `baseCoin`, `period`, `startTime`/`endTime`. Realized-vol time series per coin (relevant only if an options view is added later; out of initial scope).

### Risk limits
`GET /v5/market/risk-limit` — https://bybit-exchange.github.io/docs/v5/market/risk-limit
- `category` (linear/inverse), `symbol`. Returns tiered risk-limit table: `riskLimitValue` (max position notional at that tier), `maintainMargin`, `initialMargin`, `maxLeverage` per tier. Position size beyond a tier's `riskLimitValue` forces reduced max leverage/increased margin — needed for a margin/risk panel.

### Instruments info
`GET /v5/market/instruments-info` — https://bybit-exchange.github.io/docs/v5/market/instrument
- `category`, optional `symbol`/`baseCoin`/`status`. Returns per-symbol contract specs: `lotSizeFilter` (qty step/min/max), `priceFilter` (tick size), `leverageFilter` (min/max/step leverage), `contractType` (`LinearPerpetual`, `LinearFutures`, `InversePerpetual`, `InverseFutures`), `fundingInterval`, `launchTime`, `deliveryTime`/`deliveryFeeRate` for dated futures, `status` (`Trading`, `PreLaunch`, `Settling`, `Delivering`, `Closed`). Canonical source for the symbol picker and client-side precision validation before submitting orders.

## 5. REST — Trade endpoints

Source: https://bybit-exchange.github.io/docs/v5/order/create-order , https://bybit-exchange.github.io/docs/v5/order/amend-order , https://bybit-exchange.github.io/docs/v5/order/cancel-order , https://bybit-exchange.github.io/docs/v5/order/batch-place , https://bybit-exchange.github.io/docs/v5/order/batch-amend , https://bybit-exchange.github.io/docs/v5/order/batch-cancel , https://bybit-exchange.github.io/docs/v5/order/open-order , https://bybit-exchange.github.io/docs/v5/order/order-list , https://bybit-exchange.github.io/docs/v5/order/cancel-all , https://bybit-exchange.github.io/docs/v5/order/dcp

### Place order — `POST /v5/order/create`
Key request params (not exhaustive; see full doc for options-specific fields):
- `category` (true), `symbol` (true), `isLeverage` (spot only: `0` spot trade, `1` margin trade — requires margin trading enabled + relevant currency set as collateral).
- `side` (true): `Buy`/`Sell`. `orderType` (true): `Market`/`Limit`.
- `qty` (true, string). `price` (required for `Limit`).
- `timeInForce`: `GTC` (default), `IOC`, `FOK`, `PostOnly` (PostOnly rejects if it would immediately match/take).
- Conditional orders: `triggerPrice`, `triggerBy` (`LastPrice`/`IndexPrice`/`MarkPrice`, Perps & Futures only), `triggerDirection` (`1` = rise to trigger, `2` = fall to trigger), `orderFilter` (spot: `Order`, `tpslOrder`, `StopOrder`).
- `orderIv`: implied volatility, **option only**.
- `positionIdx`: required under hedge mode (`0` one-way, `1` hedge-Buy, `2` hedge-Sell).
- `orderLinkId`: client order ID, max 36 chars, must be unique.
- `takeProfit`/`stopLoss` (attach TP/SL directly on order create), `tpTriggerBy`/`slTriggerBy` (`MarkPrice`/`IndexPrice`, default `LastPrice`; valid for linear/inverse).
- `tpslMode`: `Full` (entire position, `tpOrderType`/`slOrderType` must be `Market`) or `Partial` (supports Limit TP/SL via `tpLimitPrice`/`slLimitPrice`, requires `tpOrderType`/`slOrderType` = `Limit`).
- `reduceOnly` (bool): order can only reduce position size; cannot combine with attaching new TP/SL. If available balance is insufficient when a reduceOnly closing order triggers, other similar-contract active orders may be cancelled/reduced to guarantee the reduce.
- `smpType`: self-match-prevention execution type.
- `mmp` (bool, option only): flag order as a market-maker-protection order.
- `bboSideType`: `Queue`-type option to price at best bid/offer.
- Response is only an **acknowledgement that the request was accepted** — it is async; use the private WS `order`/`execution` streams to confirm actual order status/fills (explicitly called out in the batch-order doc).

### Amend order — `POST /v5/order/amend`
- Modify `qty`, `price`, `triggerPrice`, TP/SL fields, etc. on an existing order by `orderId` or `orderLinkId`.

### Cancel order — `POST /v5/order/cancel`
- By `orderId` or `orderLinkId`. `POST /v5/order/cancel-all` cancels all open orders (optionally scoped to `symbol`/`baseCoin`/`settleCoin`/`orderFilter`).

### Batch endpoints — create-batch / amend-batch / cancel-batch
- https://bybit-exchange.github.io/docs/v5/order/batch-place
- Allows **1-10 orders per request** for `linear`/`inverse`/`option`. Rate-limit consumption = 1 unit per order in the batch, not per request (a batch of 5 consumes 5 of the per-second quota).
- Partial success is possible: if the remaining per-second quota is less than the batch size, the orders within quota succeed and the rest fail with a limit-exceeded error — code must handle mixed success/failure arrays in the response.
- *Footnote — corrected (see §2):* batch order endpoints **are** supported in Demo Trading, but only for `linear` and `option` categories (confirmed from the live Demo Trading Service docs) — not spot/inverse. The earlier statement that batch endpoints were unsupported on demo entirely was incorrect.

### Open/closed orders
- `GET /v5/order/realtime` (open + recently closed orders, real-time order query) — https://bybit-exchange.github.io/docs/v5/order/open-order
- `GET /v5/order/history` (historical orders, longer retention) — order history endpoint distinct from realtime.

### Order limits (per Bybit docs, embedded in trade endpoint pages)
- **Perps & Futures:** max **500 active orders** per symbol per account; max **10 active conditional orders** per symbol.
- **Spot:** 500 orders total, incl. max 30 open TP/SL orders and max 30 open conditional orders per symbol per account.
- **Option:** max 50 open orders per coin dimension by default.
- Bybit monitors aggregate daily order counts (main + sub-accounts) across UTC 0-24 and may warn/restrict abusive patterns.

### Dead man's switch
- `POST /v5/order/disconnected-cancel-all` (DCP) — https://bybit-exchange.github.io/docs/v5/order/dcp — configures the connection to auto-cancel all open orders if the client disconnects/fails to heartbeat within a set window; relevant safety feature for an automated trading terminal.

## 6. REST — Position endpoints

Source: https://bybit-exchange.github.io/docs/v5/position/position-info , https://bybit-exchange.github.io/docs/v5/position/trading-stop , https://bybit-exchange.github.io/docs/v5/position/leverage , https://bybit-exchange.github.io/docs/v5/position/close-pnl , https://bybit-exchange.github.io/docs/v5/position/set-auto-add-margin

- `GET /v5/position/list` — current positions (`category`, `symbol`/`baseCoin`/`settleCoin`). Fields include `size`, `avgPrice`, `positionValue`, `unrealisedPnl`, `markPrice`, `liqPrice`, `bustPrice`, `leverage`, `positionIdx`, `tpslMode`, `takeProfit`/`stopLoss`/`trailingStop`, `positionStatus`, `updatedTime`.
- `POST /v5/position/set-leverage` — set buy/sell leverage per symbol (must match for one-way mode; can differ per side in hedge mode in some configurations).
- `POST /v5/position/switch-isolated` — switch cross/isolated margin (`tradeMode`: `0` cross, `1` isolated).
- `POST /v5/position/switch-mode` — one-way (`0`) vs hedge (`3`) position mode.
- `POST /v5/position/set-tpsl-mode` — set `Full` vs `Partial` TP/SL mode at the symbol/position level.
- `POST /v5/position/set-auto-add-margin` — auto-add-margin toggle for isolated positions (supported on demo trading, per section 2).
- `POST /v5/position/set-risk-limit` — select a risk-limit tier (see section 4 risk-limit endpoint for the tier table) which controls max leverage available at a given position size.
- **`POST /v5/position/trading-stop`** — https://bybit-exchange.github.io/docs/v5/position/trading-stop — sets TP/SL/trailing-stop for a position (as opposed to attaching to an order at creation time):
  - `category` (`linear`/`inverse`/`option`; option supports `tpslMode=Full` only), `symbol`, `tpslMode` (`Full`/`Partial`), `positionIdx`.
  - `takeProfit`/`stopLoss`: price; `0` cancels that leg. `trailingStop`: trailing distance by price (not percentage); `0` cancels. `activePrice`: price at which the trailing stop itself becomes active/armed.
  - `tpSize`/`slSize` (Partial mode only, must be equal to each other), `tpLimitPrice`/`slLimitPrice` + `tpOrderType`/`slOrderType` (`Market` default or `Limit`, Limit only valid with Partial mode).
  - Internally these create system-managed conditional orders; the system cancels/adjusts them automatically when the position closes or changes size. One-sided modification of an existing paired TP/SL via this API breaks the paired binding relationship between the TP and SL legs.
  - Trailing-stop mechanics: trailing stop is defined as a **price distance**, not a percentage; `activePrice` gates when the trailing logic starts tracking. This differs from TradingView-style percent trailing stops — CandleViewer's rule-based stops/exits engine needs a translation layer to expose a percent-trailing UX on top of Bybit's absolute-distance API.
- `GET /v5/position/closed-pnl` — https://bybit-exchange.github.io/docs/v5/position/close-pnl — historical realized PnL per closed position, used for the auto-tracker/journal feature.

## 7. REST — Account & Asset endpoints

Source: https://bybit-exchange.github.io/docs/v5/account/wallet-balance , https://bybit-exchange.github.io/docs/v5/account/fee-rate , https://bybit-exchange.github.io/docs/v5/account/transaction-log , https://bybit-exchange.github.io/docs/v5/account/account-info , https://bybit-exchange.github.io/docs/v5/account/upgrade-unified-account , https://bybit-exchange.github.io/docs/v5/asset/transfer/create-inter-transfer

**Account:**
- `GET /v5/account/wallet-balance` — `accountType` (`UNIFIED`/`CONTRACT`), returns per-coin `equity`, `walletBalance`, `availableToWithdraw`, `unrealisedPnl`, and UTA-level `totalEquity`/`totalMarginBalance`/`accountIMRate`/`accountMMRate`.
- `GET /v5/account/fee-rate` — maker/taker fee rate per symbol/category (`makerFeeRate`/`takerFeeRate`), reflects VIP tier discounts.
- `GET /v5/account/transaction-log` — UTA ledger of all cash-flow-affecting events (trades, funding, transfers) — `cashFlow` field ties to `execPnl` in the execution WS stream (see sections 9/10).
- `GET /v5/account/account-info` — `unifiedMarginStatus`, `marginMode`, `isMasterTrader`, etc.
- `POST /v5/account/upgrade-unified-account` — irreversible upgrade from Classic/CONTRACT account to UTA.
- `POST /v5/account/set-margin-mode` — `REGULAR_MARGIN` / `PORTFOLIO_MARGIN` account-level mode.
- `POST /v5/account/demo-apply-money` — demo-trading faucet (section 2).

**Asset (subset relevant to a trading terminal; full asset API surface is broader — deposits/withdrawals/coin info):**
- `POST /v5/asset/transfer/inter-transfer` — transfer funds between master/sub UIDs or between account types (UNIFIED/FUND/CONTRACT).
- `GET /v5/asset/transfer/query-transfer-coin-list`, `GET /v5/asset/transfer/query-inter-transfer-list` — transfer history/available coins.
- `GET /v5/asset/coin/query-info` — coin metadata (chains, withdrawal min, confirmations) — lower priority for a trading-only terminal but useful for a deposits/withdrawals admin screen if ever added.

## 8. REST — User / Sub-account endpoints

Source: https://bybit-exchange.github.io/docs/v5/user/create-subuid , https://bybit-exchange.github.io/docs/v5/user/create-subuid-apikey , https://bybit-exchange.github.io/docs/v5/user/apikey-info , https://bybit-exchange.github.io/docs/v5/user/query-api

- `POST /v5/user/create-sub-member` — master-account-only; creates a sub-UID (used for the few-account-managers requirement — each manager could be modeled as a sub-account with scoped API keys rather than sharing the master key).
- `POST /v5/user/create-sub-api` — master-account-only; creates an API key for a given `subuid`, with `readOnly` flag (`0` read+write, `1` read-only) and a `permissions` object selecting granular scopes (e.g. `ContractTrade`, `Order`, `Position`, `Wallet`, `Options`, `Derivatives`, `Exchange`, `NFT`, `Spot`, `Affiliate`).
- `GET /v5/user/query-api` — apikey-info: returns the calling key's permissions, IP whitelist, expiry, and `unified` flag.
- `GET /v5/user/get-member-type` — distinguishes master vs sub UID.
- Sub-account API rate limits: a **master account can query the API rate limit of itself and its sub-accounts**; a **sub-account can only query its own** rate limit (per tiagosiebler/bybit-api source notes).
- **CandleViewer implication:** the few-account-managers requirement maps naturally onto Bybit sub-accounts plus scoped, possibly read-only or trade-only (no-withdraw) API keys per manager, created and revoked from the master account, rather than building a separate multi-tenant auth layer — worth validating whether sub-account API keys can independently hit demo-trading endpoints or whether demo mode is only available to the top-level master account (open question, see section 22).

## 9. WebSocket — Public streams

Source: https://bybit-exchange.github.io/docs/v5/ws/connect , https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook , https://bybit-exchange.github.io/docs/v5/websocket/public/trade , https://bybit-exchange.github.io/docs/v5/websocket/public/ticker , https://bybit-exchange.github.io/docs/v5/websocket/public/kline , https://bybit-exchange.github.io/docs/v5/websocket/public/liquidation

Connection endpoints (see section 2 table): one connection per `channel_type` (`spot`, `linear`, `inverse`, `option`, `spread`, `rfq`). A single connection can subscribe to multiple topics via the `args` array in the `subscribe` op, e.g. `{"op":"subscribe","args":["orderbook.50.BTCUSDT","publicTrade.BTCUSDT"]}`.

### Orderbook (`orderbook.{depth}.{symbol}`)
https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook

Depths and push frequency:

| Category | Depth | Push frequency |
|---|---|---|
| Linear & Inverse | 1 | 10ms |
| Linear & Inverse | 50 | 20ms |
| Linear & Inverse | 200 | 100ms |
| Linear & Inverse | 1000 | 200ms |
| Spot | 1 | 10ms |
| Spot | 50 | 20ms |
| Spot | 200 | 100ms |
| Spot | 1000 | 200ms |
| Option | 25 | 20ms |
| Option | 100 | 100ms |

- First message after subscribing is a `snapshot`; subsequent messages are `delta`. On receiving a new `snapshot`, the local book must be reset and rebuilt.
- Level-1 (depth=1) for linear/inverse/spot has **snapshot messages only** (no deltas) — if 3 seconds pass with no book change, a snapshot with the same `u` value is re-pushed as a keepalive.
- Response fields: `topic`, `type` (`snapshot`/`delta`), `ts`, `data.s` (symbol), `data.b`/`data.a` (bids/asks as `[price, size]`, size `"0"` means fully removed at that price), `data.u` (update ID, monotonically increasing per symbol — use to detect gaps/resync), `data.seq` (cross-sequence — smaller seq means generated earlier; useful to compare across depth-level subscriptions), `cts` (matching-engine timestamp, correlates with `T` in the public trade stream).
- RPI (Retail Price Improvement) orders are excluded from the standard orderbook feed; see the dedicated **RPI Orderbook** subsection below for the confirmed topic name/schema.

### RPI Orderbook (`orderbook.rpi.{symbol}`) — **[CONFIRMED 2026-09-14, resolves prior open question]**
Source: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook-rpi
- Topic: `orderbook.rpi.{symbol}`, e.g. `orderbook.rpi.BTCUSDT`. Available for **Spot, Perpetual & Futures**. Depth: fixed **Level 50**. Push frequency: **100ms**.
- Subscribe example: `{"op":"subscribe","args":["orderbook.rpi.BTCUSDT"]}`.
- Response: `topic`, `type` (`snapshot`/`delta`), `ts`, `data.s` (symbol), `data.b`/`data.a` — each entry is `[price, size, rpiSize]` (a 3-element array, unlike the standard orderbook's 2-element `[price, size]`): index `[1]` is always `"0"`/None as a placeholder in the RPI feed and index `[2]` carries the actual RPI size; a delta entry with size `0` means all RPI quotes at that price were filled/cancelled. When an RPI order on one side crosses a non-RPI order on the opposite side, that RPI quantity becomes invalid and is hidden from the feed. `data.u` (update ID — occasionally resets to `1` on a service restart, signalling the client must treat it as a fresh snapshot and overwrite the local book), `data.seq` (cross-sequence), `cts` (matching-engine timestamp, correlates with `T` in public trade channel).
- **CandleViewer implication:** this is the correct feed to combine with the standard `orderbook.{depth}.{symbol}` topic for a DeepDOM-style heatmap that visually distinguishes RPI liquidity from standard liquidity — RPI liquidity is invisible in the standard feed and must be sourced from this separate topic.

### Public trades (`publicTrade.{symbol}`)
- Real-time tape: `T` (timestamp ms), `s` (symbol), `S` (side `Buy`/`Sell` — taker side), `v` (volume), `p` (price), `L` (tick direction), `i` (trade ID), `BT` (block trade flag), `RPI` flag for retail-price-improvement fills.

### Tickers (`tickers.{symbol}`)
- Snapshot + delta ticker updates: `lastPrice`, `bid1Price`/`bid1Size`, `ask1Price`/`ask1Size`, `volume24h`, `turnover24h`, `openInterest`, `fundingRate`, `nextFundingTime`, `markPrice`, `indexPrice`.

### Kline (`kline.{interval}.{symbol}`)
- Same interval set as REST kline. Push frequency roughly 1–60s depending on interval and activity; each message includes a `confirm` boolean indicating whether the candle is closed (final) or still forming — critical for correct live-candle rendering in the chart engine (must not treat unconfirmed candles as final closes).

### Liquidation — **[CONFIRMED 2026-09-14, resolves prior open question]**
Source: https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation (live-fetched; the old `/docs/v5/websocket/public/liquidation` URL 404s and does **not** appear anywhere in the current docs sitemap — confirming the legacy per-order `liquidation.{symbol}` topic has been fully retired from the current docs, not merely deprecated-but-documented-alongside).
- Current (and only documented) topic: **`allLiquidation.{symbol}`**, e.g. `allLiquidation.BTCUSDT`. Covers USDT contract / USDC contract / Inverse contract. Push frequency: **500ms**.
- *Footnote — corrected:* the previous revision hedged that the 2025 change "aggregates/replaces the old single-order liquidation feed" without confirming payload details; the live docs page confirms `allLiquidation` pushes **all liquidations that occur on Bybit** (not just the subscribing account's own related liquidations, and not pre-aggregated into a single bucket — each element in `data` is one liquidation event) at a 500ms cadence, superseding the old lower-frequency single-symbol `liquidation` topic entirely (no dual-publish; only `allLiquidation` is listed in the current WS Public nav alongside Orderbook/RPI Orderbook/Full Orderbook/Trade/Ticker/Kline/Insurance Pool/Order Price Limit/ADL Alert).
- Confirmed response schema: `topic` (string), `type` (string, always `"snapshot"`), `ts` (ms), `data` (array of objects): `T` (updated timestamp ms), `s` (symbol), `S` (position side `Buy`/`Sell` — a `Buy` update means a **long** position was liquidated), `v` (executed size, string), `p` (bankruptcy price, string).
- Example payload (from live docs):
```json
{
  "topic": "allLiquidation.ROSEUSDT",
  "type": "snapshot",
  "ts": 1739502303204,
  "data": [
    {"T": 1739502302929, "s": "ROSEUSDT", "S": "Sell", "v": "20000", "p": "0.04499"}
  ]
}
```
- **CandleViewer implication:** this is a direct, confirmed feed for the DeepCharts-style "stopruns"/liquidation-tracking feature — one WS subscription per symbol of interest, no polling needed; aggregate/bucket client-side for a heatmap or ticker-tape style liquidation feed.

### Options-specific
- Options Greeks-related public data flows through `category=option` public WS with the standard orderbook/ticker/kline topics using option symbols (e.g. `BTC-26DEC25-100000-C`).

## 10. WebSocket — Private streams

Source: https://bybit-exchange.github.io/docs/v5/websocket/private/position , https://bybit-exchange.github.io/docs/v5/websocket/private/order , https://bybit-exchange.github.io/docs/v5/websocket/private/execution , https://bybit-exchange.github.io/docs/v5/websocket/private/fast-execution , https://bybit-exchange.github.io/docs/v5/websocket/private/wallet , https://bybit-exchange.github.io/docs/v5/websocket/private/greek

All private topics require auth (see section 12) on the `/v5/private` connection. Two topic addressing styles exist for several streams:
- **All-In-One topic** (e.g. `position`, `order`, `execution`): pushes updates across all categories (spot/linear/inverse/option) on one subscription.
- **Categorised topic** (e.g. `position.linear`, `order.spot`, `execution.option`): scoped to one category.
- All-in-one and categorised topics for the same stream **cannot** be combined in a single subscribe request.

### Position (`position` / `position.{category}`)
- Pushed on any position change: size, `avgPrice`, `unrealisedPnl`, `markPrice`, `liqPrice`, `bustPrice`, `positionIdx`, `tpslMode`, `takeProfit`/`stopLoss`/`trailingStop`, `updatedTime`.

### Order (`order` / `order.{category}`)
- Pushed on order state transitions (`New`, `PartiallyFilled`, `Filled`, `Cancelled`, `Rejected`, `Triggered`, etc). Fields include `orderId`, `orderLinkId`, `symbol`, `price`, `qty`, `side`, `orderType`, `stopOrderType`, `ocoTriggerBy` (spot OCO), `tpslMode`, `parentOrderLinkId` (links attached TP/SL child orders back to a parent order for Futures/Options — noted caveat: amending TP/SL via Set Trading Stop does not change `parentOrderLinkId` for Futures, but for Options it does change it; if TP/SL is set via Set Trading Stop for a position with no originally-attached TP/SL, `parentOrderLinkId` is meaningless), `blockTradeId`, `brokerOrderPrice` (EU liquidity-provider specific field).

### Execution (`execution` / `execution.{category}`) and Fast Execution (`fast-execution` / `fast-execution.{category}`)
- `execution`: full fills stream — one message may contain multiple executions for a single order. Fields: `category`, `symbol`, `isLeverage`, `orderId`, `orderLinkId`, `side`, `orderPrice`, `orderQty`, `leavesQty`, `createType`, `orderType`, `stopOrderType`, `execFee`, `execId`, `execPrice`, `execQty`, `execPnl` (ties to `cashFlow` in the transaction log, section 7), `execType`, `execValue`, `execTime`, `isMaker`, `seq`, `marketUnit`, `feeCurrency`, and (per a 2025 doc sample) an `extraFees` array (e.g. GST/regional tax fee breakdown for some jurisdictions).
- `fast-execution`: https://bybit-exchange.github.io/docs/v5/websocket/private/fast-execution — a lower-latency variant of `execution` that pushes a reduced field set for latency-sensitive consumers; use `categorised_topic` to filter by category. Recommended for the live tape/fills panel where latency matters more than full field completeness; fall back to the full `execution` stream for the journal/audit trail.

### Wallet (`wallet`)
- Real-time wallet/margin balance updates (push-based version of `GET /v5/account/wallet-balance`).

### Greeks (`greeks`)
- https://bybit-exchange.github.io/docs/v5/websocket/private/greek — option account Greeks (delta/gamma/vega/theta) pushed in real time; only relevant if/when an options view is added.

## 11. WebSocket — Order Entry (Trade over WebSocket)

Source: **[CONFIRMED 2026-09-14]** https://bybit-exchange.github.io/docs/v5/websocket/trade/guideline (canonical URL — the "Websocket Trade Guideline" page under the docs sidebar's "WebSocket Stream → Trade" section; the previously-assumed `/v5/order-entry` slug 404s and does not exist), cross-checked against tiagosiebler/bybit-api README and pybit `_websocket_trading.py`.

*Footnote — corrected/expanded from live docs:*
- Endpoint: `wss://stream.bybit.com/v5/trade` (mainnet; regional variants `wss://stream.bybit.tr/v5/trade` for Turkey-registered users, `wss://stream.bybit.kz/v5/trade` for Kazakhstan-registered users), `wss://stream-testnet.bybit.com/v5/trade` (testnet).
- **Scope — confirmed:** Support: **USDT Contract, USDC Contract, Spot, Options, Inverse contract**. **Not supported: Demo Trading, Spread Trading.** (This directly confirms the report's earlier claim that Demo Trading has no WS Trade support — now sourced from the primary docs page rather than only the third-party SDK README.)
- **Auth:** send `{"op":"auth","args":["<api_key>", <expiry_ms_timestamp>, "<signature>"]}` (optionally with a client-supplied `reqId` for correlating the response). Response `retCode`: `0` = auth success, `20001` = repeat auth, `10004` = invalid sign, `10001` = param error. Response also includes `connId` (unique connection id).
- **Create/Amend/Cancel Order:** request shape is `{"reqId": "<optional, ≤36 chars, must be unique per connection>", "header": {"X-BAPI-TIMESTAMP": "<ms>", "X-BAPI-RECV-WINDOW": "5000 (default)", "Referer": "<broker only>"}, "op": "order.create" | "order.amend" | "order.cancel", "args": [<one order object, matching the equivalent REST request body>]}`. Response `data` mirrors the equivalent REST endpoint's `result` object.
- **Confirmed error codes specific to WS Trade:** `10403` (exceed IP rate limit — 3000 requests/s per IP), `10404` (unknown op type or unsupported category), `10429` (system-level frequency protection), `20006` (duplicate `reqId`), `10016` (internal server error / service restarting), `10019` (WS trade service restarting — in-flight requests unaffected, but new requests should be routed to a fresh connection).
- Response is delivered asynchronously over the same WS connection (a `reqId`-correlated ack), and actual state changes still surface via the private `order`/`execution` streams — i.e. WS Trade is an alternate transport for *sending* the request, not a replacement for the private data streams used to *confirm* results.
- `max_active_time` connection param (documented on the Connect page, applies to private stream and order-entry): customises how long the private/order-entry connection stays alive without heartbeats — range `30s` to `600s`.
- **CandleViewer implication:** WS Trade is an optimisation, not a requirement, for a single-user/few-manager terminal; REST Trade endpoints (section 5) plus private WS streams (section 10) for confirmation are sufficient for v1. WS Trade could be added later for latency-sensitive scalping features if the roadmap calls for it. Note it cannot be used for demo-trading order flow — demo mode must always use REST for order placement.

## 12. Authentication & signing

Source: **[CONFIRMED 2026-09-14]** https://bybit-exchange.github.io/docs/v5/guide (the "Integration Guidance" page — canonical current location of the authentication guide; the previously-assumed `/v5/guide/authentication` slug 404s. Live-fetched and cross-checked against tiagosiebler/bybit-api and pybit source for WS-specific behavior not covered on this REST-focused page).

- **REST auth** uses request headers, confirmed verbatim from the live docs:
  - `X-BAPI-API-KEY`: the API key.
  - `X-BAPI-TIMESTAMP`: UTC timestamp in milliseconds.
  - `X-BAPI-RECV-WINDOW`: **confirmed default value is 5,000 ms** (footnote — corrected: the prior revision said "commonly `5000`" hedged as an SDK convention; the live Integration Guidance page states this explicitly as Bybit's own documented default, not merely an SDK habit). Smaller values are more secure but riskier if transmission time exceeds the window.
  - `X-BAPI-SIGN`: signature computed over `timestamp + api_key + recv_window + queryString` (GET) or `timestamp + api_key + recv_window + jsonBodyString` (POST).
  - `X-Referer` / `Referer`: broker-user-only header.
  - Two supported signing algorithms: **HMAC-SHA256** (secret-key based; convert to a lowercase HEX string) and **RSA_SHA256** (for users who generate an RSA keypair via Bybit's `api-rsa-generator` tool instead of a plain secret; convert to base64).
  - **Confirmed validity rule** (exact wording from live docs): `server_time - recv_window <= timestamp < server_time + 1000`, i.e. the timestamp must lie in `[server_time - recv_window, server_time + 1000)`. `server_time` is queryable via `GET /v5/market/time`. Bybit explicitly recommends keeping the local device clock NTP-synchronized at all times rather than relying solely on querying server time per request.
  - **Confirmed worked example from the live docs** (illustrates the exact string-to-sign construction):
    - GET: `timestamp="1658384314791"`, `api_key="XXXXXXXXXX"`, `recv_window="5000"`, `queryString="category=option&symbol=BTC-29JUL22-25000-C"` → string-to-sign = `"1658384314791XXXXXXXXXX5000category=option&symbol=BTC-29JUL22-25000-C"`.
    - POST: `timestamp=1658385579423`, `api_key=XXXXXXXXXX`, `recv_window=5000`, `jsonBodyString={"category":"option"}` → string-to-sign = `"1658385579423XXXXXXXXXX5000{"category":"option"}"`.
  - REST base endpoints (confirmed, with several regional variants not previously listed): Mainnet `https://api.bybit.com` / `https://api.bytick.com` (both mainnet-equivalent); regional-user-specific mainnet hosts also exist: `api.bybit.nl` (Netherlands), `api.bybit.tr` (Turkey), `api.bybit.kz` (Kazakhstan), `api.bybitgeorgia.ge` (Georgia), `api.bybit.ae` (UAE), `api.bybit.eu` (EEA — API-broker "Connect to Third-Party Applications" only), `api.bybit.id` (Indonesia), `api.manepa.jp`/`api-testnet.manepa.jp` (Japan), `api.spark-fintech.com`/`api-testnet.spark-fintech.com` (Hong Kong); Testnet `https://api-testnet.bybit.com`. **IP addresses located in the US or Mainland China are explicitly restricted and receive a 403 Forbidden.**
- **WebSocket auth** (private + order-entry connections, confirmed against the WS Trade Guideline page in §11 — the same auth scheme applies to `/v5/private`): after connecting, send `{"op":"auth","args":[api_key, expires, signature]}` where `expires` is a future ms timestamp and `signature` = HMAC-SHA256 of the string `"GET/realtime" + expires` signed with the API secret. *Footnote — this classic pre-V5 WS auth string format is retained in V5 and is now cross-confirmed via the live WS Trade Guideline doc's auth section (§11), which shows the identical `op:"auth"` / `args:[api_key, expiry_ms, signature]` request/response shape and error codes, though that page itself does not restate the exact string-to-sign formula — it only says "click here to generate signature," linking to the same signature-generation reference used for REST.* Confirmed WS auth response codes: `0` success, `20001` repeat auth, `10004` invalid sign, `10001` param error.
- **Clock sync / `recv_window`:** as above — `GET /v5/market/time` calibrates client clocks; an NTP-style pre-flight check is recommended for the backend before starting a trading session (see also §19 pitfalls).
- **Permission scopes** are attached at the API-key level (see §8/§18) — signing does not vary by scope, but requests will be rejected with a permission error if the key lacks the relevant scope (e.g. read-only key attempting `/v5/order/create`).

## 13. Rate limits

Source: https://bybit-exchange.github.io/docs/v5/rate-limit

### Full per-endpoint rate table — **[CONFIRMED 2026-09-14, live-fetched in full; resolves the "only representative excerpt" gap]**

Source: https://bybit-exchange.github.io/docs/v5/rate-limit (fetched and reproduced in full below — this supersedes the prior "illustrative" partial Trade-group table).

**HTTP IP limit (global, all endpoints):** 600 requests per 5-second window per IP by default, applying to `api.bybit.com`, `api.bytick.com`, and local-site hostnames (e.g. `api.bybit.kz`). Exceeding it returns `403 access too frequent`; Bybit recommends terminating all HTTP sessions and waiting ≥10 minutes for the ban to lift automatically — do not run at the edge of this limit.

**Trade** (Method/Path/UTA2.0 Pro limits by category/Upgradable):

| Method | Path | inverse | linear | option | spot | Upgradable |
|---|---|---|---|---|---|---|
| POST | `/v5/order/create` | 10/s | 10/s | 20/s | 10/s | Y |
| POST | `/v5/order/amend` | 10/s | 10/s | 10/s | 10/s | Y |
| POST | `/v5/order/cancel` | 10/s | 10/s | 20/s | 10/s | Y |
| POST | `/v5/order/cancel-all` | 10/s | 1/s | 20/s | 10/s | Y |
| POST | `/v5/order/create-batch` | 10/s | 10/s | 20/s | — | Y |
| POST | `/v5/order/amend-batch` | 10/s | 10/s | 20/s | — | Y |
| POST | `/v5/order/cancel-batch` | 10/s | 10/s | 20/s | — | Y |
| POST | `/v5/order/disconnected-cancel-all` | 5/s | — | — | — | N |
| POST | `/v5/order/pre-check` | 10/s | 10/s | 20/s | — | Y |
| GET | `/v5/order/realtime` | 50/s | | | | N |
| GET | `/v5/order/history` | 50/s | | | | N |
| GET | `/v5/execution/list` | 50/s | | | | N |
| GET | `/v5/order/spot-borrow-check` | — | — | — | 50/s | N |
| POST | `/v5/fcombobot/*` (getlimit/create/close/detail) | 10/s (linear only) | | | | N |
| POST | `/v5/fgridbot/*` (validate/create/close/detail) | 10/s (linear only) | | | | N |
| POST | `/v5/fmartingalebot/getlimit`/`close`/`detail` | 10/s (linear only) | | | | N |
| POST | `/v5/fmartingalebot/create` | 100/s (linear only) | | | | N |
| POST/GET | `/v5/grid/*` (validate-input, create-grid, close-grid, query-grid-detail) | 100/s (validate) / 3/s (create/close) / 10/s (query) — spot only | | | | N |
| POST | `/v5/dca/create-bot`, `/v5/dca/close-bot` | 3/s (spot only) | | | | N |
| POST/GET | `/v5/strategy/*` (create, list, order-list, stop) | 100/s (create/stop), 200/s (list/order-list) — inverse+option | | | | N |

**Position:**

| Method | Path | Limit | Upgradable |
|---|---|---|---|
| GET | `/v5/position/list` | 50/s | N |
| GET | `/v5/position/closed-pnl` | 50/s | N |
| GET | `/v5/position/get-closed-positions` (spot) | 50/s | N |
| GET | `/v5/position/move-history` | 10/s | N |
| POST | `/v5/position/set-leverage` | 10/s | N |
| POST | `/v5/position/switch-mode` | 10/s | N |
| POST | `/v5/position/trading-stop` | 10/s | N |
| POST | `/v5/position/set-auto-add-margin` | 10/s | N |
| POST | `/v5/position/add-margin` | 10/s | N |
| POST | `/v5/position/confirm-pending-mmr` | 10/s | N |
| POST | `/v5/position/move-positions` | 10/s | N |

**Account:**

| Method | Path | Limit | Upgradable |
|---|---|---|---|
| GET | `/v5/account/wallet-balance` (accountType=UNIFIED) | 50/s | N |
| GET | `/v5/account/withdrawal` | 50/s | N |
| GET | `/v5/account/borrow-history` | 50/s | N |
| POST | `/v5/account/borrow` | 1/s | N |
| POST | `/v5/account/repay` | 1/s | N |
| POST | `/v5/account/no-convert-repay` | 1/s | N |
| GET | `/v5/account/collateral-info` | 50/s | N |
| GET | `/v5/asset/coin-greeks` | 50/s | N |
| GET | `/v5/account/transaction-log` (accountType=UNIFIED) | 25/s | N |
| GET | `/v5/account/fee-rate` | 5/s | N |
| GET | `/v5/account/info` | 50/s | N |
| GET | `/v5/account/instruments-info` | 10/s | N |
| GET | `/v5/account/mmp-state` | unlimited | N |
| GET | `/v5/account/option-asset-info` | unlimited | N |
| GET | `/v5/account/pay-info` | 50/s | N |
| GET | `/v5/account/query-dcp-info` | 5/s | N |
| GET | `/v5/account/smp-group` | 5/s | N |
| GET | `/v5/account/trade-info-for-analysis` | 50/s | N |
| GET | `/v5/account/user-setting-config` | 50/s | N |
| POST | `/v5/account/mmp-modify` | 5/s | N |
| POST | `/v5/account/mmp-reset` | 5/s | N |
| POST | `/v5/account/quick-repayment` | 1/s | N |
| POST | `/v5/account/set-collateral-switch` | unlimited | N |
| POST | `/v5/account/set-collateral-switch-batch` | 5/s | N |
| POST | `/v5/account/set-delta-mode` | unlimited | N |
| POST | `/v5/account/set-hedging-mode` | unlimited | N |
| POST | `/v5/account/set-limit-px-action` | 10/s | N |
| POST | `/v5/account/set-margin-mode` | 5/s | N |
| POST | `/v5/account/upgrade-to-uta` | 1/s | N |

**Asset** (all `N` = not upgradable):

| Method | Path | Limit |
|---|---|---|
| GET | `/v5/asset/transfer/query-asset-info` | 60 req/min |
| GET | `/v5/asset/transfer/query-transfer-coin-list` | 60 req/min |
| GET | `/v5/asset/transfer/query-inter-transfer-list` | 60 req/min |
| GET | `/v5/asset/transfer/query-sub-member-list` | 60 req/min |
| GET | `/v5/asset/transfer/query-universal-transfer-list` | 5 req/s |
| GET | `/v5/asset/transfer/query-account-coins-balance` | 5 req/s |
| GET | `/v5/asset/transfer/query-account-coin-balance` | 450 req/s |
| GET | `/v5/asset/asset-overview` | 50 req/s |
| GET | `/v5/asset/withdraw/withdrawable-amount` | 300 req/s |
| GET | `/v5/asset/deposit/query-record` | 100 req/min |
| GET | `/v5/asset/deposit/query-sub-member-record` | 300 req/min |
| GET | `/v5/asset/deposit/query-address` | 300 req/min |
| GET | `/v5/asset/deposit/query-sub-member-address` | 300 req/min |
| GET | `/v5/asset/withdraw/query-record` | 300 req/min |
| GET | `/v5/asset/coin/query-info` | 5 req/s |
| GET | `/v5/asset/exchange/order-record` | 600 req/min |
| GET | `/v5/asset/exchange/query-coin-list` | 30 req/s |
| GET | `/v5/asset/covert/small-balance-history` | 5 req/s |
| GET | `/v5/asset/covert/small-balance-list` | 10 req/s |
| GET | `/v5/asset/delivery-record` | 50 req/s |
| GET | `/v5/asset/deposit/query-internal-record` | 300 req/s |
| GET | `/v5/fiat/balance-query`, `query-coin-list`, `trade-query`, `query-trade-history` | 1000 req/s each |
| GET | `/v5/asset/fundinghistory` | 30 req/s |
| GET | `/v5/asset/portfolio-margin` | 50 req/s |
| GET | `/v5/asset/settlement-record` | 50 req/s |
| GET | `/v5/asset/total-members-assets` | 50 req/s |
| GET | `/v5/asset/withdraw/vasp/list` | 1 req/s |
| GET | `/v5/asset/withdraw/query-address` | 300 req/s |
| POST | `/v5/asset/transfer/inter-transfer` | 60 req/min |
| POST | `/v5/asset/transfer/save-transfer-sub-member` | 20 req/s |
| POST | `/v5/asset/transfer/universal-transfer` | 5 req/s |
| POST | `/v5/asset/withdraw/create` | 5 req/s |
| POST | `/v5/asset/withdraw/cancel` | 60 req/min |
| POST | `/v5/asset/exchange/quote-apply` | 20 req/s |
| POST | `/v5/asset/exchange/convert-execute` | 20 req/s |
| POST | `/v5/asset/covert/small-balance-execute` | 5 req/s |
| POST | `/v5/asset/covert/get-quote` | 5 req/s |
| POST | `/v5/asset/deposit/deposit-to-account` | 300 req/s |
| POST | `/v5/fiat/trade-execute` | 100 req/s |
| POST | `/v5/fiat/quote-apply` | 1000 req/s |
| GET | `/v5/asset/exchange/convert-result-query` | 50 req/s |
| GET | `/v5/asset/exchange/query-convert-history` | 50 req/s |
| GET | `/v5/fiat/reference-price` | 1000 req/s |

**User** (all `N` = not upgradable):

| Method | Path | Limit |
|---|---|---|
| POST | `/v5/user/create-sub-member` | 1 req/s |
| POST | `/v5/user/create-sub-api` | 1 req/s |
| POST | `/v5/user/frozen-sub-member` | 5 req/s |
| POST | `/v5/user/update-api` | 5 req/s |
| POST | `/v5/user/update-sub-api` | 5 req/s |
| POST | `/v5/user/delete-api` | 5 req/s |
| POST | `/v5/user/delete-sub-api` | 5 req/s |
| GET | `/v5/user/query-sub-members` | 10 req/s |
| GET | `/v5/user/query-api` | 10 req/s |
| GET | `/v5/user/aff-customer-info` | 10 req/s |
| POST | `/v5/user/agreement` | 20 req/s |
| GET | `/v5/user/submembers` | 5 req/s |
| GET | `/v5/user/escrow_sub_members` | 5 req/s |
| GET | `/v5/user/sub-apikeys` | 10 req/s |
| GET | `/v5/user/get-member-type` | 10 req/s |
| POST | `/v5/user/del-submember` | 5 req/s |
| GET | `/v5/user/invitation/referrals` | 10 req/s |

(Spot Margin Trade, Spread Trading, RFQ, and Institutional Loan groups also have documented per-endpoint limits on the same page, generally in the 1–50 req/s range; omitted here as out of scope for CandleViewer's initial feature set — re-fetch https://bybit-exchange.github.io/docs/v5/rate-limit directly if those product lines are added later.)

### WebSocket IP limits — confirmed
- Do not establish more than **500 connections within a 5-minute window** per IP to `stream.bybit.com` (and local-site hostnames like `stream.bybit.kz`).
- Do not establish more than **1,000 connections per IP** for market data; connection limits are counted **separately per market** (Spot, Linear, Inverse, Options each have their own 1,000-connection ceiling).
- Avoid frequent connect/disconnect cycling — treat WS connections as long-lived and reconnect with backoff, not per-request.

### API rate limit (REST) — mechanics
- Based on a **rolling time window per second, per UID** (not per API key — multiple keys on the same UID share the budget).
- Error `{"retCode": 10006, "retMsg": "Too many visits!"}` signals the limit was hit.
- Every response includes headers to self-throttle:
  - `X-Bapi-Limit`: total quota for that endpoint/window.
  - `X-Bapi-Limit-Status`: remaining quota in the current window.
  - `X-Bapi-Limit-Reset-Timestamp`: ms timestamp when the window resets.
  - CandleViewer's REST client should read these headers on every response and proactively back off/queue requests as `X-Bapi-Limit-Status` approaches zero, rather than waiting for a 10006 error.

### Batch order limit consumption
- Batch endpoints (create/amend/cancel-batch) allow 1–10 orders per request; each order in the batch consumes one unit of the per-second quota (a 5-order batch consumes 5 units). If the remaining quota within the current second is less than the batch size, the orders within quota succeed and the excess fail with a limit-exceeded error per-order (partial success, not atomic).

### Order count / open-order caps
- Perps & Futures: max 500 active orders per symbol per account; max 10 active conditional orders per symbol.
- Spot: 500 orders in total, incl. max 30 open TP/SL orders and max 30 open conditional orders per symbol.
- Option: max 50 open orders in the coin dimension by default.
- Bybit reserves the right to warn/restrict accounts (main + aggregated sub-accounts) whose total daily order count (UTC 0–24) exceeds an internal threshold — treat high-frequency strategies with care even if within the second-by-second rate limit.
- To raise rate limits beyond default tiers, contact a Bybit client manager or apply via the institutional portal (https://www.bybit.com/en/institutional) — not self-service via the API.
- Third-party SDK note (informational, not an official Bybit guarantee): tiagosiebler/bybit-api's README claims requests routed through that SDK receive automatically higher rate limits (up to 400 req/s) "than the highest VIP tier" as an SDK-specific partnership benefit — this is a third-party claim, not documented on Bybit's own rate-limit page, and should not be relied upon for capacity planning without independent verification.

## 14. Heartbeats, reconnects, orderbook sequencing

Source: https://bybit-exchange.github.io/docs/v5/ws/connect , https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook , pybit `_websocket_stream.py`

- **Ping/pong:** clients should send a WS-level ping (`{"op":"ping"}`) at a regular interval (commonly every 20s, as implemented in official SDKs) to keep the connection alive; Bybit responds with a `pong` message. If no ping is sent, idle connections may be dropped by Bybit's infrastructure or load balancers even though no explicit fixed idle-timeout figure is guaranteed in the docs — always implement an active ping loop rather than relying on a passive connection.
- **`max_active_time`:** for private and order-entry connections, a connection-level parameter that sets how long the connection stays alive without a heartbeat, configurable from `30s` up to `600s` (10 minutes).
- **Reconnect strategy:** on disconnect, reconnect with exponential backoff, re-authenticate (private/order-entry), and **re-subscribe to all topics** — Bybit does not resume a dropped subscription automatically. After resubscribing to an orderbook topic, the first message received will be a fresh `snapshot`, which should fully replace the locally held book state.
- **Orderbook snapshot/delta merge algorithm** (derived from the orderbook doc, §9):
  1. On `snapshot`, discard any existing local book for that symbol/depth and initialize from the snapshot's `b`/`a` arrays.
  2. On each `delta`, for each `[price, size]` pair: if `size == "0"`, remove that price level; otherwise upsert (insert or replace) that price level.
  3. Track `u` (update ID) per symbol; if a gap is detected in `u` sequencing (implementation-specific — the docs do not document a strict "u must be exactly prior+1" contract for all depths/categories the way some other exchanges do), the safest behavior is to resubscribe and wait for a fresh snapshot rather than attempting to patch a possibly-corrupted book.
  4. Use `seq` (cross-sequence) only to compare relative recency across different depth-level subscriptions of the same symbol, not as a strict per-message increment-by-one contract.
  5. There is no explicit checksum field (e.g. CRC32) documented for Bybit V5 orderbook messages unlike some other exchanges' WS APIs (e.g. OKX's `checksum` field) — Bybit relies on the snapshot/delta + `u` sequencing model instead; do not assume a checksum-based integrity mechanism exists.
- **1s vs 100ms ticker distinction:** the `tickers` topic and derived REST 24h-ticker figures are computed on Bybit's server side at whatever internal cadence Bybit uses (not separately documented as "1s" vs "100ms" tiers publicly for `tickers` — that finer-grained distinction applies specifically to the **orderbook** depth/frequency table in §9, e.g. level-1 pushed at 10ms vs level-1000 at 200ms). Do not conflate ticker push cadence with orderbook depth cadence when building the UI's update-throttling logic — throttle chart/DOM re-renders independently per stream type.

## 15. Historical data availability & bulk downloads

Source: https://bybit-exchange.github.io/docs/v5/market/kline , https://bybit-exchange.github.io/docs/v5/market/recent-trade , https://www.bybit.com/derivatives/en/history-data (Historical Data Download portal)

- **Kline via REST:** max **1000 bars per request** (`limit` param, §4); no documented absolute historical depth limit beyond a symbol's own listing date — must page backwards with repeated `start`/`end`-bounded requests to backfill full history for a symbol. This is the same chunking pattern ccxt's `fetchOHLCV` implements internally for Bybit.
- **Recent trades via REST:** capped at the most recent up to 1000 trades (500 default for spot) — **there is no REST endpoint for historical tick-by-tick trade data** beyond this rolling window. Any tick-level trade history further back must either be (a) recorded live by CandleViewer's own ingestion pipeline going forward, or (b) sourced from Bybit's bulk historical-data downloads.
- **Bulk historical data downloads:** Bybit publishes daily CSV/data files at `https://public.bybit.com/trading/` (referenced by the "Historical Data Download" portal at https://www.bybit.com/derivatives/en/history-data) covering:
  - **Public Trading History** (Spot & Contract) — per-symbol, per-day trade-tick CSV files.
  - **Premium Index Price Kline** (Contract) — historical premium index kline data.
  - **Index Price Kline** (Contract) — historical index price kline data.
  - **OrderBook data** (Spot & Contract) — historical order-book snapshots/deltas.
  - **[CONFIRMED 2026-09-14 — resolves prior open question]** CSV column schemas were verified by directly downloading and inspecting live sample files (2026-09-08 dated files) from both directories:
    - **Contract/derivatives trade-tick files** at `https://public.bybit.com/trading/{SYMBOL}/{SYMBOL}{YYYY-MM-DD}.csv.gz` (e.g. `https://public.bybit.com/trading/BTCUSDT/BTCUSDT2026-09-08.csv.gz`) — confirmed header row: `timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional,RPI`. `timestamp` is a Unix epoch **in seconds with a fractional/decimal component** (e.g. `1788825600.4491`, not milliseconds); `grossValue` appeared in scientific notation in the sample (e.g. `4.0327026e+11`) and needs a robust float parser, not a naive integer/string parser; `RPI` is a 0/1 flag added since the RPI feature launched (footnote: this confirms the trade-history file format the previous revision guessed at was correct in column *names* but did not know the `RPI` column existed or the timestamp's seconds-with-decimal format).
    - **Spot trade-tick files** at `https://public.bybit.com/spot/{SYMBOL}/{SYMBOL}_{YYYY-MM-DD}.csv.gz` (note the underscore before the date, and the different directory — `spot/` not `trading/`; e.g. `https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-09-08.csv.gz`) — confirmed header row: `id,timestamp,price,volume,side,rpi`. Here `timestamp` is in **milliseconds** as a plain integer (e.g. `1788825600335`), unlike the derivatives file's fractional-seconds format above — CandleViewer's ETL parser must branch on directory/product-line to apply the correct timestamp-unit conversion, it cannot assume a single uniform format across both file sets.
    - Both file sets are daily, gzip-compressed, and enumerable via a directory listing at the parent URL (`https://public.bybit.com/trading/{SYMBOL}/` or `https://public.bybit.com/spot/{SYMBOL}/`), which is scriptable for a bulk-download ETL job (no auth required, plain HTTP GET).
    - OrderBook and Premium/Index-Price-Kline bulk files (also referenced on the download portal) were not individually inspected in this pass — the trade-tick schema above is the one most directly relevant to CandleViewer's footprint/Deep-Print backfill needs; re-check the orderbook-snapshot file schema specifically before building an order-book-history backfill job.
  - This bulk-download path is the practical answer to "how do I backfill a full historical tick database" for CandleViewer's footprint/Deep-Print-style features (which need historical trade-level granularity DeepCharts-style, not just OHLC candles) — the REST/WS APIs alone cannot provide multi-year tick history; the bulk files must be ingested into CandleViewer's own datastore as a one-time/periodic ETL job.
- **Practical architecture implication:** CandleViewer needs its **own persistent trade/orderbook recording layer** fed continuously by the public WS streams (§9) from day one of going live with a symbol, since Bybit's own REST history for anything below kline-granularity is effectively real-time-only. The bulk CSV downloads are best used to backfill the gap between "project start date" and "earliest live-recorded data," not as an ongoing data source.

## 16. Python SDKs & libraries

Source: https://github.com/bybit-exchange/pybit , https://github.com/tiagosiebler/bybit-api , https://docs.ccxt.com/docs/exchanges/bybit , https://github.com/ccxt/ccxt

### pybit (official)
- Repo: https://github.com/bybit-exchange/pybit — Bybit's official Python3 connector for HTTP and WebSocket V5 APIs.
- Structure: `pybit.unified_trading` module exposes `HTTP` (REST) and `WebSocket` (public/private streaming) classes covering the full V5 surface (`_v5_market.py`, `_v5_trade.py`, `_v5_position.py`, `_v5_account.py`, `_v5_asset.py`, `_v5_user.py` internal modules feeding the unified client).
- WebSocket client supports `testnet` and `demo` boolean flags (subdomains `stream-testnet`, `stream-demo`, `stream-demo-testnet` are defined internally in `_websocket_stream.py`), RSA and HMAC auth, auto-reconnect with resubscribe, and a custom ping timer.
- Does **not** appear to expose a dedicated WS Trade (order-entry) client class in the same module as the market-data/private WS client based on the source layout inspected (`_websocket_trading.py` exists as a separate module) — treat WS order entry support in pybit as present but architecturally distinct from the main `WebSocket` class; confirm exact class name/usage at implementation time.
- Actively maintained; versioned via PyPI (`pip install pybit`) — pin an exact version in CandleViewer's backend `requirements.txt`/lockfile rather than floating, since Bybit's V5 surface (topic names, params) has changed within pybit's own version history (e.g. the 2025 liquidation-stream change noted in §9 would correspond to a pybit version bump).

### bybit-api (unofficial, tiagosiebler)
- Repo: https://github.com/tiagosiebler/bybit-api — Node.js/TypeScript SDK (not Python), included here because it is the most complete third-party reference implementation of the V5 REST+WS surface and its README/source is one of the best available cross-checks against the official docs (used extensively in this research for confirming edge-case behavior like the "demo trading does not support WS order-entry" note).
- Not directly usable from CandleViewer's Python backend unless the team chooses a Node-based data/execution microservice — flagged here purely as a documentation cross-reference source, not a recommended dependency.

### ccxt / ccxt.pro
- https://docs.ccxt.com/docs/exchanges/bybit — ccxt's unified `bybit` exchange class wraps the V5 REST API with ccxt's cross-exchange-normalized method names (`fetchOHLCV`, `createOrder`, `fetchBalance`, `fetchPositions`, etc.), plus Bybit-specific passthrough methods (`enableDemoTrading()`, `isUnifiedEnabled()`, `upgradeUnifiedTradeAccount()`, `createOrders()`/`editOrders()`/`cancelOrders()` for batch operations, `cancelAllOrdersAfter()` for the dead-man's-switch/DCP feature).
- **ccxt.pro** (paid tier of ccxt) adds WebSocket streaming (`watchOrderBook`, `watchTrades`, `watchTicker`, `watchOrders`, `watchMyTrades`, `watchPositions`, etc.) with the same unified interface — a pragmatic option if CandleViewer wants exchange-agnostic architecture (project scope explicitly wants "architecture must allow more crypto exchanges later") at the cost of losing some Bybit-specific fields/nuance that a native pybit integration would expose directly (e.g. `parentOrderLinkId`, `extraFees`, risk-limit tiers may not be first-class ccxt-normalized fields).
- **Recommendation for CandleViewer:** given the requirement to eventually support other exchanges, evaluate ccxt/ccxt.pro as the abstraction layer for read-mostly/order-management operations, but plan to drop down to a native pybit client (or raw REST/WS) for Bybit-specific advanced features that DeepCharts-parity requires (footprint/tape granularity, risk-limit tiers, trailing-stop-by-distance semantics, demo-trading faucet, sub-account management) which ccxt's unified layer likely does not fully expose.

## 17. Fees

Source: https://bybit-exchange.github.io/docs/v5/account/fee-rate , general Bybit fee-schedule pages (https://www.bybit.com/en/rates-fees, referenced for VIP-tier context — not fetched directly in this pass, flagged as an open question for final verification)

- `GET /v5/account/fee-rate` returns the calling account's current `makerFeeRate`/`takerFeeRate` per `symbol`/`category`, reflecting whatever VIP/market-maker tier the account currently sits at.
- Standard retail fee structure (subject to change — verify against the live fee-schedule page, not re-fetched in this research pass): tiered maker/taker fees that decrease with 30-day trading volume and/or BIT/token holdings, separately scheduled for Spot vs Derivatives (Perps/Futures) vs Options.
- Funding-rate payments (linear/inverse perpetuals) are a distinct cost/credit from trading fees — settled periodically per each symbol's `fundingInterval` (commonly 8h, some symbols shorter) and visible historically via `GET /v5/market/funding/history` (§4) and per-account via the `wallet`/`execution`/transaction-log flows (§7/§10) — `execType` on the execution stream can indicate a funding-fee-related entry versus a trade fill (exact `execType` enum values should be checked against the current docs at implementation time).
- Demo trading: fills are simulated but fee deduction presumably mirrors live fee rates against simulated balances (Bybit docs state "basic trading rules are the same as real trading" — treat fee simulation as included under that umbrella, though not explicitly itemized in the demo-trading doc).
- **Open item — attempted but not resolved in this pass:** the exact current numeric fee schedule (base-tier %, VIP tier thresholds) could not be independently re-verified this pass. Direct attempts to fetch Bybit's marketing fee-schedule pages (`https://www.bybit.com/en/fee-rate/vip-level`, `https://www.bybit.com/en/help-center/article/Fee-Rate-Structure`, and the underlying `https://www.bybit.com/data/basic/spot/fee-rate` data API) all either returned `403 Forbidden` or served a client-side-rendered app shell with no fee data in the initial HTML (fees are loaded via an authenticated/geo-gated JS bundle, not present in static markup) — these pages are not scrapeable via a simple HTTP GET and would need a headless browser or Bybit's own (undocumented, non-V5) internal fee-rate JSON API to extract. **Still recommend pulling fresh numbers at implementation time**, ideally by calling the documented `GET /v5/account/fee-rate` endpoint directly with a real API key (which returns the account's actual effective rate) rather than relying on the public marketing page, since that endpoint is the authoritative, scriptable source of truth for CandleViewer's own account regardless of what the public page shows.

## 18. API key permissions, IP whitelisting, sub-accounts

Source: https://bybit-exchange.github.io/docs/v5/user/apikey-info , https://bybit-exchange.github.io/docs/v5/user/create-subuid-apikey , https://bybit-exchange.github.io/docs/v5/user/query-api

- **API key creation** happens in the Bybit web UI (API Management page) or programmatically for sub-accounts via `POST /v5/user/create-sub-api` (master-account-only). Each key can be scoped with:
  - `readOnly`: `0` (read+write) or `1` (read-only) — a read-only key is a safe default for any dashboard-only/monitoring integration.
  - `permissions`: a structured object selecting specific scopes, e.g. `ContractTrade`, `Spot`, `Wallet`, `Options`, `Derivatives`, `Exchange`, `NFT`, `Affiliate` — CandleViewer should request the minimum scope set needed per key (e.g. a manager's key might get `ContractTrade` + `Position` but not `Wallet`/withdrawal-adjacent scopes, since Bybit API keys cannot withdraw funds by design but *can* internally transfer between UTA sub-accounts if that scope is granted).
  - **IP whitelist:** each API key can be bound to a specific set of allowed source IPs in the Bybit UI/API; requests from non-whitelisted IPs are rejected even with a valid signature. Strongly recommended for CandleViewer's backend given it runs self-hosted (fixed egress IP) — whitelist the WSL/host's public IP per key.
  - Keys can have an **expiry date** set (visible via `GET /v5/user/query-api` → `apikey-info`), useful for periodic credential-rotation hygiene for a small-team self-hosted deployment.
- **Sub-accounts:** created via `POST /v5/user/create-sub-member` (master-account-only). Each sub-account is a fully separate UID with its own wallet balance, positions, and orders, but funds can be moved between master and sub via `POST /v5/asset/transfer/inter-transfer` (§7). This is the natural mechanism for "a few account managers" each operating their own isolated sub-account under one Bybit master login, with the master account able to monitor/aggregate across all of them via master-scoped endpoints (e.g. querying sub-account rate limits, per §8).
- **Copy trading APIs — [CONFIRMED 2026-09-14, resolves prior open question]** Source: https://bybit-exchange.github.io/docs/v5/copytrade ("How To Start Copy Trading"). *Footnote — corrected:* the previous revision implied a distinct API surface with dedicated "lead-trader order broadcast / follower position sync" endpoints; the live docs reveal Copy Trading is **not** a separate API surface at all — it is a thin usage-mode wrapper around the same core V5 endpoints:
  1. Become a Master Trader via the Bybit web UI (application process, not an API call).
  2. Create an API key with the **"Contract - Orders & Positions"** permission (a mandatory scope for copy-trading orders).
  3. Copy trading accounts can currently only trade **USDT Perpetual** symbols — check the `copyTrading` boolean field returned by `GET /v5/market/instruments-info` to determine which symbols are eligible.
  4. Place orders using the **standard** `POST /v5/order/create` endpoint (§5) — there is no separate "broadcast" or "copy-order" endpoint; Bybit's own platform handles follower replication server-side once an order is placed by a recognized Master Trader API key.
  - **CandleViewer implication:** this does **not** offer a simpler path to the "few account managers" architecture beyond what plain sub-accounts + REST already provide — it is a consumer-facing social-trading feature (become a public Master Trader, followers opt in via Bybit's own UI/app), not a private API for one operator to fan out orders across their own managed sub-accounts. For CandleViewer's actual use case (a handful of trusted account managers operating their own isolated sub-accounts under one master login), plain sub-accounts (§8/§18, below) remain the correct mechanism — Copy Trading is not a shortcut for that and can be de-scoped from further research.

## 19. Pitfalls & operational notes

- **Clock sync:** signed requests are rejected outside the `recv_window` tolerance if local clock drift is too large; the backend should periodically sync against Bybit's server-time endpoint (or standard NTP) before/while running, especially inside a WSL Ubuntu environment where clock drift after host sleep/resume is a known class of issue.
- **Orderbook sequencing:** no checksum field is provided (unlike some other exchanges) — resilience relies entirely on correctly implementing the snapshot/delta merge with `u`/`seq` tracking (§14) and being willing to drop-and-resubscribe on any suspected desync rather than trying to silently self-heal a corrupted book.
- **1s vs 100ms — depth-dependent push cadence, not a single global tick rate:** different orderbook depths and categories publish at different fixed cadences (10ms/20ms/100ms/200ms per §9); a chart/DOM renderer must decouple its own render-throttling logic from the underlying feed cadence rather than assuming one fixed update rate across all depth subscriptions.
- **Kline `confirm` flag:** always check the `confirm` boolean on WS kline messages before treating a candle as closed/final — treating an unconfirmed candle as final will produce visibly "flickering"/incorrect candles as the still-forming bar continues to update.
- **Demo trading feature gaps:** WS Trade is not supported in demo (confirmed, §2/§11); batch order endpoints **are** supported in demo but only for `linear`/`option` categories (footnote — corrected, see §2/§6) — CandleViewer's demo-mode code path must fall back to single-order REST calls for spot/inverse batch scenarios and never attempt WS Trade against the demo host.
- **Async order acknowledgement:** `POST /v5/order/create` (and amend/cancel) only confirms the request was *accepted*, not that it was filled/rejected by the matching engine — always treat the private `order`/`execution` WS streams as the source of truth for actual order state, never the synchronous REST response body.
- **TP/SL pairing side effects:** one-sided modification of an existing paired TP/SL via `POST /v5/position/trading-stop` breaks the pairing relationship between the TP and SL legs (§6) — if CandleViewer's rule-based stop/exit engine needs to move just the SL while leaving the TP untouched, be aware the two legs may become independently manageable (no longer OCO-linked) after such a change, which could be a feature or a bug depending on the intended UX; decide explicitly rather than discovering this behavior in production.
- **Trailing stop is price-distance, not percentage** (§6) — any "trail by X%" feature in CandleViewer's custom rule-based stops needs a client-side translation layer that recomputes an absolute price distance from the current mark price whenever the percentage-based rule needs to update the underlying Bybit trailing-stop distance parameter.
- **Rate-limit is per UID, not per API key** (§13) — if a single UID uses both a "read-only monitoring" key and a "trading" key simultaneously (e.g. dashboard + execution engine), they share the same per-second budget; design the backend's internal request scheduler with a single shared rate-limit tracker per UID, not per key.
- **Sub-account demo trading interplay clarified (was unverified)** (§2/§8/§18) — the live Demo Trading Service docs describe demo trading as a per-mainnet-login "shadow account" with its own user ID, not an assignable mode on arbitrary sub-accounts; design the manager-per-sub-account demo-mode UX around each manager needing their own mainnet login switched to demo, and empirically confirm before finalizing (see §2 footnote for full reasoning).
- **Historical trade-tick data is not retrievable via REST beyond ~1000 recent trades** (§15) — any footprint/Deep-Print/tape-replay feature requires CandleViewer to run its own continuous WS-fed recording pipeline from day one; retrofitting historical tick data later is only possible via Bybit's bulk CSV downloads (public.bybit.com), which cannot fill gaps for symbols/date-ranges not covered by those published files.
- **Alt domains** (`bytick.com`, `bybit.kz`) exist for regional/network reasons — do not hardcode a single hostname; make the REST/WS base URL configurable per environment/region.

## 20. Example payloads

### Place a limit order with attached TP/SL (linear, one-way mode)
```json
POST /v5/order/create
{
  "category": "linear",
  "symbol": "BTCUSDT",
  "side": "Buy",
  "orderType": "Limit",
  "qty": "0.01",
  "price": "60000",
  "timeInForce": "GTC",
  "takeProfit": "65000",
  "stopLoss": "58000",
  "tpTriggerBy": "MarkPrice",
  "slTriggerBy": "MarkPrice",
  "tpslMode": "Full",
  "positionIdx": 0,
  "orderLinkId": "cv-btc-entry-0001"
}
```

### Conditional (stop) market order, hedge mode, Buy side
```json
POST /v5/order/create
{
  "category": "linear",
  "symbol": "ETHUSDT",
  "side": "Buy",
  "orderType": "Market",
  "qty": "0.5",
  "triggerPrice": "3500",
  "triggerBy": "LastPrice",
  "triggerDirection": 1,
  "positionIdx": 1,
  "orderLinkId": "cv-eth-stopentry-0001"
}
```

### Set a trailing stop on an existing position (full position)
```json
POST /v5/position/trading-stop
{
  "category": "linear",
  "symbol": "BTCUSDT",
  "tpslMode": "Full",
  "positionIdx": 0,
  "trailingStop": "150",
  "activePrice": "61000"
}
```

### Batch place (spot, 2 orders)
```json
POST /v5/order/create-batch
{
  "category": "spot",
  "request": [
    {
      "symbol": "BTCUSDT",
      "side": "Buy",
      "orderType": "Limit",
      "isLeverage": 0,
      "qty": "0.05",
      "price": "30000",
      "timeInForce": "GTC",
      "orderLinkId": "spot-btc-03"
    },
    {
      "symbol": "ATOMUSDT",
      "side": "Sell",
      "orderType": "Limit",
      "isLeverage": 0,
      "qty": "2",
      "price": "8.5",
      "timeInForce": "GTC",
      "orderLinkId": "spot-atom-03"
    }
  ]
}
```

### Demo-trading faucet request
```json
POST /v5/account/demo-apply-money
Host: api-demo.bybit.com
{
  "adjustType": 0,
  "utaDemoApplyMoney": [
    { "coin": "USDT", "amountStr": "100000" }
  ]
}
```

### WS public orderbook subscribe (pybit style)
```python
from pybit.unified_trading import WebSocket
from time import sleep

ws = WebSocket(testnet=True, channel_type="linear")

def handle_message(message):
    print(message)

ws.orderbook_stream(depth=50, symbol="BTCUSDT", callback=handle_message)
while True:
    sleep(1)
```

### WS private auth (raw op, illustrative)
```json
{
  "op": "auth",
  "args": ["<api_key>", 1735500000000, "<hmac_sha256_signature>"]
}
```

### WS orderbook delta message (illustrative shape per docs)
```json
{
  "topic": "orderbook.50.BTCUSDT",
  "type": "delta",
  "ts": 1735500000123,
  "data": {
    "s": "BTCUSDT",
    "b": [["60123.5", "0.421"], ["60122.0", "0"]],
    "a": [["60125.0", "1.05"]],
    "u": 123456789,
    "seq": 9876543210
  },
  "cts": 1735500000100
}
```

## 21. Sources

- Bybit V5 API Introduction — https://bybit-exchange.github.io/docs/v5/intro
- Account Mode / UTA — https://bybit-exchange.github.io/docs/v5/acct-mode
- Demo Trading Service — https://bybit-exchange.github.io/docs/v5/demo
- WebSocket Connect — https://bybit-exchange.github.io/docs/v5/ws/connect
- Testnet — https://bybit-exchange.github.io/docs/v5/testnet
- Get Kline — https://bybit-exchange.github.io/docs/v5/market/kline
- Mark Price Kline — https://bybit-exchange.github.io/docs/v5/market/mark-kline
- Index Price Kline — https://bybit-exchange.github.io/docs/v5/market/index-kline
- Premium Index Price Kline — https://bybit-exchange.github.io/docs/v5/market/premium-index-kline
- Orderbook (REST) — https://bybit-exchange.github.io/docs/v5/market/orderbook
- Recent Trades (REST) — https://bybit-exchange.github.io/docs/v5/market/recent-trade
- Tickers — https://bybit-exchange.github.io/docs/v5/market/tickers
- Funding Rate History — https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
- Open Interest — https://bybit-exchange.github.io/docs/v5/market/open-interest
- Insurance — https://bybit-exchange.github.io/docs/v5/market/insurance
- Long/Short Ratio — https://bybit-exchange.github.io/docs/v5/market/long-short-ratio
- Historical Volatility — https://bybit-exchange.github.io/docs/v5/market/iv
- Risk Limit — https://bybit-exchange.github.io/docs/v5/market/risk-limit
- Instruments Info — https://bybit-exchange.github.io/docs/v5/market/instrument
- Place Order — https://bybit-exchange.github.io/docs/v5/order/create-order
- Amend Order — https://bybit-exchange.github.io/docs/v5/order/amend-order
- Cancel Order — https://bybit-exchange.github.io/docs/v5/order/cancel-order
- Batch Place — https://bybit-exchange.github.io/docs/v5/order/batch-place
- Batch Amend — https://bybit-exchange.github.io/docs/v5/order/batch-amend
- Batch Cancel — https://bybit-exchange.github.io/docs/v5/order/batch-cancel
- Open Orders — https://bybit-exchange.github.io/docs/v5/order/open-order
- Cancel All — https://bybit-exchange.github.io/docs/v5/order/cancel-all
- Dead Man's Switch (DCP) — https://bybit-exchange.github.io/docs/v5/order/dcp
- Position List / Info — https://bybit-exchange.github.io/docs/v5/position/position-info
- Set Trading Stop — https://bybit-exchange.github.io/docs/v5/position/trading-stop
- Set Leverage — https://bybit-exchange.github.io/docs/v5/position/leverage
- Closed PnL — https://bybit-exchange.github.io/docs/v5/position/close-pnl
- Set Auto Add Margin — https://bybit-exchange.github.io/docs/v5/position/set-auto-add-margin
- Wallet Balance — https://bybit-exchange.github.io/docs/v5/account/wallet-balance
- Fee Rate — https://bybit-exchange.github.io/docs/v5/account/fee-rate
- Transaction Log — https://bybit-exchange.github.io/docs/v5/account/transaction-log
- Account Info — https://bybit-exchange.github.io/docs/v5/account/account-info
- Upgrade Unified Account — https://bybit-exchange.github.io/docs/v5/account/upgrade-unified-account
- Asset Inter-Transfer — https://bybit-exchange.github.io/docs/v5/asset/transfer/create-inter-transfer
- Create Sub UID — https://bybit-exchange.github.io/docs/v5/user/create-subuid
- Create Sub UID API Key — https://bybit-exchange.github.io/docs/v5/user/create-subuid-apikey
- API Key Info — https://bybit-exchange.github.io/docs/v5/user/apikey-info
- Query API — https://bybit-exchange.github.io/docs/v5/user/query-api
- WS Public Orderbook — https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
- WS Public Trade — https://bybit-exchange.github.io/docs/v5/websocket/public/trade
- WS Public Ticker — https://bybit-exchange.github.io/docs/v5/websocket/public/ticker
- WS Public Kline — https://bybit-exchange.github.io/docs/v5/websocket/public/kline
- WS Public Liquidation (legacy — retired, kept for record) — https://bybit-exchange.github.io/docs/v5/websocket/public/liquidation (404 as of 2026-09-14)
- WS Public All Liquidation — https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
- WS Public RPI Orderbook — https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook-rpi
- WS Trade (Order Entry) Guideline — https://bybit-exchange.github.io/docs/v5/websocket/trade/guideline
- Integration Guidance / Authentication guide — https://bybit-exchange.github.io/docs/v5/guide
- How To Start Copy Trading — https://bybit-exchange.github.io/docs/v5/copytrade
- Public bulk trade-history data (derivatives) — https://public.bybit.com/trading/{SYMBOL}/
- Public bulk trade-history data (spot) — https://public.bybit.com/spot/{SYMBOL}/
- WS Private Position — https://bybit-exchange.github.io/docs/v5/websocket/private/position
- WS Private Order — https://bybit-exchange.github.io/docs/v5/websocket/private/order
- WS Private Execution — https://bybit-exchange.github.io/docs/v5/websocket/private/execution
- WS Private Fast Execution — https://bybit-exchange.github.io/docs/v5/websocket/private/fast-execution
- WS Private Wallet — https://bybit-exchange.github.io/docs/v5/websocket/private/wallet
- WS Private Greeks — https://bybit-exchange.github.io/docs/v5/websocket/private/greek
- Rate Limit Rules — https://bybit-exchange.github.io/docs/v5/rate-limit
- V5 API Explorer index — https://bybit-exchange.github.io/docs/api-explorer/v5/category
- Historical Data Download portal — https://www.bybit.com/derivatives/en/history-data
- pybit (official SDK) — https://github.com/bybit-exchange/pybit
- pybit unified_trading module — https://github.com/bybit-exchange/pybit/blob/master/pybit/unified_trading.py
- bybit-api (unofficial Node/TS SDK, cross-reference) — https://github.com/tiagosiebler/bybit-api
- ccxt Bybit docs — https://docs.ccxt.com/docs/exchanges/bybit
- Bybit API developer portal (FAQ, rate-limit increase, server location) — https://www.bybit.com/en/derivative-activity/developer

## 22. Open questions

*Updated 2026-09-14 — most items below were resolved via direct live-doc fetches; remaining unresolved items are marked explicitly.*

1. ~~**Sub-account + demo trading interplay**~~ — **Largely resolved** (see §2 footnote): the live Demo Trading docs describe demo trading as tied to the mainnet login itself (a "shadow account" with its own user ID), not to arbitrary sub-accounts. **Still unresolved:** whether a sub-account (as opposed to the master login) can independently switch into its own demo mode was not explicitly confirmed or denied by the docs — the docs only describe the single-login flow. Direct empirical testing (create a sub-account, attempt to toggle it into Demo Trading) is still recommended before finalizing the per-manager demo-mode UX.
2. ~~**Exact current REST orderbook `limit` maximums per category**~~ — **Resolved** (§4): confirmed `spot [1,1000]` default 1, `linear`/`inverse [1,1000]` default 25, `option [1,25]` default 1.
3. ~~**`allLiquidation` vs legacy `liquidation` WS topic**~~ — **Resolved** (§9): only `allLiquidation.{symbol}` exists in the current docs/sitemap; the legacy `liquidation` topic page 404s and is absent from the WS Public nav, confirming full retirement (not dual-publish). Full payload schema and example confirmed.
4. ~~**RPI orderbook topic**~~ — **Resolved** (§9): topic is `orderbook.rpi.{symbol}`, Level 50 depth, 100ms cadence, 3-element `[price, size_placeholder, rpiSize]` array format confirmed with full schema.
5. **Current numeric fee schedule** — **Still unresolved.** All direct fetch attempts against Bybit's marketing fee-schedule pages returned 403 or a client-side-rendered shell with no embedded fee data (see §17) — extracting exact current VIP-tier maker/taker percentages would require a headless browser or an internal (non-V5, undocumented) fee-rate JSON endpoint, neither of which was pursued in this pass. Recommend calling `GET /v5/account/fee-rate` with a real key at implementation time instead of relying on the public marketing page.
6. ~~**Full Position/Account/Asset/User rate-limit tables**~~ — **Resolved** (§13): full Trade, Position, Account, Asset, and User tables reproduced from the live rate-limit doc (Spot Margin Trade, Spread Trading, RFQ, and Institutional Loan groups also exist on that page but were not reproduced in full as out of current scope).
7. ~~**Copy Trading API surface**~~ — **Resolved** (§18): Copy Trading is not a separate API surface — it's a permission-scoped usage mode of the standard `POST /v5/order/create` endpoint, gated to USDT Perpetual symbols with `copyTrading=true`, requiring UI-based Master Trader approval. Does not offer a shortcut for CandleViewer's "few account managers" architecture beyond plain sub-accounts.
8. ~~**Authentication guide canonical URL**~~ — **Resolved**: canonical page is https://bybit-exchange.github.io/docs/v5/guide ("Integration Guidance"), not `/v5/guide/authentication`. Full REST signing scheme, worked HMAC examples, and the `X-BAPI-RECV-WINDOW` default (5000ms, confirmed as Bybit's own documented default, not just an SDK convention) verified directly from this page.
9. ~~**WS Order Entry canonical doc page**~~ — **Resolved**: canonical page is https://bybit-exchange.github.io/docs/v5/websocket/trade/guideline ("Websocket Trade Guideline"), not `/v5/order-entry`. Confirmed scope (no demo trading, no spread trading support), full auth/order-request/response schemas, and WS-Trade-specific error codes (10403, 10404, 10429, 20006, 10016, 10019).
10. ~~**Public historical-data CSV column schema**~~ — **Resolved** (§15): downloaded and inspected live sample files for both derivatives (`public.bybit.com/trading/`) and spot (`public.bybit.com/spot/`) trade-tick data; confirmed distinct header rows and — critically — **different timestamp units** between the two (fractional seconds for derivatives vs. millisecond integers for spot), which the ETL parser must branch on. OrderBook and Kline bulk-file schemas were **not** inspected in this pass and remain a residual gap — verify before building an order-book-history backfill job.

### Remaining unresolved items (carried forward)
- **Exact numeric fee schedule by VIP tier** (item 5 above) — blocked by anti-scraping measures on Bybit's marketing pages; use the authenticated `fee-rate` endpoint as the practical workaround.
- **Sub-account-level demo trading eligibility** (item 1 above, narrow residual) — needs empirical testing, not just doc reading, since the docs don't explicitly address the sub-account case either way.
- **OrderBook and Kline bulk historical file schemas** (item 10 above, residual) — only the trade-tick CSV schemas were confirmed; the orderbook-snapshot and kline bulk file formats referenced on the same download portal were not individually downloaded/inspected.


