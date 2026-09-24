# Bybit API v5 — Digest (source: 06-bybit-api.md)

## 1. Account architecture
- UTA 2.0 (Pro) — unified margin across Spot/USDT-Perp/USDC-Perp/Options; default for new accounts. Feasible.
- Upgrade Classic→UTA: `POST /v5/account/upgrade-unified-account` — irreversible.
- `accountType`: `UNIFIED`, `CONTRACT` (legacy).
- Check unified status: `GET /v5/user/query-api`, `GET /v5/account/account-info` (`unifiedMarginStatus`, `marginMode`).
- Margin modes: Cross / Isolated (`POST /v5/position/switch-isolated`, tradeMode 0/1) / Portfolio Margin (`set-margin-mode`=`PORTFOLIO_MARGIN`, KYC/risk-tier gated).
- Position mode (separate axis): one-way (`mode=0`) vs hedge (`mode=3`) via `POST /v5/position/switch-mode`; hedge requires `positionIdx` 0/1/2 on order/position calls.

## 2. Environments
| Env | REST | WS public | WS private | WS trade |
|---|---|---|---|---|
| Mainnet | api.bybit.com (alt api.bytick.com) | stream.bybit.com/v5/public/{cat} | stream.bybit.com/v5/private | stream.bybit.com/v5/trade |
| Testnet | api-testnet.bybit.com | stream-testnet... | stream-testnet.../private | stream-testnet.../trade |
| Demo | api-demo.bybit.com | not supported (use mainnet public) | — | **not supported** |
- Demo trading: shadow account tied to mainnet login, own user ID; unclear if sub-accounts can independently enable demo (open question).
- Demo batch orders: supported only for `linear`/`option`, not spot/inverse.
- Regional REST hosts: api.bybit.nl/.tr/.kz/.ae/.eu/.id/georgia, api.manepa.jp, api.spark-fintech.com. US/Mainland China IPs → 403.

## 3. Product categories
- `spot` — spot; margin trading via `isLeverage` flag.
- `linear` — USDT/USDC Perp + USDT Futures — most developed, hedge mode, TP/SL, trailing stop. Feasible/primary.
- `inverse` — coin-margined perp/futures, same feature parity as linear.
- `option` — USDC options, `orderIv`, `mmp` flag. Out of initial scope.
- `category` param should always be explicit (some endpoints default to `linear`).

## 4. REST — Market data
- Kline: `GET /v5/market/kline` — intervals 1,3,5,15,30,60,120,240,360,720min,D,W,M; `limit` 1–1000 (default 200); paginate via start/end for more history; no hard cap on lookback (per-symbol, verify empirically).
- Mark price kline: `/v5/market/mark-price-kline`; Index price kline: `/v5/market/index-price-kline`; Premium index kline: `/v5/market/premium-index-price-kline`.
- Orderbook: `GET /v5/market/orderbook` — limit ranges: spot [1,1000] def 1; linear/inverse [1,1000] def 25; option [1,25] def 1. Fields: s,b,a,ts,u,seq,cts.
- Recent trades: `GET /v5/market/recent-trade` — spot limit [1,60] def 60; linear/inverse/option [1,1000] def 500. No deeper historical tick REST — must record live or use bulk CSV.
- Open interest: `GET /v5/market/open-interest` — linear/inverse only; intervalTime 5min/15min/30min/1h/4h/1d; limit [1,200] def 50, cursor-paginated. Returns openInterest + singleOpenInterest.
- Tickers: `GET /v5/market/tickers` — 24h stats, funding rate, OI, mark/index price.
- Funding rate history: `GET /v5/market/funding/history` — limit max 200; funding interval varies (8h common, some 1h/2h/4h — check `fundingInterval`).
- Insurance fund: `GET /v5/market/insurance`.
- Long/short ratio: `GET /v5/market/account-ratio` — period 5min–1d, limit max 500.
- Historical volatility (options): `GET /v5/market/historical-volatility` — out of scope initially.
- Risk limits: `GET /v5/market/risk-limit` — tiered riskLimitValue/maintainMargin/initialMargin/maxLeverage.
- Instruments info: `GET /v5/market/instruments-info` — lotSizeFilter, priceFilter, leverageFilter, contractType, fundingInterval, launchTime, status. Canonical source for symbol picker/precision validation.
- All market data endpoints public, not counted against private rate limit (IP-based limits still apply; prefer WS).

## 5. REST — Trade endpoints
- Place order: `POST /v5/order/create` — category, symbol, side, orderType(Market/Limit), qty, price, timeInForce(GTC/IOC/FOK/PostOnly), triggerPrice/triggerBy/triggerDirection, orderIv(option), positionIdx(hedge), orderLinkId(≤36 chars unique), takeProfit/stopLoss + tpTriggerBy/slTriggerBy, tpslMode(Full/Partial), reduceOnly, smpType, mmp(option), bboSideType. Response = accept ack only, NOT fill confirmation — use WS order/execution streams as source of truth.
- Amend: `POST /v5/order/amend`. Cancel: `POST /v5/order/cancel`, cancel-all: `POST /v5/order/cancel-all`.
- Batch (create/amend/cancel-batch): 1–10 orders/request, `linear`/`inverse`/`option` only (not spot); rate cost = 1 unit/order; partial success possible.
- Open/closed orders: `GET /v5/order/realtime`, `GET /v5/order/history`.
- Order caps: Perps/Futures 500 active orders/symbol, 10 active conditional/symbol; Spot 500 total incl. 30 TP/SL + 30 conditional/symbol; Option 50/coin default. Daily aggregate order count monitored (main+subs).
- Dead man's switch: `POST /v5/order/disconnected-cancel-all` (DCP) — auto-cancel on disconnect.

## 6. REST — Position endpoints
- `GET /v5/position/list` — size, avgPrice, positionValue, unrealisedPnl, markPrice, liqPrice, bustPrice, leverage, positionIdx, tpslMode, TP/SL/trailingStop, positionStatus.
- `POST /v5/position/set-leverage`, `switch-isolated` (tradeMode 0/1), `switch-mode` (0 one-way/3 hedge), `set-tpsl-mode` (Full/Partial), `set-auto-add-margin` (supported on demo), `set-risk-limit`.
- `POST /v5/position/trading-stop` — sets TP/SL/trailing on position (not order); takeProfit/stopLoss price (0=cancel), trailingStop = **price distance not %** , activePrice arms trailing; tpSize/slSize (Partial, must match); tpLimitPrice/slLimitPrice + tpOrderType/slOrderType. One-sided TP/SL modification breaks OCO pairing — decide UX explicitly. Needs client translation layer for %-based trailing stop UX.
- `GET /v5/position/closed-pnl` — historical realized PnL, for journal feature.

## 7. REST — Account & Asset
- `GET /v5/account/wallet-balance` (UNIFIED/CONTRACT) — equity, walletBalance, availableToWithdraw, unrealisedPnl, totalEquity/totalMarginBalance/accountIMRate/accountMMRate.
- `GET /v5/account/fee-rate` — maker/taker per symbol/category, VIP-tier aware. **Use this for actual current fee numbers (marketing page fee schedule unscrapable/403).**
- `GET /v5/account/transaction-log` — UTA cash-flow ledger, ties to execPnl in exec WS.
- `GET /v5/account/account-info`; `POST /v5/account/upgrade-unified-account` (irreversible); `POST /v5/account/set-margin-mode` (REGULAR/PORTFOLIO_MARGIN); `POST /v5/account/demo-apply-money` (demo faucet).
- Asset: `POST /v5/asset/transfer/inter-transfer` (master/sub or account-type transfers); `GET .../query-transfer-coin-list`, `.../query-inter-transfer-list`; `GET /v5/asset/coin/query-info` (lower priority).

## 8. REST — User / Sub-account
- `POST /v5/user/create-sub-member` (master only) — models "few account managers" as sub-accounts.
- `POST /v5/user/create-sub-api` (master only) — readOnly flag, granular `permissions` (ContractTrade, Order, Position, Wallet, Options, Derivatives, Exchange, NFT, Spot, Affiliate).
- `GET /v5/user/query-api` — key's own permissions/IP whitelist/expiry/unified flag.
- `GET /v5/user/get-member-type` — master vs sub.
- Master can query its own + subs' rate limits; sub can only query its own.
- Decision: map "few account managers" → Bybit sub-accounts + scoped keys, not custom multi-tenant auth layer. Open Q: can sub-accounts independently use demo trading?

## 9. WebSocket — Public streams
- One connection per channel_type (spot/linear/inverse/option/spread/rfq); multi-topic subscribe via `args` array.
- Orderbook `orderbook.{depth}.{symbol}`: depths/cadence — linear&inverse&spot: 1@10ms,50@20ms,200@100ms,1000@200ms; option: 25@20ms,100@100ms. First msg=snapshot, then delta; depth=1 is snapshot-only (keepalive resend every 3s if unchanged). Fields: u (monotonic update id), seq (cross-sequence), cts. No checksum field — must drop/resubscribe on desync.
- RPI Orderbook `orderbook.rpi.{symbol}` — depth 50, 100ms, 3-elem [price,placeholder,rpiSize].
- Public trade, ticker, kline topics standard; kline messages carry `confirm` bool — must check before treating candle as closed (else flicker).
- Liquidation: legacy `liquidation` topic retired/404; current is `allLiquidation.{symbol}` — direct feed for stop-run/liquidation-tracking feature, no polling needed.
- Options Greeks flow through standard option-category topics.

## 10. WebSocket — Private streams
- Auth required on `/v5/private`. Two addressing styles: all-in-one (`position`,`order`,`execution`) vs categorised (`position.linear` etc) — cannot mix in same subscribe request.
- `position`/`position.{cat}` — size, avgPrice, unrealisedPnl, markPrice, liqPrice, bustPrice, positionIdx, tpslMode, TP/SL/trailingStop.
- `order`/`order.{cat}` — state transitions (New/PartiallyFilled/Filled/Cancelled/Rejected/Triggered); parentOrderLinkId links TP/SL child→parent (caveat: Set-Trading-Stop doesn't update parentOrderLinkId for Futures but does for Options).
- `execution`/`execution.{cat}` and `fast-execution` — fill-level detail; one message may bundle multiple fills.
- `wallet` — real-time balance push (push version of wallet-balance).
- `greeks` — option account Greeks (delta/gamma/vega/theta), relevant only for options view.

## 11. WebSocket — Order Entry (Trade over WS)
- Endpoint `wss://stream.bybit.com/v5/trade` (+regional .tr/.kz variants), testnet variant. Supports USDT/USDC Contract, Spot, Options, Inverse. **Not supported:** Demo Trading, Spread Trading.
- Auth: `{"op":"auth","args":[api_key, expiry_ms, signature]}`; retCode 0=success,20001=repeat auth,10004=invalid sign,10001=param error.
- Order ops: `order.create`/`order.amend`/`order.cancel` via `{"reqId","header":{X-BAPI-TIMESTAMP,X-BAPI-RECV-WINDOW,Referer},"op","args":[orderObj]}`.
- WS-Trade-specific error codes: 10403 (IP rate >3000 req/s), 10404 (unknown op/category), 10429 (system frequency protection), 20006 (dup reqId), 10016 (internal error), 10019 (service restarting, use fresh connection).
- Decision: WS Trade is an optimization not requirement for v1; REST trade + private WS confirmation streams sufficient. Demo mode must always use REST for orders.

## 12. Authentication & signing
- REST headers: X-BAPI-API-KEY, X-BAPI-TIMESTAMP (ms), X-BAPI-RECV-WINDOW (default **5000ms**, Bybit-documented default), X-BAPI-SIGN (HMAC-SHA256 hex, or RSA_SHA256 base64), X-Referer (broker only).
- Sign string: GET = timestamp+api_key+recv_window+queryString; POST = timestamp+api_key+recv_window+jsonBodyString.
- Validity window: `server_time - recv_window <= timestamp < server_time + 1000`. `GET /v5/market/time` for server time; NTP sync recommended.
- WS auth: op:"auth", args:[api_key, expires_ms, HMAC-SHA256("GET/realtime"+expires)].
- Permission scopes attached at key level; mismatched scope → rejection.

## 13. Rate limits
- **Global HTTP IP limit: 600 req/5s per IP** (403 "access too frequent" if exceeded; wait ≥10min).
- Trade group (req/s by category, UTA2.0 Pro): order/create 10(inv)/10(lin)/20(opt)/10(spot); amend 10/10/10/10; cancel 10/10/20/10; cancel-all 10/1/20/10; create/amend/cancel-batch 10/10/20/—; disconnected-cancel-all 5(inv only); pre-check 10/10/20/—. GET order/realtime, order/history, execution/list: 50/s. spot-borrow-check 50/s. Bot endpoints (combo/grid/martingale/dca/strategy) 3–200/s misc, mostly linear/spot/inverse+option only.
- Position: list/closed-pnl/get-closed-positions 50/s; move-history 10/s; set-leverage/switch-mode/trading-stop/set-auto-add-margin/add-margin/confirm-pending-mmr/move-positions 10/s.
- Account: wallet-balance/withdrawal/borrow-history/collateral-info/coin-greeks/info/pay-info/trade-info-for-analysis/user-setting-config 50/s; transaction-log 25/s; fee-rate 5/s; instruments-info 10/s; mmp-state & option-asset-info & set-collateral-switch & set-delta-mode & set-hedging-mode unlimited; borrow/repay/no-convert-repay/upgrade-to-uta 1/s; mmp-modify/reset/query-dcp-info/smp-group 5/s; set-limit-px-action 10/s; set-margin-mode 5/s.
- Asset: mostly 60/min or 5–300/s per endpoint (see source table); fiat endpoints up to 1000/s.
- User: create-sub-member/create-sub-api 1/s; frozen/update/delete-api 5/s; query-sub-members/query-api/sub-apikeys/get-member-type 10/s; agreement 20/s.
- Spot Margin/Spread/RFQ/Institutional Loan tables exist but not reproduced (out of scope, 1–50/s range).
- WS IP limits: ≤500 new connections/5min/IP; ≤1000 connections/IP per market (spot/linear/inverse/option each separate ceiling); avoid connect/disconnect churn.
- REST rate mechanics: **per-UID rolling window, shared across API keys** (not per-key). Error 10006 "Too many visits!". Response headers X-Bapi-Limit / X-Bapi-Limit-Status / X-Bapi-Limit-Reset-Timestamp — client should self-throttle off these proactively.
- Batch consumption: 1 unit/order in batch (partial success if quota insufficient).
- Order caps (recap): Perps/Futures 500/symbol +10 conditional; Spot 500 total +30 TP/SL +30 conditional; Option 50/coin. Daily aggregate monitored.
- Raising limits: contact Bybit account manager / institutional portal — not self-service.
- Unverified 3rd-party claim: tiagosiebler SDK claims up to 400 req/s bonus — not official, don't rely on it.

## 14. Heartbeats, reconnects, sequencing
- Ping every ~20s (`{"op":"ping"}`) to keep WS alive; no documented fixed idle timeout but implement active pings regardless.
- `max_active_time` (private/order-entry): configurable 30s–600s (10min) heartbeat window.
- Reconnect: backoff + resubscribe; no checksum on orderbook — resync via drop/rebuild on suspected desync using u/seq tracking.

## 15. Historical data & bulk downloads
- No REST tick-level history beyond recent-trade window (~1000/500/60 depending on category) — must run own continuous WS recording pipeline from day one for footprint/Deep-Print features.
- Bulk CSV downloads: `public.bybit.com/trading/{SYMBOL}/` (derivatives) and `.../spot/{SYMBOL}/` — no auth, scriptable ETL. **Different timestamp units**: derivatives = fractional seconds, spot = ms integers — parser must branch.
- Orderbook & kline bulk file schemas not inspected — residual gap, verify before building order-book-history backfill.
- Architecture decision: bulk CSVs backfill only the pre-launch gap; live WS recording is the ongoing source of truth.

## 16. Python SDKs
- **pybit** (official) — `pybit.unified_trading` exposes HTTP + WebSocket classes; supports testnet/demo flags, RSA+HMAC auth, auto-reconnect+resubscribe, ping timer. WS Trade (order entry) lives in separate `_websocket_trading.py` module, not unified with main WS client — confirm exact usage at implementation time. Pin exact version (breaking changes across versions).
- **tiagosiebler/bybit-api** (unofficial Node/TS) — cross-reference only.
- **ccxt** — wraps fetchOHLCV via since/limit chunking (same pagination approach needed manually against kline endpoint); has `upgradeUnifiedTradeAccount` helper.

## 17. Fees
- Exact current VIP-tier maker/taker fee schedule — **unresolved**, marketing pages blocked (403/client-rendered). **Decision: call `GET /v5/account/fee-rate` with real key at implementation time** instead of scraping.

## 18. API key permissions, IP whitelisting, sub-accounts
- Sub-API keys via `create-sub-api`: readOnly 0/1; granular `permissions` (ContractTrade, Spot, Wallet, Options, Derivatives, Exchange, NFT, Affiliate) — request minimum scope per manager key.
- API keys cannot withdraw by design; can transfer within UTA if scoped.
- IP whitelist per key — recommended for self-hosted fixed-egress-IP deployment.
- Keys support expiry dates — useful for credential rotation.
- Sub-accounts: separate UID, own wallet/positions/orders; funds move via inter-transfer. Natural mechanism for "few account managers" model.
- Copy Trading — **not a separate API**: thin wrapper over standard `/v5/order/create`; requires Master Trader UI approval + "Contract - Orders & Positions" permission; USDT Perp only (`copyTrading` flag on instruments-info). **Decision: not useful for CandleViewer's manager-fanout use case; de-scoped.**

## 19. Pitfalls & operational notes
- Clock sync mandatory (recv_window rejection risk, esp. WSL clock drift after sleep/resume).
- No orderbook checksum — must drop-and-resubscribe on desync, not self-heal.
- Depth-dependent push cadence (10–200ms) — decouple renderer throttling from feed cadence.
- Kline `confirm` flag must gate "closed candle" logic to avoid flicker.
- Demo: WS Trade unsupported; batch orders demo-supported only linear/option.
- Async order ack ≠ fill — always trust WS order/execution streams over synchronous REST response.
- One-sided TP/SL modification via trading-stop breaks OCO pairing — needs explicit UX decision.
- Trailing stop = price distance, not %; needs client-side translation layer for %-trail UX.
- Rate limit is per-UID (shared across keys on same UID) — design single shared rate-limit tracker per UID, not per key.
- Sub-account demo eligibility unconfirmed — empirical test needed before finalizing per-manager demo UX.
- Historical tick data beyond REST recent window requires own recording pipeline from day one; bulk CSVs can't fill arbitrary gaps.
- Alt/regional domains (bytick.com, bybit.kz, etc.) — make REST/WS base URL configurable, don't hardcode.

## 20. Example payloads (present in doc, not reproduced here)
- Limit order w/ TP/SL (linear, one-way); conditional stop-market (hedge mode); trailing stop set on position; batch place (spot, 2 orders); demo faucet request; WS public orderbook subscribe (pybit); WS private auth; WS orderbook delta message.

## Open questions (as of 2026-09-14)
1. **Unresolved:** Can a sub-account (not just master login) independently enable Demo Trading? Needs empirical test.
2. Resolved: REST orderbook limit maxes per category (see §4).
3. Resolved: only `allLiquidation.{symbol}` exists; legacy `liquidation` topic fully retired (404).
4. Resolved: RPI orderbook topic = `orderbook.rpi.{symbol}`, depth 50, 100ms, 3-elem array.
5. **Unresolved:** Exact current numeric fee schedule by VIP tier — blocked by anti-scraping; use `GET /v5/account/fee-rate` at implementation time instead.
6. Resolved: full Trade/Position/Account/Asset/User rate-limit tables captured (§13).
7. Resolved: Copy Trading is not a separate API surface; no shortcut for manager-fanout architecture.
8. Resolved: Auth guide canonical URL = `/v5/guide` ("Integration Guidance").
9. Resolved: WS Order Entry canonical URL = `/v5/websocket/trade/guideline`.
10. **Partially unresolved:** Public bulk CSV trade-tick schemas confirmed (differing timestamp units derivatives vs spot); orderbook-snapshot and kline bulk-file schemas NOT inspected — verify before building order-book-history backfill job.
