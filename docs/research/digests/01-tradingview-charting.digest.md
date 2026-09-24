# Digest: 01-tradingview-charting.md

Source last researched 2026-09-13. Re-verify numbers live at tradingview.com/pricing before relying on them.

## Chart types (20+ marketed; 17 Basic/Essential/Plus, 21 Premium/Ultimate)
Time-based classic: Line, Line w/markers, Step line, Area, HLC area, Baseline, Bar(OHLC), High-low, Candlestick, Hollow candlestick, Volume candlestick, Heikin Ashi, Column.
Price-based: Renko, Line break, Kagi, Point&Figure, Range bars — none work on tick intervals; intraday variants gated Plus+.
Indicator-based: Volume footprint (Premium+, launched 2024-05-14), Session Volume Profile (Essential+ entitlement), TPO/Market Profile (Plus+).
- Volume footprint settings: row size (Auto=0.2×Normalized ATR, or manual tick), display mode (Cluster/Profile), 4 content types (bid/ask/delta/vol%), togglable labels, per-side POC, Info Box or Table summary; intrabar granularity coarsens further back in history.
- Seconds intervals: 1/5/10/15/30/45s, Premium/Ultimate only; data from Aug 2022; ~2wk/~10K bars history (unconfirmed secondary figure).
- Tick intervals: Ultimate only, 7-day depth; Renko/Kagi/LineBreak/P&F excluded.
- Compare tool: overlay w/ forced % Y-axis. Add Symbol/Overlay: shared %, independent scale, or new pane. Ratio/spread symbol syntax (e.g. BTCUSDT/ETHUSDT). MTF via Pine `request.security()`.
- Feasibility: all standard chart types trivial to replicate (public formulas); footprint/order-flow needs own Bybit tick/orderbook pipeline (CandleViewer's own data access removes TV's tier-gating constraint).

## Drawing tools (110+ marketed)
Trend: Trendline, Arrow, Ray, Info line, Extended line, Trend angle, Horizontal line/ray, Vertical line, Crossline, Anchored VWAP.
Channels: Parallel, Regression trend, Flat top/bottom, Disjoint.
Gann/Fib: Fib retracement/extension/channel/time zone/speed resistance fan/time/circles/spiral/arcs/wedge, Pitchfan, Gann box/square fixed/square/fan.
Pitchforks: Andrews, Schiff, Modified Schiff, Inside.
Shapes: Brush, Highlighter, Rectangle, Rotated rectangle, Circle, Ellipse, Triangle, Arc, Path, Curve, Double curve, Polyline.
Annotation: Text, Note, Anchored note, Signpost, Callout, Comment, Price label, Price note, Table, Arrow marker (+4 directions), Flag mark, Pin.
Patterns: XABCD, Cypher, ABCD, Triangle, Three drives, Head&shoulders, Elliott impulse/triangle/triple combo/correction/double combo waves, Cyclic lines, Time cycles, Sine line.
Predictions/measurement: Long/Short position, Position forecast, Bars pattern, Projection, Date range, Price range, Date&price range, Ghost feed, Sector, Fixed range volume profile, Anchored volume profile.
Icons/stickers/emoji (Twemoji v13.0), paste X/Twitter posts onto chart.
Cursor modes: Regular, Crosshair, Measure (drag), Zoom-in.
Feature set: Magnet (weak/strong), Lock (individual/all), Stay-in-drawing-mode, Hide all, Object tree, Per-timeframe visibility, Templates (save/apply/bulk), Bulk color change, Cross-chart sync (multi-layout), Favorite tools pin, Custom restrictions (Advanced Charts white-label only), Drawing API (Advanced Charts), Reverse position, Undo/redo.

## Indicators
- Marketing: "400+ pre-built" + "100K+ community." Actual Help Center catalog: **~195 distinct built-in titles** (209 articles in folder minus ~5 non-indicator companion/conceptual articles, e.g. funding-rate guide, liquidation-data guide).
- Per-chart limits by tier (Basic/Essential/Plus/Premium/Ultimate): Indicators 2/5/10/25/50; Indicator-on-indicator 1/1/9/24/49; Financials-per-chart 1/4/7/10/25.
- Custom indicator templates: gated, exact tier not confirmed.
Trend/MA built-ins: ALMA, DEMA, EMA, Hull MA, KAMA, Least Squares MA, MA Cross, McGinley Dynamic, MA Ribbon, Moving Averages, MovingAvg Cross, MovingAvg2Line Cross, SMA, SMMA, Triple EMA, TRIX, VWMA, WMA, Linear Regression, Ichimoku Cloud, Parabolic SAR, Supertrend, Williams Alligator, Williams Fractal, Zig Zag, Trend Strength Index, Vortex.
Oscillators/momentum: AO, BOP, BBTrend, Bull Bear Power, CMO, Coppock Curve, CCI, Connors RSI, DPO, Fisher Transform, Klinger Oscillator, KST, MACD, Mass Index, Momentum, PPO, PMO, Pring's Special K, RCI (+Ribbon), ROC, RSI (+divergence), Relative Vigor Index, SMI Ergodic (Indicator/Oscillator), Stochastic, Stochastic Momentum Index, Stochastic RSI, True Strength Index, Ultimate Oscillator, Williams %R, Woodies CCI.
Volatility: ADR, ATR, Bollinger Bands (+%b, +BandWidth, +Bars), Chande Kroll Stop, Chandelier Exit, Choppiness Index, Historical Volatility, Keltner Channels, Relative Volatility Index, Ulcer Index, Volatility Stop, Donchian Channels, Envelope.
Volume/order-flow-adjacent: 24h Volume, ADL, Chaikin Money Flow, Chaikin Oscillator, Cumulative Volume Delta, Cumulative Volume Index, Ease of Movement, Elder's Force Index, Klinger, MFI, NVI, Net Volume, OBV, PVI, PVT, Relative Volume at Time, Up/Down Volume, Volume, Volume Delta, VWAP, TWAP, Visible Average Price, VWAP Auto Anchored.
Directional/trend-strength: ADX, DMI, Chop Zone, Aroon Indicator/Oscillator.
Auto-drawn tools (shipped as indicators): Auto Fib Extension/Retracement, Auto key levels, Auto Pitchfork, Auto Trendlines, Pivot Points High Low/Standard, Technical Ratings, Seasonality, Correlation Coefficient, Median, Performance, Rob Booker suite (ADX Breakout, Knoxville Divergence, Intraday Pivot Points, Missed Pivot Points, Reversal, Ziv Ghost Pivots), Trading Sessions, Moon Phases, Power-Law Model, Multi-Time Period Charts.
Breadth: Advance/Decline Line, Ratio, Ratio(Bars).
Fundamental: Analyst price forecast, Dividend Yield, Price target, Premium.
Crypto on-chain/on-exchange (directly relevant to CandleViewer): Funding rate [verified], Open Interest [verified], Liquidation data [verified], Long/Short Ratio (Accounts/%), Top trader long/short (accounts+positions+ratios), Basis, Mark price, Index price, Hash Rate, Difficulty, Block height, Blocks mined, Created/Spent UTXOs (+ full mean/median on-chain stats family: block interval/size, gas used/limit/price, tx fees/size, transfer volume), Active addresses w/contracts, Addresses w/balance≥X (%/USD), Held tokens in addresses≥X, 1yr active supply%, Realized market cap, Receiving/Sending addresses, SOPR, Stock-to-Flow Ratio USD, Supply Equality Ratio, Large transaction volume, Transaction fees/rate, Transfer count/rate, Total block size/gas/tx size/UTXOs, ETF balances/flows (incl. US spot crypto), Ethereum deposits/depositors/staked value stats, El Salvador Gov't balance, Average transaction volume.
- **CandleViewer takeaway**: on-chain/on-exchange metrics (funding rate, OI, liquidation, long/short ratio) map directly onto Bybit REST endpoints — cheap to replicate. Classic TA = public formulas, treat as backlog checklist not research.

### Volume Profile / order-flow family
| Item | Notes | Gate |
|---|---|---|
| Fixed Range Volume Profile | manual range, POC/VAH/VAL | Essential+ |
| Session Volume Profile | per-session auto | Essential+ |
| Session Volume Profile HD | higher-res variant | Premium/Ultimate-leaning |
| Periodic Volume Profile | configurable period | paid |
| Visible Range Volume Profile | recalcs to visible range | paid |
| Auto Anchored Volume Profile | anchors to swing/pivot | paid |
| Anchored VWAP (drawing) | manual anchor + stdev bands | all tiers (drawing tool) |
| Session VWAP (indicator) | resets per session | broad |
| Volume Delta | per-bar buy-sell diff, oscillator | via `ta.requestVolumeDelta()` |
| Cumulative Volume Delta (CVD) | cumulative delta, own candle series, configurable anchor | confirmed first-party built-in |
| TPO | chart type + indicator view | Plus+ |
- CVD/Volume Delta/Footprint are all first-party (not community-only); no native per-price-level delta indicator exists outside the Footprint chart type itself.

## Pine Script
- Proprietary scripting language, gated feature (Essential+ typically).
- Strategy backtesting: basic vs advanced report metrics, CSV/XLSX export, Deep backtesting — separate gated rows, escalating Essential→Ultimate (deep backtesting Ultimate-exclusive).

## Auto pattern recognition
- Auto chart patterns (Plus/Premium+, cutoff unconfirmed).
- Candlestick pattern recognition (separate gated row).
- Auto Fib retracement (auto swing detection).

## Chart settings
Price scale types: Regular(linear), Log, Percentage, Indexed-to-100. Auto/lock scale. Multiple price scales (independent L/R or overlay). Sessions/Extended trading hours (paid-gated). Timezones (exchange or local). Countdown to bar close. Symbol info overlay. Bar replay (see below). Compare/overlay symbols. Custom time intervals (paid-gated). Second-based intervals (Premium/Ultimate). Tick-based intervals (Ultimate, BETA at times). Spread/custom-formula intraday charts (paid-gated).

## Bar Replay
- Single-chart and Multi-chart/"All charts" sync mode (launched ~Sept 2024); larger-interval charts wait on smaller ones to stay aligned.
- Session restore: symbols/intervals/last bar/state persist; chart style not saved; only replay-capable chart types restore.
- Minute-replay depth formula (official, corrects old flat-day figures):
  - Basic: none (daily+ only)
  - Essential: months ≈ 6 × interval-minutes (1min→6mo, 15min→90mo)
  - Plus: years ≈ 1 × interval-minutes (1min→1yr, 15min→15yr)
  - Premium/Ultimate: all stored data
  - Tick Replay: Ultimate-only, 7 days
- Second-based data stored from Aug 17 2022 (earliest replayable second-bar).
- Workaround for deep intraday: start replay at higher interval, then switch down.
- "Select first available day" jumps to earliest replayable bar. Continuous futures symbols exempt from depth caps.
- Hotkeys: Shift+↓ play/pause, Shift+→ step forward.
- Indicators Replay & Trading-in-Bar-Replay are separate gated rows.

## Layouts / multi-chart / watchlists / symbol search / hotkeys / alerts
- Charts per tab: 1/2/4/8/16 (Basic/Essential/Plus/Premium/Ultimate). Advanced Charts (embeddable library, different product): up to 8/layout — do not conflate with 16-chart web app figure.
- Saved layouts: 1/5/10/unlimited/unlimited.
- Sync axes: Symbol, Interval, Crosshair, Time, Date range (toggle via Select Layout). Separate drawing-sync toggle (same-symbol charts only). Emoji-tag chart grouping = finer-grained alt sync mechanism.
- Watchlists: Basic=1 (cap ~30 symbols, third-party-sourced), paid tiers "multiple" but no official numeric cap found (open question). Custom columns/sorting. Import/export (gated). Flag colors: 1(Basic)/7(paid). Watchlist alerts: 0/0/0/2/15 (Basic→Ultimate).
- Symbol search: global type-ahead; Compare/overlay entry point.
- Hotkeys: `/` Pine editor, `.` load layout, Ctrl+S save layout, type-to-search symbol, `,` or digits/letters change interval, Alt+A alert, Alt+N note, Alt+S snapshot; zoom scroll up/down, arrows pan (Ctrl+arrow = bigger jump), Alt+G go to date; Shift+B/S market buy/sell; watchlist ↓/Space next, ↑/Shift+Space prev, Alt+Enter flag, Ctrl+A/Shift+↓/↑ select; screener same pattern; Ctrl+C/V/Delete for scripts. Desktop app OS-level shortcuts also documented (tab/window mgmt).
- Alerts: Price 3/20/100/400/1000, Technical 0/20/100/400/1000 (Basic→Ultimate). Watchlist alerts separate quota (above). Second-based alerts paid-gated. "Alerts that don't expire" gated feature (unverified secondary source).
  - 3 alert categories: Price (Crossing/Up/Down, Greater/Less Than, Entering/Exiting Channel), Indicator (same vocabulary on indicator outputs), Drawing-tool (price touching drawn object). Trigger freq: Once / Once Per Bar / Once Per Bar Close. Editing underlying object doesn't retroactively update alert.
  - Webhook alerts: HTTP POST to user URL; JSON body → Content-Type application/json else text/plain. Restrictions: **ports 80/443 only, no IPv6, 3s timeout, 2FA required**. Other channels: in-app popup, browser/desktop push, mobile push, email, SMS (region/tier-gated, unconfirmed).
- Screenshots/export:
  - Chart image: camera icon → Download/Copy Image (PNG). **No custom-resolution/DPI export** — resolution = current on-screen render only.
  - CSV/OHLCV chart-data export: Pro+/Premium-tier+ (exact floor unconfirmed). Only exports bars currently loaded (not full history); includes OHLCV + visible indicator values; excludes drawings. ISO or Unix timestamp choice.
  - Pine Strategy backtest CSV/XLSX export is a separate, higher-gated feature.
- Screener: Stock/Forex/Crypto/ETF/Bond; click-through row→chart with full drawing/indicator retained; custom/Pine columns supported (column-count limits per tier unconfirmed). `tradingview-screener` PyPI package exists for programmatic access. CandleViewer scoping: full screener likely out of scope (single-exchange), but click-through-to-chart UX pattern reusable for watchlist/positions list.
- Templates: chart layout templates (full workspace state), indicator templates (input+style defaults), drawing templates (style, bulk apply).

## Per-tier limits table (Basic/Essential/Plus/Premium/Ultimate)
| Metric | Basic | Essential | Plus | Premium | Ultimate |
|---|---|---|---|---|---|
| Price/mo (annual) | $0 | ~$12.95 | ~$29.95 | ~$59.95 | ~$199.95 |
| Charts/tab | 1 | 2 | 4 | 8 | 16 |
| Saved layouts | 1 | 5 | 10 | unlimited | unlimited |
| Indicators/chart | 2 | 5 | 10 | 25 | 50 |
| Indicator-on-indicator | 1 | 1 | 9 | 24 | 49 |
| Financials/chart | 1 | 4 | 7 | 10 | 25 |
| Parallel data connections | 2 | 10 | 20 | 50 | 200 |
| Historical intraday bars | 5K | 10K | 10K | 20K | 40K |
| Minute replay depth | none | 6×interval mo | 1×interval yr | all | all |
| Second data | — | — | — | all | all |
| Tick data | — | — | — | — | 7 days |
| Price alerts | 3 | 20 | 100 | 400 | 1,000 |
| Technical alerts | 0 | 20 | 100 | 400 | 1,000 |
| Watchlist alerts | 0 | 0 | 0 | 2 | 15 |
| Watchlists | 1 (30 sym cap) | "multiple" (no official count) | same | same | same |
| Portfolios | 1 | 3 | 4 | 5 | 7 |
| Flag colors | 1 | 7 | 7 | 7 | 7 |
| Active contests | 0 | 3 | 5 | 10 | 25 |
| Volume Profile | — | ✓ | ✓ | ✓ | ✓ |
| Volume footprint | — | — | — | ✓ | ✓ |
| TPO | — | — | ✓ | ✓ | ✓ |
| Volume candles | ✓ | ✓ | ✓ | ✓ | ✓ |
| Bar Replay | — | ✓ | ✓ | ✓ | ✓ |
| Trading in Bar Replay | — | — | — | ✓(inferred) | ✓ |
| Custom time intervals | — | ✓ | ✓ | ✓ | ✓ |
| Second intervals | — | — | — | ✓ | ✓ |
| Tick intervals | — | — | — | — | ✓ |
| Intraday Renko/Kagi/LB/P&F | — | — | ✓ | ✓ | ✓ |
| Chart types (count) | 17 | 17 | 17 | 21 | 21 |
| Extended trading hours | — | ✓ | ✓ | ✓ | ✓ |
| Auto chart patterns | — | — | ✓(inf) | ✓ | ✓ |
| Candlestick pattern recog | — | ✓(inf) | ✓ | ✓ | ✓ |
| Deep backtesting | — | — | — | — | ✓ |
| Max market-data subs | — | 2 | 4 | 6 | more(truncated) |
| Ads | shown | none | none | none | none |
Many "—/✓/inferred" cells are reconstructed from ambiguous scraped checkmarks — flagged as approximate.

## Mobile parity
- No official parity matrix exists (confirmed genuine gap, not just a research gap).
- Web/desktop app = same codebase (Electron wrapper); "identical" per third-party source. Mobile app parity unaddressed officially.
- Anecdotal iOS complaints: watchlist load 20–30s for 10 symbols; can't multi-add symbol across watchlists from chart screen.
- Home-screen widgets = separately gated paid feature.
- CandleViewer takeaway: build React frontend mobile-responsive from day one; don't chase an undocumented TV parity contract.

## TradingView vs. DeepCharts gap analysis (Section 10)
| DeepCharts feature | TV equivalent | Verdict |
|---|---|---|
| Footprint/Deep Print | Volume footprint (Premium+) | Partial — reconstructed intrabar data, not raw tape |
| DeepDOM (liquidity heatmap) | Only basic DOM ladder row, no heatmap found | Gap |
| DeepGamma (options gamma) | None (crypto-only scope anyway) | Gap (out of scope) |
| Deep Profile/Stats | Volume Profile family covers viz; no stats-panel equivalent | Partial |
| Big Trades / large-print | None built-in; only community whale scripts | Gap |
| Imbalance tracker | Footprint has imbalance lines, but scoped to that chart type only | Partial |
| Speed of tape | None found | Gap |
| VWAPs | Anchored VWAP + Session VWAP confirmed | Covered |
| Stoprun/iceberg detector | None; community heuristics only | Gap |
| Market regime | No first-party classifier; ADX/ATR/Bollinger/Keltner are building blocks; community Pine scripts only | Gap |
| Tick replay/backtester | Tick Replay (Ultimate, 7d) + Pine Strategy backtest exist but are separate, not unified | Partial |
| Trading terminal | Broker-integrated chart trading + DOM row exist; not deep-dived | Not assessed |
| Auto-tracker journal | Not found | Gap |
**Conclusion**: TV good baseline for charting UX/VWAP/Volume Profile conventions; no substitute for DOM/tape/regime layer — CandleViewer must build directly against Bybit WS trade/orderbook feeds for order-flow depth.

## Key numeric limits recap
- Chart types: 17 (Basic/Ess/Plus) vs 21 (Premium/Ultimate).
- Indicators/chart: 2/5/10/25/50. Indicator-on-indicator: 1/1/9/24/49. Financials/chart: 1/4/7/10/25.
- Charts/tab: 1/2/4/8/16 (web); 8 max (Advanced Charts library, different product).
- Saved layouts: 1/5/10/∞/∞.
- Historical intraday bars: 5K/10K/10K/20K/40K.
- Parallel data connections: 2/10/20/50/200.
- Alerts: price 3/20/100/400/1000; technical 0/20/100/400/1000; watchlist 0/0/0/2/15.
- Portfolios: 1/3/4/5/7. Flag colors: 1/7/7/7/7. Contests: 0/3/5/10/25.
- Seconds intervals: 1/5/10/15/30/45s (Premium/Ultimate only), data since Aug 2022.
- Tick data: 7 days, Ultimate only.
- Webhooks: ports 80/443 only, no IPv6, 3s timeout, 2FA required.
- Built-in indicator catalog: ~195 titles (vs "400+" marketing claim).
- Chart types marketed: "20+"; drawing tools marketed: "110+"; indicators marketed "400+ pre-built / 100K+ community."
- Bar replay minute depth: Essential = 6×interval(min) months; Plus = 1×interval(min) years; Premium/Ultimate = all.

## Open questions (unresolved)
1. Exact tier cutoffs for several gated rows (Bar Replay on Basic, Trading-in-Bar-Replay, Auto chart patterns, Candlestick pattern recognition, Custom indicator templates, watchlist count/tier) — scraped checkmarks render ambiguous; needs visual/API re-check.
2. ~~Full indicator catalog~~ RESOLVED (~195 titles, Section 3.2); "400+" marketing figure not fully reconciled.
3. ~~Mobile parity~~ PARTIALLY RESOLVED — no official parity matrix exists at all (genuine TV-side gap).
4. DOM/Depth-of-Market feature depth (ladder controls, heatmap depth) — needs dedicated follow-up doc.
5. ~~Bar Replay minute-depth per tier~~ RESOLVED via official formula (Section 5).
6. Advanced Charts "8 charts/layout" vs web app "16 charts/tab" — confirmed different products; exact relationship/version parity unexplored; Advanced Charts more relevant as architecture reference (Drawings API, multi-pane).
7. "Equivolume" chart type — seen in unrelated third-party project, NOT confirmed as ever a TV feature; avoid false attribution.
8. Indicators-per-chart/indicator-on-indicator figures (2/5/10/25/50, 1/1/9/24/49) — corroborated by multiple third-party 2026 sources but never an official primary-source screenshot; treat as highly-likely-correct but not fully verified.
9. Exact number of watchlists per paid tier — genuine gap on TV's own public page (only "Multiple watchlists" checkmark, no number); Basic=1 confirmed.
10. Screener column-count limits per tier, and SMS notification channel region/tier gating — unconfirmed.
11. DeepCharts' own feature depth — this doc only researched the TV side; a dedicated DeepCharts research doc needed for rigorous Section 10 gap verdicts.
