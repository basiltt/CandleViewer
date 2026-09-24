# Digest: 04-deepcharts-deepchart.md

Source: DeepCharts (Volumetrica engine) — Deepchart/DeepDOM feature inventory. Research date 2026-09-14.

## Pricing tiers
- DeepCharts Orderflow — $59/mo ($708/yr) — Big Trades, Deep Print, Deep Profile, CVD, Deep Stats, Imbalance Tracker, Speed of Tape.
- DeepCharts Full Advanced — $79/mo ($948/yr) — adds premium studies.
- DeepCharts Pro — $100/mo (list $125, -20%, $1200/yr) — full bundle: DeepGamma Pro/Classic, Deep Effort, Deep Trades, Deep V-Tracker, Pattern Builder & Auto-Backtester, DeepDom (3-mo trial).
- DeepDOM standalone — $39/mo (~$468/yr) — Heatmap Liquidity Tracker, DOM trading.
- Bundle (Deepchart+DeepDOM) — $1,599/yr — + Orderflow Mastery Course + VIP Discord + Liquidity Bootcamp; Windows only.
- Note: Deep Swing Profile & Deep-M IVB listed separately under "Deep Models & Proprietary Tech" (available across paid tiers), not Pro-exclusive.

## Price chart settings
- Chart types: Candlestick, Bar/OHLC, Line, Equi-Volume Bars, Delta-Volume Bars.
- Bar modes: Time (sec/min/day/week/month), Range, Volume, Tick/Trades, Renko (fixed or ATR brick), Point & Figure.
- Params: Days to Load, Continuous Contract + Rollover Basis (date/volume/price-adjusted, futures-only), ETH session toggle, Countdown Timer to bar close.
- Delta Bars: new bar on cumulative delta threshold hit.

## 1. Deep Print (Footprint®)
- Type (cell data): Volume, Ask/Bid Split, Delta, Delta+Total Volume.
- Mode: Profile (histogram) or Box (numeric).
- Input Type: Volume, Aggregate Volume, Order, Num Trades.
- Filters: Min/Max value filter (noise suppression).
- Coloring: bg/text by Delta or Imbalance thresholds.
- Diagonal imbalance detection: aggressive ask vs. one-tick-below bid, green/red.
- Bybit: Buy/Sell+price/qty stream covers Volume/Delta/Bid-Ask-Split. "Order" input needs L2 order-arrival counting — Bybit orderbook.50/200 gives depth snapshots/deltas, not per-order (no L3/MBO) — approximate only.

## 2. Deep Stats
- Per-bar stats: Total Volume, Bid Volume, Ask Volume, Delta, Max Delta, Min Delta, Delta %, Cumulative Delta, Number of Trades.
- Bybit: fully derivable from public trade stream.

## 3. Deep Profile (Volume/Delta Profile)
- VBP Period: Composite, Multiples, Visible, Personalized.
- Length Type/Value: minutes/days/weeks/months or volume-unit count.
- Input Data: Volume, Order, Aggregate Trades, Number of Trades.
- Plotted: Volume POC, Value Area (~70%), VWAP+stdevs, Peaks/Valleys (HVN/LVN proxy).
- Splitting: composite/session/custom.
- Open Q: naked/prior-session POC persistence not itemized explicitly.
- Bybit: computable client-side from trade history; historical depth limited by REST recent-trades lookback → needs local tick DB.

## 4. Big Trades (= Deep Trades, confirmed same feature; legacy alias)
- Data Settings: Days to Load, Input Type (Volume/Order/Aggregate Volume/Num Trades), Filter Mode Manual (Min/Max size) or Automatic (Big Trades Analysis algo, Intensity Level Low/Med/Strong, one-off cached run via Options→Tools→Big Trades Analysis).
- Plot — General: Marker Type (Circle/Square/Diamond/Text), Hollow Fill.
- Plot — Size: Standard Deviation scaling, Min/Max Size px.
- Plot — Color: Min/Max Opacity, Ask Color, Bid Color.
- Plot — Text: Plot Only Inside Bar, Text Size/Color (Text marker mode only).
- Zones — General: Biggest Only.
- Zones — Shadow Mode (wick trades): All/Reverse Only/Trend Only/None.
- Zones — Body Mode (body trades): same 4 options.
- Zones — Color: Bid/Ask Color, Opacity.
- Alert Settings: Enable Alert Sound, Bid Alert, Ask Alert.
- Premium: MBO data, iceberg detection, print-stitching aggregation.
- Bybit: trade size+side → bubbles fully replicable; iceberg/MBO aggregation not possible (no L3); heuristic-only via repeated same-price/side prints.

## 5. Imbalance Tracker
- Settings: Imbalance-minimum %, Minimum volume-difference, Include zero on imbalance, Min. no. of consecutive imbalances, Number bars-extension, Line thickness, Coloring, Display duration.
- Virgin Zone: untouched high-imbalance zone = future price magnet; Zone Crossed state (Show zone-crossed, Signal-only-touch) on retest.
- Related but distinct: Imbalance Rejector, Session Imbalance (not fully covered).
- Bybit: fully derivable from trade+side stream.

## 6. Unfinished Auction
- Settings: color, rectangle toggle, background opacity, volume filter threshold.
- Flags bar high/low where opposing aggression incomplete; rectangle marker, magnet reference.

## 7. Bar POC
- Intrabar point of control (highest-volume price level within one footprint bar).

## 8. Speed of Tape (+ "Instant" variant)
- Input Data: Volume, Order (order count) — confirmed; "Trades" as 3rd type unconfirmed.
- Filters: Filter Min/Max, Number of Seconds (rolling window), Std Dev Per Filter.
- Style: Bull/Bear Border+Fill, Line style/width, Short Name.
- Open Q: exact distinction Standard vs. Instant variant not confirmed.

## 9. VWAP & Envelopes
- Two related articles: "VWAP" (base line+bands) and "VWAP Envelopes" (multi-band 1/2/3 STD).
- Envelope/Band Mode: Standard Deviation or Percentage change in price.
- Envelope params: multipliers for 1st/2nd/3rd bands (~68/95/99.7% coverage) or fixed %.
- Display: per-band color/line style/width/bandwidth, show/hide.
- Open Q: "Period Mode: Day/Minutes/Seconds/Orders" anchor unconfirmed; true click-to-anchor VWAP (arbitrary bar) unconfirmed — may only support fixed period/session resets.
- Bybit: fully derivable from trade data.

## 10. Cumulative Volume Delta (CVD)
- Display modes: Candlestick, Histogram, Line.
- Related: Delta Cumulative Candlestick, Delta Cumulative Histogram, Delta Bar (single-bar), Delta % Highlight, Divergence Detector (price/delta divergence labels).

## 11. Market Profile (TPO) — resolved
- Periods (default 30 min) → sequential letters A→Z; shown alongside Volume Profile.
- TPO Base Minute (default 30, customizable).
- TPO Type: Blocks or Profile (continuous histogram).
- Period TPO: Composite / Multiples / Custom.
- Length Type/Value: minutes/days/weeks/months (for Multiples/Custom).
- Split TPO: None / Last / Every.
- Custom Date/Time picker (Period TPO=Custom).
- Background "Third Range": highlights C-period range (IB-equivalent window).
- Standard MP concepts (industry, not DC-specific): POC (letter-count), Value Area (~70%), Initial Balance (first N periods, typically A+B), single prints (naked/thin), D/P/b-profile shapes.
- Data needed: timestamp+price only (no volume/side).
- Crypto note: no natural RTH open/close in 24/7 markets — day-boundary (e.g. UTC 00:00) must be redefined.

## 12. Deep-M Effort
- Proprietary trend/orderflow-bias model by Fabio Valentini ("Fabervaale"), pre-tuned for NQ 40-Range chart.
- Green = bullish path of least resistance, purple = bearish; dynamic chart-specific MA for confirmation; alert on bias shift; minimal config.
- Instrument-tuned; portability to crypto needs recalibration; algorithm proprietary/undocumented.

## 13. Deep-M IVB
- Algorithmic ORB ("Instrumented" Opening Range Breakout) tool, also by Fabervaale.
- Automated opening-range calc, predefined projection/protection levels, reaction zones, daily bias summary.
- Crypto: no single daily RTH opening range in 24/7 markets — needs redefinition (e.g. UTC daily open).

## 14. Deep V-Tracker
- Patterns Module: Acceleration, Exhaustion, Slowdown (Pattern Mode strength: Strong/Medium/Weak).
- Absorption & Pressure Module: color-coded lines marking buyer/seller absorption/pressure with control/extreme labels.
- Configurable noise filtering + visual markers.

## 15. Deep Pattern Builder
- Rule-builder: condition inputs = Reference (OHLCV), Indicator output (e.g. Delta), Constant, or Unused (disabled).
- Combine via OR / AND / "AND+OR (Advanced)", up to 4 conditions.
- Automatic backtesting/simulation against history.
- No confirmed generic math operators beyond logical combination.
- Best UX reference for CandleViewer custom stop/exit rule builder.

## 16. Deep Profile Swing (a.k.a. "Deep Swing Profile")
- Vbp Type: Volume / Ask-Bid split (implied) / Delta+Total Volumes / Delta Percentage / VWAP (swing-relative).
- Include Reversal Bar: toggle whether swing-start bar counts toward prior swing's profile.
- Display Mode: Profile And Lines / Lines Only.
- Main Swing Settings (swing definition): Left Right Bar (N-bar pivot), Highest Lowest (new high/low), Reversal Absolute (fixed $ reversal, "Abs. Rev"), Reversal Tick ("Tick Rev.").
- Extra: Right Bar (confirm bars for Left-Right-Bar), Swing Stop Settings (Enable Stop Swing toggle mirrors Main Swing), VWAP Swing sub-mode with Swing Max Ticks, VWAP Break Ticks.
- Data: OHLCV + side for Delta variants; pure price-swing overlay = ZigZag + Volume Profile combined.

## 17. Deep Replay (Tick Replay/Backtester)
- Setup: Options→Replay Tick Data→Manage Settings→symbol+date range→open new chart→Play.
- Requires disconnect from live feed / close open charts first.
- Speed control: presets or scroll bar.
- Simulated trading during replay (sim mode).
- Footprint/order-flow visuals replay live historically, incl. Big Trades markers.
- Bybit: replicable with local tick DB (trade+book-delta); book-replay needs stored L2 diffs over time.

## 18. Trading Terminal / Trading From Chart
- Enable trading: dollar icon or right-click "Trading enabled."
- Trading Panel toggle.
- Order placement: Market/Limit/Stop via panel or click-on-chart.
- Order mgmt: left-click line to reprice, right-click to cancel.
- Flat button: close position + cancel all pending in one action.
- OCO: SL/TP mode (single pair, size in ticks or $), Multi mode (multi-contract, move-to-breakeven, scaled targets), Server OCO (broker-side, survives disconnect; Rithmic/DXFeed — futures-specific, Bybit OCO support TBD), Client OCO (local, needs connection), Quick ad-hoc SL/TP squares.
- Trade Copier: multi-account order mirroring (dedicated article).
- Risk Manager: dedicated article exists, details not retrieved (open Q).
- Strategy Reports: Trading menu→Strategy Report→Broker/Account→Generate.
- Orders Window: manage all open/working orders.

## 19. Keyboard Shortcuts
- Configure via Options→Settings→Shortcuts.
- Category: General, Chart.
- Type: Action, Control, Drawing and Annotation, Scroll, Trading.
- Table columns: Category, Type, Description, key-combo.
- Create: Register→press keys→Save Settings.
- Open Q: no default key-bindings enumerated; unclear if platform ships fixed defaults.

## 20. DeepDOM (Liquidity Heatmap + DOM)
- Heatmap: color-coded resting limit-order concentration per price level (dark/warm=high).
- Fuses live L2 book + Time & Sales.
- Historical playback of order-book evolution.
- MBO (per-order, needs L3) vs. MBP (aggregated per-level, L2 sufficient) modes; MBO enables iceberg/absorption-wall detection.
- DOM panel: live bid/ask ladder + place/manage orders.
- Stop-run tracker / iceberg tracker: premium/advanced.
- Bybit: orderbook.1/50/200 (L2 incremental) sufficient for MBP heatmap+ladder; true MBO/iceberg not available — only trade-heuristic approximations.

## 21. Data Feeds & Brokers (futures/legacy context)- Feeds: dxFeed (primary, desktop+web), CQG, Rithmic, IQFeed, MT5, Interactive Brokers (aggregated only), Quote Media, Trading Technologies, + direct brokerage (Directa, Sella, IWBank, WeBank).
- Exchanges: CME, CBOT, COMEX, NYMEX, EUREX, NASDAQ, Italian (MTA/IDEM/MOT).
- Platform: Windows standalone (full), web (dxFeed, limited), Mac via Parallels/VMWare or web/Safari.
- No native crypto integration at all — CandleViewer must build own Bybit connector from scratch; no DC crypto adapter to reference beyond generic feed-abstraction patterns.

## 22. Templates, Workspaces, Compact View- Templates: single chart's indicators/styles/settings; save/load via right-click chart.
- Workspaces: full multi-chart layout, each chart potentially with own template; dedicated management panel.
- Both save locally or to cloud.
- Pre-built ("ready-made") Orderflow templates/workspaces ship with platform (inferred, teaser only).
- Open Q: Compact/group multi-chart view & screenshot/export workflow — not retrieved.

## 23. Performance Analysis / Strategy Reports (= "Auto-Tracker Journal" mislabeling, resolved)
- No literal "Auto-Tracker" feature exists; actual feature = Performance Analysis / Strategy Reports.
- Workflow: Trading menu→Strategy Report→choose Broker+Account→date-range/symbol picker→Generate Report.
- Report sections: Strategy Performance (Balance, Profit, Losses, # trades, Commissions, DrawDown, Run-up, %win, by period); Trade List (per-trade entry/exit time/price/qty/PnL/DD/Run-up); Symbol Performance (per-symbol balance); Chart (equity curve, drawdown, per-trade breakdown); Time Analysis (profitability by hour/day/month/year).
- Data: full closed-trade execution history — buildable purely from CandleViewer's own fills DB.

## 24. Stop Run & Deep Wall (iceberg/stop-sweep detectors)
### Stop Run
- Params: Minimum Tick (move size to qualify), Min. Stop Run Vol (triggering volume), Max number of orders, Max MS (cascade time window), Display Mode, Ask/Bid Color, Marker Thickness, Text Settings.
- Logic: price moves ≥Min Tick within ≤Max MS driven by burst ≥Min Stop Run Vol, typically at prior high/low/S-R. Bybit: fully derivable from trade stream alone, no L2/L3 needed.

### Deep Wall
- ES-futures-tuned; detects passive order walls absorbing aggressive orders → price rejection = iceberg signature. Rare (few times/week-month), mostly low-liquidity sessions.
- Minimal settings: Alert Sound, Message Popup; no manual thresholds (internal preset). Bybit: no true iceberg flag/L3 — approximate via trade-tape + L2 book-depth-refill pattern.

## 25. Additional confirmed indicators (§30)
- "Market Regime" — NOT a real DeepCharts feature; build own classifier (e.g. ADX + realized-vol). Closest DC analogs: Deep-M Effort, Confluence Identifier, generic Super Trend/ADX/Aroon.
- **Imbalance Rejector** (reversal, distinct from Imbalance Tracker): % Min. Imbalance (candle high/low), Minimum Diagonal Comparison (tick-levels back), Lookback Period (swing validity bars), Tick Offset (marker placement).
- **Deep Delta** (advanced Delta Bars): Input Data (Volume/Aggregate Trades/Trades), Delta Mode (Classic or Multi-Range, up to 4 filterable ranges), Range 1–4 Min/Max (max=0 disables), Threshold→Level Settings (up to 2 ref lines), Threshold→Marker (min+max delta cross flags absorption/acceleration).
- **Confluence Identifier**: Tick Sensitivity, Minimum Number of Confluences, Starting Mode (Zig Zag/Date), Zig Zag Swing Settings (two-stage %), First/Second/Third VBP (up to 3 profiles: Daily/Weekly/Monthly/Composite; enablements POC/Value Area/Peaks/Valleys/Delta Imbalances), S&R Colors by confluence count.
- **Auction Gap Tracker** (zero/thin-print, related to Unfinished Auction): Minimum Tick Vol, Threshold-max unfinished (0=true zero, 1=also 1-contract), Include Mode (Intrabar/All), Min. Num. Consecutive Zero.
- All 4: Bybit-sufficient via trade prints; Confluence Identifier also needs multi-timeframe Volume Profile.

## Numeric limits / recommendations
- TPO Base Minute default: 30 min. Value Area default: ~70% (Volume Profile & TPO).
- Envelope bands: 1st/2nd/3rd STD ≈ 68%/95%/99.7% coverage.
- Deep Delta Multi-Range: up to 4 filterable ranges. Deep Pattern Builder: up to 4 conditions (AND/OR/AND+OR). Confluence Identifier: up to 3 VBP profiles.
- No numeric ceilings found for: max charts/workspace, max indicators/chart, max historical days loadable, max symbols per Big Trades Analysis run.
- No crypto exchange (Bybit/Binance/etc.) natively supported by DeepCharts — confirmed gap.

## Full feature → Bybit-feasibility summary table
| Feature | Bybit sufficiency |
|---|---|
| Deep Print (Footprint) | Yes; "Order" input approximate |
| Deep Stats | Yes |
| Deep Profile | Yes, needs local tick DB |
| Big Trades / Deep Trades | Yes; iceberg/MBO not possible |
| Imbalance Tracker | Yes |
| Unfinished Auction | Yes |
| Bar POC | Yes |
| Speed of Tape | Yes |
| VWAP + Envelopes | Yes |
| CVD | Yes |
| Market Profile (TPO) | Yes (timestamps only) |
| Deep-M Effort | Conceptually yes; algo proprietary |
| Deep-M IVB | Needs 24/7 session redefinition |
| Deep V-Tracker | Yes, approximate (undocumented algo) |
| Deep Pattern Builder | Yes — UX reference |
| Deep Profile Swing | Yes |
| Deep Replay | Yes, needs local tick+book-delta storage |
| Trading Terminal/OCO/Trade Copier | Partial — no native Bybit server-side OCO parity |
| DeepDOM Heatmap+DOM | Yes via L2 MBP; no true MBO/iceberg |
| Data Feeds | No — build custom Bybit connector |
| Stop Run | Yes — pure trade-tape heuristic |
| Deep Wall | Approximate only, no L3 |
| Imbalance Rejector | Yes |
| Deep Delta | Yes |
| Confluence Identifier | Yes, w/ multi-period Volume Profile |
| Auction Gap Tracker | Yes |
| Performance Analysis/Strategy Reports | Yes — internal fills DB |
| Templates & Workspaces | Yes — standard app-state |
| Market Regime | Not a real feature — build own |

## Open questions (unresolved as of this pass)
1. Exact default hotkey-to-action mapping — may not exist (user-assignable only).
2. Whether VWAP supports true click-to-anchor (arbitrary bar) vs. only fixed period/session resets.
3. Numeric ceilings (max charts/workspace, indicators/chart, historical days, symbols/Big-Trades-Analysis run) — none surfaced.
4. Compact/group multi-chart view UI + screenshot/export workflow — no article found.
5. Whether "Order" input type (used across Deep Print, Deep Stats, Deep Profile, Speed of Tape, Deep Delta, Deep Trades) means true per-order-arrival counting (needs L2 incremental diffs) or a relabeled aggregate — ambiguous; key cross-reference article "different-types-of-input" never fetched — top priority for follow-up.
6. Feature/version differences between Full Advanced ($79/mo) vs. Pro ($100/mo) beyond headline list — not itemized.
7. Speed of Tape vs. Speed of Tape (Instant) — exact distinction unconfirmed.
8. Naked/prior-session POC persistence in Deep Profile — not explicitly itemized.
9. Risk Manager feature details — not retrieved.
10. Imbalance Rejector vs. Session Imbalance vs. Imbalance Tracker — possible overlap unexplored.
