# Digest: 08-crypto-data-metrics.md (Bybit v5 crypto data & derived metrics)

Source scope: Bybit `linear` primary, `inverse`/`spot`/`option` secondary. `REST`/`WS`/`LOCAL`/`HYBRID` tags per item.

## 1. API primer & limits
- REST base: `api.bybit.com` (mainnet), `api-testnet.bybit.com`; demo trading `api-demo.bybit.com` (orders only, market-data shared w/ mainnet).
- WS public: `wss://stream.bybit.com/v5/public/{spot|linear|inverse|option}`; testnet `stream-testnet.bybit.com`.
- WS private: `wss://stream.bybit.com/v5/private` (auth).
- Data-availability posture: REST = live/recent only (recent trades ≤500-1000; kline OHLCV only, no historical book). Everything else (tape, L2, liquidations, OI-hi-res, footprint, profile, imbalances, CVD, iceberg/absorption) → must be WS-captured + locally persisted by CandleViewer recorder.
- **REST public rate limit:** ~600 req/5s per IP (~120 req/s sustained) — unconfirmed on primary docs page (Open Q #11), sourced from DeepWiki mirror.
- **WS subscribe limit:** ≤10 topics/request, ≤~21,000 chars serialized args/request; multiple subscribe msgs OK on one connection.
- **WS connection cap:** ~1,000 concurrent/IP per category (not a binding constraint at CandleViewer scale).
- Practical sizing: batch subscribes ≤10 topics, respond to keepalives, budget REST backfill <120 req/s/IP.

## 2. Trades, aggressor side, CVD
- Raw trades: `WS publicTrade.{symbol}` fields `T,s,S,v,p,L,i,BT` (+ option: `mP,iP,mIv,iv`). `S`=taker/aggressor side directly (Buy/Sell) — no reconstruction needed.
- REST `GET /v5/market/recent-trade`: default limit **60** (spot/linear/inverse), **500** (option); max **1000** all categories — always pass explicit `limit=1000`.
- Cadence: push per match, unthrottled. **CandleViewer: WS, record every message.**
- **CVD**: signed running sum (+v Buy, −v Sell), reset at anchor (session/UTC day/custom/"since load"). Variants: session-reset, anchored (AVWAP-style), per-timeframe, multi-symbol/composite (needs USD-notional normalization across linear/inverse).
- **Per-bar delta**: net signed vol in bar.
- **Min/max delta (delta range)**: track running intrabar delta path, record min/max — LOCAL, needs intrabar tracking.
- **Delta divergence** (single-bar heuristic): price new high + delta/CVD not confirming → flag.
- **Multi-bar divergence (recommended)**: rolling N-bar (default 10) window, compare swing highs/lows in price vs CVD independently (pivot-based swing detector preferred over naive argmax/argmin).
- Data source: LOCAL, all from `publicTrade` WS.

## 3. Footprint / imbalances / unfinished auctions
- **Footprint cell** (price×bar): bidVolume (Sell hits), askVolume (Buy lifts), delta, totalVolume, tradeCount. LOCAL from `publicTrade` grouped by tick-rounded price; tick size via REST `instruments-info.priceFilter.tickSize`.
- **Diagonal imbalance**: buy_imbalance(P)=askVol(P)/bidVol(P−tick); sell_imbalance(P)=bidVol(P)/askVol(P+tick). Default ratio **300%** (some platforms 500%), configurable, industry range 3x–5x.
- **Stacked imbalance**: ≥N (default **3**) consecutive same-direction diagonal imbalances. Config: minStack, ratio, minVolume.
- **Unfinished auctions**: bar closes at high/low with significant volume still trading at that extreme tick → suggests continuation. LOCAL from footprint.
- **Per-bar POC/VA**: mini volume profile scoped to one bar's footprint cells.
- All LOCAL, built on footprint cells / `publicTrade`.

## 4. Volume profile & TPO
- **Volume profile**: histogram of volume by price over a period (session/custom/composite). LOCAL from `publicTrade` grouped by tick price.
- **POC**: price level w/ highest volume.
- **Value Area (default 70%)**: contiguous range around POC containing ~70% volume; algorithm expands to whichever adjacent price step (above/below) has more volume, repeat until target reached. 70% ≈ 1 std dev convention; some platforms use 68% or 80%. Note: "textbook" TPO algorithm expands 2 rows at a time; single-step version here is an accepted approximation (Open Q #9 — verify against reference platform if exact parity needed).
- **Naked/Virgin POC**: prior period's POC not yet retraded; flips to "tested" once a later bar's range covers it.
- **HVN/LVN**: local maxima/minima in volume-by-price histogram (peak/trough detection).
- **Composite profile**: sum priceLevels across multiple sub-periods before POC/VA calc.
- **TPO / Market Profile**: counts discrete time periods (classically 30-min, lettered A,B,C...) touching each price, rather than summing volume; can diverge from volume profile (large trades vs. many small trades over time). LOCAL from bar highs/lows or trade prices, bucketed into configurable periods.

## 5. VWAP variants
- **Session VWAP**: Σ(price×vol)/Σvol from session start; crypto has no natural session — user-configurable anchor (00:00 UTC daily common, or Bybit funding times 00/08/16 UTC).
- **Anchored VWAP (AVWAP)**: same formula, user-chosen arbitrary anchor.
- **Rolling/Moving VWAP (MVWAP)**: fixed trailing window of n bars/trades, never resets.
- **VWAP SD bands**: volume-weighted variance around VWAP, band at ±kσ (k=1,2,3 typical, Bollinger-style).
- Data source: LOCAL; Bybit klines can approximate VWAP via bar typical price×volume if trade-level not stored, but trade-level preferred for accuracy.

## 6. Open interest & OI-price quadrant
- REST `GET /v5/market/open-interest`: params category(required linear/inverse), symbol(required), startTime, endTime, intervalTime(5min/15min/30min/1h/4h/1d), limit([1,200] default 50), cursor. Fields: `openInterest`(both sides sum), `singleOpenInterest`, `timestamp`. **Units**: inverse=USD, linear=base coin (must ×price for USD).
- WS `tickers.{symbol}`: `openInterest`, `openInterestValue`(USD), 100ms cadence — practical live source; REST better for historical backfill.
- **OI delta per bar**: LOCAL, OI(close_time)−OI(open_time).
- **OI-price quadrant** (price sign × OI sign):
  | Price | OI | Regime |
  |---|---|---|
  | Up | Up | Long build-up |
  | Up | Down | Short covering |
  | Down | Up | Short build-up |
  | Down | Down | Long liquidation/unwind |
- Data source: HYBRID (OI REST/WS + LOCAL quadrant logic).

## 7. Funding rate
- WS `tickers.{symbol}`: `fundingRate`, `nextFundingTime`, `fundingIntervalHour`, `fundingCap`/`fundingFloor` (perp); futures use `basisRateYear` instead. 100ms cadence.
- REST `instruments-info`: static `fundingInterval` (minutes, e.g. 480=8h), `upperFundingRate`/`lowerFundingRate` caps.
- No distinct "predicted funding rate" field documented (Open Q #8) — `fundingRate` = currently-accruing rate applying at nextFundingTime.
- REST `GET /v5/market/funding/history`: category, symbol, startTime, endTime, limit([1,200] default 200). Fields: symbol, fundingRate, fundingRateTimestamp. Only startTime→error; only endTime→200 up to endTime; neither→most recent 200. Intervals vary per symbol (8h common, but 1h/2h/4h exist) — always check `fundingInterval`, don't assume 8h.
- **Annualized funding**: periodsPerYear=(365*24*60)/fundingIntervalMinutes; annualizedRate=rate*periodsPerYear. Example: 480min interval → 1095 periods/yr; 0.01%/period → ~10.95%/yr.
- Data source: HYBRID (raw REST/WS, annualization LOCAL trivial).

## 8. Mark/index price, basis/premium
- WS `tickers.{symbol}`: `markPrice`,`indexPrice`,`lastPrice`, 100ms.
- REST historical: `/v5/market/mark-price-kline`, `/v5/market/index-price-kline` (intervals 1,3,5,15,30,60,120,240,360,720,D,W,M).
- Index price = composite of major spot exchanges (methodology not fully public). Mark price = index adjusted by smoothed basis, prevents manipulation-driven liquidations.
- **Basis/premium**: basis=lastPrice(or mark)−indexPrice; premiumPct=basis/indexPrice*100. Dated futures get `basisRateYear` directly from Bybit (WS).
- **Premium-index-price-kline** (gap-fix, distinct 3rd series): `GET /v5/market/premium-index-price-kline` — category=linear only, params symbol/interval(same set)/start/end/limit(default&max 1000). Response: `[startTime,open,high,low,close]` (no volume). This is Bybit's own funding-relevant premium calc — **treat as authoritative historical/chartable premium series (REST, no local recording needed)**, reserving §8.2 LOCAL basis for live-only/gaps.
- Data source: HYBRID; premium-index-kline reclassifies basis history from must-record-locally → native REST kline (significant recorder-scope simplification).

## 9. Liquidations
- WS `allLiquidation.{symbol}` (current documented topic; legacy singular topic deprecated/404s expected). Batches at most 1 update/symbol/500ms window (data[] array) — recorder must store full array, not assume 1 record/push.
- `S` (side) = liquidated position's closing order side: `Sell`=long liquidated, `Buy`=short liquidated.
- Bankruptcy price field exists in extended schema (margin balance reaches zero).
- **Liquidation bars**: sum notional (price*qty) per bar, split long-liq(S=Sell)/short-liq(S=Buy) + count. LOCAL.
- **Liquidation heatmap**: 2D grid (price bucket × time bucket), color by cumulative liquidated notional, optional decay — same technique as order-book heatmap (§11.3) but from realized events.
- **Estimated liquidation levels** (Coinglass/Hyblock-style, predictive not realized): LOCAL modeled — no exchange publishes; methodology: (1) aggregate OI + assumed leverage-tier distribution, (2) back-calc hypothetical liq prices via `liqPrice_long≈entryPrice*(1−1/leverage+maintMarginRate)`, `liqPrice_short≈entryPrice*(1+1/leverage−maintMarginRate)` using Bybit `REST /v5/market/risk-limit` maintenance margin tiers, (3) weight by estimated notional at entry price (recent volume/OI-at-price proxy), (4) render as heatmap (Coinglass "Model 3": y_axis price levels, liquidation_leverage_data triplets, price_candlesticks). Explicit limitation: estimates only, not confirmed data. CandleViewer approach: combine Bybit OI + risk-limit tables + leverage distribution calibrated against own recorded realized liquidations. Flagged as nontrivial modeling project (Open Q).
- **Insurance fund** (gap-fix, out-of-scope note): REST `GET /v5/market/insurance` (no auth), current balance by coin (USDT/USDC/BTC/ETH pools) + updatedTime. Snapshot only, no historical series — poll periodically for a chart. Useful as systemic-risk ambient context alongside liquidation feed.

## 10. Long/short account ratio & taker buy/sell ratio
- REST `GET /v5/market/account-ratio`: category, symbol, period(5min/15min/30min/1h/4h/1d), limit(~50 default, up to 500 some refs — reverify, doc page 404'd, Open Q). Fields buyRatio/longAccountRatio, sellRatio/shortAccountRatio (schema needs live reverification). % of accounts (not size-weighted), REST-only, no WS.
- **Taker buy/sell ratio**: not a dedicated Bybit endpoint; LOCAL from `publicTrade` side aggregation: buyVol/sellVol or buyVol/(buyVol+sellVol) normalized.

## 11. Order book metrics & liquidity heatmap
- WS `orderbook.{depth}.{symbol}`; depth tiers commonly 1/50/200/500 (linear/inverse), 1/50/200 (spot), some categories 1000 — reverify live docs (tiers have changed over time, Open Q).
- Snapshot/delta: first msg `type:snapshot` (full state); subsequent `delta` (size=0→delete, new price→insert, existing→overwrite). Fields: topic, type, ts, data.s, data.b[]/a[] (price,size), data.u(update ID, resets to 1=full-restart signal), data.seq(cross-seq ordering), cts(matching-engine ts, correlates with trade `T`).
- Field-order quirk: spot(all levels)+futures L1: `ts` before `type`; futures other levels: `ts` after `type` — don't assume fixed key order.
- L1 (`orderbook.1.{symbol}`) resends snapshot every 3s even w/ no change (heartbeat, reuses same `u`).
- **Order book imbalance**: (sumBid−sumAsk)/(sumBid+sumAsk), range[-1,1], over top-N or ±X% band.
- **Depth at ±1%/±2%**: sum bid size ≥ mid*(1-pct), ask size ≤ mid*(1+pct).
- **Cumulative depth** (DOM ladder): running sum walking down bids / up asks.
- **Resting liquidity heatmap**: maintain live book → sample at fixed cadence (throttle 100-250ms) → quantize price into tick rows, time into columns → store size (max/mean/last per cell) → log-scaled + per-window normalized color mapping (heavy-tailed size dist) → optional decay/fade for staleness (distinct from but combinable with iceberg reload heuristic). Largest storage driver in the system (§19).
- Data source: LOCAL on top of HYBRID (WS snapshot+delta) local book.

## 12. Big trade / iceberg / cluster detection
- **Absolute threshold**: size≥X or notional≥$Y, configurable per symbol.
- **Relative threshold**: size ≥ k×rollingAvgSize (EMA or SMA), k=5-10x typical.
- **Rolling z-score**: z=(size−rollingMean)/rollingStd ≥ zThreshold(e.g. 3.0) — more robust across regimes.
- **Trade clustering** (split-fill aggregation, aggressor-side): group consecutive same-side same-price(±tolerance) trades within timeWindowMs(default 50ms) into one cluster; if cluster total ≥ big-trade threshold, display as single large print. Distinct terminology from resting-side iceberg (§12.3).
- **Iceberg detection (resting L2, reload heuristic)**: correlate orderbook deltas + trade tape at a price level; if visible size trades off then reloads to similar size ≥minReloadCount(default 3) times within sizeTolerancePct(default 0.2), flag probable iceberg. **Inherently probabilistic** — Bybit has no per-order-ID/MBO feed; genuine iceberg indistinguishable from coincidental refill by multiple participants. Present as confidence signal, not certainty.
- All LOCAL from `publicTrade` + `orderbook.{depth}.{symbol}`.

## 13. Speed of tape
- tradesPerSecond(window), volumePerSecond(window), bookUpdatesPerSecond(window) — computed over multiple rolling windows (1s/5s/30s) vs. longer baseline (e.g. 300s trailing avg).
- tapeAcceleration = tradesPerSec(1s)/avgTradesPerSec(300s); ratio >3-5x baseline = "speeding up" alert threshold (configurable).
- Rendered as real-time gauge/sparkline, color-coded by taker side (green=buy accel, red=sell accel).
- LOCAL, no extra endpoint — pure rate measurement on already-flowing streams.

## 14. Stop-run / sweep detection
- Heuristic: identify recent well-defined swing high/low; detect sweep bar exceeding level by min buffer (ideally with speed-of-tape burst / one-sided footprint-CVD signature); confirm reversal within maxBarsToReverse(default 3) bars closing back past level by reversalPct(default 0.5) of excursion.
- Confidence boosters: absorption at level (§15), CVD/delta divergence at sweep (§2.2), liquidation cluster coincidence (§9.1).
- LOCAL, derived from OHLCV+swing detection+tape+book+liquidation stream, no dedicated endpoint.

## 15. Absorption & exhaustion
- **Absorption**: large volume at a level with little/no further price movement (footprintCell.totalVolume≥minVolume, |priceMovedTicks|≤maxPriceMove(default 1)); optionally require strongly one-sided delta.
- **Exhaustion**: sustained directional move where volume/delta at extreme declines even as price continues/stalls (trendingSameDirection AND decliningParticipation over lookback, default 5 bars).
- LOCAL, built entirely on footprint cells (§3.1)/per-bar delta (§2.2)/volume already captured.

## 16. Market regime classification
- **ADX** (Wilder, period 14 typical): standard +DM/-DM/TR/smoothing/±DI/DX/ADX formula. ADX>25 trending, <20 ranging/choppy (convention, configurable).
- **ATR** (Wilder/simple/EMA, period 14 typical): TR=max(high-low, |high-prevClose|, |low-prevClose|); volatility gauge + normalizer for other metrics (stop-run buffer, range-bar sizing).
- **Hurst exponent**: R/S analysis across window scales; H=slope of log(R/S)_n vs log(n). H>0.55 trending, H<0.45 mean-reverting, 0.45-0.55 random walk.
- **Combined classification**: adx>25&hurst>0.55→Trending; adx<20&hurst<0.5→Ranging; atrPctOfPrice>threshold→Volatile/transitional; else Mixed/undefined.
- All LOCAL from OHLCV bars (REST/WS klines or locally-built bars).

## 17. Volatility (realized/ATR/options IV)
- **Realized vol (close-close)**: logReturn stdev over N periods × sqrt(periodsPerYear) (1h bars→8760/yr; daily→365).
- **Parkinson estimator**: σ²=(1/(4N ln2))Σ[ln(high/low)]² (uses HL range).
- **Garman-Klass**: σ²=(1/N)Σ[0.5(ln(H/L))² − (2ln2−1)(ln(C/O))²] (more efficient than close-close).
- **Yang-Zhang**: accounts for overnight/session gaps (less relevant 24/7 crypto but noted for funding-time session resets).
- ATR: same as §16.2, used as pure vol magnitude gauge here.
- Bybit option `iv`/`mIv` fields on `publicTrade`/`tickers` (option category) = implied vol per contract, quoted directly. No standalone historical-vol-index endpoint (no Deribit DVOL equivalent) — CandleViewer's own realized-vol calc is the practical substitute reference line.
- Data source: realized vol/ATR = LOCAL from klines; option IV = WS/REST Bybit-provided (option category only).

## 18. Options data & crypto GEX analog
- Bybit `category=option`: `publicTrade`, `tickers`(mark/index price, mark IV/contract), REST `/v5/market/instruments-info?category=option` (chain: strikes/expiries). Bybit options OI/volume << Deribit's — Deribit API likely needed as primary/supplementary options-OI source for meaningful GEX (Open Q #7, out of Bybit-scope, needs dedicated research pass).
- OI by strike: no single aggregate endpoint on Bybit or Deribit; must fan out per-contract OI calls + aggregate client-side, filtered to near-dated/front-month expiries typically.
- **Bybit options contract spec** (gap-fix): USDC-settled, European-style/cash-settled, priced vs futures/forward (hence Black-76 not Black-Scholes). Table:
  | Spec | Bybit BTC | Bybit ETH | Deribit |
  |---|---|---|---|
  | Settlement | USDC | USDC | BTC/ETH (coin-margined) |
  | Multiplier | 1 | 1 | 1 |
  | Exercise | European cash-settled | same | same |
  | Expiries | daily→quarterly | same | daily→quarterly |
  | Expiry time | 08:00 UTC | 08:00 UTC | 08:00 UTC |
  Hybrid design must handle Bybit USDC-denominated vs Deribit coin-denominated notional conversion.
- Endpoints for OI-by-strike: `instruments-info?category=option`, `open-interest?category=option&symbol=...` (per-contract, fan-out required), `tickers`(markIv).
- **Black-76 pricing/Greeks**: d1=(ln(F/K)+0.5σ²T)/(σ√T); d2=d1−σ√T; Call=e^-rT[F·N(d1)−K·N(d2)]; Put=e^-rT[K·N(-d2)−F·N(-d1)]; Gamma=e^-rT·N'(d1)/(F·σ·√T). F=forward, K=strike, T=yrs-to-expiry, σ=IV(quoted or solved via Newton-Raphson), r≈0 for crypto typically.
- **GEX by strike**: GEX_strike=Σ(Gamma_call·OI_call·multiplier·F)−Σ(Gamma_put·OI_put·multiplier·F); netGEX=Σ_strikes GEX_strike; gammaFlipPoint = spot price where netGEX changes sign. Convention: dealers assumed net long gamma from calls/short from puts sold (simplification, same caveat as equity GEX). Positive netGEX regions dampen realized vol (dealers buy dips/sell rips); negative netGEX regions amplify moves.
- Data source: HYBRID/LOCAL — raw OI/IV via REST; Black-76/Greeks/GEX aggregation entirely LOCAL (no exchange publishes GEX).

## 19. Data storage & replay
- **Must record continuously per symbol**: `publicTrade.{symbol}` (every fill, indefinite), `orderbook.{depth}.{symbol}` (snapshot+every delta, deepest allowed depth, indefinite or defined retention), `allLiquidation.{symbol}` (every event), `tickers.{symbol}` (OI/mark/index/funding/bbo, native cadence or throttled). Periodic REST snapshots: funding/history, open-interest (cross-check), instruments-info (tick size/funding interval/margin tiers — version-track, not static).
- **Estimated data rates (BTCUSDT, planning-only, unverified — Open Q #5)**:
  | Stream | Rate | Bytes/day (raw JSON) | Notes |
  |---|---|---|---|
  | publicTrade | few–50+/sec | ~50-500 MB/day | ~150-250B/msg, gzip 5-10x |
  | orderbook.50 | sub-second deltas | low-to-mid GB/day | store true deltas not re-snapshots; depth 200/500 scales up further |
  | allLiquidation | low/bursty | KB-MB/day (spikes in vol events) | 500ms batching bounds message count |
  | tickers | ~10/sec (100ms) | tens of MB/day | small payload, constant rate |
  - Recommend Parquet/columnar/append-only tick store, per-symbol partitioning+compression.
- **Bar construction from recorded trade tape** — all LOCAL, all derivable once tape recorded: time bars, tick bars(ticksPerBar), volume bars(volumePerBar), range bars(rangeSize high-low threshold), delta bars(cumulative signed-vol threshold).
- **Replay**: read recorded trades/deltas/liquidations back in timestamp order at chosen speed through same live ingestion pipeline (single code path for live+historical, avoid dual implementation).

## 20. Bybit public historical trade CSVs
- Location: `public.bybit.com` (plain directory listing, confirmed reachable) — `trading/` (derivatives, per-symbol subdirs), `spot/` (per-symbol), plus `kline_for_metatrader4/`, `premium_index/`, `spot_index/`.
- File naming: daily gzip CSV, one/UTC-day, pattern `{SYMBOL}{YYYY-MM-DD}.csv.gz`-ish — verify exact pattern via live listing, don't hardcode.
- Typical fields (unverified — Open Q #4): timestamp, symbol, side(Buy/Sell taker), size/qty, price, trade_id/execId; some venues' dumps use is_buyer_maker instead — spot-check Bybit's actual dump.
- Known gaps: no official changelog of outages; trades-only archive (no L2/liquidations/fine-grained OI history) — useful for pre-CandleViewer bulk backfill only, not authoritative going-forward source.
- Community downloader tools exist (Anton495/bybit-data-downloader, suenot/bybit-history) — informative but build own downloader for production.
- Data source: REST-adjacent static file archive, one-time backfill use only.

## 21. Summary matrix (41 metrics) — condensed
1 Raw trades+taker side–WS publicTrade/REST recent-trade(ltd hist) | 2 CVD–LOCAL | 3 Per-bar delta,min/max–LOCAL(intrabar tracking) | 4 Delta divergence–LOCAL | 5 Footprint cells–LOCAL | 6 Diagonal/stacked imbalance–LOCAL | 7 Unfinished auctions–LOCAL | 8 Per-bar POC/VA–LOCAL | 9 Volume profile/POC/VA/naked POC/HVN-LVN/composite–LOCAL | 10 TPO/Market Profile–LOCAL | 11 VWAP(session/anchored/rolling)+SD bands–LOCAL | 12 Open interest–REST open-interest/WS tickers(unit:linear=coin,inverse=USD) | 13 OI delta per bar–LOCAL | 14 OI-price quadrant–LOCAL | 15 Funding rate(current)–WS tickers/REST instruments-info(interval) | 16 Funding rate history–REST funding/history | 17 Annualized funding–LOCAL | 18 Mark/index price(live)–WS tickers | 19 Mark/index price(historical)–REST mark-price-kline/index-price-kline | 20 Basis/premium–LOCAL(perp);WS basisRateYear(dated futures) | 21 Liquidations(realized)–WS allLiquidation(500ms batched) | 22 Liquidation bars/heatmap–LOCAL | 23 Estimated liquidation levels/heatmap–LOCAL modeled(OI+risk-limit+assumed leverage dist) | 24 Long/short account ratio–REST account-ratio(schema needs reverify) | 25 Taker buy/sell ratio–LOCAL | 26 Order book L2 live–WS orderbook.{depth} | 27 OB imbalance,depth at ±X%–LOCAL | 28 Liquidity heatmap(resting)–LOCAL | 29 Big trade detection–LOCAL | 30 Trade clustering(split-fill)–LOCAL | 31 Iceberg detection(resting book)–LOCAL heuristic,probabilistic | 32 Speed of tape–LOCAL | 33 Stop-run/sweep detection–LOCAL heuristic | 34 Absorption/exhaustion–LOCAL heuristic | 35 Market regime(ADX/ATR/Hurst)–LOCAL | 36 Realized volatility(close-close/Parkinson/GK)–LOCAL | 37 Option implied vol/mark IV–WS/REST tickers+publicTrade(option cat) | 38 Options OI by strike–REST instruments-info(option);Deribit likely needed | 39 GEX/gamma exposure by strike–LOCAL(Black-76×OI) | 40 Historical trade CSVs–static archive public.bybit.com(trades only) | 41 Instrument metadata(tick size/leverage/funding interval)–REST instruments-info(version-track)

## Key numeric limits (all in one place)
- REST recent-trade: default 60 (spot/linear/inverse), 500(option); max 1000 all.
- REST public rate limit: ~600 req/5s/IP (~120 req/s) — unverified primary source.
- WS subscribe: ≤10 topics/request, ≤~21,000 chars/request; ≤~1,000 conns/IP/category.
- Open interest REST: limit [1,200] default 50; intervalTime 5min/15min/30min/1h/4h/1d.
- Funding history REST: limit [1,200] default 200.
- Premium-index-kline: limit default & max 1000.
- Account-ratio REST: limit ~50 default, up to 500 per some (unverified) refs.
- Liquidation batching: ≤1 push/symbol/500ms window (array-batched).
- Stacked imbalance defaults: ratio 300% (range 3x-5x industry), minStack 3.
- Value Area default: 70% (some platforms 68%/80%).
- TPO period: classically 30 min (configurable).
- Big-trade relative threshold: k=5-10x rolling avg; z-score threshold ~3.0.
- Trade cluster window: 50ms default.
- Iceberg reload heuristic: minReloadCount 3, sizeTolerancePct 0.2.
- Tape acceleration alert: >3-5x baseline (1s vs 300s window).
- ADX/ATR period: 14 typical; ADX>25 trending, <20 ranging.
- Hurst: >0.55 trending, <0.45 mean-reverting, 0.45–0.55 random walk.
- Order book depth tiers: commonly 1/50/200/500 (linear/inverse), 1/50/200 (spot), some 1000 — reverify live.
- L1 orderbook heartbeat: resend every 3s.

## Key recommendations
- Recorder-first architecture is foundational: capture WS trades/book/liquidations/tickers continuously; REST only for backfill/cross-check/metadata.
- Use `premium-index-price-kline` (REST) as authoritative historical premium series instead of locally recording live ticker basis.
- Store true order-book deltas, not full re-snapshots each message (major storage driver).
- Use Parquet/columnar append-only tick store w/ per-symbol partitioning+compression.
- Single ingestion code path for both live WS and historical replay (avoid dual logic).
- Keep terminology distinct: trade-clustering (aggressor split-fill, §12.2) vs iceberg detection (resting book reload heuristic, §12.3).
- Treat estimated-liquidation-levels and Deribit-GEX-integration as separate follow-on research/design phases, not simple endpoint integrations.
- Present iceberg/stop-run/absorption/exhaustion signals as confidence heuristics, not certainties.
- Instrument the recorder from day 1 to replace all planning-level data-rate estimates with real measurements.
- Always pass explicit `limit=1000` on recent-trade REST call rather than relying on per-category default.
- Version-track instrument metadata (tick size, leverage tiers, funding interval) — these change occasionally.

## Open questions (12, verbatim-condensed)
1. Order book depth tiers per category — reverify live docs at implementation time (tiers have changed historically).
3. Account-ratio endpoint schema — doc page 404'd this pass; field names reconstructed from third-party summary, reverify live response.
4. Public CSV archive: exact header/schema/timestamp units not confirmed by fetching a real `.csv.gz` — must download+inspect sample before building importer.
5. §19.2 data-rate/size estimates are planning-only, not measured — no citable current benchmark found; instrument recorder early to replace with real numbers.
6. Estimated-liquidation-levels modeling (§9.3): Coinglass/Hyblock formulas proprietary; CandleViewer's proposed OI+risk-limit+leverage-calibration approach is nontrivial — scope as distinct research/design phase after recording realized liquidations for a while.
7. Deribit integration scope for options/GEX: Bybit options OI << Deribit's; needs dedicated research pass on Deribit API (chain endpoints, OI-by-strike, IV) before committing to GEX feature.
8. Predicted funding rate precision: no distinct "predicted" field found in Bybit docs; confirm via live ticker capture whether `fundingRate` already represents pre-settlement predicted value.
9. Value Area algorithm granularity: simplified single-step expansion vs. textbook two-row TPO expansion — match reference platform's tie-breaking rules if exact parity needed.
10. Archive.org/Wayback snapshots of key Bybit docs pages (orderbook depth, rate-limit, ws/connect) not obtainable this pass (429 rate-limited) — manually capture before implementation to harden citations against future doc changes.
11. Exact REST rate-limit numbers (600 req/5s, ~120 req/s) not directly confirmed on primary docs page (fetch errors) — sourced from DeepWiki mirror/blogs only; reverify via live page or `X-Bapi-Limit`/`X-Bapi-Limit-Status` response headers before finalizing recorder rate-limiting.
12. Deribit-side options contract specs (multiplier, settlement, tick sizes, expiry cadence) only lightly sketched for comparison — needs own dedicated research pass alongside #7 before hybrid Bybit+Deribit GEX design finalized.
