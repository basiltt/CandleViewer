# Digest: 03-tradingview-gaps.md

Source compiled 2026-09-13. TradingView not built for order-flow/microstructure; strong charting/social ecosystem but weak on order flow, pricing/alerts, Pine limits, paper trading realism. Trustpilot 1.6/5 (1,300+ reviews, Aug 2026).

## Gaps (24) — Name — Evidence strength — CandleViewer fit

1. No true tick bid/ask footprint (estimates only, not exchange order-flow); native `request.footprint()` Premium/Ultimate only (unverified tier claim) — Strong — **Strong**: Bybit `publicTrade` WS gives real taker-side data.
2. No DOM/order-book liquidity heatmap (vs Sierra Chart/ATAS/Bookmap) — Moderate — **Strong**: Bybit `orderbook.50`/`orderbook.500` WS.
3. Footprint gated behind Premium/Ultimate (~$60-240/mo) — Strong — **Strong (moot)**, no tiers.
4. Footprint data thins/blanks on older bars & higher TFs (strict lookback limit) — Strong — Moderate, depends on our tick-store retention design.
5. Aggregated OI/liquidations/funding limited to fixed exchange list (Binance/Bybit/OKX/Bitget/Deribit/HTX/Coinbase/BitMEX/Kraken) — Moderate — Low now (Bybit-only v1) / High later if multi-exchange.
6. Historical bar limits scale by tier: Basic 5K, Essential 10K, Plus 10K, Premium 20K, Ultimate 40K bars — Strong — **Strong (moot)**, self-hosted DB.
7. Bybit-TradingView broker connection expires every 24h, forces re-auth — Strong (Bybit help center) — **Strong**: own persistent API key/session mgmt.
8. No native Bybit webhook/automation; must use 3rd-party bridges (TradingView Hub, PickMyTrade) w/ quirks (3 different TP-attach fields: `setTpToPosition`, `targetAssignedToPosition`, `useEntireAccountBalance`; single-TP-only) — Strong — **Strong**: direct Bybit v5 REST+WS.
9. Paper trading = perfect fills, no slippage/queue modeling; exchange demo accounts recommended over TV's simulator — Strong — **Strong**: use Bybit demo-trading mode (real matching engine).
10. OCO/bracket limits: can't attach OCO to open positions; brackets only via Order Panel, not chart-click market orders — Strong (illustrative, Tradovate-specific) — **Strong**: build natively against Bybit v5 conditional orders.
11. No native scale-in/laddered entries or rule-based auto-exits without Pine strategies/3rd-party bots — Weak-moderate — **Strong**, core scope.
12. Alert limits: Active price alerts 3/20/100/400/1,000 across Basic→Ultimate tiers; watchlist alerts capped (2, up to 15 some tiers); alert expiry 1-2 months except Ultimate — Strong (pricing page + Reddit) — **Strong (moot)**: uncapped, non-expiring, rule-based.
13. Webhook alerts: hard 3-second response timeout, NO retry on timeout (only retries on 5xx, excl. 504), port 80/443 only, 1-5s added backend delay at peak — Strong (official docs + measured dataset of 34,174 alerts) — **Strong**: no webhook relay, direct API.
14. No true tick-level backtest; bar-close fill model default; Bar Magnifier only approximates via lower-TF OHLC; disabling default (`process_orders_on_close=false`) can cut backtest perf 15-30%; zero slippage/commission defaults — Strong (multiple blogs) — Strong but long-term (needs own tick store).
15. Pine Script sandbox limits: no external API/HTTP/fetch, no ML models, no DB, no WebSocket; hard cap **40 request.*() calls per script instance per bar** (dedup identical calls); 2-min compile-time limit; no resource-usage introspection — Strong (official docs) — **Strong**: real Python backend, no sandbox.
16. Repainting: indicators/strategies retroactively change; strategy tester can peek into future — Strong (TV's own help center) — Moderate: avoid by design (act only on closed/confirmed data).
17. No fully-automated one-click execution; requires alert→webhook→3rd-party bridge, fragile (breaks on any link failure) — Moderate — **Strong**: single integrated process, no bridge.
18. 2026 price hikes 17-20%: Essential (new) $14.95/mo; Plus $29.95→$34.95 (+17%); Premium $59.95→$69.95 (+17%); Ultimate $199.95→$239.95 (+20%, note: $199.95=annual billing rate, $239.95=monthly billing rate, same plan, NOT conflicting figures) — Strong — **Strong (moot)**, no subscription.
19. Poor support (chatbot-only), billing double-charges, slow refunds; Trustpilot 1.6/5 from 1,300+ reviews (Aug 2026); TV disputes fake-review skew — Strong — **Strong (moot)**.
20. Bar Replay: tier-gated for intraday TFs (free = daily+ only); replay depth by tier (Essential ~6mo of 1-min, Plus ~1yr, Premium/Ultimate = stored-data limit); no slippage/spread modeling; no multi-symbol sync; buggy even for paid users (Reddit thread) — Strong (5 sources + Reddit) — Strong but long-term (needs own tick store).
21. Trailing Stop/OCO support inconsistent by broker; crypto brokers absent from full order-type support matrix (Trailing Stop: IBKR/Alpaca/Tradovate/OANDA only; OCO: IBKR/TradeStation/Tradovate/Saxo only) — Moderate — **Strong**: build against Bybit's native order-type surface.
22. No user-programmable, ladder-native hotkey system (one-click trading toggle exists for panel Buy/Sell/right-click, DOM click-to-trade exists but requires broker-provided L2 data) — Confirmed this pass — **Strong**: DeepDOM-style ladder w/ full hotkey binding (buy/sell-at-price, flatten, cancel-all, size presets, OCO-attach).
23. Multi-account/sub-account not first-class: 24h broker re-auth, no in-chart sub-account toggle (must reconnect); Bybit allows up to 5 Standard sub-accounts (20 for VIP/KYC) — this is a Bybit-side limit, not TV's — Confirmed this pass — Moderate→Strong: build clean in-chart switcher, no re-auth.
24. General performance/lag with many indicators/heavy charts — NOT corroborated (open question, not confirmed) — Unknown.

## Numeric limits reference table

| Limit | Value |
|---|---|
| Pine `request.*()` calls | 40 per script instance per bar (dedup identical calls) |
| Pine compile time | 2 minutes |
| Webhook response timeout | 3 seconds, no retry on timeout, only retries on 5xx (excl. 504) |
| Webhook allowed ports | 80/443 only |
| Webhook backend delay (peak) | +1-5 seconds |
| Historical bars by tier | Basic 5K / Essential 10K / Plus 10K / Premium 20K / Ultimate 40K |
| Active price alerts by tier | 3 / 20 / 100 / 400 / 1,000 (Basic→Ultimate) |
| Watchlist alerts | capped at 2 (up to 15 on some tiers) |
| Alert expiry | 1 mo / 2 mo / 2 mo by tier; non-expiring = Ultimate-exclusive |
| Ultimate plan power-user caps | 16 charts/tab, 50 indicators/chart, 1,000 alerts |
| 2026 pricing | Essential $14.95/mo; Plus $34.95/mo; Premium $69.95/mo; Ultimate $239.95/mo (monthly) or $199.95/mo (annual, $2,399.40/yr) |
| Bybit sub-accounts | 5 Standard / 20 VIP-KYC |
| Trustpilot rating | 1.6/5, 1,300+ reviews (Aug 2026) |
| Backtest perf impact of realistic fill setting | -15% to -30% when `process_orders_on_close=false` |

## Key recommendations (§5 Key takeaways)

1. Genuine order flow is the flagship differentiator — build real footprint/DeepDOM from Bybit `publicTrade` + `orderbook` WS topics (real taker-side/depth data vs TV's estimated splits).
2. Skip the TradingView-broker-bridge architecture entirely — talking to Bybit v5 API directly resolves gaps 7, 8, 13, 17, 21 (24h re-auth, webhook relay, 3s timeout, fragile automation, inconsistent order types) at once.
3. Use Bybit's own demo-trading environment (real matching engine/liquidity) instead of building a synthetic paper-trading simulator — solves gap 9 directly; matches what 3rd-party automation vendors already recommend.
4. Phase tick-level replay/backtesting and deep historical footprint as later milestones (not v1) — requires building/maintaining own tick-level data store.
5. Pricing/billing/support complaints are structurally moot for a private tool, but validate the "TradingView killer, private, no tiers" framing.
6. Weakest-evidenced items — hotkeys/ladder trading, multi-account UX, general performance/lag — should be validated against user's own TV/Bybit experience before being treated as confirmed requirements.

## DeepCharts sub-feature → TradingView mapping (§3.11)

| DeepCharts feature | Closest TV approximation | Native TV equivalent? | Limitation |
|---|---|---|---|
| Deep Print/footprint | Footprintchart, FlowSight scripts; native `request.footprint()` | Partial (tier-gated, unverified) | Estimated bid/ask, not true aggressor data on most symbols |
| Iceberg detector | "Iceberg Detector [JOAT]", "[A618] Liquidity Tracker/Iceberg Detector V2 Pro" (invite-only) | No | Inferential from wick/body/volume shape, not real order-book replenishment |
| Stop-run/liquidity sweep | "Liquidity Sweep Detector [DefinedEdge]", "[BigBeluga]", "Pro [Jos-ProTrader]" | No | Zone modeling from swing highs/lows+volume, not real resting stop data |
| Imbalance/speed of tape | "Orderflow Detector [OmegaTools]" | No | Authors admit true tape speed needs L2/tick data Pine can't access |
| Deep Stats/Big Trades | No dedicated widely-used equivalent found | No | — (open item) |
| Market regime | Not evaluated against DeepCharts' definition this pass | Partial (unverified) | Needs follow-up |
| Aggregated OI/liquidation heatmap | "Liquidation Heatmap BullVision", "Aggregated OI Alpha Extract", "Liquidation Heatmap Alpha_Precision_Charts" | No native aggregation | Modeled/estimated via assumed leverage tiers (5x-125x), not real per-trader thresholds |

All 7 buildable from Bybit v5 API at higher fidelity than community TV scripts (real tick data vs derived heuristics). Market regime + Deep Stats/Big Trades need dedicated design work.

## Additional confirmed findings

- §3.10 pricing correction: $199.95 (annual billing) vs $239.95 (monthly billing) are the SAME Ultimate plan, not conflicting figures — earlier "disputed" framing was an error.
- §3.12: TV has no native cross-exchange aggregated OI/liquidation heatmap (community scripts only); native Funding Rate indicator exists (Financials tab, incl. Bybit) but shows only current rate, no countdown timer to next settlement — only fix is 3rd-party browser extensions. CandleViewer: Bybit v5 exposes OI/funding rate/next-funding-time natively → live countdown + liquidation-density overlay straightforward.
- §3.9: One-click trading toggle and right-click/Buy-Sell button flow ARE real/native (not a gap); DOM click-to-trade requires broker-provided L2 data. Gap is specifically absence of ladder-native, user-programmable hotkeys (vs Bookmap/Sierra Chart/NinjaTrader/Jigsaw).
- §3.14: TV supports connecting Bybit Main or Sub-account, prompts to switch if balance insufficient, but switching between sub-accounts mid-session requires reconnect flow, not one-click toggle. Charting-library docs describe "multiple accounts" capability at framework level but this is integrator-side, not end-user-controllable on hosted TradingView.com.

## Open questions (8, from source doc)

1. ~~Hotkeys/ladder trading~~ RESOLVED §3.9: confirmed gap — no ladder-native user-programmable hotkey system.
2. General performance/lag with heavy charts/many indicators — still NOT corroborated after two passes; genuinely unresolved. Recommend targeted r/TradingView + r/Daytrading pass with direct Reddit access.
3. ~~Multi-account/sub-account complaints~~ RESOLVED §3.14: confirmed (24h re-auth, no in-chart toggle), lower priority given small user base.
4. ~~Pricing figures $199.95 vs $239.95 "disputed"~~ RESOLVED §3.10: not conflicting, same plan different billing cadence.
5. ~~Speed of tape/imbalance/stoprun/iceberg TV equivalents~~ RESOLVED §3.11: full mapping added. STILL OPEN: no equivalent found for "Deep Stats"/"Big Trades" or DeepCharts-specific "market regime" classifier — needs further targeted search.
6. Verification of exact Reddit thread quotes — unresolved; no direct Reddit scraping performed (WebSearch synthesis only). Recommend dedicated pass with direct Reddit access before using exact quotes in outward-facing docs.
7. Rate limiting constrained this pass — Parallel Search MCP free-tier exhausted at session start; all queries routed through WebSearch fallback (synthesized summaries, not raw excerpts). Nothing independently re-verified against raw primary-source HTML.
8. "Deep Stats"/"Big Trades"/"market regime" TV equivalents — no specific community script identified; needs dedicated follow-up search.

## Methodology notes (condensed)

Sources: Reddit (r/TradingView, r/Daytrading, r/algotrading), TV's own Pine docs/Help Center, Trustpilot/PissedConsumer/ComplaintsBoard, comparison blogs (Bookmap, GoCharting, NexusFi, tv-hub.org, pineify.app, tickerly.net, TradersPost, CMC Markets, stockalarm.io). Reddit content accessed via search snippets, not full scraping — substance corroborated 2+ sources in nearly all cases. Parallel Search MCP rate-limited mid-session; fallback WebSearch used for remainder (synthesized, not raw excerpts) — flagged per-claim.

~330 source URLs cited in original (§ Sources) — omitted here as pure reference list; available in source doc if needed.
