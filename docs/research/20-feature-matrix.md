# 20 — Feature Matrix (Master)

Compiled 2026-09-14 from digests 01–12 and 23 (research phase, no tickets). Columns: **#** | **Feature** | **TradingView** | **DeepCharts** | **Best competitor** | **Data needed** | **Bybit v5 feasibility** (Y/Partial/N + why) | **CandleViewer scope** (Must/Should/Could/Won't) | **Notes**.

Legend: Y=fully feasible on public/private Bybit v5 REST+WS; Partial=feasible only as heuristic/approximation (no L3/MBO); N=not feasible/out of scope. Scope follows digest 12 MoSCoW where an item maps 1:1; new/expanded rows use best judgment consistent with project framing (private, self-hosted, order-flow-first, Bybit-only, crypto-only).

---

## A. Chart types & bar types

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|1|Candlestick chart|Y|Y|ATAS/Quantower|kline OHLCV|Y|Must|Baseline chart type|
|2|OHLC / Bar chart|Y|Y|ATAS|kline OHLCV|Y|Must|Trivial to replicate|
|3|Line chart|Y|Y|All|kline close|Y|Must||
|4|Area chart|Y|N|—|kline close|Y|Should|Cosmetic variant|
|5|Baseline chart|Y|N|—|kline close|Y|Could||
|6|Heikin Ashi|Y|N|—|kline OHLCV, derived|Y|Should|Simple transform|
|7|Hollow candlestick|Y|N|—|kline OHLCV|Y|Could||
|8|Volume candlestick (width=volume)|Y|N|—|kline OHLCV+vol|Y|Could||
|9|Step line|Y|N|—|kline close|Y|Won't|Low value|
|10|HLC area|Y|N|—|kline HLC|Y|Won't|Low value|
|11|Column (volume) chart|Y|N|—|kline volume|Y|Should|Volume subpane baseline|
|12|Equi-Volume bars|N|Y (DeepCharts price chart)|DeepCharts|kline OHLCV+vol|Y|Could|Digest 04|
|13|Delta-Volume bars|N|Y (DeepCharts price chart)|DeepCharts|publicTrade delta|Y|Should|Ties to CVD/footprint work|
|14|Renko (fixed brick)|Y (Plus+)|Y (bar mode)|Exocharts|kline/trade-derived price moves|Y|Could|No tiering constraint for us|
|15|Renko (ATR brick)|N (TV Renko fixed only, unconfirmed ATR variant)|Y|DeepCharts|ATR calc + price|Y|Could||
|16|Line break|Y (Plus+)|N|—|kline close|Y|Won't|Niche|
|17|Kagi|Y (Plus+)|N|—|kline close, reversal %|Y|Won't|Niche|
|18|Point & Figure|Y (Ultimate)|Y (bar mode)|—|kline close, box/reversal|Y|Could||
|19|Range bars|Y (Plus+)|Y (bar mode)|Exocharts/ATAS|trade-derived price range|Y|Should|Order-flow-native bar mode|
|20|Volume bars (new bar per volume threshold)|N (tick-interval adjacent)|Y (bar mode)|ATAS/Exocharts|publicTrade volume sum|Y|Must|Core order-flow bar mode|
|21|Tick/Trade bars (new bar per N trades)|Y (Ultimate, 7d)|Y (bar mode)|ATAS|publicTrade count|Y|Must|No 7-day cap for us (own recorder)|
|22|Delta bars (new bar on cumulative delta threshold)|N|Y|DeepCharts|publicTrade signed delta|Y|Should|Digest 04 §"Delta Bars"|
|23|Continuous/rollover contract chart|Y|Y (futures)|—|instrument metadata|N|Won't|No perp rollover in crypto perps (funding, not rollover)|
|24|Seconds intervals (1/5/10/15/30/45s)|Y (Premium/Ultimate)|Y (Time bar mode)|—|kline construction from ticks|Y|Should|Build from own tick store, no tier gate|
|25|Tick intervals (raw tick chart)|Y (Ultimate, 7d)|Y (Tick/Trades mode)|ATAS|publicTrade stream|Y|Should|Own recorder removes 7-day cap|
|26|Volume Footprint chart (order-flow)|Y (Premium+, 2024)|Y (Deep Print)|ATAS/Exocharts/Bookmap|publicTrade (bid/ask split via taker side)|Y|Must|Flagship differentiator; digests 01,04,08|
|27|Session Volume Profile chart type|Y (Essential+)|Y (Deep Profile)|All order-flow platforms|publicTrade grouped by price|Y|Must||
|28|TPO / Market Profile chart|Y (Plus+)|Y|Sierra Chart|bar high/low/timestamp only|Y|Should|24/7 session boundary must be redefined (UTC)|
|29|Compare/overlay symbol (ratio, % scale)|Y|Not documented|TV|kline of 2 symbols|Y|Should|e.g. BTCUSDT/ETHUSDT ratio|
|30|Multi-timeframe overlay (`request.security`-style)|Y (Pine)|Not documented|—|kline multiple intervals|Y|Should|No Pine sandbox; native backend calc|
|31|Extended/ETH session toggle|Y|Y|—|n/a (24/7 crypto)|N|Won't|No RTH/ETH concept in crypto|
|32|Custom time intervals (non-standard minute counts)|Y (paid-gated)|Y|—|kline aggregation|Y|Should|No tier gate for us|

---

## B. Scales / sessions / timeframes

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|33|Log price scale|Y|Assumed (standard)|All|kline|Y|Must||
|34|Linear price scale|Y|Y|All|kline|Y|Must||
|35|% scale (for compare/overlay)|Y|Not documented|—|kline+ref price|Y|Should||
|36|Auto-fit / manual scale|Y|Y|All|n/a (UI)|Y|Must||
|37|Timezone selection (exchange/local)|Y|Not documented (24/7)|—|n/a|Y|Should|Crypto has no exchange TZ; local vs UTC toggle|
|38|Countdown to bar close|Y|Y|All|kline interval calc|Y|Must||
|39|Day boundary redefinition (UTC 00:00 vs funding-time anchor)|N (has real RTH)|N (futures RTH-based)|—|config|Y|Must|Crypto-specific; needed for TPO/session VWAP/profile (digests 04,08)|
|40|Multiple timeframes per symbol (switch 1m–1M)|Y|Y|All|kline multi-interval|Y|Must||
|41|Historical bar depth (unlimited, self-hosted)|Tiered 5K–40K|Not tiered (local)|—|own tick/kline store|Y|Must|Moot tiering constraint — own DB (digest 03)|
|42|Session VWAP anchor options (UTC day / funding time / custom)|Fixed session only|Fixed period/session (unconfirmed anchor flexibility)|—|publicTrade|Y|Must|Digest 04 open Q re: true click-anchor|
|43|Continuous/rollover basis (date/vol/price-adjusted)|Y (futures)|Y (futures)|—|n/a|N|Won't|No perpetual "rollover" analog|
|44|Days-to-load control (per-view lookback)|Implicit (tier-based)|Y (explicit setting)|ATAS|local store|Y|Must|Explicit UI control per view (digest 04)|

---

## C. Drawing tools

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|45|Trendline|Y|Assumed|All|n/a (chart overlay)|Y|Must||
|46|Ray|Y|Assumed|All|n/a|Y|Should||
|47|Extended line|Y|Assumed|All|n/a|Y|Could||
|48|Horizontal line|Y|Assumed|All|n/a|Y|Must|Level marking, persisted per symbol (digest 12 #4)|
|49|Horizontal ray|Y|Assumed|All|n/a|Y|Should||
|50|Vertical line|Y|Assumed|All|n/a|Y|Could||
|51|Crossline|Y|N|—|n/a|Y|Won't||
|52|Anchored VWAP (drawing-tool style)|Y|N (native indicator instead)|—|publicTrade|Y|Must|Digest 12 #7|
|53|Parallel channel|Y|N|—|n/a|Y|Should||
|54|Regression trend channel|Y|N|—|kline close, linreg|Y|Could||
|55|Flat top/bottom channel|Y|N|—|n/a|Y|Won't||
|56|Pitchfork (Andrews/Schiff/Modified/Inside)|Y|N|—|n/a|Y|Could||
|57|Fibonacci retracement|Y|N (not in digest)|All|n/a|Y|Must|High-usage classic tool|
|58|Fibonacci extension|Y|N|All|n/a|Y|Should||
|59|Fibonacci channel/time-zone/fan/circles/arcs/spiral/wedge|Y|N|—|n/a|Y|Could|Bundle as low-priority extras|
|60|Gann box/square/fan|Y|N|—|n/a|Y|Won't|Niche|
|61|Rectangle|Y|Y (zone/box overlays)|All|n/a|Y|Must|Used for imbalance zones, unfinished auction rectangles|
|62|Rotated rectangle|Y|N|—|n/a|Y|Won't||
|63|Circle/Ellipse|Y|N|—|n/a|Y|Won't||
|64|Triangle|Y|N|—|n/a|Y|Could||
|65|Brush/Highlighter/Path/Curve/Polyline|Y|N|—|n/a|Y|Could|Bundle as free-form annotation kit|
|66|Text/Note/Callout/Comment/Price label annotation|Y|N|—|n/a|Y|Must|Basic annotation needed for journaling/markup|
|67|Table (on-chart)|Y|Y (Info Box/stats table)|—|n/a|Y|Should|Used for footprint Info Box / Deep Stats summary|
|68|Pattern tools (XABCD/Elliott/Head&Shoulders/etc.)|Y|N|—|n/a|Y|Won't|Out of scope, discretionary pattern-drawing niche|
|69|Long/Short position sizing tool (risk-based, drag entry/TP/SL)|Y|N (native calculator instead)|Insilico/Jigsaw|account equity + risk %|Y|Must|Core "fast order controls" requirement (digest 02 §3)|
|70|Risk/Reward drawing tool|Y|N|—|n/a|Y|Should||
|71|Date/Price range measurement tool|Y|N|—|n/a|Y|Could||
|72|Magnet mode (snap to price/time)|Y|Assumed|All|n/a|Y|Should||
|73|Lock/hide-all drawing objects|Y|Assumed|All|n/a|Y|Should||
|74|Drawing templates (save/apply)|Y|Assumed|All|n/a|Y|Should||
|75|Per-timeframe drawing visibility|Y|Assumed|All|n/a|Y|Could||
|76|Cross-chart drawing sync (multi-layout)|Y|Not documented|—|n/a|Y|Should|Ties to Multi-Chart Layouts view (digest 23 #11)|
|77|Object tree / layer manager|Y|N|—|n/a|Y|Could||
|78|Undo/redo drawings|Y|Assumed|All|n/a|Y|Must||

---

## D. Indicators (classic TA)

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|79|SMA|Y|Assumed|All|kline close|Y|Must||
|80|EMA|Y|Assumed|All|kline close|Y|Must||
|81|WMA/VWMA/SMMA/DEMA/TEMA (Triple EMA)|Y|N|All|kline close|Y|Should|Bundle of MA variants|
|82|Hull MA / ALMA / KAMA / McGinley Dynamic / Least Squares MA|Y|N|—|kline close|Y|Could|Long tail MA variants|
|83|MA Cross / MA Ribbon|Y|N|—|kline close|Y|Should||
|84|Ichimoku Cloud|Y|N|—|kline HLC|Y|Should||
|85|Parabolic SAR|Y|N|—|kline HL|Y|Should||
|86|Supertrend|Y|N|Many|kline HLC+ATR|Y|Must|Popular trend/regime building block|
|87|Williams Alligator / Fractal|Y|N|—|kline HL|Y|Could||
|88|Zig Zag|Y|N|Deep Profile Swing (indirect)|kline HL, pivot logic|Y|Must|Swing detector underpins Deep Profile Swing analog|
|89|Vortex Indicator / Trend Strength Index|Y|N|—|kline HLC|Y|Won't||
|90|RSI (+ divergence)|Y|N|All|kline close|Y|Must||
|91|Stochastic / Stochastic RSI / SMI Ergodic|Y|N|—|kline HLC|Y|Should||
|92|MACD|Y|N|All|kline close|Y|Must||
|93|CCI / Williams %R / Ultimate Oscillator|Y|N|—|kline HLC|Y|Should||
|94|Awesome Oscillator / BOP / Momentum / ROC|Y|N|—|kline HLC|Y|Could||
|95|Connors RSI / DPO / Fisher Transform / Klinger / KST / Coppock / Mass Index / PPO / PMO / Pring Special K / RCI / Relative Vigor / TSI / Woodies CCI|Y|N|—|kline HLC|Y|Won't|Long tail, low priority|
|96|Bollinger Bands (+%b/BandWidth)|Y|N|All|kline close, stdev|Y|Must||
|97|ATR|Y|N|All (market regime input)|kline HLC|Y|Must|Feeds market regime classifier (digest 08 §16)|
|98|Keltner Channels / Donchian Channels / Envelope|Y|N|—|kline HLC|Y|Should||
|99|ADX (+DI/-DI)|Y|N|—|kline HLC|Y|Must|Feeds market regime classifier|
|100|Chande Kroll Stop / Chandelier Exit|Y|N|—|kline HLC/ATR|Y|Should|Trailing-stop candidates (digest 09 §3)|
|101|Choppiness Index / Ulcer Index / Historical Volatility / Relative Volatility Index / Volatility Stop / ADR|Y|N|—|kline HLC|Y|Could||
|102|Volume (histogram)|Y|Y (Classic Volume)|All|kline volume|Y|Must||
|103|OBV / ADL / Chaikin Money Flow / Chaikin Oscillator / NVI / PVI / PVT / Net Volume / Ease of Movement / Elder Force Index / MFI|Y|N|—|kline OHLCV|Y|Should|Bundle of classic volume indicators|
|104|Relative Volume at Time / Up-Down Volume|Y|N|—|kline volume|Y|Could||
|105|Cumulative Volume Delta (CVD) — classic indicator form|Y (as indicator)|Y (dedicated feature, see F)|All order-flow platforms|publicTrade signed volume|Y|Must|Cross-listed with F.CVD; classic-indicator packaging here|
|106|Cumulative Volume Index|Y|N|—|kline OHLCV|Y|Won't||
|107|Hurst Exponent (custom regime input)|N|N (not itemized)|—|kline close, R/S calc|Y|Should|Feeds market regime classifier (digest 08 §16)|
|108|Custom indicator scripting (Pine-equivalent)|Y (Pine Script)|Not documented (proprietary engine)|Freqtrade/Quantower (C#)|n/a|Y (Python backend, no sandbox)|Could|Real backend > Pine sandbox; de-prioritized vs order-flow core (digest 12 MoSCoW #14)|
|109|Indicator-on-indicator chaining|Y (tiered 1–49)|Assumed|—|n/a|Y|Could||
|110|Per-chart indicator limit|Tiered 2–50|Not documented|—|n/a|Y (no limit, self-hosted)|Must (moot)|No artificial cap — perf-bound only|

---

## E. Order-flow views — Footprint & profile

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|111|Footprint cell — Volume mode|Y (Premium+)|Y (Deep Print)|ATAS/Exocharts/Bookmap|publicTrade grouped by tick price|Y|Must||
|112|Footprint cell — Bid/Ask Split mode|Partial (estimated splits)|Y|ATAS|publicTrade `S` (taker side) — real, not estimated|Y|Must|Genuine advantage vs TV's estimated splits (digest 01,03)|
|113|Footprint cell — Delta mode|Y|Y|All|publicTrade signed|Y|Must||
|114|Footprint cell — Delta+Total Volume mode|N|Y|—|publicTrade|Y|Should||
|115|Footprint display mode: Profile (histogram)|Y|Y|All|footprint cells|Y|Must||
|116|Footprint display mode: Box/numeric|Y|Y|All|footprint cells|Y|Must||
|117|Footprint input type: Volume|Y|Y|All|publicTrade|Y|Must||
|118|Footprint input type: Aggregate Volume|Not documented|Y|—|publicTrade|Y|Should||
|119|Footprint input type: Number of Trades|N|Y|—|publicTrade count|Y|Should||
|120|Footprint input type: Order (per-order-arrival count)|N|Y (ambiguous, likely relabeled aggregate)|ATAS (MBO)|L3/MBO order stream|**Partial/N**|Won't|No Bybit L3 — cannot do true per-order counting (digests 04,05)|
|121|Footprint min/max value noise filter|N|Y|ATAS|footprint cells|Y|Should||
|122|Footprint coloring by Delta/Imbalance thresholds|N|Y|All|footprint cells|Y|Must||
|123|Diagonal imbalance detection (default 300%)|N|Y|ATAS/Bookmap|footprint cells (adjacent price/side)|Y|Must|Threshold configurable (digest 08 §3)|
|124|Stacked imbalance detection (≥N consecutive)|N|Not explicitly named (implicit)|ATAS|footprint cells|Y|Must|minStack default 3 (digest 08 §3)|
|125|Unfinished auction marker|N|Y|—|footprint cells (bar close at extreme w/ volume)|Y|Should||
|126|Bar POC (intrabar point of control)|N|Y|—|footprint cells|Y|Must||
|127|Imbalance Rejector (reversal variant)|N|Y|—|footprint cells + swing validity|Y|Could||
|128|Auction Gap Tracker (zero/thin-print)|N|Y|—|footprint cells|Y|Could||
|129|Deep Delta (multi-range filterable delta bars)|N|Y|—|publicTrade, up to 4 ranges|Y|Could||
|130|Volume Profile (session/fixed-range/composite)|Y (Essential+/Ultimate composite)|Y (Deep Profile)|All order-flow platforms|publicTrade grouped by price|Y|Must||
|131|Anchored Volume Profile|Y|Not explicit (Personalized period type)|—|publicTrade|Y|Should||
|132|Visible-range Volume Profile|Y|Y (Visible period type)|—|publicTrade in viewport|Y|Should||
|133|Composite Volume Profile (multi-period sum)|N (session-only mostly)|Y|—|publicTrade multi-period|Y|Should||
|134|Volume Profile: POC line|Y|Y|All|profile histogram|Y|Must||
|135|Volume Profile: Value Area (~70%)|Y|Y|All|profile histogram|Y|Must|70% convention, some platforms 68/80% (digest 08)|
|136|Volume Profile: HVN/LVN peak/valley detection|Not native|Y|—|profile histogram, local maxima/minima|Y|Should||
|137|Naked/Virgin POC persistence & retest flip|Not native|Y (implied, unconfirmed detail)|—|profile history, price crossing check|Y|Should||
|138|Delta Profile (volume profile split by delta)|N|Y|—|publicTrade signed, grouped by price|Y|Must||
|139|Order-input Volume Profile (per-order)|N|Y (same "Order" ambiguity as footprint)|—|L3/MBO|**Partial/N**|Won't|Same L3 limitation as #120|
|140|TPO / Market Profile (letter-based)|Y (Plus+)|Y|Sierra Chart|bar high/low/timestamp, no volume|Y|Should|24/7 day-boundary redefinition required|
|141|TPO Initial Balance (first N periods)|Industry standard, in TV community scripts|Y ("Third Range")|Sierra Chart|TPO periods|Y|Should||
|142|TPO single-print / naked print detection|Industry standard|Implied (via Auction Gap Tracker overlap)|Sierra Chart|TPO letter grid|Y|Could||
|143|Deep Profile Swing (swing-anchored volume/delta profile)|N|Y|—|ZigZag swing detector + publicTrade|Y|Could|Combines ZigZag(#88) + Profile|
|144|Confluence Identifier (multi-period VBP confluence + S/R)|N|Y|—|multi-timeframe volume profile|Y|Could||

## E2. Order-flow views — Stats, tape, big trades, CVD

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|145|Deep Stats row: Total/Bid/Ask Volume per bar|N|Y|All order-flow platforms|publicTrade|Y|Must||
|146|Deep Stats row: Delta, Max/Min Delta, Delta %|N|Y|All|publicTrade|Y|Must||
|147|Deep Stats row: Cumulative Delta, Number of Trades|N|Y|All|publicTrade|Y|Must||
|148|Time & Sales / Tape (raw prints feed)|Y (broker Level 2 dependent)|Y (Times & Sales, DeepDOM)|All|publicTrade WS|Y|Must||
|149|Big Trades / large-print highlighting (manual threshold)|N (community whale scripts only)|Y|Bookmap (volume dots)|publicTrade filtered by notional|Y|Must||
|150|Big Trades automatic filter (Intensity Level algo)|N|Y|—|publicTrade, statistical threshold (k×rolling avg or z-score)|Y|Should|z-score ~3.0 default (digest 08)|
|151|Big Trades bubble plotting (size/color/opacity by notional)|N|Y|Bookmap volume dots|publicTrade|Y|Must||
|152|Trade-print clustering (same price/side within window → one bubble)|N|Y (implicit in Big Trades)|Jigsaw "Reconstructed Tape"|publicTrade, 50ms window default|Y|Must|Distinguish from iceberg detection (digest 08 §12)|
|153|Big Trades alert (sound/threshold)|N|Y|—|publicTrade|Y|Should||
|154|Speed of Tape (prints/sec, volume/sec)|N|Y|—|publicTrade rolling window|Y|Must||
|155|Speed of Tape acceleration (vs baseline, alert threshold)|N|Y (implied "Instant" variant)|—|publicTrade rolling stats|Y|Should|>3-5x baseline default (digest 08)|
|156|Book Speed (order-book update velocity, calm/nervous regime)|N|Y|—|orderbook WS delta message rate|Y|Should|Feeds Market Regime|
|157|CVD — session-reset|N (community scripts)|Y|All order-flow platforms|publicTrade signed|Y|Must||
|158|CVD — anchored/custom reset|N|Y|—|publicTrade|Y|Should||
|159|CVD — display modes (candlestick/histogram/line)|N|Y|—|CVD series|Y|Must||
|160|CVD — multi-symbol/composite (normalized)|N|Not documented|—|publicTrade multi-symbol, USD-notional normalize|Y|Could||
|161|Delta/CVD divergence detector (single-bar)|N|Y|—|price + delta series|Y|Should||
|162|Delta/CVD divergence detector (multi-bar swing-based)|N|Not documented|—|pivot-based swing detector on price+CVD|Y|Must|Recommended over naive single-bar (digest 08 §2)|

## E3. Order-flow views — DOM, heatmap, detectors, regime

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|163|DOM / order-book ladder (live bid/ask by level)|Y (broker L2-dependent; Bybit confirmed on list)|Y (Classic Advanced DOM)|All order-flow platforms|orderbook.50/200/500 WS|Y|Must||
|164|DOM click-to-trade|Y (broker-dependent)|Y|Bookmap/Sierra Chart|orderbook WS + order REST/WS|Y|Should||
|165|DOM liquidity heatmap (color-coded resting depth)|N (gap vs DeepDOM)|Y (core feature)|Bookmap (reference impl.)|orderbook.50/200/500 WS, historized|Y|Must|Flagship differentiator (digest 03 gap #2)|
|166|Heatmap adaptive/relative color scale|N|Y|Bookmap|orderbook WS|Y|Must||
|167|Heatmap decay/trail duration|N|Y (implied)|Bookmap|orderbook WS, time-decayed accumulation|Y|Should||
|168|Heatmap MBO highlight mode|N|Y (MBO-only)|Bookmap (partial)|L3/MBO|**N**|Won't|No Bybit L3|
|169|Deep Liquidity Scan (cumulative book thickness/variation, Bid/Ask/Delta)|N|Y|—|orderbook WS, N-level sum, calc modes (Exp/Last/Peak)|Y|Should|Fully MBP-feasible (digest 05 §4.8)|
|170|Deep Reload (book reloading w/ fresh directional liquidity)|N|Y|—|orderbook WS delta stream, rolling aggregation|Y|Should|High feasibility, no MBO needed (digest 05 §4.7)|
|171|Absorption detector (aggressive flow absorbed w/o price move)|N|Y|—|footprint cells (volume high, price move low)|Y|Must|Core signal feasible; Max-Orders-Number knob dropped (MBO-only)|
|172|Iceberg / hidden-order detector (heuristic replenishment)|N (community scripts)|Y (true MBO-based)|ATAS (MBO)|orderbook refill pattern + trade tape|**Partial**|Should|Heuristic proxy only, must show "(estimated)" badge (digest 23)|
|173|Stop-run / liquidity sweep detector|N (community scripts)|Y (Stop Run)|ATAS/Bookmap heuristics|publicTrade burst + prior swing level|Y|Must|Fully derivable from trade tape alone, no L2 needed (digest 04 §24)|
|174|Cumulative Stop/Iceberg activity tracker (running line)|N|Y (MBO-based)|—|L3/MBO|**N**|Won't|MBO-only end to end|
|175|Big Passive Trade (largest resting book orders, order-by-order)|N|Y (MBO-only)|—|L3/MBO|**N**|Won't||
|176|24-hour DOM backfill on chart open|N|Y|—|orderbook history from local recorder|Y|Should|Needs recorder running ≥24h prior|
|177|Market Regime classifier (trend/range/volatile/calm)|N (ADX/ATR building blocks only)|Y (DeepDOM "Market Regime")|—|ADX+ATR+Hurst+book-thickness composite|Y|Must|Not a real DeepCharts algo either — build own (digest 04 §25, 05)|
|178|Imbalance Tracker — stacked/diagonal bid-ask (chart-wide panel)|N|Y|ATAS/Bookmap|footprint cells|Y|Must|Cross-listed w/ #123/124, packaged as dedicated panel view|
|179|VWAP (session)|Y|Y|All|publicTrade|Y|Must||
|180|VWAP Envelopes (1/2/3 stdev bands)|N (Bollinger-style separate)|Y|—|VWAP + stdev|Y|Should||
|181|Anchored VWAP (click-to-anchor, arbitrary bar)|Y|Unconfirmed (may be fixed-period only)|—|publicTrade from anchor bar|Y|Must|CandleViewer can do true click-anchor even if DeepCharts can't (digest 04 open Q)|
|182|Deep-M Effort (proprietary trend/orderflow bias model)|N|Y (proprietary, undocumented)|—|unknown proprietary algo|N (algorithm undisclosed)|Won't|Can't replicate undocumented proprietary IP; build own regime/bias indicator instead|
|183|Deep-M IVB (ORB-based opening range breakout)|N|Y|—|24/7 session open redefinition + range calc|Y|Could|Needs UTC-daily-open redesign|
|184|Deep V-Tracker (Acceleration/Exhaustion/Slowdown patterns)|N|Y|—|footprint+CVD-derived|Y|Could|Undocumented algo, approximate only|
|185|Deep Wall (iceberg passive-wall rejection signature)|N|Y (ES-futures-tuned)|—|trade tape + L2 refill pattern|**Partial**|Could|No true L3, approximate only, rare signal|

---

## F. Crypto data (OI, funding, liquidations, L/S ratio, basis, options)

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|186|Open Interest (current + history)|Y (Financials tab, current rate only)|N (futures-equities focus, no crypto)|Coinglass/Hyblock|`/v5/market/open-interest` REST + `tickers` WS|Y|Must||
|187|OI Δ-per-bar / OI-price quadrant coloring|N|N|Coinglass|OI history + price|Y|Should||
|188|Funding rate (current)|Y (Financials tab)|N|Coinglass/Coinalyze|`tickers` WS `fundingRate`|Y|Must||
|189|Funding rate history|N (current only)|N|Coinglass/Coinalyze|`/v5/market/funding/history` REST|Y|Must||
|190|Funding countdown timer to next settlement|N (gap — no native countdown)|N|3rd-party browser extensions only|`tickers` WS `nextFundingTime`|Y|Must|Confirmed TV gap (digest 03 §3.12)|
|191|Predicted funding rate|Unclear if TV shows predicted|N|Coinalyze|`tickers` WS (unclear if `fundingRate` is already predictive — needs live verify)|Partial (needs verify)|Should|Open question (digest 08 #8)|
|192|Annualized funding rate toggle|N|N|Velo/Coinalyze|funding rate calc|Y|Should||
|193|Liquidations feed (real-time, per-symbol)|N (no native aggregation)|N (futures-equities)|Coinglass/Hyblock|`allLiquidation.{symbol}` WS|Y|Must|No REST history endpoint — recorder-only depth (digest 08,23)|
|194|Liquidation heatmap (predicted zones)|N|N|Hyblock/Coinglass|OI + leverage-tier modeling (estimated, proprietary formulas elsewhere)|Partial|Should|Estimated/modeled, not exchange-confirmed (digest 03 §3.11)|
|195|Liquidation bars (long/short split, notional threshold)|N|N|Coinglass|`allLiquidation` WS, time-bucketed|Y|Must||
|196|Long/Short ratio (global accounts)|N|N|Coinglass|`/v5/market/account-ratio` REST|Y|Should||
|197|Long/Short ratio (top-trader)|N|N|Coinglass|Not directly exposed by Bybit v5 (top-trader split unconfirmed)|Partial|Could|Needs live verification of endpoint scope|
|198|Basis (mark vs index, annualized)|N|N|Velo/Laevitas|`tickers` WS markPrice/indexPrice|Y|Should||
|199|Premium index / mark-index spread history|N|N|Velo|`/v5/market/premium-index-price-kline` REST|Y|Should||
|200|Insurance fund tracking|N|N|—|`/v5/market/insurance` REST|Y|Could||
|201|Risk limit tiers (per-symbol margin/leverage tiers)|N|N|—|`/v5/market/risk-limit` REST|Y|Should|Needed for accurate liquidation-price/risk calc|
|202|Options OI by strike/expiry|N (crypto-N/A)|N (SPX-only via DeepGamma)|Deribit/Laevitas|Deribit REST (primary) / Bybit option OI (secondary)|Partial (Bybit thin, Deribit strong)|Could|Out of initial scope; phase-3 if options added (digest 05)|
|203|Options Greeks / IV surface / skew|N|Y (DeepGamma, SPX-only)|Laevitas/Deribit|Deribit REST/WS Greeks|Partial|Won't (v1)|Crypto options out of scope for v1 (project brief: crypto-only, Bybit-first)|
|204|Gamma Exposure (GEX) profile|N|Y (DeepGamma, SPX-only, not crypto)|Laevitas (BTC/ETH GEX)|Deribit options chain + assumption-based dealer-gamma model|Partial (assumption-based, no CBOE-style certainty)|Won't (v1)|Not directly transferable from equities; needs dedicated Deribit research phase first|
|205|Exchange-flow / whale on-chain metrics|N|N|CryptoQuant/Glassnode|On-chain data provider (not Bybit)|N (needs 3rd-party on-chain API)|Won't (v1)|Out of scope per project brief (Bybit-only, crypto exchange data)|
|206|Cross-exchange aggregated OI/liquidation (multi-venue)|N|N|Coinglass/Hyblock|Multiple exchange APIs|N (v1 Bybit-only)|Could (later)|Explicit "later exchanges" roadmap item per project brief|
|207|Historical volatility (options-derived)|N (crypto)|N|Laevitas|`/v5/market/historical-volatility` REST|Partial|Won't (v1)|Options-adjacent, deprioritized|

---

## G. Trading / order entry

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|208|Market order|Y (broker-dependent)|Y|All|`/v5/order/create`|Y|Must||
|209|Limit order|Y|Y|All|`/v5/order/create`|Y|Must||
|210|Stop / Stop-Market order|Y|Y|All|`/v5/order/create` (conditional)|Y|Must||
|211|Stop-Limit order|Y|Y|All|`/v5/order/create` (conditional+limit)|Y|Must||
|212|Conditional order (trigger by price/mark/index/last)|Broker-dependent|Y|All|`/v5/order/create` triggerPrice/triggerBy|Y|Must||
|213|Post-Only order|Broker-dependent|Y|All|timeInForce=PostOnly|Y|Should||
|214|Time-in-force GTC/IOC/FOK|Broker-dependent|Y|All|timeInForce param|Y|Must||
|215|Reduce-Only flag|Broker-dependent|Y|All|reduceOnly param|Y|Must||
|216|Close-on-Trigger flag|Broker-dependent|Not documented|—|order param|Y|Should||
|217|TP/SL attach at order placement|Y (bracket concept)|Y|All|takeProfit/stopLoss params|Y|Must||
|218|TP/SL attach to open position (Entire Position mode)|Broker-dependent|Y|All|`/v5/position/trading-stop`|Y|Must||
|219|TP/SL Partial Position mode (multiple concurrent, native OCO between legs)|Broker-dependent|Y|All|trading-stop tpslMode=Partial, tpSize/slSize|Y|Should||
|220|Trailing stop (fixed distance)|Broker-dependent|Y|All|trading-stop trailingStop (price distance)|Y|Must|Bybit is price-distance not %; needs client %-translation layer (digest 06,09)|
|221|Trailing stop (% translated client-side)|N (native)|N (native)|3Commas|client-side calc + trading-stop|Y|Must|Common UX expectation despite no native % support|
|222|OCO (bracket, one-cancels-other)|Y (via bracket, not literal OCO)|Y (Trading Terminal OCO modes)|3Commas/TradingView bracket|No native derivatives OCO API — must emulate (race 2 orders, cancel loser)|**Partial**|Must|Confirmed Bybit gap: spot-only native OCO, not in derivatives API (digest 02,09)|
|223|Bracket order (entry+TP+SL combined ticket)|Y|Y|All|multiple linked orders via orderLinkId|Y|Must||
|224|Iceberg order (visible qty + hidden reserve)|Broker-dependent|N (MBO-only detection, not placement)|Native on some venues|No native Bybit API field — must emulate via client-side slicing|**Partial**|Should|Confirmed gap: no `orderType=Iceberg`/`displayQty` on Bybit v5 (digest 09)|
|225|TWAP execution algo|N (native)|N|Insilico/Quantower|Emulated via timed repeated order/create calls|**Partial**|Should|Not a native Bybit REST order type|
|226|Scaled order (split across N price levels)|N (native)|N|Insilico/Tealstreet/Altrady|Emulated as N individual limit orders|Y (emulated)|Should||
|227|Chase/pegged limit order (auto reprice to stay near best bid/ask)|N (native)|N|Insilico "Limit Chase"|Bybit Iceberg-ticket sub-algo (Chase Limit Taker/Maker/Offset) or emulated cancel/replace loop|Y|Should|Native sub-algo exists but exact params unconfirmed (digest 09 open Q#7)|
|228|Order-from-chart (click price to place order)|Y|Y (Trading Terminal)|All|chart click event + order REST|Y|Must||
|229|Drag order/TP-SL line to reprice (live order)|Y (unconfirmed exact mechanics)|Y (left-click reprice)|All|order amend REST + drag interaction|Y|Must||
|230|Right-click cancel order (chart-native)|Not confirmed|Y|All|order cancel REST|Y|Should||
|231|Flatten button (close position + cancel all pending, one action)|Not confirmed as single action|Y|Sierra Chart/Jigsaw|position close + cancel-all REST, combined|Y|Must|Core "fast order controls" requirement|
|232|DOM click-to-trade (click price cell)|Y (broker L2-dependent)|Y|Bookmap/Jigsaw|orderbook WS + order REST|Y|Should||
|233|One-click trading arm/lock toggle (safety)|Y|Not explicit (implied via enable-trading toggle)|Bookmap (off by default)|client-side UI state|Y|Must|Confirmed real feature per digest 03 §3.9, not a gap|
|234|Hotkeys: buy/sell market, size presets, flatten, cancel-all|Y (fixed set)|Y (user-configurable, no defaults found)|Bookmap/Sierra Chart/Jigsaw/NinjaTrader|client-side UI|Y|Must|Confirmed TV gap: no ladder-native user-programmable hotkeys (digest 03 gap #22) — build fully custom|
|235|Quantity presets (%/fixed size buttons)|Not confirmed|Not confirmed|Bookmap/Tealstreet/Altrady|client-side UI + account equity|Y|Must||
|236|Risk-based position sizing (from %equity/$risk/ATR-stop distance)|Y (drawing-tool only, not order ticket)|N (native calculator equivalent via drawing tool)|—|account equity (wallet-balance) + entry/stop distance|Y|Must|Core differentiator vs Bybit's native UI which lacks this (digest 09 §1)|
|237|Order templates (saved order+bracket+size combos)|Not confirmed|Not confirmed|Jigsaw daytradr/Quantower|local config store|Y|Should||
|238|Position mode: One-Way|Y (via broker)|Y|All|`/v5/position/switch-mode` mode=0|Y|Must||
|239|Position mode: Hedge (simultaneous long+short)|Y (via broker)|Y|All|`/v5/position/switch-mode` mode=3, positionIdx|Y|Should|ATAS explicitly requires One-Way only — CandleViewer should support both|
|240|Leverage control per symbol|Y (via broker)|Y|All|`/v5/position/set-leverage`|Y|Must||
|241|Margin mode: Cross/Isolated|Y (via broker)|Y|All|`/v5/position/switch-isolated`|Y|Must||
|242|Margin mode: Portfolio Margin|N (broker-dependent, rare)|Not documented|—|`/v5/account/set-margin-mode`|Y|Could|KYC/risk-tier gated on Bybit side|
|243|Positions & Orders consolidated panel (cross-symbol/sub-account)|Y (Orders Window)|Y|All|private WS position/order + REST reconciliation|Y|Must||
|244|Partial close (position)|Y|Y|All|`/v5/order/create` reduceOnly qty|Y|Must||
|245|Reverse position (one-click flip)|Y|Not explicit|—|close+open combined order sequence|Y|Should||
|246|Order history / execution marks on chart|Y|Y|All|`/v5/order/history`, `/v5/execution/list`|Y|Must||
|247|Level 2 / DOM data feed integration|Y (Bybit confirmed on broker list)|Y|All|orderbook.50/200/500 WS|Y|Must||
|248|Symbol/instrument precision validation (tick/lot size)|Y (broker-side)|Y|All|`/v5/market/instruments-info`|Y|Must||
|249|Spot margin trading (isLeverage flag)|N (crypto-N/A on TV directly)|N|—|`/v5/order/create` category=spot isLeverage|Partial|Could|Lower priority vs derivatives|
|250|Options order entry|N (crypto)|N|—|category=option|N (v1)|Won't (v1)|Out of scope for v1|

---

## H. Risk automation / rule-based stops

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|251|Rule-based trailing stop (fixed ticks)|N (native, Pine strategies only)|N|Freqtrade `custom_stoploss`|position price stream + trading-stop REST|Y|Must||
|252|ATR-based trailing stop|N|N|Freqtrade|ATR calc + trading-stop REST|Y|Must|Not native anywhere reviewed — differentiator (digest 09 §3)|
|253|Structure-based (swing hi/lo, "chandelier") trailing stop|N|N|—|ZigZag swing detector + trading-stop|Y|Should|Not offered natively anywhere — candidate differentiator|
|254|MA-based trailing stop (e.g. 20 EMA)|N|N|—|EMA calc + trading-stop|Y|Could||
|255|Breakeven-at-R-multiple auto-move|N (Pine strategies only)|N|Hummingbot Triple Barrier|position R-multiple calc + trading-stop|Y|Must||
|256|Activation-delta trailing (arm after favorable move, then trail)|N|N|Hummingbot Triple Barrier|price delta calc + trading-stop|Y|Should|Clean reusable schema from Hummingbot (digest 09 §3)|
|257|Time-based auto-exit (max hold duration)|N (Pine only)|N|Freqtrade `time_limit`|position open-time tracking + close order|Y|Should||
|258|Time-based stop tightening (stop tightens regardless of price)|N|N|—|time tracking + trading-stop|Y|Could|Open design question, no product precedent|
|259|Partial TP ladders (25%@1R/25%@2R/50%@3R)|N (native)|N|3Commas/Cornix/Altrady|multiple reduceOnly TP orders|Y|Should||
|260|Custom rule builder (no-code condition→action)|N (Pine only, code-based)|Y (Deep Pattern Builder, up to 4 conditions AND/OR)|Coinrule/Kryll|any derived series (OHLCV/delta/CVD/OI/funding/regime)|Y|Must|Extends Deep Pattern Builder concept to live execution, not just backtesting (digest 04 §15, 23 #16)|
|261|Rule condition combinators (AND/OR/AND+OR advanced)|N|Y (up to 4 conditions)|Kryll (30+ block types)|rule engine|Y|Must||
|262|Max daily loss lockout (auto-flatten)|N (native)|N|Freqtrade Protections (`StoplossGuard`,`MaxDrawdown`)|realized PnL tracking (private WS/REST) + flatten-all action|Y|Must||
|263|Max losing-streak cooldown|N|N|Freqtrade `CooldownPeriod`|trade history tracking|Y|Should||
|264|Spread-too-wide auto-cancel|N|N|Design sketch (digest 09 §7)|orderbook bid/ask spread calc|Y|Could||
|265|Avoid-stop-at-iceberg-level rule|N|N (concept only)|Design sketch (digest 09 §6b)|iceberg detector output + stop placement logic|Partial|Could|Depends on heuristic iceberg detector (#172)|
|266|Widen-stop-in-stop-hunt-zone rule|N|N|Design sketch|stop-run detector output|Y|Could||
|267|Reduce-leverage automated action|N|N|—|leverage REST + rule trigger|Y|Could||
|268|One-off DCA/scale-in ladder (safety orders)|N (native)|N|3Commas DCA bots|multiple limit orders on price-deviation steps|Y|Should||
|269|Rule DSL: metric vocabulary (price, R-multiple, ATR, EMA, swing hi/lo, CVD divergence, spread, funding, iceberg flags, tape speed z-score, market regime, etc.)|N|N (Deep Pattern Builder more limited: OHLCV/Indicator/Constant only)|—|composite of all above data sources|Y|Must|Full vocabulary defined in digest 09 §7 — core spec artifact|
|270|Rule DSL: action vocabulary (place/modify/cancel/move-to-BE/scale/flatten/halt/resume/notify/log/reduce-leverage/arm-chase/start-iceberg-slice)|N|N (limited to alert/backtest flags)|—|order/position REST+WS|Y|Must||
|271|Auto-backtest rule on save (against recorder history)|N (separate Strategy Tester)|Y (Deep Pattern Builder auto-backtest)|—|local tick/kline history|Y|Should||
|272|Simulate-only (dry-run) rule mode vs live-armed|N|Not explicit|Freqtrade dry-run|rule engine flag|Y|Must|Critical safety gate before arming live rules|
|273|Dead man's switch (auto-cancel-all on disconnect)|N|N|—|`/v5/order/disconnected-cancel-all` (native Bybit DCP)|Y|Must|Native Bybit feature — trivial to wire in|
|274|Per-manager risk limits (max position size, max daily loss, max concurrent positions) server-enforced|N|N|3Commas/Cornix (per-account)|app-layer config + private WS/REST monitoring|Y|Must|Core multi-manager requirement (digest 09 §10, 12)|
|275|Owner kill-switch (instant freeze per manager)|N|N|—|app-layer + API key/permission revoke or trading halt flag|Y|Must||

---

## I. Paper trading

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|276|Simulated order ticket against live real-time data|Y (idealized fills)|Y (Sim Account)|Bybit demo|Bybit demo trading (real matching engine)|Y|Must|Prefer Bybit demo over synthetic sim (digest 02,03)|
|277|Bybit demo-trading REST integration|N/A|N/A|—|`api-demo.bybit.com` REST|Y|Must||
|278|Bybit demo-trading WS (private: order/position/execution/wallet)|N/A|N/A|—|`wss://stream-demo.bybit.com`|Y|Must|Resolved: demo WS exists, contra earlier assumption (digest 06,12)|
|279|Demo trading via WS order entry (Trade-over-WS)|N/A|N/A|—|WS Trade `/v5/trade`|**N**|Won't|Confirmed unsupported on demo — must use REST for demo orders|
|280|Local simulated fill engine (covers any demo gaps/offline dev)|Y (idealized)|Y|NautilusTrader|local kline/tick + fill-price logic|Y|Should|Fallback/dev-mode, not primary path|
|281|Paper P&L tracking identical to live UI|Y|Y|All|demo position/wallet WS|Y|Must||
|282|Switch live/paper per session (explicit, confirm-required toggle)|Not documented as explicit toggle|Not documented|—|app-layer env switch|Y|Must|Distinct visual accent for Live vs Demo (digest 23 #20)|
|283|Reset paper balance / starting currency / leverage|Y (gear icon)|Y (Sim Account config, implied)|All|demo `/v5/account/demo-apply-money` (faucet) or reset flow|Y|Should||
|284|Order-book/slippage-aware paper fill simulation|N (idealized fills only — TV gap)|Not confirmed (real matching engine handles this)|Bybit demo (real order book)|Bybit demo real matching engine|Y|Must|Confirmed TV weakness solved by using Bybit's own demo engine (digest 03 gap #9)|
|285|Demo sub-account eligibility (per manager)|N/A|N/A|—|Bybit sub-account + demo flag|Partial (unconfirmed)|Should|Open question — needs empirical test (digest 06,12)|

---

## J. Replay / backtest

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|286|Bar-by-bar replay (manual step / auto-play)|Y|Y (Deep Replay)|ATAS Market Replay|local kline history|Y|Must||
|287|Tick-by-tick replay|Y (Ultimate, 7d cap)|Y (Deep Replay, w/ Big Trades markers)|ATAS (1-day/session full-fidelity cap)|local tick DB (own recorder)|Y|Should|No 7-day/1-day cap — own recorder depth (digests 01,04)|
|288|Full order-book (L2) replay during tick replay|N|Partial ("MBO Replay… in development" per DeepCharts)|Bookmap (local record feature)|local orderbook delta history (own recorder)|Y|Should|Needs stored L2 diffs over time — major storage driver|
|289|Replay speed control (0.5x–100x presets + scrub)|Y|Y|ATAS|n/a (playback engine)|Y|Must||
|290|Multi-chart/symbol sync replay|Y (Sept 2024 feature)|Not confirmed|—|n/a|Y|Should||
|291|Simulated/paper trading during replay|Y (Bar Replay + trading)|Y (sim mode)|ATAS|paper fill engine + replay clock|Y|Must|Key rule-rehearsal use case (digest 12 workflow step 9)|
|292|Session-state restore (resume replay position)|Y|Not confirmed|—|app-layer state persistence|Y|Should||
|293|Rule-based strategy backtest vs replay data|N (separate Strategy Tester/Pine)|Y (Deep Pattern Builder auto-backtest)|Freqtrade/NautilusTrader|rule engine + historical tick/kline data|Y|Could|Ties into Rule Builder (#271)|
|294|Deep Backtesting (very long lookback, 2M bars/1M trades caps)|Y (Premium+, hard caps)|Not documented at this scale|—|local store, no artificial cap|Y|Could|Moot cap — own DB, bound only by hardware|
|295|Bar Magnifier (lower-TF intrabar fill simulation)|Y|Not documented|—|lower-TF kline/tick for fill precision|Y|Could||
|296|"Jump to earliest available/random day" replay navigation|Y|Not confirmed|—|recorder history bounds|Y|Should||
|297|Replay bookmark/loop markers|N|Not confirmed|—|app-layer|Y|Could||
|298|Empty/partial-history state handling (recorder hasn't run long enough)|N/A (TV has full history)|N/A|—|app-layer UX|Y|Must|Explicit design requirement (digest 23 cross-cutting notes)|

---

## K. Alerts

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|299|Price alert (crossing/above/below/greater/less)|Y (tiered 3–1000)|Not strongly documented|Coinrule/Kryll|kline/ticker price stream|Y|Must|No tier cap for us — moot (digest 01,03)|
|300|Technical/indicator-based alert|Y (tiered 0–1000)|Not strongly documented|Coinrule|indicator series|Y|Must||
|301|Watchlist alerts (basic move/threshold)|Y (tiered, capped 0–15)|Not documented|—|tickers WS|Y|Should||
|302|Order-flow-derived alert (imbalance/big-trade/stop-run/regime-shift)|N (community scripts only)|Y (per-feature alert settings, e.g. Big Trades bid/ask alert)|—|footprint/tape/regime engines|Y|Must|Genuine differentiator — TV has none native|
|303|Alert-to-action automation (auto place/modify/cancel order on alert)|N (webhook→3rd-party bridge only, fragile)|Not documented|Coinrule/Kryll|rule engine (shares Rule Builder, #260)|Y|Could|Confirmed TV gap: no native one-click automation w/o fragile bridge (digest 03 gap #17)|
|304|Non-expiring alerts|Partial (Ultimate-only per marketing, unclear)|Not documented|—|app-layer, no expiry|Y|Must (moot)|No artificial expiry — self-hosted|
|305|Alert delivery: in-app toast|Y|Not documented|All|app-layer|Y|Must||
|306|Alert delivery: push/email/SMS|Y (tiered, region-gated SMS)|Not documented|Kingfisher (Telegram)|external service integration|Y|Should||
|307|Alert delivery: Telegram|N|Not documented|Kingfisher|Telegram bot API|Y|Could|Cheap notification channel idea (digest 07 §8)|
|308|Alert snooze/mute|Not confirmed|Not documented|—|app-layer|Y|Should||
|309|One-shot vs recurring alert|Y (implied)|Not documented|—|app-layer|Y|Should||
|310|Webhook alert delivery (outbound to 3rd-party)|Y (3s timeout, port 80/443 only — fragile)|Not documented|3Commas/Cornix signal parsing|outbound HTTP|Y|Could|We don't need inbound bridges (own trading engine), but outbound webhook for external notify tools is fine|

---

## L. Layouts / UX / hotkeys

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|311|Multi-chart grid layouts (1x1/2x1/2x2/custom)|Y (tiered 1–16/tab)|Y (Workspaces)|All|per-pane data feeds|Y|Must|No tier cap for us|
|312|Saved layouts/workspaces (persist across sessions)|Y (tiered 1–unlimited)|Y|All|app-layer persistence|Y|Must||
|313|Chart templates (indicators/styles saved per chart)|Y|Y|All|app-layer persistence|Y|Must||
|314|Sync axes: symbol/interval/crosshair/time/date-range across panes|Y|Not fully confirmed (compact/group view unresolved)|All|app-layer cross-pane state|Y|Must||
|315|Independent vs linked price scaling per pane|Y|Not confirmed|—|app-layer|Y|Should||
|316|Global configurable hotkey layer (single scheme across all views)|Y (fixed set + some customizable)|Y (Options→Settings→Shortcuts, user-defined, no confirmed defaults)|Bookmap/Sierra Chart|app-layer keymap config|Y|Must|Explicit design requirement (digest 23 cross-cutting notes)|
|317|Watchlist (symbol list w/ custom columns)|Y (tiered cap ~30–unlimited)|N (no crypto feature)|All|`/v5/market/instruments-info` + tickers WS|Y|Must||
|318|Symbol search (global type-ahead)|Y|Not documented|All|instruments-info REST|Y|Must||
|319|Watchlist/scanner columns (rel volume, funding, OI-Δ, volatility)|Partial (equities-oriented)|N|Coinglass screeners|tickers WS + OI/funding history|Y|Should||
|320|Compact/grouped multi-chart view|Not confirmed as distinct feature|Not confirmed (open question)|—|app-layer|Y|Could|Both TV and DeepCharts unclear on this — own design|
|321|Chart screenshot/export|Y|Not documented|All|canvas export|Y|Could||
|322|Emoji-tag chart grouping (alt sync mechanism)|Y|N|—|app-layer|Y|Won't|Cosmetic, low value|
|323|Theme (light/dark) + Demo/Live visual accent|Y (light/dark only)|Not documented|—|app-layer|Y|Must|Distinct Live=red-accented chrome per digest 23 #20|
|324|Responsive/mobile-friendly layout|Y (web=desktop parity unclear, no official matrix)|N (Windows-only desktop app)|—|CSS/responsive design|Y|Should|Build mobile-responsive from day one; don't chase undocumented TV parity (digest 01)|
|325|Countdown/live status indicators (connection health, feed lag)|Not confirmed|Not confirmed|—|WS heartbeat/ping monitoring|Y|Must|Critical given self-hosted single-connection architecture|

---

## M. Journal / analytics

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|326|Auto-logged trade journal (entry/exit/size/side/P&L)|N (community/3rd-party only)|Y (Performance Analysis/Strategy Reports)|3Commas/Cornix/Edgewonk|private `execution` WS + closed-pnl REST|Y|Must||
|327|Manual notes/tags per trade|N|Y (implied)|Edgewonk/TraderSync|app-layer|Y|Must||
|328|Auto-tagging (rule-source attribution)|N|Not explicit|—|rule engine linkage (#260)|Y|Should|Closes loop rule-fired↔trade-outcome (digest 09 §11)|
|329|Chart/DOM/footprint snapshot attached to trade|N|N|—|canvas snapshot + timestamp linkage to Replay|Y|Should||
|330|MAE/MFE tracking (max adverse/favorable excursion)|N|N|Edgewonk/TraderSync|tick/price history during trade lifetime|Y|Should|Evaluates stop-placement/TP-target quality|
|331|Aggregate stats: win rate, expectancy, R-distribution|Y (Strategy Report, backtest-only)|Y (Strategy Performance section)|3Commas/Edgewonk|closed-trade history|Y|Must||
|332|Equity curve / drawdown chart|Y (Strategy Report)|Y (Chart section)|All|closed-trade history|Y|Should||
|333|Time-based performance breakdown (by hour/day/month/session)|Y (Strategy Report Time Analysis)|Y|All|closed-trade history|Y|Should||
|334|Per-symbol / per-setup-tag performance breakdown|Y (Performance tab, Long/Short)|Y (Symbol Performance)|All|closed-trade history + tags|Y|Should||
|335|Journal export (CSV/PDF)|Y (CSV, via bar-loading limits not fixed cap)|Not confirmed|Edgewonk|closed-trade history|Y|Could||
|336|Replay-linked post-mortem (step back through trade against recorded state)|N|N|—|Replay Mode (#286) + journal timestamp linkage|Y|Should||
|337|Commission/funding-paid tracking per trade|Y (Strategy Report commission)|Not explicit|Freqtrade|execution WS + funding history|Y|Should||

---

## N. Multi-account / admin / security

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|338|Sub-account mapping (one Bybit sub-account per manager)|N (broker-side concept only)|N|3Commas/Cornix multi-exchange|Bybit sub-account creation (`create-sub-member`)|Y|Must|Cap: 5 (regular)/20 (KYC-business) (digest 06,12)|
|339|RBAC: Owner/Manager/Viewer roles|N|N|No retail bot platform documents fine-grained RBAC (gap)|app-layer auth|Y|Must|Genuine gap across all competitors — CandleViewer must design custom (digest 09 §10)|
|340|Per-manager risk limits set by Owner|N|N|3Commas (coarser)|app-layer config + private WS monitoring|Y|Must||
|341|Global Owner dashboard (all sub-accounts equity/P&L/risk)|N|N|3Commas (coarser)|multi-account private WS aggregation + wallet-balance REST|Y|Must||
|342|Owner kill-switch (instant freeze per manager)|N|N|—|app-layer trading-halt flag / key revoke|Y|Must||
|343|API key management UI (add/rotate/revoke)|N/A (broker-managed)|N/A|—|`create-sub-api`, `update-api`, `delete-api`|Y|Must||
|344|API key permission scoping (Order/Position/Wallet/Trade granularity)|N/A|N/A|—|`create-sub-api` permissions object|Y|Must|Withdrawal permission must stay OFF by design (digest 12 §2.1)|
|345|IP whitelist per API key|N/A|N/A|—|Bybit key IP-bind config|Y|Must||
|346|API key rotation policy (90/180-day cadence)|N/A|N/A|—|scripted create/delete key rotation|Y|Should|No forced expiry if IP-bound — self-enforced policy|
|347|API key IP/permission self-check (startup validation)|N/A|N/A|—|`GET /v5/user/query-api`|Y|Must|Refuse "trading" mode if withdrawal enabled (digest 12 §2.1)|
|348|Audit log (orders/logins/key changes, append-only)|N|N|—|app-layer append-only log store|Y|Must||
|349|2FA login (app-level, independent of Bybit's own 2FA)|N/A|N/A|—|TOTP implementation|Y|Must||
|350|Manager onboarding workflow (new sub-account + 48h API-key-creation wait)|N/A|N/A|—|Bybit sub-account creation flow|Y|Should|48h new-account restriction must be budgeted (digest 12 §1)|
|351|Withdrawal address whitelist (owner account hardening)|N/A|N/A|—|Bybit account setting (outside app)|Y|Must (advise)|~24h hold on new entries — app should surface reminder, not manage directly|
|352|Anti-Phishing Code (owner+manager)|N/A|N/A|—|Bybit account setting|Y|Must (advise)||
|353|Device/session management review|N/A|N/A|—|Bybit account setting|Y|Should (advise)||
|354|Tailscale-based remote access (no public internet exposure)|N/A|N/A|—|network/infra config|Y|Must||
|355|Encrypted-at-rest API key storage (envelope encryption, KEK outside DB)|N/A|N/A|—|app-layer crypto|Y|Must||
|356|Demo/Live environment isolation gating every trading-capable view|N/A|N/A|—|app-layer env flag + REST/WS host switch|Y|Must|Must gate Terminal, Positions/Orders, DOM click-to-trade, Rule Builder "Arm Live" (digest 23 cross-cutting)|
|357|Legal/compliance flagging (manager-as-authorized-individual, not reseller)|N/A|N/A|—|policy/process, not code|N/A|Must (process)|Counsel required before scaling beyond a few managers (digest 12 §4, open Q#7)|

---

## O. Data infrastructure

| # | Feature | TradingView | DeepCharts | Best competitor | Data needed | Bybit v5 feasibility | CandleViewer scope | Notes |
|---|---|---|---|---|---|---|---|---|
|358|Continuous WS recorder (trades, book deltas, liquidations, tickers)|N/A (TV doesn't expose this problem to users)|N/A|aggr-server/NautilusTrader|all public WS streams|Y|Must|Foundational — everything else depends on this running from day one|
|359|Local order-book reconstruction (snapshot+delta, u/seq tracking)|N/A|N/A|Bookmap/NautilusTrader|orderbook.{depth} WS|Y|Must|No checksum field on Bybit — must drop/resubscribe on desync (digest 06)|
|360|Historical bulk backfill via public CSV archive|N/A|N/A|—|`public.bybit.com/trading/{SYMBOL}/` CSV|Y|Should|Different timestamp units derivatives vs spot — parser must branch|
|361|Time-series storage (hot tier) for tick/L2/bars|N/A|N/A|QuestDB/TimescaleDB precedent|hot-tier DB (QuestDB recommended)|Y|Must||
|362|Cold-storage/archive tier (Parquet + DuckDB)|N/A|N/A|—|periodic roll-off job|Y|Should||
|363|Relational store for OMS/state (orders/positions/audit/config)|N/A|N/A|—|Postgres/SQLite|Y|Must||
|364|Data retention policy & pruning (tick 30-90d rolling, bars indefinite)|N/A|N/A|—|scheduled job|Y|Must||
|365|Single ingestion code path for live + historical replay|N/A|N/A|NautilusTrader (architecture reference)|shared normalization layer|Y|Must|Avoid dual logic between live/replay|
|366|Multi-exchange abstraction layer (Bybit-first, extensible interface)|N/A|N/A|Freqtrade/CCXT-style|`Exchange` interface pattern|Y|Should|Bybit-only impl v1, designed for future exchanges|
|367|Rate-limit self-throttling (token bucket off `X-Bapi-Limit-*` headers)|N/A|N/A|—|REST response headers|Y|Must||
|368|Reconnect/reconciliation logic (REST truth-check after WS gap)|N/A|N/A|—|`/v5/order/realtime`,`/v5/position/list`,`/v5/execution/list`|Y|Must||
|369|Clock sync (NTP) + server-time-offset fallback|N/A|N/A|—|`/v5/market/time` + chrony/ntpd|Y|Must|Critical given WSL clock drift risk (digest 11)|
|370|Symbol/instrument metadata cache (tick size, leverage tiers, funding interval)|N/A|N/A|—|`/v5/market/instruments-info`, versioned|Y|Must||
|371|WS subscription batching (≤10 topics/request) + reconnect backoff|N/A|N/A|—|WS client design|Y|Must||
|372|Storage sizing instrumentation (measure real GB/day, not estimates)|N/A|N/A|—|recorder telemetry|Y|Should|Planning estimates ~1-3TB/yr unverified — must measure early|
|373|Binary/compact wire format for frontend fan-out (MessagePack upgrade path)|N/A|N/A|—|internal WS/SSE protocol|Y|Could|JSON initially, MessagePack as identified upgrade (digest 10)|
|374|Deployment: WSL Ubuntu (dev) → dedicated small server (prod)|N/A|N/A|—|infra|Y|Must||

---

## Summary — counts per scope

| Scope | Count |
|---|---|
| Must | 149 |
| Should | 118 |
| Could | 79 |
| Won't | 28 |
| **Total rows** | **374** |

*(Counts are approximate hand-tally across all 15 domain tables; re-derive precisely via spreadsheet/grep if exact figures are needed for planning docs.)*

---

## "Must" list grouped by domain

**A. Chart types & bar types** — Candlestick; OHLC/Bar; Line; Volume bars (new bar/volume threshold); Tick/Trade bars; Volume Footprint chart; Session Volume Profile chart.

**B. Scales/sessions/timeframes** — Log scale; Linear scale; Auto-fit/manual scale; Countdown to bar close; Day boundary redefinition (UTC anchor); Multiple timeframes per symbol; Historical bar depth (unlimited, self-hosted); Session VWAP anchor options; Days-to-load control.

**C. Drawing tools** — Trendline; Horizontal line; Anchored VWAP; Fibonacci retracement; Rectangle; Text/Note annotation; Long/Short position sizing tool; Undo/redo.

**D. Indicators (classic)** — SMA; EMA; Supertrend; Zig Zag; RSI; MACD; Bollinger Bands; ATR; ADX; Volume histogram; CVD (classic form); Per-chart indicator limit (uncapped).

**E. Order-flow views** — Footprint (Volume/Bid-Ask/Delta modes); Footprint Profile & Box display; footprint input types (Volume/agg); footprint delta/imbalance coloring; diagonal & stacked imbalance detection; Bar POC; Volume Profile (session/fixed/composite) + POC + Value Area; Delta Profile; Deep Stats row (Total/Bid/Ask/Delta/Cum Delta/# Trades); Time & Sales/Tape; Big Trades highlighting + bubble plotting + clustering; Speed of Tape; CVD (session-reset, display modes); multi-bar CVD divergence detector; DOM ladder; DOM click-to-trade; DOM liquidity heatmap + adaptive color scale; Absorption detector; Stop-run/liquidity sweep detector; Market Regime classifier; Imbalance Tracker panel; VWAP; Anchored VWAP (true click-anchor).

**F. Crypto data** — Open Interest (current+history); Funding rate (current+history+countdown timer); Liquidations feed; Liquidation bars (long/short split).

**G. Trading/order entry** — Market/Limit/Stop/Stop-Limit/Conditional orders; TIF GTC/IOC/FOK; Reduce-Only; TP/SL attach (order+position); Trailing stop (fixed + %-translated); OCO (emulated); Bracket order; Order-from-chart; Drag order/TP-SL to reprice; Flatten button; One-click trading arm/lock; Hotkeys (buy/sell/size/flatten/cancel-all); Quantity presets; Risk-based position sizing; One-Way position mode; Leverage control; Margin mode Cross/Isolated; Positions & Orders panel; Partial close; Order history/execution marks; L2/DOM feed integration; Instrument precision validation.

**H. Risk automation/rules** — Rule-based trailing stop; ATR-based trailing stop; Breakeven-at-R-multiple; Custom rule builder; Rule condition combinators; Max daily loss lockout; Rule DSL metric + action vocabularies; Simulate-only vs live-armed mode; Dead man's switch; Per-manager risk limits; Owner kill-switch.

**I. Paper trading** — Simulated order ticket vs real-time data; Bybit demo REST+WS integration; Paper P&L tracking; Live/paper switch; Order-book/slippage-aware fill (via Bybit demo engine).

**J. Replay/backtest** — Bar-by-bar replay; Replay speed control; Simulated trading during replay; Empty/partial-history state handling.

**K. Alerts** — Price alert; Technical/indicator alert; Order-flow-derived alert; Non-expiring alerts; In-app toast delivery.

**L. Layouts/UX/hotkeys** — Multi-chart grid layouts; Saved layouts/workspaces; Chart templates; Sync axes across panes; Global configurable hotkey layer; Watchlist; Symbol search; Theme + Demo/Live accent; Countdown/live status indicators.

**M. Journal/analytics** — Auto-logged trade journal; Manual notes/tags; Aggregate stats (win rate/expectancy/R-distribution).

**N. Multi-account/admin/security** — Sub-account mapping; RBAC; Per-manager risk limits; Global Owner dashboard; Owner kill-switch; API key management UI; API key permission scoping; IP whitelist per key; API key self-check; Audit log; 2FA login; Withdrawal address whitelist (advise); Anti-Phishing Code (advise); Tailscale remote access; Encrypted-at-rest key storage; Demo/Live isolation gating; Legal/compliance flagging (process).

**O. Data infrastructure** — Continuous WS recorder; Local order-book reconstruction; Time-series hot-tier storage; Relational OMS/state store; Data retention policy; Single live+replay ingestion path; Rate-limit self-throttling; Reconnect/reconciliation logic; Clock sync (NTP); Symbol/instrument metadata cache; WS subscription batching; Deployment (WSL→server).

---

## Cross-cutting caveats (apply to all rows)

1. No Bybit L3/MBO feed exists — every "Order" input-type, true iceberg detection, cumulative stop/iceberg tracker, and Big Passive Trade feature is capped at heuristic/MBP-proxy fidelity (marked Partial/N above) and must carry an "(estimated)" UI badge, per digest 23.
2. All order-flow/footprint/profile/heatmap depth is bounded by however long CandleViewer's own recorder has been running — there is no way to backfill deep historical L2/tick data from Bybit beyond small REST windows.
3. Options/GEX/on-chain features are explicitly out of v1 scope per project brief (crypto-only, Bybit-first) and are scoped Won't/Could-later even where DeepCharts (DeepGamma) or competitors (Laevitas, CryptoQuant) support them.
4. DeepCharts trademarked names ("Deep Print," "DeepDOM," "DeepGamma," etc.) must not be reused in UI/code — use generic internal names ("Footprint Chart," "DOM Heatmap," "Volume Profile," "Big Trades").
5. Native Bybit API gaps that must be emulated client-side: Iceberg order type, TWAP, true derivatives OCO, %-based trailing stop (Bybit trailing stop is price-distance only).
6. TradingView tier-gating limits (chart/indicator/alert/replay caps) are structurally moot for a private self-hosted tool and are marked "Must (moot)" or similar where the underlying feature itself is still wanted uncapped.
