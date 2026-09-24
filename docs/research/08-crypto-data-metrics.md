# Crypto-specific market data & derived metrics — definitions and computation

> Research phase document for CandleViewer (self-hosted, Bybit-first crypto order-flow terminal). Covers every datapoint/derived metric a DeepCharts-class terminal needs, how it is defined, how it is computed, and how it maps onto Bybit API v5 (REST vs WebSocket) vs what must be computed/recorded locally.
>
> Scope: Bybit `linear` (USDT/USDC perpetuals) primarily, with notes on `inverse` and `spot` where relevant. All Bybit endpoint/field names below were pulled from the official Bybit V5 API docs (bybit-exchange.github.io) in September 2026; see Sources.

## Table of contents

1. [Conventions & Bybit v5 API primer](#1-conventions--bybit-v5-api-primer)
2. [Trades, aggressor side, and CVD](#2-trades-aggressor-side-and-cvd)
3. [Footprint / bid×ask cells, imbalances, unfinished auctions](#3-footprint--bidask-cells-imbalances-unfinished-auctions)
4. [Volume profile & TPO](#4-volume-profile--tpo)
5. [VWAP variants](#5-vwap-variants)
6. [Open interest & OI-price quadrant analysis](#6-open-interest--oi-price-quadrant-analysis)
7. [Funding rate](#7-funding-rate)
8. [Mark price, index price, basis/premium](#8-mark-price-index-price-basispremium)
9. [Liquidations](#9-liquidations)
10. [Long/short account ratio & taker buy/sell ratio](#10-longshort-account-ratio--taker-buysell-ratio)
11. [Order book metrics & liquidity heatmap](#11-order-book-metrics--liquidity-heatmap)
12. [Big trade / iceberg / cluster detection](#12-big-trade--iceberg--cluster-detection)
13. [Speed of tape](#13-speed-of-tape)
14. [Stop-run / sweep detection](#14-stop-run--sweep-detection)
15. [Absorption & exhaustion](#15-absorption--exhaustion)
16. [Market regime classification](#16-market-regime-classification)
17. [Volatility (realized, ATR, options historical vol)](#17-volatility-realized-atr-options-historical-vol)
18. [Options data & crypto GEX analog](#18-options-data--crypto-gex-analog)
19. [Data storage & replay](#19-data-storage--replay)
20. [Bybit public historical trade CSVs](#20-bybit-public-historical-trade-csvs)
21. [Summary matrix: REST vs WS vs computed-locally](#21-summary-matrix-rest-vs-ws-vs-computed-locally)
22. [Sources](#sources)
23. [Open questions](#open-questions)

---

## 1. Conventions & Bybit v5 API primer

### 1.1 API surfaces

Bybit V5 unifies spot, linear (USDT/USDC perpetual & futures), inverse (coin-margined perpetual & futures), and option under one API. Docs root: `https://bybit-exchange.github.io/docs/v5/intro`.

- **REST base URLs:** `https://api.bybit.com` (mainnet), `https://api-testnet.bybit.com` (testnet), demo trading uses `https://api-demo.bybit.com` for order-management/trade endpoints (market-data endpoints are shared with mainnet — this is Bybit's documented demo-trading design: demo accounts route order placement/position/wallet calls to `api-demo.bybit.com` while all `/v5/market/*` public data calls use the normal mainnet host, since demo trading needs real live prices to simulate against). *Re-checked against Bybit's Demo Trading docs during this research pass; the original claim held up but is footnoted here as re-verified rather than left as an assumption — no endpoint-routing change was found as of Sept 2026.*
- **WebSocket public endpoints:** `wss://stream.bybit.com/v5/public/{category}` where `{category} ∈ {spot, linear, inverse, option}`. Testnet: `wss://stream-testnet.bybit.com/v5/public/{category}`.
- **WebSocket private endpoints** (orders/executions/positions/wallet): `wss://stream.bybit.com/v5/private` (auth required); not the focus of this doc but relevant for building a local "my trades" ledger.
- Category matters: CandleViewer's crypto-derivatives scope means primarily `linear` (USDT-margined perps, the dominant liquidity venue) with `inverse` as a secondary category for coin-margined contracts. `spot` is needed for spot CVD/tape but has no OI/funding/liquidation concepts.

### 1.2 General data-availability posture

Bybit's V5 API is oriented around **live/recent data**. Historical depth for most REST market-data endpoints is limited (e.g., recent trades capped at 500–1000 records depending on category — see §1.4 below — kline history usually goes back to symbol listing but only in OHLCV form, no historical order-book snapshots via REST). This has a direct architectural consequence for CandleViewer:

> **Everything that is not a REST-queryable historical series (raw trades tape, L2 book deltas, liquidations, open interest at high resolution, footprint cells, volume profile, imbalances, CVD, iceberg/absorption signals, etc.) must be captured live from WebSocket streams and persisted locally by CandleViewer's own recorder/backend, then replayed from local storage for any charting further back than what Bybit's REST endpoints retain.**

This recorder-first architecture recurs throughout this document and is detailed in [§19](#19-data-storage--replay).

### 1.3 Notation used below

- `REST` = value obtainable via a Bybit v5 REST GET call, on demand, for the requested history window (subject to Bybit's own retention/pagination limits).
- `WS` = value pushed via a Bybit v5 public WebSocket topic; must be consumed live and stored to reconstruct history.
- `LOCAL` = value not provided by Bybit in any form; must be entirely computed/derived by CandleViewer from other WS/REST primitives (trades, book, OI, klines, etc.) and persisted.
- `HYBRID` = combination, e.g., snapshot via REST + live updates via WS, or WS-sourced raw data on which CandleViewer must run its own aggregation.

### 1.4 Rate limits (REST + WebSocket) — sizing the recorder

These numbers matter directly for CandleViewer's recorder-first architecture (§1.2, §19), which needs to poll REST backfill endpoints for many symbols and hold many concurrent WS subscriptions:

- **REST — public/market-data endpoints:** Bybit's official rate-limit docs (`https://bybit-exchange.github.io/docs/v5/rate-limit`) state public (unauthenticated) market-data endpoints are limited **per IP address**, commonly cited at **600 requests per 5 seconds per IP** (i.e., ~120 req/s sustained) across market-data paths on a given domain (`api.bybit.com` and mirrors). This is distinct from Bybit's authenticated/private endpoint limits, which are enforced **per UID** and vary by endpoint category and VIP tier (e.g., account/trade endpoints), and from the previously-noted Feb 2026 change reducing the Transaction Log endpoint from 50→30 req/s per UID (not a market-data endpoint, but evidence Bybit does periodically retune specific limits). Exceeding the public per-IP limit returns HTTP 403/429-style throttling. **CandleViewer implication:** a multi-symbol REST backfill job (OI history, funding history, kline gap-fill) should implement its own client-side token-bucket well under ~120 req/s per IP and should prefer running from a single outbound IP (or track the limit per IP if using multiple).
- **WebSocket — subscription limits:** per the official WS connect docs (`https://bybit-exchange.github.io/docs/v5/ws/connect`) and corroborating sources, a single `subscribe` request is capped at **10 topics (`args` entries) per request** for public streams (spot/linear/inverse/option), with an additional **~21,000-character cap on the total serialized `args` string** per request — CandleViewer must therefore batch symbol/topic subscriptions into multiple `subscribe` messages (10 topics at a time) rather than one giant request, but can send multiple subscribe messages over the *same* connection. **Per-IP connection cap:** commonly cited at up to **1,000 concurrent WS connections per IP** for public market data (counted per category — spot/linear/inverse/option are separate pools), which should be more than sufficient for CandleViewer's single-deployment, few-hundred-symbol scale, so the practical constraint is topics-per-connection (10/request, but many subscribe requests can be sent on one connection) rather than connection count.
- **Practical sizing:** since Bybit allows many topics to be subscribed on one connection (just batched 10 at a time per request) and up to ~1,000 connections/IP, connection count itself is not expected to be a binding constraint for CandleViewer's scope (tens of tracked symbols, not thousands); the more relevant discipline is (a) batching subscribe requests in groups of ≤10 topics, (b) responding to server pings/keepalives to avoid idle disconnects, and (c) budgeting REST backfill calls under the ~120 req/s/IP public ceiling.
- **Caveat:** as with other numeric limits in this document, Bybit has changed rate-limit specifics before; these figures were cross-checked against the official docs pages and DeepWiki mirrors of `bybit-exchange/docs` in Sept 2026 but should be re-verified against the live `rate-limit` and `ws/connect` pages (and against actual `X-Bapi-Limit`/`X-Bapi-Limit-Status` response headers) at implementation time.


## 2. Trades, aggressor side, and CVD

### 2.1 Raw trades with aggressor side

**Bybit source:**
- `WS` topic `publicTrade.{symbol}` on `wss://stream.bybit.com/v5/public/{category}`. Fields (per trade object, per official docs): `T` (fill timestamp ms), `s` (symbol), `S` (side — **`Buy`/`Sell`, this is the taker/aggressor side**), `v` (trade size, base units), `p` (trade price), `L` (tick direction, perps/futures only), `i` (trade ID), `BT` (whether it's a block trade), and for `option`: `mP`/`iP`/`mIv`/`iv` (mark/index price, implied vol at time of trade).
- `REST` `GET /v5/market/recent-trade` (category, symbol, `limit` param default **60**, max **1000** for `spot`/`linear`/`inverse`; for `category=option` the default/max is **500**/`1000`) returns the same taker `side` field but only the most recent trades (no historical pagination beyond that window) — response fields: `execId`, `symbol`, `price`, `size`, `side`, `time`, `isBlockTrade`. *Footnote (corrected): the earlier draft of this doc stated a flat "500–1000 records" range for all categories. Re-checked against the official `recent-trade` endpoint docs (bybit-exchange.github.io/docs/v5/market/recent-trade) and secondary confirmations (DeepWiki mirror of bybit-exchange/docs): the **default `limit` is 60 for spot/linear/inverse (not 500)**, while `option` category defaults to 500; the **max is 1000 across all categories**. CandleViewer's recorder/backfill code should always pass an explicit `limit=1000` rather than relying on the per-category default.*

**Aggressor-side semantics:** Bybit's `side` field on both the WS trade stream and REST recent-trade endpoint is the **taker (aggressor) side** — `Buy` means a market/aggressive order lifted the ask, `Sell` means a market/aggressive order hit the bid. This is exactly the "aggressor side" needed for CVD/delta — no reconstruction against the book is required (unlike some other exchanges/feeds that only provide `is_buyer_maker`, requiring inversion). CandleViewer's recorder should store `(T, s, S, v, p, i)` per trade at minimum.

**Cadence:** push on every match; Bybit does not batch/throttle `publicTrade`.

**CandleViewer requirement:** `WS` (record every message; not retrievable historically at fill granularity via REST beyond ~1000 most recent).

### 2.2 CVD (Cumulative Volume Delta)

**Definition:** For each executed trade `i` with taker side `S_i` and size `v_i`:

```
signedVolume_i = +v_i   if S_i == Buy
signedVolume_i = -v_i   if S_i == Sell

delta(bar) = Σ signedVolume_i  for all trades i within the bar's time/tick/volume/range window

CVD(t) = CVD(anchor) + Σ_{i: anchor ≤ time_i ≤ t} signedVolume_i
```

CVD is a **running (cumulative) sum of signed trade volume**, plotted as its own series (line or bar-based), reset at an anchor point (session start, UTC day boundary, custom anchor, or "since chart load").

**Variants:**
- **Session-reset CVD:** resets to 0 at a fixed daily time (e.g., 00:00 UTC, or exchange's daily settlement time). Requires CandleViewer to define a "session" concept for crypto (which trades 24/7) — typically UTC-day or a user-configurable anchor hour.
- **Anchored CVD:** user picks an arbitrary anchor bar/time (a swing high/low, a news event, funding time) and CVD accumulates from there — same mechanism as anchored VWAP (§5.2), just replacing price×volume with signed volume.
- **Per-timeframe CVD:** CVD can be computed and displayed at any bar resolution (1m, 1h, 1D...) by aggregating the underlying tick-level signed volumes into that timeframe's cumulative series; the underlying event stream (`publicTrade`) is timeframe-agnostic, only the display/reset cadence changes.
- **Multi-symbol / composite CVD:** sum CVD across multiple perp/spot venues or across linear+inverse for the same base asset (advanced; requires normalizing to consistent size units, e.g. USD notional rather than contracts, because inverse contracts are USD-denominated size and linear are coin-denominated).

**Per-bar delta:** `delta(bar)` as defined above — the net signed volume within a single OHLCV bar. Displayed as a column beneath/within the bar (delta bars) or as a footprint-cell aggregate (§3).

**Min/max delta (delta range) per bar:** requires reconstructing the **intra-bar running delta path**, not just the bar's final delta. Algorithm:
```
runningDelta = 0
minDelta = +inf; maxDelta = -inf
for each trade i in bar (in time order):
    runningDelta += signedVolume_i
    minDelta = min(minDelta, runningDelta)
    maxDelta = max(maxDelta, runningDelta)
# min/maxDelta describe how far the cumulative delta swung within the bar,
# useful for spotting delta flips (buy pressure that reversed to sell pressure intrabar)
```
This is a `LOCAL` metric — Bybit has no bar-level delta concept; CandleViewer must maintain the running intrabar sum per open bar as trades stream in.

**Delta divergence:** occurs when price makes a new high/low but delta (or CVD) does not confirm — e.g., price prints a higher high while per-bar delta or CVD prints a lower high, suggesting the move was not supported by aggressive buying. Detection heuristic (`LOCAL`, built on top of CVD/delta series once computed):
```
bullish_price_new_high = close[t] > max(close[t-1], ..., close[t-N])
bearish_delta_no_confirm = delta[t] < delta[t_prevHighBar]   # or CVD[t] < CVD[t_prevHighBar]
if bullish_price_new_high and bearish_delta_no_confirm:
    flag "bearish divergence" (price up, effort down)
# symmetric for bullish divergence on new lows
```

**Multi-bar variant (gap fix):** the single-bar heuristic above compares only the current bar against the immediately preceding swing-high/low bar. A more rigorous, industry-standard formulation looks for divergence **across a rolling window of N bars** rather than a single bar pair, which reduces false positives from noisy single-bar comparisons:
```
def cvd_divergence(bars, N=10):
    window = bars[-N:]
    priceHighIdx = argmax(window.close)      # or argmax(window.high)
    priceLowIdx  = argmin(window.close)      # or argmin(window.low)
    cvdHighIdx   = argmax(window.cvd)
    cvdLowIdx    = argmin(window.cvd)

    # Bearish divergence: price makes its window-high at/after the bar where CVD made its window-high,
    # but price's high bar is later than (or higher than a prior comparable swing) while CVD's high bar
    # is earlier/lower -- i.e., the *trend* of swing highs in price vs. swing highs in CVD diverge:
    bearish = (window.close[priceHighIdx] > prior_swing_high(window, priceHighIdx)
               and window.cvd[priceHighIdx] < window.cvd[cvdHighIdx] < prior_swing_cvd_high(window))

    # Bullish divergence: symmetric, using swing lows
    bullish = (window.close[priceLowIdx] < prior_swing_low(window, priceLowIdx)
               and window.cvd[priceLowIdx] > window.cvd[cvdLowIdx] > prior_swing_cvd_low(window))

    return {"bearish": bearish, "bullish": bullish}
```
In words: rather than a single-bar-to-single-bar comparison, the multi-bar variant identifies **swing highs/lows in both price and CVD independently over the same lookback window** and checks whether the sequence of price swing highs is rising while the corresponding sequence of CVD swing highs is falling (bearish), or the reverse for swing lows (bullish) — the same "higher high in price / lower high in indicator" logic used for classical RSI/MACD divergence detection, applied to CVD instead of an oscillator. `N` (lookback bars) and the swing-detection method (simple argmax/argmin over the window vs. a proper pivot/fractal detector requiring confirmation bars on both sides) are both configurable; a pivot-based swing detector is generally preferred over naive argmax/argmin to avoid flagging divergence against a bar that isn't a "real" local extreme.


**Data source summary:** `LOCAL`, built from `publicTrade` (WS) taker-side trades — Bybit provides no bar-delta, CVD, or divergence primitives directly.

## 3. Footprint / bid×ask cells, imbalances, unfinished auctions

### 3.1 Footprint cells (bid × ask per price level per bar)

**Definition:** For a given bar (time/tick/volume/range bar) and a given price level (tick) within that bar's range, a footprint cell records:
```
cell(price, bar) = {
    bidVolume: Σ v_i for trades i where price_i == price and side_i == Sell (aggressor sold, hit the bid)
    askVolume: Σ v_i for trades i where price_i == price and side_i == Buy  (aggressor bought, lifted the ask)
    delta:     askVolume - bidVolume
    totalVolume: askVolume + bidVolume
    tradeCount: count(i)
}
```
Rendered as a grid: rows = price ticks within the bar's high-low range, columns = bars; each cell shows `bidVolume x askVolume` (or delta, or total volume, depending on the chosen footprint mode — Volume, Delta, Bid×Ask, or Volume Profile mode).

**Data source:** `LOCAL` — must be built entirely from `publicTrade` WS stream (price + size + taker side per trade), grouped by `(price rounded to tick size, bar)`. Tick size per symbol comes from `REST GET /v5/market/instruments-info` → `priceFilter.tickSize` (and CandleViewer may also let the user group multiple exchange ticks into a coarser footprint row — "tick grouping").

### 3.2 Diagonal imbalance & stacked imbalance (ratio threshold, e.g. 300%)

**Diagonal imbalance:** compares the ask volume at price level `P` to the bid volume one tick **below** `P` (for a buy-side imbalance), or the bid volume at `P` to the ask volume one tick **above** (for a sell-side imbalance) — a diagonal (not same-row) comparison, reflecting how footprint reading works (an aggressive buyer lifting offers at P is compared to the aggressive seller hitting bids one tick lower, since these are the "competing" flows at the same relative moment as price transits that boundary).
```
buy_imbalance(P)  = askVolume(P) / bidVolume(P - tick)     # flag if >= ratio threshold (e.g., 3.0 = 300%)
sell_imbalance(P) = bidVolume(P) / askVolume(P + tick)     # flag if >= ratio threshold
```
Common default ratio threshold: **300%** (i.e., dominant side ≥ 3× the diagonal opposite), configurable; some platforms also require a minimum absolute volume filter to suppress noise on thin levels. *Verified against industry practice: ATAS's own "Imbalance Levels" / stacked-imbalance indicators use the same default of a **5x (500%)** ratio in some presets and **3x (300%)** in others depending on indicator version, with a default **minimum stack of 3 consecutive levels** — i.e., CandleViewer's chosen 300%/3-level defaults sit within the commonly-used ATAS/Sierra Chart range rather than being an arbitrary example number, though traders commonly retune the ratio between 3x–5x depending on symbol/timeframe. Both values should remain user-configurable rather than hardcoded.*

**Stacked imbalance:** ≥ N consecutive price levels (commonly N=3, configurable) each showing a diagonal imbalance in the **same direction** (all buy-imbalances or all sell-imbalances). Interpreted as a zone of aggressive, sustained one-sided flow, often treated as a support (stacked buy imbalances) or resistance (stacked sell imbalances) zone on retest.
```
def stacked_imbalances(bar, minStack=3, ratio=3.0, minVolume=0):
    flags = [level for level in bar.priceLevels if is_diagonal_imbalance(level, ratio, minVolume)]
    # group consecutive same-direction flags; keep runs with length >= minStack
    return runs_of_consecutive_same_direction(flags, minStack)
```

**Data source:** `LOCAL`, computed on top of the footprint cells above (§3.1), which are themselves `LOCAL` from `publicTrade`.

### 3.3 Unfinished auctions

**Definition:** A footprint concept describing a bar where price closed at (or very near) its high with significant ask-side volume still trading right at the top tick (or closed at/near its low with significant bid-side volume trading at the bottom tick) — i.e., the "auction" for that price extreme did not visibly exhaust before the bar ended, suggesting continuation is likely on the next bar. Detection heuristic:
```
def unfinished_auction_high(bar, minVolumeAtExtreme):
    topTick = bar.high
    return bar.close == topTick and cell(topTick, bar).totalVolume >= minVolumeAtExtreme
# symmetric for unfinished_auction_low using bar.low and bar.close == bottomTick
```

**Data source:** `LOCAL`, derived from footprint cells (§3.1).

### 3.4 POC / VA per bar (intrabar profile)

A per-bar Point of Control and Value Area can be computed from the same footprint cell data (i.e., a mini volume profile confined to that single bar's price range) — see §4 for the general POC/VA algorithm, applied here with `priceLevels` limited to the bar's own footprint cells rather than a full session.

## 4. Volume profile & TPO

### 4.1 Volume profile, POC, Value Area (70%)

**Volume profile** is a histogram of traded volume by price level (not by time) over a chosen period (session, custom range, or composite of multiple periods).

**Point of Control (POC):** the price level with the single highest traded volume in the profile.

**Value Area (default 70%):** the contiguous range of price levels around the POC that together contain ~70% of total volume in the profile. Algorithm:
```
def value_area(priceLevels, targetPct=0.70):
    # priceLevels: dict price -> volume, already aggregated over the profile period
    totalVolume = sum(priceLevels.values())
    poc = max(priceLevels, key=priceLevels.get)
    included = {poc}
    runningVolume = priceLevels[poc]
    sortedPrices = sorted(priceLevels.keys())
    pocIndex = sortedPrices.index(poc)
    lo, hi = pocIndex, pocIndex
    while runningVolume < targetPct * totalVolume:
        # look at the next price step above and below the current VA range,
        # each time adding whichever single step (or pair of steps, per row) has more volume
        volAbove = priceLevels.get(sortedPrices[hi+1]) if hi+1 < len(sortedPrices) else 0
        volBelow = priceLevels.get(sortedPrices[lo-1]) if lo-1 >= 0 else 0
        if volAbove == 0 and volBelow == 0:
            break
        if volAbove >= volBelow:
            hi += 1; runningVolume += volAbove
        else:
            lo -= 1; runningVolume += volBelow
    return {
        "poc": poc,
        "vah": sortedPrices[hi],   # Value Area High
        "val": sortedPrices[lo],   # Value Area Low
    }
```
Note: standard implementations expand the VA two price rows at a time (mimicking the original TPO-based algorithm which worked in "double-tick" increments); the simplified single-step version above is an acceptable close approximation used by many modern volume-profile tools. 70% is the market convention (approximates one standard deviation of a normal distribution); some platforms allow adjusting this to 68% or 80%.

**Naked POC (Virgin POC):** the POC of a **previous** period's profile that price has not yet traded back through since that period ended. Tracked by keeping each historical period's POC and marking it "naked" until a subsequent bar's [low, high] range covers it, at which point it flips to "tested."

**HVN / LVN (High/Low Volume Nodes):** local maxima / minima in the volume-by-price histogram — HVNs are price levels with disproportionately high volume relative to neighboring levels (often acting as consolidation/support-resistance zones); LVNs are levels with disproportionately low volume (price tends to move through these quickly, "air pockets"). Detected via peak/trough detection on the smoothed volume-by-price series (e.g., a level is an HVN if its volume exceeds both neighbors by some factor, or via a rolling-window local-maxima scan).

**Composite profile:** a volume profile built by summing `priceLevels` across multiple sub-periods (e.g., multiple sessions, or a custom multi-day range) before computing POC/VA — same algorithm as above, just with pre-aggregated volume across a longer or user-selected range.

**Data source:** `LOCAL`. Bybit provides no volume-by-price/profile endpoint. CandleViewer must build `priceLevels` from the `publicTrade` WS stream (grouping by tick-rounded price) accumulated over the desired session/period, exactly the same underlying data as footprint cells (§3.1) but aggregated across the whole period instead of per-bar.

### 4.2 TPO (Time Price Opportunity) / Market Profile

**Definition:** Instead of summing traded volume at each price, TPO counts the number of discrete time periods ("TPO periods," classically 30 minutes, labeled with letters A, B, C, ...) during which price traded at each level.
```
def build_tpo(trades_or_bars, periodMinutes=30):
    periods = split_into_time_periods(trades_or_bars, periodMinutes)  # each period gets a letter
    tpoCounts = defaultdict(set)  # price -> set of period-letters that touched this price
    for letter, period in periods:
        for price in price_levels_touched_in(period):  # from period's low..high (using the period's own high/low, or footprint prices)
            tpoCounts[price].add(letter)
    # "TPO count" per price = len(tpoCounts[price])
    # POC/VA/HVN/LVN computed the same way as volume profile, but using TPO-count instead of volume
```
TPO can diverge from volume profile especially on days with a few very large trades concentrated at one level (high volume, low TPO count) vs. many small trades spread across time at another level (lower volume, high TPO count). Both are complementary "auction theory" views.

**Data source:** `LOCAL`, built from bar high/low ranges (from klines) or from trade prices directly, bucketed into 30-minute (or configurable) periods.

## 5. VWAP variants

### 5.1 Session VWAP

```
VWAP_t = Σ_{i=sessionStart}^{t} (price_i * volume_i) / Σ_{i=sessionStart}^{t} volume_i
```
Where `price_i` is typically the trade price (tick-level) or the typical price `(H+L+C)/3` of bar `i` if computed from bars rather than raw trades. Resets at a fixed session boundary — for 24/7 crypto, CandleViewer should let the user choose the reset anchor (00:00 UTC daily is the most common convention; Bybit's own funding/settlement cadence, e.g., 00:00/08:00/16:00 UTC, is another reasonable choice).

### 5.2 Anchored VWAP (AVWAP)

Same formula as session VWAP but the summation starts from a user-chosen anchor bar/time (a swing high/low, an event, a funding timestamp) instead of session open:
```
AVWAP_t = Σ_{i=anchor}^{t} (price_i * volume_i) / Σ_{i=anchor}^{t} volume_i
```

### 5.3 Rolling / Moving VWAP (MVWAP)

Uses a fixed-length trailing window of `n` bars/trades instead of resetting at a session boundary — a continuously "rolling" VWAP that never resets:
```
MVWAP_t = Σ_{i=t-n+1}^{t} (price_i * volume_i) / Σ_{i=t-n+1}^{t} volume_i
```

### 5.4 VWAP standard-deviation bands

Compute the volume-weighted variance of price around VWAP over the same window (session/anchored/rolling), then band at `±kσ`:
```
σ_t = sqrt( Σ_{i=a}^{t} [ (price_i - VWAP_t)^2 * volume_i ] / Σ_{i=a}^{t} volume_i )
upperBand_k = VWAP_t + k * σ_t
lowerBand_k = VWAP_t - k * σ_t
```
Typical multipliers: k = 1, 2, 3 (Bollinger-style multi-band). `a` = the same anchor as whichever VWAP variant is in use (session start, custom anchor, or rolling window start).

**Data source:** `LOCAL`. Bybit's kline endpoints give OHLCV per bar which is sufficient to approximate VWAP from bar-level `(typical price × volume)` if trade-level granularity is not stored, but for accuracy CandleViewer should compute VWAP directly from the `publicTrade` WS stream (trade price × trade size), which it is already recording for CVD/footprint purposes — same underlying data, different aggregation.

## 6. Open interest & OI-price quadrant analysis

### 6.1 Open interest (REST + WS)

**Bybit source:**
- `REST GET /v5/market/open-interest` — params: `category` (`linear`/`inverse`, required), `symbol` (required), `startTime`, `endTime`, `intervalTime` (documented values include `5min`, `15min`, `30min`, `1h`, `4h`, `1d`), `limit` ([1,200], default 50), `cursor`. Response `list[]` items: `openInterest` (sum of both sides), `singleOpenInterest` (single side), `timestamp`. **Units:** for inverse contracts (e.g. `BTCUSD`) the unit is **USD**; for linear contracts (e.g. `BTCUSDT`) the unit is the **base coin** (e.g. BTC) — i.e. OI is always expressed in the *non-settlement* leg's natural unit. To express linear OI in USD, multiply `openInterest` (in BTC) by the current mark/last price.
- `WS` topic `tickers.{symbol}` also streams `openInterest` and `openInterestValue` (the latter explicitly in USD/quote-notional) as part of the broader ticker payload, at 100ms cadence for derivatives — this is the practical live-tracking source; the REST endpoint is better for historical backfill at the supported `intervalTime` granularities.

**OI delta per bar:** `LOCAL` — `OIdelta(bar) = OI(bar.close_time) - OI(bar.open_time)`, computed by sampling/interpolating the OI series (from WS ticker updates or REST interval snapshots) at each bar boundary.

### 6.2 OI-price quadrant analysis

Classifies each bar (or each OI-sample interval) into one of four regimes by comparing the **sign of price change** to the **sign of OI change** over the same window:

| Price change | OI change | Regime | Interpretation |
|---|---|---|---|
| Up | Up | **Long build-up** | New longs entering, driving price up with fresh leverage |
| Up | Down | **Short covering** | Price rising because shorts are closing (buying back), not necessarily new longs |
| Down | Up | **Short build-up** | New shorts entering, driving price down with fresh leverage |
| Down | Down | **Long liquidation / long unwind** | Price falling because longs are closing/being liquidated, OI unwinding |

```
def oi_price_quadrant(priceChange, oiChange):
    if priceChange > 0 and oiChange > 0: return "Long build-up"
    if priceChange > 0 and oiChange < 0: return "Short covering"
    if priceChange < 0 and oiChange > 0: return "Short build-up"
    if priceChange < 0 and oiChange < 0: return "Long liquidation / unwind"
    return "Neutral / flat"
```

**Data source:** `HYBRID` — OI itself is `REST`+`WS` (Bybit-provided), but the quadrant classification logic is `LOCAL` (simple derived comparison against price change over the same interval).

## 7. Funding rate

### 7.1 Current & predicted funding rate

**Bybit source:**
- `WS` topic `tickers.{symbol}` includes `fundingRate` (current/last-settled rate for the symbol) and `nextFundingTime` (ms timestamp of next settlement), plus `fundingIntervalHour` (e.g. `"8"`) and `fundingCap`/`fundingFloor` limits (perpetual only; futures instead expose `basisRateYear`). Push cadence: 100ms for derivatives.
- `REST GET /v5/market/instruments-info` exposes the static `fundingInterval` (in **minutes**, e.g. `480` = 8 hours) per symbol, plus `upperFundingRate`/`lowerFundingRate` caps.
- Bybit's public API does not expose a separate "predicted next funding rate" numeric field distinct from the current settled `fundingRate` in the same way some other venues do; the practical predicted rate is the **currently-accruing** rate that will apply at `nextFundingTime`, computed by Bybit internally from the interest-rate/premium-index formula and reflected via the ticker stream in real time before settlement. CandleViewer should treat `tickers.{symbol}.fundingRate` as "the rate that will be charged at nextFundingTime" until it flips over.

### 7.2 Funding rate history

**Bybit source:** `REST GET /v5/market/funding/history` — params: `category` (`linear`/`inverse`), `symbol`, `startTime`, `endTime`, `limit` ([1,200], default 200). Response `list[]`: `symbol`, `fundingRate`, `fundingRateTimestamp`. Docs note: passing only `startTime` errors; passing only `endTime` returns 200 records up to `endTime`; passing neither returns the most recent 200 records. Each symbol has its own settlement interval (commonly 8h = 480 min, but Bybit has introduced 1h/2h/4h intervals for some symbols — always check `fundingInterval` via instruments-info rather than assuming 8h).

### 7.3 Annualized funding rate

**Definition:** normalizes the per-interval funding rate to an annual percentage, for comparability across symbols with different funding intervals:
```
periodsPerYear = (365 * 24 * 60) / fundingIntervalMinutes
annualizedFundingRate = fundingRate * periodsPerYear
```
E.g., for an 8-hour interval (480 min): `periodsPerYear = 1095`; a funding rate of `0.01%` per period annualizes to `~10.95%`.

**Data source:** `HYBRID` — raw funding rate + interval are Bybit-provided (`REST`/`WS`); annualization is a trivial `LOCAL` computation.

## 8. Mark price, index price, basis/premium

### 8.1 Mark price & index price

**Bybit source:**
- `WS` topic `tickers.{symbol}`: `markPrice`, `indexPrice`, `lastPrice` all streamed together, 100ms cadence.
- Bybit also exposes historical **mark price kline** and **index price kline** REST endpoints (`/v5/market/mark-price-kline`, `/v5/market/index-price-kline`) returning OHLC series for mark/index price at the same interval granularities as the regular kline endpoint (`1,3,5,15,30,60,120,240,360,720,D,W,M`), which is the main way to get *historical* mark/index price bars (the ticker WS stream is live-only).
- **Index price** is Bybit's composite reference price (aggregated from multiple spot exchanges, methodology not fully published in the public docs beyond "composite index of major spot exchanges"). **Mark price** is used for margin/liquidation calculations and is typically the index price adjusted by a smoothed basis component (to avoid manipulation via last-traded-price spikes on Bybit alone) — Bybit's help center describes mark price as designed to track fair value and prevent unnecessary liquidations from temporary Bybit-only price dislocations.

### 8.2 Basis / premium index

**Definition:**
```
basis = lastPrice (or markPrice) - indexPrice
premiumPct = basis / indexPrice * 100
```
For dated futures (not perpetuals), Bybit's `tickers` payload includes `basisRateYear` (annualized basis rate) directly for `LinearFutures`/`InverseFutures` contract types (perpetuals instead return `fundingRate`/`fundingCap`, since perpetuals use funding rather than basis convergence to track spot).

**Data source:** `HYBRID` — raw mark/index/last prices are Bybit-provided (`WS` live, `REST` mark/index klines for history); basis/premium % is a trivial `LOCAL` derived computation; annualized basis for dated futures is provided directly by Bybit (`basisRateYear`, `WS`).

### 8.3 Premium-index-price kline — a distinct historical basis series (gap fix)

Bybit also exposes `GET /v5/market/premium-index-price-kline`, a **third, separate** kline series alongside `mark-price-kline` and `index-price-kline` (§8.1), specifically for the **premium index** — i.e., the funding-rate-relevant premium/discount of the perpetual contract's price versus its underlying index, expressed as an OHLC series over time rather than a live-only ticker field. This closes a gap in the original draft, which only discussed live `tickers.{symbol}` basis fields and the mark/index klines, implying CandleViewer would need to locally record every basis/premium data point from the live ticker stream to get history — that is unnecessary since Bybit already retains this as queryable kline history.

- **Endpoint:** `GET /v5/market/premium-index-price-kline`
- **Category support:** `linear` only (perpetuals/premium index is a linear-contract concept; not applicable to `inverse`, `spot`, or `option`).
- **Params:** `category` (must be `linear`), `symbol`, `interval` (`1,3,5,15,30,60,120,240,360,720,D,M,W` — same granularity set as regular/mark/index klines), `start`, `end` (ms timestamps), `limit` (default and max **1000** per request).
- **Response:** array of `[startTime, open, high, low, close]` premium-index values (no volume field, since it's a derived index series, not a traded-volume series) — i.e., an OHLC series of the *premium index* itself, which is the input Bybit's funding-rate formula smooths/averages over the funding interval, not the raw `basis = markPrice - indexPrice` spot-in-time difference computed in §8.2.
- **Relationship to §8.2's `basis`/`premiumPct`:** the premium-index-price-kline series is Bybit's own **funding-rate-relevant** premium calculation (used internally in Bybit's funding formula), whereas §8.2's `basis = markPrice - indexPrice` is a simpler, general-purpose spot-in-time basis definition. CandleViewer should treat `premium-index-price-kline` as the authoritative **historical, chartable** premium/basis series (`REST`, no local recording needed for history), and reserve the `LOCAL` basis calc from §8.2 for live-only display or for symbols/timeframes where the kline series doesn't have coverage.
- **Data source:** `REST` (fully Bybit-provided historical series) — this reclassifies part of §8.2's `HYBRID` basis/premium history from "must be locally recorded" to "available as native Bybit kline history," a meaningful simplification for CandleViewer's recorder scope.



## 9. Liquidations

### 9.1 Bybit liquidation streams — semantics

Bybit v5 offers two related public WS topics:

- **`allLiquidation.{symbol}`** — "push all liquidations that occur on Bybit" for USDT/USDC/Inverse contracts. Push frequency: **500ms** (batched, not per-event instantaneous). Topic example: `allLiquidation.BTCUSDT`. Response `data[]` fields (per official docs example): `T` (updated timestamp ms), `s` (symbol), `S` (side of the liquidation order — `Buy` or `Sell`), `v` (quantity liquidated), `p` (price). Example payload:
```json
{
  "topic": "allLiquidation.ROSEUSDT",
  "type": "snapshot",
  "ts": 1739502303204,
  "data": [
    { "T": 1739502302929, "s": "ROSEUSDT", "S": "Sell", "v": "20000", "p": "0.04499" }
  ]
}
```
- There is also a legacy/simpler **`liquidation.{symbol}`** topic referenced in older Bybit docs/SDKs (single-order push, since deprecated/merged in favor of `allLiquidation` per current docs structure — the exact current top-level nav no longer surfaces a standalone `liquidation` page at the URL checked; `allLiquidation` is the current documented topic for public liquidation data as of Sept 2026). CandleViewer should subscribe to `allLiquidation.{symbol}` per-symbol as the primary source, and treat any 404 on a legacy topic as expected/deprecated.
- **Important caveat (documented behavior on this stream family historically):** Bybit's liquidation feed pushes at most one update per symbol per fixed interval window (500ms), meaning multiple liquidation events within the same 500ms window for the same symbol are batched into a single `data[]` array (the example shows an array, confirming batching support) rather than being individually rate-limited away — but a burst of liquidations occurring inside one interval could still be represented as fewer discrete pushes than raw underlying liquidation-engine events; the CandleViewer recorder should store the full array from every message and should not assume exactly one liquidation record per API push.
- `S` (side) in the liquidation payload is the side of the **liquidated position's closing order** — e.g. `S: "Sell"` means a long position was liquidated (forced to sell to close), `S: "Buy"` means a short position was liquidated (forced to buy to close).
- Also referenced: a bankruptcy-price field `p`/related concept exists in the extended schema tied to [Bybit's Bankruptcy Price definition](https://www.bybit.com/en-US/help-center/s/article/Bankruptcy-Price-USDT-Contract) — the price at which the position's margin balance reaches zero.

### 9.2 Aggregating into liquidation bars / heatmap

**Liquidation bars (time-bucketed):** aggregate raw liquidation events into the chart's bar resolution, summing notional (`price * qty`) separately for long-liquidations (`S=Sell`) and short-liquidations (`S=Buy`):
```
def liquidation_bar(events_in_bar):
    longLiqNotional  = sum(e.price * e.qty for e in events_in_bar if e.side == "Sell")
    shortLiqNotional = sum(e.price * e.qty for e in events_in_bar if e.side == "Buy")
    return {"longLiq": longLiqNotional, "shortLiq": shortLiqNotional, "count": len(events_in_bar)}
```
Rendered as a histogram beneath the price chart, or as colored markers sized by notional, split by side.

**Liquidation heatmap (price × time grid):** bucket liquidation notional into a 2D grid of `(price bucket, time bucket)` cells, then color by cumulative liquidated notional per cell (with optional decay over time so older cells fade) — same grid-construction technique as the order-book liquidity heatmap (§11.3), but populated from actual realized liquidation events instead of resting order-book size.

**Data source:** `WS` (`allLiquidation.{symbol}`) for raw events; all aggregation into bars/heatmap is `LOCAL`.

### 9.3 Estimated liquidation levels (Coinglass/Hyblock-style, from OI + leverage distributions)

Unlike realized liquidations (§9.1–9.2, which are actual historical events Bybit pushes), **estimated liquidation levels** are a **predictive/probabilistic model** of where currently-open positions would be force-closed if price moved there — this is not data Bybit (or any exchange) publishes directly (individual traders' entry price/leverage/margin mode are private), so third-party tools like Coinglass and Hyblock Capital build a proprietary estimate. Based on public research (Coinglass's own docs/help articles; exact formulas are proprietary and not fully disclosed), the general methodology is:

1. **Aggregate market data** across as many exchanges/pairs as possible: total open interest per symbol, historical price action, and *assumed* leverage-tier distributions (since actual per-trader leverage is private, providers infer a typical leverage histogram from known platform defaults, historical liquidation-event backtests, and funding/OI dynamics).
2. **Back-calculate hypothetical liquidation prices** for a spread of assumed leverage levels (e.g., model positions opened at various recent prices with 5x, 10x, 25x, 50x, 100x leverage) using standard isolated-margin liquidation-price math:
```
# Simplified isolated-margin long liquidation price (ignoring funding/fees adjustments):
liqPrice_long  ≈ entryPrice * (1 - 1/leverage + maintenanceMarginRate)
liqPrice_short ≈ entryPrice * (1 + 1/leverage - maintenanceMarginRate)
```
   where `maintenanceMarginRate` is exchange- and tier-specific (obtainable from Bybit's own risk-limit/maintenance-margin tables via `REST GET /v5/market/risk-limit`, which CandleViewer *can* query directly for its own liquidation-price estimates rather than relying on a third-party black box).
3. **Weight/aggregate these hypothetical liquidation prices by estimated notional at each entry price** (using recent volume/OI-at-price as a proxy for "how much size likely entered near this price"), producing a distribution of liquidation-price "mass" across price levels.
4. **Render as a heatmap:** Y-axis = price levels, color intensity = aggregated estimated liquidation notional at that price, often with a time/candle axis overlay for context. Coinglass's public "Model 3" API structure (confirmed via their published API docs) returns `y_axis` (price levels), `liquidation_leverage_data` (array of `[xIndex, yIndex, notionalValue]` triplets), and `price_candlesticks` (OHLCV for context).
5. **Explicit limitation, stated by Coinglass itself:** these are estimates, not confirmed liquidation data — real liquidations may differ; the intensity map is meant to show relative "risk zones" / potential price magnets, not exact predicted volumes.

**For CandleViewer**, a first-party (non-Coinglass-dependent) approximation is achievable by combining: (a) Bybit's own OI series (§6.1), (b) Bybit's maintenance margin/risk-limit tiers (`REST /v5/market/risk-limit`, giving `maintainMargin` per notional bracket per symbol), and (c) an assumed/estimated leverage distribution informed by CandleViewer's own recorded realized-liquidation history (§9.1–9.2) as a calibration input (i.e., backtest which assumed leverage buckets best explain the historically observed liquidation-price clusters, then reuse that calibration going forward) — this is a nontrivial modeling project flagged in [Open questions](#open-questions).

**Data source:** No Bybit endpoint provides this directly — `LOCAL` computed/estimated using Bybit OI (`REST`/`WS`) + Bybit risk-limit/maintenance-margin tables (`REST`) + a locally-calibrated leverage-distribution model informed by recorded realized liquidations.

### 9.4 Insurance fund data (out-of-scope note, gap fix)

Bybit exposes a public insurance-fund endpoint: **`GET /v5/market/insurance`** — no authentication required. It returns the current balance and last-updated timestamp of Bybit's insurance fund(s), broken out **by coin** (e.g., `USDT`, `USDC`, `BTC`, `ETH` pools), reflecting the reserve Bybit maintains to cover shortfalls from liquidations that close at worse-than-bankruptcy prices (avoiding auto-deleveraging of profitable counterparties). Response fields (per coin entry): `coin`, `balance`, and the payload's top-level `updatedTime`.

Some order-flow/liquidation-focused terminals (in the Coinglass/Hyblock mold) display insurance-fund balance alongside a liquidation feed as ambient "systemic risk" context (a fund balance that is flat or growing suggests liquidations are being absorbed normally; a fast-draining fund alongside a liquidation cascade is a stress signal). Bybit only exposes the **current balance snapshot**, not a granular historical time series via this endpoint — a historical chart of insurance-fund balance would require CandleViewer to poll `/v5/market/insurance` periodically (e.g., hourly) and record the values itself (`HYBRID`: live/latest value is `REST`-fetchable on demand; a history/chart of it is `LOCAL`, built by CandleViewer's own periodic polling since Bybit does not appear to expose a kline/history endpoint for insurance-fund balance).

**Scope decision for CandleViewer:** this document treats insurance-fund display as **explicitly out of scope for the initial build** (it is not part of the DeepCharts feature set CandleViewer is replicating — DeepCharts' own public feature pages do not list insurance-fund balance as a tracked metric either) but is documented here so the option exists later: it would be a low-cost addition (single low-frequency REST poll, no WS needed) if a future iteration wants it as auxiliary liquidation-cascade context.

**Data source:** `REST` (current snapshot, `GET /v5/market/insurance`, public/no-auth); `LOCAL` if historical charting of the balance is wanted (Bybit provides no insurance-fund kline/history endpoint).

## 10. Long/short account ratio & taker buy/sell ratio

### 10.1 Long/short account ratio

**Bybit source:** `REST GET /v5/market/account-ratio` — params: `category` (`linear`/`inverse`), `symbol`, `period` (e.g. `5min`, `15min`, `30min`, `1h`, `4h`, `1d`), `limit` (default/max around 50, up to 500 per some references — confirm against live docs at call time as Bybit periodically revises limits). Response `list[]`: `timestamp`, `buyRatio`/`longAccountRatio` and `sellRatio`/`shortAccountRatio` (exact field names should be verified against the live response schema at implementation time, as this endpoint's documentation page returned a 404 in this research pass and had to be reconstructed from third-party summaries — flagged in Open Questions). Definition: percentage of **accounts** (not position size) holding net-long vs net-net-short positions on Bybit over the given period — a sentiment gauge, not a size-weighted metric.
```
longAccountRatio + shortAccountRatio = 1.0   (approximately, by construction)
```
No WS equivalent is documented; this is REST-only, polled periodically (e.g. every `period` interval).

### 10.2 Taker buy/sell volume ratio

Bybit does not appear to expose a dedicated "taker buy/sell ratio" REST endpoint analogous to Binance's `takerlongshortRatio`; the equivalent is derived `LOCAL` by aggregating the taker `side` field from `publicTrade` (§2.1) over a chosen window:
```
def taker_buy_sell_ratio(trades_in_window):
    buyVol  = sum(t.size for t in trades_in_window if t.side == "Buy")
    sellVol = sum(t.size for t in trades_in_window if t.side == "Sell")
    return buyVol / sellVol if sellVol > 0 else float('inf')
    # or express as buyVol / (buyVol + sellVol) for a 0-1 normalized ratio
```

**Data source:** account ratio = `REST` (Bybit-provided, low-frequency poll); taker buy/sell ratio = `LOCAL` (derived from `publicTrade` WS stream, same raw data as CVD).

## 11. Order book metrics & liquidity heatmap

### 11.1 Order book WS feed — snapshot/delta semantics

**Bybit source:** `WS` topic `orderbook.{depth}.{symbol}`. Documented depth levels per category (confirm exact set per category in live docs; commonly `1, 50, 200, 500` for linear/inverse and `1, 50, 200` for spot, with `1000` available on some categories) — CandleViewer should query the docs at integration time per category since Bybit has expanded depth tiers over time.

**Processing snapshot → delta:**
- First message per subscription is `type: "snapshot"` — full book state at that depth.
- Subsequent messages are `type: "delta"` — apply as: if size == 0 for a price, delete that level; if the price doesn't exist locally, insert it; if it exists, overwrite the size.
- Response fields: `topic`, `type` (`snapshot`/`delta`), `ts` (system-generated timestamp, ms), `data.s` (symbol), `data.b[]` (bids, `[price, size]`, sorted descending), `data.a[]` (asks, `[price, size]`, sorted ascending), `data.u` (update ID — occasionally resets to `1`, signaling a service-restart snapshot that must overwrite local state entirely), `data.seq` (cross-sequence number for ordering/dedup across redundant connections), `cts` (matching-engine timestamp, correlatable with the `T` field on the public trade channel for causal ordering between trades and book changes).
- Field ordering quirk (documented): for **spot (all levels)** and **futures Level-1**, `ts` appears before `type` in the JSON; for **futures (all other levels)**, `ts` appears after `type` — a parsing detail CandleViewer's WS client must not assume a fixed key order for.
- Level-1 (`orderbook.1.{symbol}`) resends the snapshot every 3 seconds even with no change, reusing the same `u` — useful as a heartbeat/liveness check for that specific topic.

### 11.2 Basic order book metrics

**Order book imbalance:**
```
imbalance = (sumBidSize - sumAskSize) / (sumBidSize + sumAskSize)   # range [-1, +1]
# computed over top-N levels, or over all levels within a fixed price band (e.g., ±X% from mid)
```

**Depth at ±1% / ±2% (or other bands):**
```
def depth_within_pct(book, midPrice, pct):
    bidDepth = sum(size for price, size in book.bids if price >= midPrice * (1 - pct))
    askDepth = sum(size for price, size in book.asks if price <= midPrice * (1 + pct))
    return bidDepth, askDepth
```

**Cumulative depth (for DOM ladder / depth chart):**
```
cumulativeBidDepth[i] = Σ_{j=0}^{i} bidSize[j]   (walking down from best bid)
cumulativeAskDepth[i] = Σ_{j=0}^{i} askSize[j]   (walking up from best ask)
```

**Data source:** `LOCAL` computation on top of the maintained local order book, which is itself `HYBRID` (`WS` snapshot + deltas, continuously applied).

### 11.3 Resting liquidity heatmap construction

A DeepDOM-style liquidity heatmap visualizes resting order-book size across price and time as a 2D grid with color intensity ∝ size, with optional temporal decay so stale/aging levels fade even if not yet consumed.

**Construction pipeline:**
```
1. Maintain the live local order book (per §11.1) at the chosen depth (deeper = better fidelity, more storage).
2. On a fixed sampling cadence (e.g., every book-update tick, or throttled to e.g. 100-250ms to bound storage),
   snapshot the current (price, size) pairs for both sides into a time-indexed store.
3. Quantize price into a fixed tick/row grid (matching or coarser than the symbol's tickSize) and time into
   fixed-width columns (matching the chart's x-axis resolution, e.g. 1 pixel-column per N seconds).
4. For each (priceRow, timeColumn) cell, store the observed size (or a decayed/blended value if multiple
   snapshots fall in the same cell — e.g., max, mean, or last-observed-size within that time bucket).
5. Color normalization: map cell size to a color scale, typically log-scaled (since resting size distributions
   are heavy-tailed — a few huge walls would otherwise wash out all normal-sized levels on a linear scale) and
   normalized per-visible-window (min-max or percentile clipping) so the heatmap auto-contrasts as liquidity
   conditions change, rather than using a single fixed absolute-size-to-color mapping across all time.
6. Decay (optional): apply an exponential or linear fade to a cell's rendered intensity as time passes since
   it was last refreshed/observed at that size, so a big resting wall that hasn't moved still visually
   "ages" if you want to distinguish "old, static wall" from "actively defended, freshly-replenished wall"
   (this decay is a rendering choice, distinct from the iceberg-detection reload heuristic in §12.2, though
   the two can be combined: a decaying-but-reloading level is a strong iceberg/absorption signal).
```

**Storage sizing implication:** full L2 snapshot-and-delta recording at meaningful depth (50-500 levels) for a liquid pair like BTCUSDT, sampled continuously, is one of the largest storage drivers in the whole system — quantified in [§19](#19-data-storage--replay).

**Data source:** `LOCAL`, built entirely from the `orderbook.{depth}.{symbol}` WS feed (§11.1); Bybit provides no heatmap/history endpoint for order-book depth.

## 12. Big trade / iceberg / cluster detection

### 12.1 Big trade detection thresholds

Three common threshold styles, all `LOCAL` computations over the `publicTrade` stream:

**Absolute threshold:** flag any trade where `size >= X` (fixed units, e.g. `>= 10 BTC`) or `notional (price*size) >= $Y` (e.g. `>= $500,000`), configurable per symbol since "big" is relative to typical size.

**Relative threshold (vs. recent average):** flag trades where size exceeds a multiple of a rolling average trade size:
```
rollingAvgSize = EMA(tradeSize, window=N)   # or simple moving average
if trade.size >= k * rollingAvgSize:   # e.g. k = 5-10x
    flag as "big trade"
```

**Rolling z-score threshold:** flag trades whose size is statistically extreme relative to the recent distribution, not just its mean:
```
rollingMean = mean(tradeSize over window N)
rollingStd  = stdev(tradeSize over window N)
z = (trade.size - rollingMean) / rollingStd
if z >= zThreshold:   # e.g. zThreshold = 3.0
    flag as "big trade"
```
Z-score is more robust across changing volatility/liquidity regimes than a fixed absolute or fixed-multiple threshold, since it adapts to the recent activity level automatically.

### 12.2 Aggregating split fills into "iceberg" / "trade cluster" events

A single large market order frequently executes as **many separate fills** against multiple resting orders at the same (or very close) price within a few milliseconds — Bybit's `publicTrade` stream reports each fill as its own event. To reconstruct the "real" size of the underlying aggressive order:
```
def cluster_trades(trades, timeWindowMs=50, priceTolerance=0):
    # group consecutive trades (in time order) that share the same side, same price
    # (or within priceTolerance ticks), and occur within timeWindowMs of each other
    clusters = []
    current = [trades[0]]
    for t in trades[1:]:
        last = current[-1]
        if (t.side == last.side
            and abs(t.price - last.price) <= priceTolerance
            and (t.time - last.time) <= timeWindowMs):
            current.append(t)
        else:
            clusters.append(current)
            current = [t]
    clusters.append(current)
    return [{
        "side": c[0].side,
        "price": c[0].price,             # or volume-weighted avg price across the cluster
        "totalSize": sum(x.size for x in c),
        "fillCount": len(c),
        "startTime": c[0].time,
        "endTime": c[-1].time,
    } for c in clusters]
```
A "cluster" that aggregates to a size/notional above the big-trade threshold (§12.1) is then flagged and displayed as a single large-trade marker/print rather than many small ones — this is the standard technique platforms use to avoid under-representing large orders that were filled in pieces (a distinct concept from "iceberg orders" on the resting side of the book, §12.3 below, though both are colloquially called "iceberg" detection in retail order-flow tooling — CandleViewer should keep the terminology distinct: this section (12.2) is about **aggressor-side split-fill reconstruction from the tape**, §12.3 is about **detecting hidden resting liquidity in the book**).

### 12.3 Iceberg detection from L2 (resting-side, reload heuristic)

**Definition:** an iceberg order shows only a small visible "peak" on the book; as that visible size trades, the hidden remainder reloads at the same price almost immediately, repeating multiple times. Since Bybit's public L2 feed is price-aggregated (no per-order IDs / no Market-by-Order feed), detection must rely on a behavioral heuristic combining the order-book delta stream (§11.1) with the trade tape (§2.1):
```
def detect_iceberg(priceLevel, bookUpdates, trades, minReloadCount=3, sizeTolerancePct=0.2):
    reloadEvents = 0
    lastObservedSize = None
    for update in bookUpdates_at(priceLevel):
        tradedVolumeSinceLastUpdate = sum_trades_at_price_between(trades, priceLevel, prevUpdateTime, update.time)
        if lastObservedSize is not None and tradedVolumeSinceLastUpdate >= lastObservedSize * 0.9:
            # the previously-visible size (or nearly all of it) was consumed by trades...
            newSize = update.size
            if newSize >= lastObservedSize * (1 - sizeTolerancePct):
                # ...and the level "reloaded" back to a similar size almost immediately
                reloadEvents += 1
        lastObservedSize = update.size
    return reloadEvents >= minReloadCount   # flag as probable iceberg if enough reloads observed
```
**Key limitation (must be documented for users):** this is inherently **probabilistic** on Bybit's public feed since only aggregated price-level size is visible, not individual order IDs — a genuine iceberg reload and "coincidental" replenishment by multiple independent market participants at the same popular round-number price are indistinguishable without a Market-by-Order feed (which Bybit's public API does not offer). CandleViewer should present iceberg flags as a confidence/heuristic signal, not a certainty.

**Data source:** `LOCAL`, built by correlating `orderbook.{depth}.{symbol}` (WS, book state/deltas) with `publicTrade.{symbol}` (WS, executed volume) at the same price levels — Bybit provides neither icebergs nor any related flag directly.

## 13. Speed of tape

**Definition:** real-time measures of market activity intensity, used to detect accelerating/decelerating order flow (a precursor signal to breakouts, stop-runs, or exhaustion).

```
tradesPerSecond(window) = count(trades in last `window` seconds) / window
volumePerSecond(window) = sum(trade.size for trades in last `window` seconds) / window
bookUpdatesPerSecond(window) = count(orderbook delta messages in last `window` seconds) / window
```
Typically computed over multiple rolling windows simultaneously (e.g., 1s, 5s, 30s) and compared to a longer-baseline rolling average (e.g., trailing 5-minute average) to compute a relative "acceleration" ratio:
```
tapeAcceleration = tradesPerSecond(1s) / avgTradesPerSecond(baseline=300s)
# ratio > ~3-5x baseline commonly used as a "tape speeding up" alert threshold
```
Rendered as a small real-time gauge/sparkline (trades/sec, volume/sec, book-updates/sec) alongside the DOM/footprint, often color-coded (green=accelerating buy flow, red=accelerating sell flow, using the same taker-side split as CVD).

**Data source:** `LOCAL`, computed directly from the `publicTrade` and `orderbook.{depth}.{symbol}` WS streams already being consumed for other purposes — no additional Bybit endpoint required, this is a pure rate/frequency measurement on data already flowing in.

## 14. Stop-run / sweep detection

**Definition:** a "stop run" or "liquidity sweep" is a rapid, aggressive price move through a recognizable prior swing high/low (where resting stop-loss orders are presumed clustered) followed by a swift reversal — interpreted as market makers/large players deliberately (or incidentally) triggering stops to fill their own orders against that forced liquidity, before reversing.

**Heuristic detection (`LOCAL`, combining price structure + tape + book):**
```
def detect_stop_run(bars, priorSwingLevel, lookbackBars=3, reversalPct=0.5, maxBarsToReverse=3):
    # 1. Identify a recent, well-defined swing high/low (priorSwingLevel) — from swing-detection
    #    logic (e.g., a local extremum with N bars on each side not exceeding it).
    # 2. Detect a "sweep" bar/sequence: price trades through priorSwingLevel by at least a
    #    minimum tick/percentage buffer, ideally with a burst in speed-of-tape (§13) and/or a
    #    footprint/CVD signature showing aggressive one-sided volume driving the breach
    #    (i.e., not just a slow drift through the level).
    sweepBar = first_bar_that_exceeds(bars, priorSwingLevel, buffer=minBuffer)
    if sweepBar is None:
        return None
    # 3. Confirm reversal: within `maxBarsToReverse` bars after the sweep, price closes back on
    #    the opposite side of priorSwingLevel by at least `reversalPct` of the sweep's excursion.
    excursion = abs(sweepBar.extremePrice - priorSwingLevel)
    for bar in bars_after(sweepBar, maxBarsToReverse):
        if reversal_confirmed(bar, priorSwingLevel, excursion * reversalPct):
            return {"sweepBar": sweepBar, "reversalBar": bar, "level": priorSwingLevel}
    return None
```
Supporting signals that increase confidence (all `LOCAL`, derived from data already being recorded):
- **Absorption at the level:** high traded volume at/through the level without a proportional further price advance (see §15).
- **CVD/delta divergence** at the sweep (§2.2): the breakout print shows lower participation/delta than the initial approach to the level, suggesting the breach lacked genuine follow-through demand.
- **Liquidation cluster coincidence:** a spike in the `allLiquidation` feed (§9.1) at/near the sweep level and time strengthens the "stop/liquidation cascade" interpretation (actual forced closes, not just resting limit stops, may have been triggered).

**Data source:** `LOCAL`, entirely derived from OHLCV bars/swing detection + trade tape + order book + liquidation stream, all already captured for other metrics above; no dedicated Bybit endpoint exists for this.

## 15. Absorption & exhaustion

**Absorption:** large traded volume occurs at a price level with **little or no further price movement** in the direction of the aggressor flow — interpreted as a large passive participant "absorbing" aggressive market orders without yielding the level (a classic support/resistance-holding signature).
```
def detect_absorption(footprintCell, priceMovedTicks, minVolume, maxPriceMove=1):
    # footprintCell: bid/ask volume at a price level for the bar/period in question
    return footprintCell.totalVolume >= minVolume and abs(priceMovedTicks) <= maxPriceMove
    # optionally require footprintCell.delta to be strongly one-sided (aggressive flow was real)
    # while price nonetheless failed to advance — the core "absorption" signature
```

**Exhaustion:** the mirror case — after a sustained directional move, traded volume/delta at the current extreme **declines** even as price continues nudging further (or fails to make meaningful further progress despite continued one-sided attempts), suggesting the aggressive side is running out of participation/energy, often preceding a reversal or at least a pause.
```
def detect_exhaustion(recentBars, lookback=5):
    deltas = [bar.delta for bar in recentBars[-lookback:]]
    volumes = [bar.volume for bar in recentBars[-lookback:]]
    prices  = [bar.close for bar in recentBars[-lookback:]]
    trendingSameDirection = is_monotonic(prices)  # price still extending in one direction
    decliningParticipation = is_decreasing(volumes) or is_decreasing([abs(d) for d in deltas])
    return trendingSameDirection and decliningParticipation
```
Both absorption and exhaustion are qualitative/heuristic pattern-recognition built on top of already-computed footprint cells (§3.1), per-bar delta (§2.2), and volume — no new raw data source is needed.

**Data source:** `LOCAL`, derived entirely from footprint/delta/volume data already captured.

## 16. Market regime classification

**Goal:** classify the current market into broad regimes (trending vs. ranging, high vs. low volatility) to adapt strategy/display behavior (e.g., suppress mean-reversion signals in a strong trend).

### 16.1 ADX (Average Directional Index) — trend strength

```
# Standard Wilder ADX, computed from OHLC bars:
+DM = high[t] - high[t-1]   if (high[t]-high[t-1]) > (low[t-1]-low[t]) and > 0, else 0
-DM = low[t-1] - low[t]     if (low[t-1]-low[t]) > (high[t]-high[t-1]) and > 0, else 0
TR  = max(high[t]-low[t], abs(high[t]-close[t-1]), abs(low[t]-close[t-1]))
smoothedTR, smoothed+DM, smoothed-DM = Wilder's smoothing (EMA-like, period commonly 14)
+DI = 100 * smoothed+DM / smoothedTR
-DI = 100 * smoothed-DM / smoothedTR
DX  = 100 * abs(+DI - -DI) / (+DI + -DI)
ADX = Wilder-smoothed average of DX over the same period
```
Interpretation: `ADX > 25` commonly taken as "trending," `< 20` as "ranging/choppy" (thresholds are convention, not fixed law — configurable).

### 16.2 ATR (Average True Range) — volatility regime

```
TR = max(high[t]-low[t], abs(high[t]-close[t-1]), abs(low[t]-close[t-1]))
ATR = Wilder-smoothed (or simple/EMA) moving average of TR, period commonly 14
```
Used both as a standalone volatility gauge and as a normalizer for other metrics (e.g., stop-run buffer sizing, bar-range-based bar construction — see §19).

### 16.3 Hurst exponent — trend persistence vs. mean reversion

Estimates whether a price series behaves as trending (persistent, H > 0.5), mean-reverting (anti-persistent, H < 0.5), or a random walk (H ≈ 0.5), via rescaled-range (R/S) analysis or generalized Hurst exponent methods:
```
# Simplified R/S method:
for each window length n in a range of scales:
    split series into chunks of length n
    for each chunk: compute mean-adjusted cumulative deviation series, range R = max-min of that series,
                    and standard deviation S of the chunk
    average (R/S) across chunks for this n -> (R/S)_n
# Hurst H = slope of log((R/S)_n) vs log(n), via linear regression across scales n
```
`H > 0.55` → trending regime; `H < 0.45` → mean-reverting; `H ≈ 0.45-0.55` → effectively random walk / no strong regime signal.

### 16.4 Combined trend/range classification

```
def classify_regime(adx, atrPctOfPrice, hurst):
    if adx > 25 and hurst > 0.55:
        return "Trending"
    if adx < 20 and hurst < 0.5:
        return "Ranging"
    if atrPctOfPrice > highVolThreshold:
        return "Volatile / transitional"
    return "Mixed / undefined"
```

**Data source:** `LOCAL` — all three (ADX, ATR, Hurst) are computed purely from OHLCV bar series (from Bybit klines `REST`/`WS`, or from CandleViewer's own locally-built bars of any type per §19); Bybit has no regime-classification endpoint.

## 17. Volatility (realized, ATR, options historical vol)

### 17.1 Realized volatility

```
# Close-to-close realized vol over N periods, annualized:
logReturn[t] = ln(close[t] / close[t-1])
realizedVol = stdev(logReturn over last N periods) * sqrt(periodsPerYear)
# periodsPerYear depends on bar size, e.g. for 1-hour bars: 24*365 = 8760; for daily bars: 365
```
Alternative estimators (better use of intrabar range information, all standard, all `LOCAL` from OHLC bars):
- **Parkinson estimator:** uses high-low range, `σ²_Parkinson = (1/(4N ln2)) * Σ [ln(high_t/low_t)]²`.
- **Garman-Klass estimator:** uses OHLC, more efficient than close-to-close, `σ²_GK = (1/N) * Σ [ 0.5*(ln(high_t/low_t))² - (2ln2 - 1)*(ln(close_t/open_t))² ]`.
- **Yang-Zhang estimator:** further refines to account for overnight/session gaps (less relevant for 24/7 crypto, but included for completeness since some venues still have "session" boundaries via funding-time resets).

### 17.2 ATR

Covered in §16.2 — same Wilder ATR formula, used here purely as a volatility magnitude gauge rather than a regime-classification input.

### 17.3 Bybit's own historical/implied vol for options

Bybit's option market data includes an `iv` (implied volatility) and `mIv` (mark IV) field on `publicTrade`/`tickers` for `option` category instruments (seen in the trade WS schema at §2.1) — this is **implied**, not historical/realized, vol, quoted directly by Bybit's option pricing engine per contract. Bybit does not appear to publish a separate standalone "historical volatility index" REST endpoint akin to Deribit's DVOL; CandleViewer's own realized-vol calculations (§17.1) computed on the underlying's kline series are the practical substitute for a historical-vol reference line to compare against quoted option IVs.

**Data source:** realized vol / ATR = `LOCAL` (from klines, `REST`/`WS`); option IV/mark-IV = `WS`/`REST` (Bybit-provided per-contract, `option` category only, via `tickers.{symbol}` and `publicTrade.{symbol}`).

## 18. Options data & crypto GEX analog

### 18.1 Data inputs

- **Bybit options:** `category=option` supports `publicTrade`, `tickers` (mark/index price, mark IV, IV per contract), and `REST /v5/market/instruments-info?category=option` for the option chain (strikes, expiries). Bybit's own options market is comparatively lower open interest/volume than Deribit's; for a meaningful GEX analog, CandleViewer will likely need **Deribit's public API** as the primary/supplementary options-OI data source for BTC/ETH options, since Deribit remains the dominant crypto options venue by open interest. (Deribit's own public API is out of this document's Bybit-centric scope but is flagged here as a required secondary integration in [Open questions](#open-questions).)
- **Open interest by strike:** both Bybit's and Deribit's instruments/options-chain endpoints expose per-contract (per strike+expiry) open interest; this must be pulled per-contract and aggregated by strike across all listed expiries (or filtered to near-dated expiries only, matching how most GEX dashboards default to "front month"/nearest few expiries since gamma decays with time and far-dated OI contributes little near-term pinning effect).

### 18.1a Bybit options contract specification (settlement, multiplier) — gap fix

Bybit's crypto options are **USDC-settled** (all margining, premiums, and final cash settlement denominated in USDC, not in the underlying coin), European-style (exercisable only at expiry, cash-settled — no physical delivery of the underlying), and quoted/settled against the **futures/forward-style** price rather than raw spot, which is why §18.2 uses Black-76 rather than plain Black-Scholes. Key contract-spec facts relevant to a hybrid Bybit+Deribit design:

| Spec | Bybit BTC options | Bybit ETH options | Deribit (for comparison) |
|---|---|---|---|
| Settlement currency | USDC | USDC | BTC/ETH (coin-margined; Deribit is *not* USDC-settled) |
| Contract multiplier | 1 (1 contract ≈ 1 BTC notional) | 1 (1 contract ≈ 1 ETH notional) | 1 (1 contract = 1 BTC or 1 ETH notional) |
| Exercise style | European, cash-settled | European, cash-settled | European, cash-settled |
| Expiries offered | Daily, bi-daily, weekly, bi-weekly, tri-weekly, monthly, bi-monthly, quarterly | Same cadence as BTC | Similar cadence (daily through quarterly) |
| Expiry time | 08:00 UTC | 08:00 UTC | 08:00 UTC (matches Bybit) |

This matters for a hybrid design because **Bybit option P&L/margin/IV quoting is USDC-denominated while Deribit's is coin-denominated** — if CandleViewer blends OI/IV from both venues into one GEX aggregation, notional conversions must account for this difference (Bybit OI in USDC-equivalent notional vs. Deribit OI in BTC/ETH-equivalent notional) rather than assuming both are already in the same unit.

**Bybit option market-data endpoints relevant to OI-by-strike:** `REST GET /v5/market/instruments-info?category=option` (chain/instrument list per strike+expiry, including `deliveryTime`), `REST GET /v5/market/open-interest?category=option&symbol=...` (per-contract OI, must be queried per listed strike/expiry symbol since there is no single "OI by strike" aggregate endpoint — CandleViewer must fan out one OI call per contract symbol and aggregate client-side), and `WS`/`REST` `tickers` for per-contract mark IV (`markIv`) used as the Black-76 input.

**Data source:** `REST` (Bybit instruments-info + per-contract open-interest, fanned out and aggregated `LOCAL`ly by CandleViewer); no single "OI by strike" endpoint exists on Bybit (or, per public docs reviewed, on Deribit) — both require the same per-contract fan-out-and-aggregate pattern.


### 18.2 Black-76 pricing/Greeks (for futures-settled options, as used by Deribit/Bybit)

Since crypto options (Deribit, Bybit) are typically priced/settled against the **futures/forward price** rather than spot, the **Black-76** model (a Black-Scholes variant for options on futures) is the standard choice rather than classic Black-Scholes:
```
d1 = ( ln(F/K) + 0.5 * σ² * T ) / (σ * sqrt(T))
d2 = d1 - σ * sqrt(T)

Call price = e^(-rT) * [ F * N(d1) - K * N(d2) ]
Put price  = e^(-rT) * [ K * N(-d2) - F * N(-d1) ]

Gamma = e^(-rT) * N'(d1) / (F * σ * sqrt(T))
```
Where `F` = futures/forward price, `K` = strike, `T` = time to expiry (years), `σ` = implied volatility (from the quoted option's `iv`/`mIv` field, or solved via Newton-Raphson/bisection against the traded option price if IV is not directly quoted), `r` = risk-free rate (commonly treated as ≈0 for crypto, or the relevant funding/basis rate), `N` = standard normal CDF, `N'` = standard normal PDF.

### 18.3 Aggregating into GEX (Gamma Exposure) by strike

```
GEX_strike = Σ (Gamma_call * OI_call * contractMultiplier * F) - Σ (Gamma_put * OI_put * contractMultiplier * F)
# multiplying by F (spot/forward) converts unit gamma into a dollar-gamma-per-1%-move convention,
# matching how equity-market GEX dashboards (SqueezeMetrics, SpotGamma) present the metric;
# sign convention: dealers are typically assumed short puts/long calls from selling options to
# retail/directional flow, so a common convention nets: +callOI*Gamma - putOI*Gamma (assumes
# dealers are net long gamma from calls, short gamma from puts they've sold — this assumed-dealer-
# positioning convention is itself a simplification/estimate, same caveat as GEX in equities)
netGEX = Σ_strikes GEX_strike
gammaFlipPoint = the spot/forward price at which netGEX (recomputed at that hypothetical spot) changes sign
```
**Interpretation:** positive net GEX regions are associated with dealer hedging that dampens realized volatility (dealers buy dips/sell rips to stay hedged); negative net GEX regions are associated with dealer hedging that can amplify moves (dealers sell into drops/buy into rallies). The "gamma flip point" is watched as a potential volatility regime boundary.

**Data source:** `HYBRID`/`LOCAL` — raw option chain, OI-by-strike, and IV are `REST` (Bybit and/or Deribit option instruments endpoints); the Black-76 pricing, Greeks, and GEX aggregation are entirely `LOCAL` computation (no exchange publishes GEX directly; third-party dashboards like SqueezeMetrics/Cryptogamma/RektCalc all compute this the same way from public OI+IV data).

## 19. Data storage & replay

### 19.1 What must be recorded continuously

Given Bybit's REST retention limits (§1.2), CandleViewer's backend must run a persistent recorder subscribed to, at minimum, per tracked symbol:
- `publicTrade.{symbol}` (all categories traded) — every fill, indefinitely.
- `orderbook.{depth}.{symbol}` — snapshot + every delta, at the deepest depth the venue/plan allows (50/200/500), indefinitely (or with a defined retention/rollup policy, see below).
- `allLiquidation.{symbol}` — every liquidation event.
- `tickers.{symbol}` — for OI, mark/index price, funding rate, best bid/ask, at its native push cadence (or throttled/sampled if full-cadence storage is excessive).
- Periodic `REST` snapshots of `funding/history`, `open-interest` (as a backfill/cross-check against the WS-derived series), and `instruments-info` (tick size, funding interval, leverage/margin tiers — these change occasionally and must be version-tracked, not assumed static).

### 19.2 Estimated data rates/sizes — BTCUSDT example

Order-of-magnitude estimates (these will vary with market activity and must be validated empirically once the recorder is running against live Bybit data — treat the following as planning estimates, not measured facts):

| Stream | Approx. message rate | Approx. raw bytes/day (uncompressed JSON) | Notes |
|---|---|---|---|
| `publicTrade.BTCUSDT` | Highly variable; can range from a few to 50+ trades/sec in active periods | Roughly 50-500 MB/day depending on activity | Each trade message is small (~150-250 bytes JSON); compresses well (gzip commonly 5-10x) |
| `orderbook.50.BTCUSDT` | Frequent deltas, sub-second cadence during active trading | Materially larger than trades; commonly estimated in the low-to-mid GB/day range for a top pair at 50-depth | Depth 200/500 scales up roughly linearly to several-fold more volume than depth-50; snapshot-of-full-state-at-each-delta approaches (rather than storing only true deltas) multiply this further — CandleViewer should store true deltas, not re-snapshot the full book each message |
| `allLiquidation.BTCUSDT` | Low (bursty around volatility events; can be near-zero for long stretches) | Negligible (KB-MB/day) except during high-volatility periods | 500ms batching keeps message count bounded even during liquidation cascades |
| `tickers.BTCUSDT` | ~10/sec (100ms cadence) | Tens of MB/day | Small payload but constant-rate cadence |

**Practical guidance:** these figures should be treated as **rough planning inputs only** — CandleViewer should instrument its own recorder from day one (message counts, byte counts per stream per symbol per day) to get authoritative numbers for its actual tracked symbol set, since public benchmarks for this specific combination (Bybit v5, current 2026 market activity levels) were not found as a citable primary source during this research pass (flagged in Open Questions). Using a binary/columnar storage format (e.g., Parquet, or a purpose-built append-only tick store) with per-symbol partitioning and compression is standard practice and will reduce on-disk size substantially versus raw JSON.

### 19.3 Rebuilding bars of any type from recorded trades

Given a recorded, ordered trade tape `(time, price, size, side)`, all common bar types can be constructed:

```
def build_time_bars(trades, intervalSeconds):
    bars = []
    for trade in trades:
        bucket = floor(trade.time / (intervalSeconds*1000)) * (intervalSeconds*1000)
        bar = get_or_create_bar(bars, bucket)
        update_ohlcv(bar, trade)
    return bars

def build_tick_bars(trades, ticksPerBar):
    bars = []; current = new_bar()
    for trade in trades:
        update_ohlcv(current, trade)
        if current.tradeCount >= ticksPerBar:
            bars.append(current); current = new_bar()
    return bars

def build_volume_bars(trades, volumePerBar):
    bars = []; current = new_bar()
    for trade in trades:
        update_ohlcv(current, trade)
        if current.volume >= volumePerBar:
            bars.append(current); current = new_bar()
    return bars

def build_range_bars(trades, rangeSize):
    bars = []; current = new_bar()
    for trade in trades:
        update_ohlcv(current, trade)
        if (current.high - current.low) >= rangeSize:
            bars.append(current); current = new_bar()
    return bars

def build_delta_bars(trades, deltaThreshold):
    # closes the bar once cumulative signed volume (delta) within the bar crosses a threshold
    bars = []; current = new_bar()
    for trade in trades:
        update_ohlcv(current, trade)
        current.delta += trade.size if trade.side == "Buy" else -trade.size
        if abs(current.delta) >= deltaThreshold:
            bars.append(current); current = new_bar()
    return bars
```
All bar types derive purely from the recorded trade tape (plus, for footprint/profile overlays, the same tape grouped by price per §3/§4) — no separate Bybit endpoint is needed once the tape is captured; this is precisely why continuous tape recording (§19.1) is the foundational requirement underlying nearly every other metric in this document.

### 19.4 Replay

Historical replay (for backtesting the tick-replay/backtester DeepCharts feature) is implemented by reading recorded trades/book-deltas/liquidations back in original timestamp order at a chosen playback speed, feeding them through the same live bar-building/footprint/CVD/etc. pipelines used for live data — i.e., the recorder's storage format should be designed so the *exact same ingestion code path* can consume either a live WS feed or a stored historical file, avoiding a second parallel implementation of all the derived-metric logic in this document.

## 20. Bybit public historical trade CSVs

**Location:** `https://public.bybit.com/` — a plain directory-listing site (confirmed reachable during this research pass) with two top-level directories relevant to derivatives/spot trade history: `trading/` (derivatives — futures/perpetuals, one subdirectory per symbol, e.g. `trading/BTCUSDT/`) and `spot/` (spot pairs, one subdirectory per symbol, e.g. `spot/BTCUSDT/`). Additional top-level directories observed: `kline_for_metatrader4/`, `premium_index/`, `spot_index/`.

**File naming/format (per symbol subdirectory):** daily files, gzip-compressed CSV, one file per UTC day, named per-symbol-per-date (pattern commonly `{SYMBOL}{YYYY-MM-DD}.csv.gz` for derivatives and a similar dated pattern for spot — CandleViewer's downloader should enumerate the actual filenames present in each symbol's directory listing rather than hardcoding a guessed pattern, since exact separators/casing should be verified against a live directory listing at implementation time).

**Typical fields (derivatives trade files), based on community tooling/downloaders and general Bybit convention** (exact header row should be verified by downloading one sample file, since this was not directly confirmed via a fetched CSV in this research pass — flagged in Open Questions):
- `timestamp` — trade execution time (commonly Unix epoch, seconds or ms — verify per file).
- `symbol` — trading pair.
- `side` — `Buy`/`Sell` (taker/aggressor side, consistent with the live `publicTrade` stream's `S` field).
- `size` / `qty` — trade quantity.
- `price` — execution price.
- `trade_id` / `execId` — unique identifier, when present.
- `is_buyer_maker` or equivalent — some historical dumps from other venues include this instead of a direct taker-side field; Bybit's own dumps are expected to align with the live API's direct `side`-as-taker-side convention, but this should be spot-checked against a real downloaded file.

**Known gaps/caveats:**
- No official changelog of gaps/outages in this historical archive was found during this research pass; CandleViewer's recorder-first architecture (§19) is the reliable path for any data going forward from when CandleViewer starts recording — the public CSV archive should be treated as a **useful bulk-backfill convenience for pre-CandleViewer history**, not a guaranteed-complete or officially-SLA'd data source.
- The archive appears to cover **trades only** (and index/premium/kline auxiliary series) — it does **not** appear to include historical L2 order-book snapshots/deltas, liquidations, or open interest at fine granularity; those must come from CandleViewer's own live recording from day one, with no way to backfill pre-recording history for those data types from Bybit's public archive.
- Community tooling exists to help enumerate/download this archive in bulk (e.g., GitHub projects such as `Anton495/bybit-data-downloader` and `suenot/bybit-history`), which can inform CandleViewer's own ingestion-tooling design, though CandleViewer should implement its own downloader against the live directory listing rather than depending on third-party unofficial tools in production.

**Data source:** `REST`-adjacent (plain HTTPS file download, not the authenticated/rate-limited v5 API) — `HYBRID` in the sense that it's Bybit-hosted but effectively a static-file archive rather than a queryable API; useful strictly for one-time historical trade backfill, not live operation.

## 21. Summary matrix: REST vs WS vs computed-locally

| # | Metric / datapoint | Bybit source | Notes |
|---|---|---|---|
| 1 | Raw trades + taker side | `WS publicTrade.{symbol}`; `REST /v5/market/recent-trade` (limited history) | `side` is already taker/aggressor side |
| 2 | CVD (any anchor/timeframe) | `LOCAL` | Built from `publicTrade` |
| 3 | Per-bar delta, min/max delta | `LOCAL` | Requires intrabar running-sum tracking |
| 4 | Delta divergence | `LOCAL` | Built on top of #2/#3 |
| 5 | Footprint cells | `LOCAL` | Grouped `publicTrade` by tick-price × bar |
| 6 | Diagonal/stacked imbalance | `LOCAL` | Built on top of #5 |
| 7 | Unfinished auctions | `LOCAL` | Built on top of #5 |
| 8 | Per-bar POC/VA | `LOCAL` | Mini volume profile from #5 |
| 9 | Volume profile / POC / VA / naked POC / HVN-LVN / composite | `LOCAL` | Aggregated `publicTrade` by price over a period |
| 10 | TPO / Market Profile | `LOCAL` | Time-bucketed price touches, from bars or trades |
| 11 | VWAP (session/anchored/rolling) + SD bands | `LOCAL` | From `publicTrade` (or klines as an approximation) |
| 12 | Open interest | `REST /v5/market/open-interest`; `WS tickers.{symbol}` (`openInterest`, `openInterestValue`) | Units differ linear (coin) vs inverse (USD) |
| 13 | OI delta per bar | `LOCAL` | Sampled/interpolated OI series |
| 14 | OI-price quadrant | `LOCAL` | Comparing OI delta sign to price delta sign |
| 15 | Funding rate (current) | `WS tickers.{symbol}.fundingRate`; static interval via `REST instruments-info.fundingInterval` | |
| 16 | Funding rate history | `REST /v5/market/funding/history` | |
| 17 | Annualized funding | `LOCAL` | Trivial normalization |
| 18 | Mark price / index price (live) | `WS tickers.{symbol}` | |
| 19 | Mark/index price (historical bars) | `REST /v5/market/mark-price-kline`, `/v5/market/index-price-kline` | |
| 20 | Basis/premium | `LOCAL` (perp); `WS tickers.{symbol}.basisRateYear` (dated futures, Bybit-provided directly) | |
| 21 | Liquidations (realized) | `WS allLiquidation.{symbol}` | 500ms batched push |
| 22 | Liquidation bars/heatmap (realized) | `LOCAL` | Aggregated from #21 |
| 23 | Estimated liquidation levels/heatmap | `LOCAL` (modeled) | Uses OI (#12) + `REST /v5/market/risk-limit` (maintenance margin tiers) + assumed leverage distribution; no Bybit endpoint provides this directly |
| 24 | Long/short account ratio | `REST /v5/market/account-ratio` | Field-level schema should be reverified live (doc page 404'd in this pass) |
| 25 | Taker buy/sell ratio | `LOCAL` | Aggregated `publicTrade` side |
| 26 | Order book (L2) live state | `WS orderbook.{depth}.{symbol}` | Snapshot + delta semantics |
| 27 | Order book imbalance, depth at ±X% | `LOCAL` | From maintained local book |
| 28 | Liquidity heatmap (resting) | `LOCAL` | Time-sampled book snapshots, gridded |
| 29 | Big trade detection | `LOCAL` | Thresholds on `publicTrade` size |
| 30 | Trade clustering (split-fill aggregation) | `LOCAL` | Time/price/side grouping of `publicTrade` |
| 31 | Iceberg detection (resting book) | `LOCAL` (heuristic) | Correlates #26 deltas with #1 trades; inherently probabilistic |
| 32 | Speed of tape | `LOCAL` | Rate measurement on #1/#26 streams |
| 33 | Stop-run / sweep detection | `LOCAL` (heuristic) | Combines price structure, #2/#5, #21 |
| 34 | Absorption / exhaustion | `LOCAL` (heuristic) | Built on #5/#3 |
| 35 | Market regime (ADX/ATR/Hurst) | `LOCAL` | From OHLCV bars (`REST`/`WS` klines, or #(§19) locally built bars) |
| 36 | Realized volatility (close-close, Parkinson, GK) | `LOCAL` | From OHLCV bars |
| 37 | Option implied vol / mark IV | `WS tickers.{symbol}`, `WS publicTrade.{symbol}` (`option` category) | Bybit-quoted per contract |
| 38 | Options OI by strike | `REST /v5/market/instruments-info?category=option` (Bybit); Deribit API likely needed for meaningful depth | |
| 39 | GEX / gamma exposure by strike | `LOCAL` | Black-76 Greeks × OI, computed locally from #37/#38 |
| 40 | Historical trade CSVs (bulk backfill) | Static file archive at `public.bybit.com` | Trades only; no L2/liquidations/OI history |
| 41 | Instrument metadata (tick size, leverage tiers, funding interval) | `REST /v5/market/instruments-info` | Changes occasionally; version-track it |

## Sources

- Bybit V5 API docs root: https://bybit-exchange.github.io/docs/v5/intro
- Bybit V5 Orderbook WS: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
- Bybit V5 Trade WS: https://bybit-exchange.github.io/docs/v5/websocket/public/trade
- Bybit V5 Ticker WS: https://bybit-exchange.github.io/docs/v5/websocket/public/ticker
- Bybit V5 All Liquidation WS: https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
- Bybit V5 Get Open Interest (REST): https://bybit-exchange.github.io/docs/v5/market/open-interest
- Bybit V5 Get Funding Rate History (REST): https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
- Bybit V5 Get Instruments Info (REST): https://bybit-exchange.github.io/docs/v5/market/instrument
- Bybit V5 Get Recent Public Trades (REST): https://bybit-exchange.github.io/docs/v5/market/recent-trade
- Bybit V5 Account Ratio (long/short) — endpoint referenced at https://bybit-exchange.github.io/docs/v5/market/account-ratio (returned 404 during this research pass; schema reconstructed from third-party summary, see below — reverify live)
- Bybit Bankruptcy Price (USDT Contract) help article: https://www.bybit.com/en-US/help-center/s/article/Bankruptcy-Price-USDT-Contract
- Bybit API usage examples (GitHub): https://github.com/bybit-exchange/api-usage-examples
- pybit WebSocket example (GitHub): https://github.com/bybit-exchange/pybit/blob/master/examples/websocket_example_explanatory.py
- Bybit public historical data archive: https://public.bybit.com/ , https://public.bybit.com/trading/ , https://public.bybit.com/spot/
- Bybit historical data community downloader (GitHub): https://github.com/Anton495/bybit-data-downloader
- Bybit historical data community downloader (GitHub): https://github.com/suenot/bybit-history / https://pypi.org/project/bybit-history/
- Trading Strategies Academy — Bybit long/short ratio summary: https://trading-strategies.academy/archives/47608
- ATAS Help Center — Stacked Imbalance: https://help.atas.net/en/support/solutions/articles/72000602474-stacked-imbalance
- Trader Profesional — Stacked Imbalances: https://traderprofesional.com/en/stacked-imbalances/
- Trader Profesional — Footprint Chart Patterns: https://traderprofesional.com/en/footprint-patterns/
- JustScalpIt — Stacked Imbalance Indicator for ATAS: https://justscalpit.com/atas-smart-imbalance-indicator/
- FlowDeck — Volume profile: POC, value area & how to read it: https://flowdeck.us/learn/volume-profile
- JournalPlus — Value Area: VAH, VAL & POC (80% Rule discussion): https://journalplus.co/learn/glossary/value-area/
- QuantCrawler — Volume Profile Trading: POC & Value Area: https://quantcrawler.com/learn/volume-profile
- FuturesHive — VAH, VAL & POC Trading: https://www.futureshive.com/blog/volume-profile-trading-strategy-2025
- StockCharts ChartSchool — Anchored VWAP: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/anchored-vwap
- FinancialTechWiz — Anchored VWAP: Strategies, Settings: https://www.financialtechwiz.com/post/anchored-vwap/
- Alchemy Markets — Anchored VWAP Explained: https://alchemymarkets.com/education/indicators/anchored-vwap/
- TradingView script — Rolling VWAP by hCaostrader: https://www.tradingview.com/script/BdguQiFQ-Rolling-VWAP/
- ProRealCode — Rolling VWAP: https://www.prorealcode.com/prorealtime-indicators/rolling-vwap/
- TrendSpider — VWAP with St.Dev Bands: https://help.trendspider.com/kb/indicators/vwap-with-st-dot-dev-bands
- TradingView script — VWAP with Standard Deviation Bands by pmk07: https://www.tradingview.com/script/ZsBqfHHq-VWAP-with-Standard-Deviation-Bands/
- Forex Factory thread — Anchored VWAP with SD Bands: https://www.forexfactory.com/thread/1314266-anchored-vwap-with-standard-deviation-bands
- dxFeed — Iceberg Orders Detection and Prediction: https://dxfeed.com/solutions/iceberg-detection-solution/
- Curved Trading — Iceberg Orders Explained: https://curvedtrading.com/articles/en/what-is/iceberg-orders-level-2/
- Order Flow Futures — Iceberg orders: detecting the hidden size: https://orderflowfutures.com/en/blog/how-to-detect-iceberg-orders
- Bookmap Knowledge Base — Iceberg Orders Tracker: https://bookmap.com/knowledgebase/docs/KB-Bookmap-Wiki-Iceberg-Orders-Tracker
- QuantStrategy.io — Detecting Hidden Intent: Unmasking Iceberg Orders: https://quantstrategy.io/blog/detecting-hidden-intent-unmasking-iceberg-orders-and-order/
- QuantStrategy.io — Detecting Spoofing and Iceberg Orders: https://quantstrategy.io/blog/detecting-spoofing-and-iceberg-orders-advanced-techniques/
- CoinGlass API docs — Liquidation Aggregated Heatmap Model 3: https://docs.coinglass.com/reference/liquidation-aggregated-heatmap-model3
- CoinGlass API docs (GitHub) — Liquidation Aggregated Heatmap Model 3: https://github.com/coinglass-official/coinglass-api-docs/blob/main/rest/Futures/Liquidation/liquidation-aggregated-heatmap-model3.md
- CoinGlass — How to use Liquidation Heatmaps to assist trading: https://www.coinglass.com/learn/how-to-use-liqmap-to-assist-trading-en
- Grokipedia — CoinGlass Liquidation Heatmap Model 3 overview: https://grokipedia.com/page/CoinGlass_Liquidation_Heatmap_Model_3
- DeepCharts — Deep Print (Footprint®) help article: https://www.deepcharts.com/helpcenter/article/deep-print-(footprint%C2%AE)
- DeepCharts helpdesk — order flow bid/ask footprint: https://helpdesk.deepcharts.com/portal/en/kb/articles/order-flow-bid-and-ask-footprint
- Order Flow Futures — DeepCharts footprint (Deep Prints) complete guide: https://orderflowfutures.com/en/deepcharts/footprint
- DeepCharts — DeepDOM Features: https://www.deepcharts.com/features/deepdom
- DeepCharts — DeepGamma Features: https://www.deepcharts.com/features/deepgamma
- DeepCharts — Deepchart Features: https://www.deepcharts.com/features/deepchart
- DeepCharts homepage: https://www.deepcharts.com/
- Jakob Linder — Black-76 Options Pricer: https://jakob-linder.com/projects/black-scholes
- blackscholes (GitHub Pages) — The Greeks (Black-76): https://carlolepelaars.github.io/blackscholes/4.the_greeks_black76/
- Eisphora Crypto docs: https://eisphoracrypto.com/docs
- Crypto Gamma Exposure Dashboard: https://cryptogamma.io/
- RektCalc — Gamma Exposure (GEX) & Gamma Flip Calculator: https://rektcalc.com/options-gamma-exposure-calculator.html
- crypto-bs (PyPI): https://pypi.org/project/crypto-bs/
- fr00000/ibit-gex (GitHub): https://github.com/fr00000/ibit-gex
- Bybit V5 API docs — Get Premium Index Price Kline: https://bybit-exchange.github.io/docs/v5/market/premium-index-price-kline
- Bybit V5 API docs — Get Mark Price Kline: https://bybit-exchange.github.io/docs/v5/market/mark-price-kline
- Bybit V5 API docs — Get Insurance Fund: https://bybit-exchange.github.io/docs/v5/market/insurance
- Bybit V5 API docs — Rate Limit rules: https://bybit-exchange.github.io/docs/v5/rate-limit
- Bybit V5 API docs — WebSocket Connect (subscription/topic limits): https://bybit-exchange.github.io/docs/v5/ws/connect
- Bybit V5 API docs — Get Recent Trades: https://bybit-exchange.github.io/docs/v5/market/recent-trade
- DeepWiki mirror (bybit-exchange/docs) — Rate Limiting System: https://deepwiki.com/bybit-exchange/docs/2.2-rate-limiting-system
- DeepWiki mirror (bybit-exchange/docs) — Insurance and Risk Data: https://deepwiki.com/bybit-exchange/docs/5.3-insurance-and-risk-data
- DeepWiki mirror (bybit-exchange/docs) — REST Market Data APIs: https://deepwiki.com/bybit-exchange/docs/5.1-rest-market-data-apis
- DeepWiki mirror (bybit-exchange/pybit) — Market Data API: https://deepwiki.com/bybit-exchange/pybit/5.1-market-data-api
- Bybit — USDC Options Trading (contract specs, USDC settlement): https://www.bybit.com/en/promo/global/options-trading
- Bybit Learn — Options Parameters Introduction (BTC/ETH contract multiplier, tick size, expiry): https://www.bybit.com/en/learn/options/bybit-options-lesson-options-parameters-introduction
- CoinDesk — Bybit to Settle Options Contracts in USDC (2022): https://www.coindesk.com/markets/2022/06/29/crypto-derivatives-exchange-bybit-to-settle-options-contracts-in-usdc
- Hedgeweek — Bybit settles options in USDC: https://www.hedgeweek.com/bybit-settles-options-usdc/
- GoCharting docs — Delta and Cumulative Delta Bars: https://docs.gocharting.com/docs/charting/technical-indicator/orderflow/delta-and-cumulative-delta-bars
- ForexBee — Cumulative delta divergence: https://forexbee.co/cumulative-delta-divergence/
- justintrading.com — How to Read Footprint Charts and Trade Cumulative Delta Divergence: https://justintrading.com/how-to-read-footprint-charts-and-trade-cumulative-delta-divergence/
- ATAS Marketplace — Imbalance Levels indicator (ratio/stack defaults): https://marketplace.atas.net/product/imbalance-levels
- traMADA glossary — Stacked Imbalance: https://tra-mada.de/en/glossary/stacked-imbalance
- Chart Champions — Stacked Imbalance Guide: https://blog.chartchampions.co/stacked-imbalance-guide/

## Open questions

1. **`market/account-ratio` schema:** the official Bybit docs page for this endpoint returned HTTP 404 during this research pass (path may have moved or the endpoint may have been deprecated/renamed in the current v5 docs tree). The field names and `limit`/`period` bounds documented here (§10.1) were reconstructed from a third-party summary, not the primary docs — **must be verified against a live API call (or the current docs tree) before implementation.**
2. **Legacy `liquidation.{symbol}` topic:** unclear whether Bybit still offers a single-event (non-batched) liquidation topic distinct from `allLiquidation.{symbol}`, or whether `allLiquidation` is now the sole public liquidation feed. The docs page at the guessed URL for a standalone `liquidation` topic 404'd; confirm current topic list directly against Bybit's WS nav before wiring the recorder.
3. **Exact order-book depth tiers per category:** this document lists commonly-cited depths (1/50/200/500, sometimes 1000) but the authoritative per-category (`spot`/`linear`/`inverse`/`option`) depth table and push-frequency table should be pulled fresh from the orderbook docs page at implementation time, since Bybit has changed these tiers over its API's history.
4. **Public CSV archive exact CSV header/schema and timestamp units:** not directly confirmed by fetching/parsing an actual `.csv.gz` file in this research pass (only the directory listing was fetched); download and inspect one real sample file per category (`trading/` and `spot/`) before building the bulk-backfill importer.
5. **Data-rate/size estimates in §19.2:** flagged explicitly as planning-level estimates, not measured — no authoritative, current (2026), citable public benchmark for Bybit-specific v5 message rates/sizes at various order-book depths was found. CandleViewer should instrument its own recorder early and replace these numbers with real measurements.
6. **Estimated-liquidation-levels modeling (§9.3):** Coinglass/Hyblock's exact aggregation/weighting formulas are proprietary and not publicly disclosed; the approach outlined here (using Bybit's own OI + risk-limit maintenance-margin tiers + a leverage-distribution model calibrated against CandleViewer's own recorded realized liquidations) is a reasonable first-party alternative design, but is a nontrivial research/modeling task in its own right and not a simple "call this endpoint" integration — recommend scoping it as a distinct follow-on research/design phase once realized-liquidation history has been recorded for a meaningful period.
7. **Deribit integration scope for options/GEX (§18):** Bybit's own options market has materially lower open interest than Deribit's; a genuinely useful crypto-GEX analog likely requires integrating Deribit's public API as a secondary data source (out of this Bybit-focused document's scope) — recommend a dedicated research pass on Deribit's options API (chain endpoints, OI-by-strike, IV data) before committing to the GEX feature.
8. **Predicted funding rate precision:** Bybit's public ticker stream surfaces the current/accruing `fundingRate` but this document did not find a distinct, separately-labeled "predicted next funding rate" numeric field/formula published in Bybit's own docs (unlike some competitor exchanges that expose a distinct predicted-rate field). Confirm via a live ticker payload capture whether `fundingRate` in `tickers.{symbol}` already represents the settling-soon predicted value or only the last-settled value, since this affects how CandleViewer should label/display it.
9. **Value Area algorithm granularity:** the simplified single-step VA expansion algorithm in §4.1 is a common approximation; the "textbook" TPO-derived algorithm expands two price rows at a time in specific tie-breaking order. If exact parity with a specific reference platform's VA calculation is required, that platform's precise tie-breaking rules should be sourced and matched.
10. **Archive.org snapshots not obtainable this pass:** an attempt was made to fetch/verify `web.archive.org` (Wayback Machine) snapshots of the key Bybit v5 docs pages cited in this document (orderbook depth tiers, rate-limit page, ws/connect page) to harden citations against future doc changes, per a reviewer request — the Wayback `available` API returned HTTP 429 (rate-limited) throughout this research pass and no snapshot links could be captured. **Unresolved:** before implementation, someone should manually pull `https://web.archive.org/web/*/https://bybit-exchange.github.io/docs/v5/market/orderbook`, `.../v5/rate-limit`, and `.../v5/ws/connect` snapshots (or take fresh ones via the Wayback "Save Page Now" tool) and add the resulting timestamped snapshot URLs alongside the live doc links in [Sources](#sources), so future doc changes/404s can be diffed against a known-good historical capture.
11. **Exact REST rate-limit numbers not directly confirmed on the primary docs page:** the official `bybit-exchange.github.io/docs/v5/rate-limit` page itself could not be fetched directly in this research pass (fetch tool errors); the "600 requests / 5 seconds per IP for public endpoints" and "~120 req/s" figures in the new §1.4 are sourced from a DeepWiki mirror of the same docs repo and secondary blog summaries, not a direct read of the primary page. **Should be re-verified against the live primary docs page (or by observing `X-Bapi-Limit`/`X-Bapi-Limit-Status` response headers from real API calls) before the recorder's rate-limiting logic is finalized.**
12. **Deribit-side options contract specs not researched in this pass:** §18.1a documents Bybit's own USDC-settled options contract specs (multiplier, settlement, expiry cadence) as requested, but a full Deribit contract-spec table (contract multiplier, settlement currency/mechanism, tick sizes, expiry cadence) was only lightly sketched for comparison purposes and should get its own dedicated research pass alongside open question #7 (Deribit API integration scope) before a hybrid Bybit+Deribit GEX design is finalized.

