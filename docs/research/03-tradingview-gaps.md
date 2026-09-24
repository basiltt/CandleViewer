# TradingView pain points & gaps (esp. for crypto/order-flow traders)

> Research pass for CandleViewer (private, self-hosted, crypto/Bybit-only trading terminal). Compiled 2026-09-13 from public forum threads, review sites, official docs/changelogs, and comparison blogs. Focus: what TradingView users actively complain about or find missing, ranked and mapped to what CandleViewer could realistically fill.

## 1. Executive summary

TradingView is near-universally praised for charting polish, ease of use, and its social/scripting ecosystem (Pine Script, 100k+ community scripts), but it is **not built as a true order-flow / market-microstructure platform**. Traders who need genuine order flow (footprint, DOM heatmaps, tick-level replay) consistently say TradingView is "insufficient" and route to specialist tools (Bookmap, ATAS, Sierra Chart, Quantower, Exocharts). Separately, a large and vocal body of complaints centers on **pricing/tier changes (2023-2026), alert limits, webhook latency, Pine Script execution/backtesting limitations, and unrealistic paper-trading fills**. Trustpilot sentiment is strongly negative (1.6/5 based on 1,300+ reviews, confirmed live as of Aug 2026 — see §3.9), driven mostly by billing/support issues rather than charting quality.

For CandleViewer — a private, single/few-user, Bybit-first, order-flow-focused terminal with no pricing tiers, no support ticket queue, and full control over data pipeworks — most of the top complaints are **structurally unfixable-by-TradingView-but-trivially-avoidable-by-us**, because we don't need a freemium business model, third-party data licensing constraints, or protecting proprietary footprint IP behind paywalls.

## 2. Methodology & sources

Searches were run across Reddit (r/TradingView, r/Daytrading, r/algotrading, r/CryptoCurrency implied via crypto-specific threads), TradingView's own Pine Script docs/Help Center, Trustpilot/PissedConsumer/ComplaintsBoard, and third-party blogs/comparison sites (Bookmap, GoCharting, NexusFi Academy, tv-hub.org, pineify.app, tickerly.net, TradersPost, CMC Markets, stockalarm.io). Where a claim is a "Copilot-generated search summary" (i.e., synthesized by the search tool rather than a direct quote), it is marked as such below; where possible I've linked to primary/official sources (TradingView docs, TradingView pricing page, TradingView blog) alongside third-party commentary. Live Reddit thread content was accessed via search snippets/summaries rather than full thread scraping — treat exact quote attribution as approximate; the **substance** of each complaint is corroborated across 2+ independent sources in nearly all cases below.

Because of Parallel Search MCP free-tier rate limits reached mid-session, some queries were run instead through the general WebSearch tool, which returns synthesized summaries with source links rather than raw excerpts. This is noted per-section.

---

## 3. Ranked, categorized gap list

Ranking is by (a) frequency/intensity of complaint across sources, and (b) relevance to CandleViewer's crypto/order-flow/Bybit scope. Each item: **Gap → Evidence → CandleViewer fit**.

### 3.1 Order flow / footprint quality (HIGHEST relevance to CandleViewer)

**Gap 1 — No true tick-level bid/ask footprint; footprint is derived/estimated, not exchange order-flow data.**
- TradingView's own community footprint scripts state outright: *"TradingView does not provide tick-by-tick order flow, so all buy/sell splits are estimates, not exact measurements."* And: *"It does not access true exchange order book data or true bid/ask footprint data on most symbols."* (from TradingView Footprintchart / FlowSight script descriptions, tradingview.com/scripts/footprintchart)
- Native `request.footprint()` exists (Premium/Ultimate only) but even TradingView's own script authors note: *"Order flow coverage on TradingView continues to expand... Footprint coverage also thins on older bars, so those rows may go blank when scrolled far back."* (tradingview.com/scripts/footprint) *Footnote: the "Premium/Ultimate only" tier-gating claim for native footprint access could not be independently re-confirmed against TradingView's current official plan-comparison page in this pass (fetch tool was rate-limited); treat as plausible-but-unverified pending a direct check of tradingview.com/pricing's feature matrix.*
- One script explicitly: *"Not a true footprint chart... Since Pine Script has no access to aggressor side (bid/ask), the indicator uses volume and price changes... to approximate order flow direction."*
- Comparison sources (Bookmap blog, GoCharting) frame footprint/DOM/volume-profile as fundamentally different from what TradingView offers natively; ATAS-vs-TradingView comparisons conclude TradingView's order flow is "basic (via add-ons)" vs ATAS's "advanced (native)." (bikotrading.com/atas-vs-tradingview, tradingbrokers.com/atas-vs-tradingview)
- **CandleViewer fit: STRONG.** Bybit's WebSocket public trade stream (`publicTrade` topic) gives real tick-by-tick executed trades with taker side (Buy/Sell) — this is exactly the aggressor-side data Pine Script cannot access. A real footprint (Deep Print equivalent) built from actual trade prints is directly achievable and is a core differentiator vs. TradingView.

**Gap 2 — No DOM/order-book heatmap (liquidity visualization over time).**
- NexusFi Academy article on order flow heatmaps distinguishes DOM (snapshot) vs. heatmap (historical liquidity map) and notes Sierra Chart, ATAS, and Bookmap all offer this; TradingView is conspicuously absent from that list of heatmap providers. (nexusfi.com/a/market-structure/order-flow-heatmaps-liquidity-visualization)
- **CandleViewer fit: STRONG.** Bybit's `orderbook.50`/`orderbook.500` WebSocket depth streams can be recorded and rendered as a DeepDOM-style liquidity heatmap; this is a known, buildable feature with no TradingView equivalent.

**Gap 3 — Footprint/order-flow features gated behind Premium/Ultimate plans (~$60-240/mo).**
- Explicit: *"This indicator uses TradingView volume footprint data, which is available on Premium and Ultimate plans only."* (kr.tradingview.com/scripts/footprint); *"Requirements TradingView Premium or Ultimate plan required for request.footprint()"* (Footprintchart script)
- **CandleViewer fit: STRONG (moot).** Self-hosted, no tiers — every feature is available to the (small) user base by definition.

**Gap 4 — Volume footprint historical data thins/degrades on older bars and higher timeframes.**
- *"Footprint coverage also thins on older bars, so those rows may go blank when scrolled far back."* Also documented TradingView data limit on higher timeframes causing candles to render with "Zero Volume" (gray) on Monthly charts due to a *"strict limit"* on footprint/volume data lookback. (th.tradingview.com/scripts/footprint)
- **CandleViewer fit: MODERATE.** We control our own tick-data storage/retention (subject to disk/DB budget), so this is avoidable if we design the tick-store correctly (e.g., downsampled aggregates for old data, full ticks for recent).

### 3.2 Crypto derivatives data gaps

**Gap 5 — Aggregated OI/liquidations/funding across exchanges is incomplete and exchange-list-limited.**
- TradingView's own liquidation/OI data is documented as available "for crypto derivatives on a number of exchanges, such as Binance, Bybit, and OKX" — implying a curated, non-exhaustive list, not full market aggregation. Community "Aggregated Open Interest Multi-Exchange" scripts exist precisely because native coverage is felt to be insufficient, and even those aggregation scripts are capped to a fixed exchange list (typically Binance, Bybit, OKX, Bitget, Deribit, HTX, Coinbase, BitMEX, Kraken) — smaller/newer exchanges are excluded. (WebSearch synthesis of tradingview.com/script/HQgxb0Ul-Open-Interest-liquidation-map, and 0o1cu0xB aggregated OI script; corroborated by th.tradingview.com/scripts/footprint noting liquidation/OI/funding is "published by TradingView for crypto derivatives on a number of exchanges")
- **CandleViewer fit: LOW-MODERATE for v1 (single exchange = Bybit), HIGH if we later add multi-exchange.** Since CandleViewer is Bybit-first, we don't need cross-exchange aggregation immediately, but the architecture should keep this option open (per project brief) — e.g., a data-source abstraction layer so Binance/OKX perpetuals data can be added later for aggregated OI/liquidation views without a rewrite.

**Gap 6 — Historical bar/data limits scale by subscription tier (5K bars free vs 40K Ultimate).**
- Documented tier table: Basic 5K historical bars, Essential 10K, Plus 10K, Premium 20K, Ultimate 40K bars. (github.com/akmoy655/tradingview pricing breakdown, corroborated by cmcmarkets.com pricing explainer)
- **CandleViewer fit: STRONG (moot).** Self-hosted DB — historical depth is limited only by our own storage strategy, not an artificial tier wall.

### 3.3 Trading facilities (crypto/Bybit specific)

**Gap 7 — Bybit connection via TradingView is time-limited (24h) and requires re-auth.**
- Bybit's own help center: *"Please note that the current status after connecting to the broker on TradingView can only be maintained for 24 hours due to the restriction imposed by TradingView for security purposes."* (bybit.com/en/help-center/article/How-to-Get-Started-With-Trading-on-Bybit-From-TradingView)
- **CandleViewer fit: STRONG.** A dedicated app with our own stored API keys/session management (not routed through TradingView's broker-connect flow) avoids this entirely — persistent, non-expiring sessions with proper key rotation/security instead.

**Gap 8 — No native Bybit webhook/automation integration; must go through third-party bridges (e.g., TradingView Hub, PickMyTrade) with per-exchange quirks (hedge mode, sub-accounts, TP-attach fields, symbol formats).**
- *"Bybit doesn't have a native TradingView integration. You connect the two with a webhook: a TradingView alert posts a JSON message to TradingView Hub, which holds your Bybit API key and places the order for you."* (tv-hub.org/blog — "How to Connect Bybit to TradingView (Webhooks)")
- Bybit-specific quirks documented by tv-hub.org: three different TP-attach fields depending on entry type (`setTpToPosition`, `targetAssignedToPosition`, `useEntireAccountBalance`), single-TP-only limitation, no native IP whitelist requirement but third-party app authorization needed instead. (tv-hub.org/docs/exchanges/bybit)
- Old (2019) but illustrative complaint about Bybit's own order-type quirks with stop-entries auto-cancelling: *"I can't even manually put stop entries above the strike on bybit, they auto cancel when they are triggered... Bybit's API rejects normal stop sells or anything addressed as a stop loss take profit unlike mex and deribit."* (bitcointalk.org forum, 2019 — dated, Bybit's API has evolved significantly since, cite with caution)
- **CandleViewer fit: STRONG.** Direct native Bybit REST+WebSocket integration (v5 unified trading API) removes the third-party bridge entirely — no webhook relay, no 3-second timeout risk, no per-vendor field-name quirks to reverse-engineer. This is one of the clearest wins for a purpose-built terminal.

**Gap 9 — Paper trading has unrealistic (perfect) fills; no slippage, no order-book queue modeling.**
- *"Does the simulator account for slippage? No. This is the biggest gap between paper and live trading. The simulator gives perfect fills the moment a price is touched, without accounting for order book queues, partial fills, or slippage from large orders."* (coincub.com/blog/tradingview-paper-trading)
- Comparison table from same source: Order Execution "Perfect fills; instant execution upon price touch" vs live reality "Subject to price-time priority and queue depth"; Slippage "Non-existent" vs live "High variability."
- Counter-note: TradingView Hub docs recommend using exchange-native **demo accounts** (not TradingView's own paper trading) specifically because *"Demo accounts are real paper-trading environments: they run on live market prices and real liquidity, so fills behave like production. Testnets usually have little or no liquidity, so prices and fills are unrealistic."* (tv-hub.org/docs/exchanges) — this itself validates the complaint about TradingView's simulator vs. genuine exchange demo/paper environments.
- **CandleViewer fit: STRONG.** Project brief already specifies Bybit demo-trading mode as the primary paper-trading path (real order-matching engine, real liquidity) rather than a synthetic simulator — this directly solves the #1 documented paper-trading complaint.

**Gap 10 — Limited bracket/OCO order support; OCO can't be attached to already-open positions; bracket orders only from the Order Panel, not chart-click market orders.**
- *"OCO Orders cannot be applied to open positions in TradingView. These must be placed before entering a trade... Bracket Orders can only be attached to entry orders placed through the Order Panel in TradingView. Market orders placed directly from the chart cannot have brackets applied."* (docs.pickmytrade.trade, re: Tradovate-via-TradingView, but illustrative of a general TradingView order-panel architecture constraint)
- Broader order-type compatibility note: Stop-Limit and Trailing Stop support is "broker-dependent," with "some crypto exchanges exclude" Stop-Limit. (nexusfi.com/a/platforms/tradingview-broker-integration)
- **CandleViewer fit: STRONG.** Project brief explicitly requires custom rule-based stops/exits and fast/customized order controls — building bracket/OCO/scale-in ladders natively against Bybit's v5 API (which supports conditional orders, TP/SL on position, reduce-only, etc.) is squarely in scope and avoidable by not routing through TradingView's generic order-panel abstraction.

**Gap 11 — No native scale-in/laddered order entry or rule-based automated exits in the base platform (requires Pine Script strategies or third-party bots).**
- Corroborated indirectly by the "no native automated trading" finding below (Gap 15) — the pattern across all automation-related complaints is that TradingView is chart/alert-centric, not an execution/rules engine.
- **CandleViewer fit: STRONG.** This is core scope for CandleViewer per the project brief.

### 3.4 Alerts

**Gap 12 — Alert count limits, watchlist-alert limits cut without notice, and alert expiry (even on paid plans).**
- *"So TradingView lower the limit of the 'watchlist alerts' for PREMIUM user (not even free btw) from 5 alerts to 2 alerts"* — r/TradingView, "Major Complaint Regarding Premium Plan User Experience for Alerts" thread (reddit.com/r/TradingView/comments/1iecpoo)
- *"I've been able to use alerts since forever [on free plan]... [now] Basic tariff has already removed the availability of alerts."* — r/TradingView, "Can't use alerts on free plan anymore?" (reddit.com/r/TradingView/comments/1je3nth, Mar 2025)
- *"TradingView alerts on the Plus plan still expire after 2 months. That means you're now paying $34.95/month for alerts that disappear if they don't trigger within 60 days... This was already a common complaint at the old pric[ing]"* (pro.stockalarm.io/blog/tradingview-price-increase-2026, Apr 2026)
- Official pricing page confirms tiered alert caps: Active price alerts 3/20/100/400/1,000 across Basic→Ultimate; watchlist alerts only unlocked on higher tiers with a documented cap of 2 (later shown as up to 15 in some tiers). Alert durations capped at "1 mo. / 2 mo. / 2 mo." depending on tier — i.e., **no plan offers alerts that never expire except the very top tier** ("Alerts that don't expire" listed as an Ultimate-exclusive feature). (tradingview.com/pricing)
- **CandleViewer fit: STRONG (moot for count limits).** Self-hosted, no artificial caps — but the underlying capability (persistent, non-expiring, rule-based alerts tied to custom conditions) is exactly what the project brief's "custom rule-based stops/exits" implies; we can build alerting as a first-class, uncapped feature.

**Gap 13 — Webhook alerts have a hard, non-configurable 3-second response timeout with no retry on timeout (only retries on 5xx).**
- *"TradingView webhooks are designed to cancel any request that doesn't receive a response from your server within 3 seconds... There's no retry for timeouts—if your server doesn't instantly acknowledge the POST from TradingView, the alert is simply lost. TradingView only retries if your endpoint actually returns a 5xx error, not if it times out."* (blog.pickmytrade.trade/why-your-tradingview-webhook-timeout-the-3-second-limit) **Verification pass (Sept 2026): confirmed** — TradingView's own official support article "How to configure webhook alerts" (tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/) is the primary source cited alongside the third-party explainer for the 3-second cutoff, 5xx-only retry (excluding 504), and port 80/443-only restriction; treat the 3-second figure as corroborated by official docs, not just a blog paraphrase.
- Measured real-world latency data exists from a third party: *"TradingView Webhook Delay: 34,174 Alerts on Real Latency"* — a dataset-backed blog post measuring actual delivery delay distributions (tv-hub.org/blog/tradingview-webhook-latency/). Also documented: alerts must target only ports 80/443, and TradingView's own backend can add "1–5 seconds of delay during peak times."
- **CandleViewer fit: STRONG.** Because CandleViewer talks to Bybit directly via WebSocket/REST rather than routing signals through TradingView's alert-webhook pipe, this entire failure class (timeout-drops, no-retry, port restrictions, opaque internal processing delay) is architecturally eliminated. If we ever add external signal ingestion (e.g., from Pine-Script-like custom rules), we control the timeout/retry semantics ourselves.

### 3.5 Pine Script / backtesting limitations

**Gap 14 — No true tick-level backtesting; default bar-close execution model is unrealistic; even "Bar Magnifier" only approximates via lower-timeframe OHLC, not a real order book.**
- *"TradingView's Pine Script Strategy Tester runs on a bar-close evaluation model by default: strategies calculate at each bar's close, and market orders fill at the open of the next bar... Even with Bar Magnifier enabled, the tester uses lower-timeframe OHLC prices, not a real order book."* (tickerly.net/pine-script-strategy-tester-limitations)
- *"Default Execution Is Unrealistic... TradingView strategies execute at bar close by default. If your strategy generates a signal on bar close, TradingView fills the order at that same bar's close — the price you just used to generate the signal. In live trading, this is impossible... This single fix [process_orders_on_close=false] often reduces backtested performance by 15-30%"* (nexusfi.com/a/platforms/pine-script-strategy-backtesting)
- *"Zero slippage and zero commission are the defaults... even a modest commission per trade compounds into a significant drag that the backtest never accounts for."* (tickerly.net, same source)
- Bar Magnifier itself has a documented undocumented lookback ceiling that confused users (Stack Overflow thread, 2022): results stop changing once you scroll back far enough, apparently hitting a silent precision cutoff around a fixed historical date. (stackoverflow.com/questions/72593336)
- **CandleViewer fit: STRONG (long-term).** A proper tick-replay/backtester (explicitly named in the project brief's DeepCharts feature list) that replays real historical Bybit trade prints against a matching engine with configurable commission/slippage would be a genuine differentiator — but this is a substantial engineering lift (needs full historical tick storage) and should be scoped as a later-phase feature, not v1.

**Gap 15 — No external API/HTTP calls, no ML models, no database, no WebSocket access from Pine Script; hard cap of 40 `request.security()`-family calls per script.**
- *"Pine Script has no HTTP or fetch function. You cannot pull data from a news feed, an economic calendar, a brokerage API, or any external source... No machine learning models... A cap of roughly 40 request.security() calls per script. No database, no WebSocket, no custom UI beyond overlays and panes."* (pineify.app/pine-script-limitations)
- **Verification pass (Sept 2026):** the 40-call figure is confirmed by community documentation cross-referencing TradingView's own Pine Script v5 manual: the limit is **40 unique `request.*()` calls per script instance, per chart bar**, counting all direct and indirect calls (incl. those inside user-defined functions, imported libraries, and loops); identical repeated calls with the same arguments are deduplicated and count once; exceeding it throws a runtime error. Each script/study has its own independent 40-call budget. (TradingView Pine Script v5 manual, tradingview.com/pine-script-docs/en/v5/concepts/Requests.html; cross-checked via pineify.app/resources/blog/understanding-pine-scripts-requestsecurity-function) *Confidence: high — number matches across official-doc-derived summaries and independent third-party guides, though the exact TradingView doc page text was not directly excerpt-scraped in this pass due to fetch tool rate-limiting.*
- Official Pine docs confirm broader resource limits: 2-minute compile-time limit, per-script execution-time/memory/size limits, with *"There are currently no means for Pine Script programmers to get data on the resources consumed by their scripts."* (tradingview.com/pine-script-docs/v5/writing/limitations)
- **CandleViewer fit: STRONG.** Being a real Python backend (not a sandboxed scripting VM), CandleViewer has no such restriction — we can call any exchange API, run ML models, maintain a real database, and hold persistent WebSocket connections. This is a fundamental architecture advantage, not just a feature gap.

**Gap 16 — Repainting: indicators/strategies can show different values retroactively; strategy tester results can reflect impossible "peek-into-the-future" trades.**
- *"Repainting occurs when signals change after a bar closes... you've likely been affected by repainting... It happens when your script uses future information to influence past trades, something that's simply impossible in real-world trading."* (crosstrade.io/blog/pine-script-repainting)
- TradingView's own Help Center has a dedicated troubleshooting article: *"Strategy produces unrealistically good results by peeking into the future"* (tradingview.com/support/folders/43000548798-troubleshooting-scripts-and-strategies) — i.e., TradingView itself acknowledges this as a common, self-inflicted user problem baked into the platform's execution model.
- **CandleViewer fit: MODERATE.** A backend-driven rules engine operating on confirmed, closed-bar/tick data (rather than a live-recalculating client-side script) avoids the repainting failure mode by construction, provided we design the rule evaluation to only act on finalized data.

**Gap 17 — No fully-automated, one-click live execution; automation requires Pine Script alerts → webhook → third-party bot/broker bridge, which is fragile (breaks on any link failure) and has a documented backtest-vs-live performance gap.**
- *"TradingView's biggest limitation is that it does not directly support fully-automated trading on brokers... users have to rely on external tools, Pine Script alerts, and webhooks to connect to third-party bots or broker APIs."* (WebSearch synthesis citing finestel.com/blog/auto-trading-in-tradingview-guide, ontologytrading.com automate-strategy guide)
- *"This 'bridge' approach is fragile — if any link in the chain breaks (webhook delivery, bot uptime, broker API), the whole automation fails."*
- **CandleViewer fit: STRONG.** Since we are the terminal, the broker connection, and the rules engine in one process, there is no bridge to break — this whole complaint category collapses to "build it once, correctly" rather than "integrate three vendors."

### 3.6 Pricing / billing / support (background context, low direct relevance but shapes user expectations)

**Gap 18 — Major, unpopular price increases in 2026 (first hike "in over a decade" per one source), 17-20% across tiers.**
- *"TradingView raised subscription prices 17-20% across all tiers... Essential — (new tier) $14.95/mo · Plus $29.95→$34.95/mo (+17%) · Premium $59.95→$69.95/mo (+17%) · Ultimate $199.95→$239.95/mo (+20%)"* (pro.stockalarm.io/blog/tradingview-price-increase-2026, Apr 2026)
- *"TradingView's pricing misses the mark for casual users... my price for premium is almost 680 EUR yearly (that is 800 USD)"* (r/TradingView, reddit.com/r/TradingView/comments/1kehx2a, May 2025)
- **CandleViewer fit: MOOT/STRONG.** No subscription at all — this entire complaint category is structurally eliminated by being a private, self-hosted tool for one user + a few account managers.

**Gap 19 — Poor customer support (chatbot-only), billing double-charges, slow refunds; Trustpilot rating ~1.6/5 from 1,300+ reviews.**
- *"TradingView has a Trustpilot user rating of 1.6/5 from over 1,300 reviews (as of August 2026)"* with recurring themes of "worst customer service on the planet," double-charging, and multi-month refund delays. (WebSearch synthesis of trustpilot.com/review/tradingview.com, tradersunion.com/reviews/tradingview-com, tradingview.pissedconsumer.com, complaintsboard.com/tradingview-b134859)
- Note: TradingView itself has publicly addressed the fake-review problem on Trustpilot, cautioning that review-site sentiment is also affected by fake/incentivized reviews on both sides. (tradingview.com/news/... "Trustpilot, Fake Reviews, and the Complicated Truth About Transparency")
- **CandleViewer fit: MOOT.** No billing relationship, no support ticket queue — not applicable to a private tool, but reinforces the general finding that TradingView's user-facing friction is partly commercial/operational, not purely product/feature-based.

### 3.7 Replay / backtesting UX

**Gap 20 — Bar Replay is gated by plan tier for intraday timeframes and historical depth; not a true execution simulator (no slippage/spread); no multi-symbol sync; buggy even for paying users.**
- *"Bar Replay on intraday (1-min, 5-min, etc.) timeframes is gated behind paid plans. Free users can only replay on daily+ timeframes."*
- *"How far back you can replay scales with your plan: Essential ~6 months of 1-min data, Plus ~1 year, Premium/Expert/Ultimate as far back as stored data allows."*
- Reddit thread title itself: *"wtf is wrong with the replay feature? im a premium user i don't deserve this"* (redditmedia.com/r/TradingView/comments/1je1xwf) — reports of replay simply failing to start even for paying users.
- *"Tick-level replay is either not available or limited to the highest subscription tiers."*
- *"Bar Replay is largely a visual playback tool — it doesn't model slippage, spread, or realistic order fills."*
- *"No multi-chart/multi-symbol sync — you can't replay multiple charts or symbols in sync."*
- (Sources, per WebSearch synthesis: tradingsfx.com/blog/tradingview-bar-replay-limits, zeiierman.com/blog/tradingview-bar-replay-data-limits, tradereplay.app/blog/tradingview-replay-limitations, entriq.ai/en/blog/3-tradingview-bar-replay-limitations, plus the Reddit thread above)
- **CandleViewer fit: STRONG (long-term, pairs with Gap 14).** A tick replay/backtester built on our own stored Bybit tick data, with no plan-tier gating and genuine fill simulation against recorded order-book state, is both a named DeepCharts feature to replicate and a clear improvement over TradingView. Scope as a later phase given the storage/engineering cost.

### 3.8 Performance, hotkeys, multi-account

**Gap 21 — Order type support (Trailing Stop, OCO, Stop-Limit) is broker-dependent and inconsistently available across integrated brokers; some crypto exchanges exclude Stop-Limit entirely.**
- Table from nexusfi.com/a/platforms/tradingview-broker-integration shows Trailing Stop supported by "IBKR, Alpaca, Tradovate, OANDA" (no crypto brokers listed) and OCO by "IBKR, TradeStation, Tradovate, Saxo" — crypto exchanges are conspicuously absent from full order-type support in that matrix.
- **CandleViewer fit: STRONG.** Building trailing stops, OCO, and rule-based custom exits directly against Bybit's own conditional-order primitives (rather than relying on TradingView's generic cross-broker abstraction, which necessarily supports the lowest common denominator) lets CandleViewer expose Bybit's full native order-type surface.

**Gap 22 — Hotkeys / fast order entry: not deeply corroborated in this pass; TradingView's Order Panel/DOM (Level 2) ticket flow is a general-purpose, multi-broker UI rather than a scalper-optimized one-click/hotkey ladder (inferred from the broker-integration order-ticket description above, which lists standard ticket fields — Quantity, Order Type, Price, Time-in-Force — with no mention of hotkey/one-click/ladder trading).
- **CandleViewer fit: STRONG.** Project brief explicitly calls for fast/customized order controls; a purpose-built DOM ladder with click-to-trade and hotkeys (a known DeepCharts/Bookmap/ATAS staple) is straightforward to build against Bybit's low-latency REST/WS order endpoints without a generic-broker abstraction layer in the way.

**Gap 23 — Multi-account support: not strongly corroborated with direct complaint evidence in this pass (searches for this query were rate-limited before completion — see Open Questions). Weak indirect signal: Bybit-TradingView connection docs mention sub-account handling as a per-exchange quirk requiring separate setup (tv-hub.org/docs/exchanges), suggesting multi-account/sub-account workflows are not first-class in TradingView's broker-connect model.
- **CandleViewer fit: MODERATE.** Since the user base is "one user + a few account managers," native multi-account/sub-account switching (view different managers' books, place trades on behalf of sub-accounts) is in scope and should be designed in from the start given Bybit UTA sub-account support.

**Gap 24 — Performance/lag with many indicators or heavy charts: not corroborated with direct evidence in this research pass (queries for this were rate-limited before completion). Commonly cited in general tech-support forums but not verified here — flagged as an open question rather than a confirmed finding.**

---

## 4. Summary table: gap → CandleViewer fit

| # | Gap (short) | Category | Evidence strength | CandleViewer fit |
|---|---|---|---|---|
| 1 | No true tick bid/ask footprint (estimated only) | Order flow | Strong (TV's own script docs) | **Strong** — Bybit trade-stream taker side |
| 2 | No DOM/liquidity heatmap | Order flow | Moderate (comparison articles) | **Strong** — Bybit orderbook WS |
| 3 | Footprint gated to Premium/Ultimate | Order flow / pricing | Strong (TV script requirements) | **Strong (moot)** — no tiers |
| 4 | Footprint data thins on old/higher-TF bars | Order flow / data | Strong (TV script docs) | Moderate — depends on our retention design |
| 5 | Aggregated OI/liquidations exchange-list-limited | Data | Moderate (inferred/synthesis) | Low now / High later (multi-exchange) |
| 6 | Historical bar count capped by tier | Data | Strong (pricing page) | **Strong (moot)** |
| 7 | Bybit-TV connection expires every 24h | Trading | Strong (Bybit help center) | **Strong** |
| 8 | No native Bybit automation; third-party bridge quirks | Trading | Strong (tv-hub.org docs) | **Strong** |
| 9 | Paper trading has perfect, unrealistic fills | Trading | Strong (coincub.com + tv-hub demo-vs-testnet note) | **Strong** — use Bybit demo mode |
| 10 | OCO/bracket restrictions (can't attach to open positions, chart-click) | Trading | Moderate (PickMyTrade/Tradovate-specific but illustrative) | **Strong** |
| 11 | No native scale-in ladders / rule-based exits | Trading | Weak-moderate (inferred) | **Strong** |
| 12 | Alert count/watchlist-alert limits, expiry | Alerts | Strong (Reddit + pricing page) | **Strong (moot)** |
| 13 | Webhook 3s timeout, no retry, latency | Alerts | Strong (dedicated blog + measured dataset) | **Strong** — no webhook relay needed |
| 14 | No true tick backtest; bar-close fill model | Pine/backtest | Strong (multiple independent blogs) | Strong but long-term (needs tick store) |
| 15 | No external API/DB/WS/ML from Pine | Pine/backtest | Strong (official docs + pineify) | **Strong** — real backend, no sandbox |
| 16 | Repainting / peek-into-future results | Pine/backtest | Strong (TV's own help center) | Moderate — avoid by design |
| 17 | No native full automation; fragile bridges | Automation | Moderate (WebSearch synthesis) | **Strong** |
| 18 | 2026 price hikes 17-20% | Pricing | Strong (dedicated blog + Reddit) | **Strong (moot)** |
| 19 | Poor support, billing issues, 1.6/5 Trustpilot | Support/billing | Strong (multiple review sites) | **Strong (moot)** |
| 20 | Bar Replay tier-gated, buggy, no fill simulation | Replay | Strong (5 sources + Reddit thread) | Strong but long-term |
| 21 | Trailing stop/OCO support inconsistent per broker | Trading | Moderate (comparison table) | **Strong** |
| 22 | No hotkey-driven, DOM-ladder one-click order entry | Trading UX | **Confirmed this pass** (TV support docs + comparison sources) | **Strong** |
| 23 | Multi-account/sub-account not first-class (24h re-auth, no in-chart toggle) | Trading UX | **Confirmed this pass** (Bybit help center + TV charting-library docs) | **Strong** |
| 24 | General performance/lag complaints | Performance | Not corroborated this pass (see §3.13) | Unknown |

---

### 3.9 Hotkeys / one-click order entry / DOM ladder trading (was Open Question 1 — now researched)

**Gap 22 — TradingView's "one-click trading" toggle covers panel Buy/Sell buttons and right-click context menu, but there is no true hotkey-bindable, ladder-native order entry (click-a-price-row-with-a-key rather than a mouse).**
- TradingView's own support docs confirm one-click trading exists as a settings toggle for placing/modifying/canceling orders and closing positions without confirmation dialogs, via Buy/Sell buttons, right-click menu, and general keyboard shortcuts (tradingview.com/support/solutions/43000480920). This is real and native — not a gap in itself.
- The DOM (Depth of Market) panel does support click-to-trade on the ladder (market/limit/stop by clicking a price row), but **requires the connected broker to provide Level 2 data**; it is unavailable on broker connections without L2 (financialtechwiz.com/post/tradingview-order-book-dom).
- The specific gap: there is no first-class, user-programmable hotkey system for ladder-based order entry the way dedicated order-flow platforms (Bookmap, Sierra Chart, NinjaTrader, Jigsaw) provide — e.g., a single keypress to buy/sell at the ladder row under the cursor, or hotkey-driven order-size presets/flattening bound to the DOM itself. TradingView's shortcuts are chart/panel-level, not ladder-level.
- **CandleViewer fit: STRONG.** This maps directly onto the "fast/customised order controls" requirement. A DeepDOM-style ladder with fully user-bindable hotkeys (buy/sell-at-price, flatten, cancel-all, size presets, OCO-attach) is straightforward to build against Bybit's REST/WebSocket order API and is a clear differentiator vs. TradingView's mouse-first DOM.
- Sources: https://www.tradingview.com/support/solutions/43000480920-i-d-like-to-place-orders-without-having-to-confirm-them-every-time/ ; https://www.financialtechwiz.com/post/tradingview-order-book-dom/ ; https://www.financialtechwiz.com/post/tradingview-shortcuts/

### 3.10 TradingView pricing — corrected (was flagged as "disputed $199.95 vs $239.95")

**Correction:** the report's earlier framing of $199.95 vs $239.95 as "disputed/disagreeing figures" was itself incorrect. Both numbers are accurate simultaneously for the **same Ultimate plan**: $239.95/month billed monthly, vs. $199.95/month effective rate when billed annually ($2,399.40/yr). There is no discrepancy to resolve. *Corrected: gap 18 and open question 4 originally implied unresolved conflicting sources; they are not in conflict.*
- Full 2026 tier matrix (per multiple aggregator sources, cross-checked against tradingview.com/pricing structure): Basic (free) → Essential (~$14.95/mo, ~$12.95/mo annual) → Plus (~$29.95/mo, ~$24.95/mo annual) → Premium ($69.95/mo, $59.95/mo annual) → Ultimate ($239.95/mo, $199.95/mo annual). Ultimate is positioned for power users (16 charts/tab, 50 indicators/chart, 1,000 alerts).
- Confidence: moderate-high — figures are consistent across five independent 2026 pricing-aggregator sources, but this pass could not directly re-fetch tradingview.com/pricing itself (fetch tool rate-limited), so treat as corroborated-by-aggregators rather than freshly primary-sourced.
- Sources: https://www.financialtechwiz.com/post/how-much-is-tradingview/ ; https://friendofthetrend.com/tradingview/plan-comparison/ ; https://pineify.app/resources/blog/how-much-does-tradingview-cost-a-complete-pricing-guide ; https://impactwealth.org/how-much-does-tradingview-really-cost-full-pricing-breakdown-2026/ ; https://tradeproperly.com/tradingview-pricing

### 3.11 DeepCharts sub-feature → TradingView community-script mapping (was Open Question 5)

| DeepCharts feature | Closest TradingView community approximation | Native TV equivalent? | Key limitation vs. real order flow |
|---|---|---|---|
| Deep Print / footprint | Footprintchart, FlowSight scripts; native `request.footprint()` (see Gap 1/3) | Partial (Premium/Ultimate-gated, unverified — see footnote §3.1) | Estimated bid/ask split, not true aggressor-side data on most symbols |
| Iceberg detector | "Iceberg Detector [JOAT]" (in.tradingview.com/script/Y4HHvjwz-Iceberg-Detector-JOAT/) — infers hidden iceberg orders from wick/body ratio, local extremes, above-average volume clustering, no L2 needed; "[A618] Liquidity Tracker and Iceberg Detector V2 Pro" (invite-only) | No | Purely inferential from candle/volume shape, not real order-book replenishment detection |
| Stop-run / liquidity sweep | "Liquidity Sweep Detector [DefinedEdge]", "Liquidity Sweep Hunter [BigBeluga]", "Liquidity Sweep Detector Pro [Jos-ProTrader]" — map stop-cluster zones and flag sweep-and-snap-back price action with volume/wick filters | No | Zone modeling based on swing highs/lows + volume, not actual resting stop-order data (no venue exposes that) |
| Imbalance tracker / speed of tape | "Orderflow Detector [OmegaTools]" — combines intrabar price/volume analysis with directional volume imbalance to flag absorption/iceberg/sweep together; closest available proxy for "speed of tape" | No | Explicitly acknowledged (even by script authors) that true tick-by-tick tape speed requires L2/tick data Pine Script cannot access |
| Deep Stats / Big Trades | No dedicated widely-used community equivalent found this pass; large-trade detection is usually folded into the orderflow/footprint scripts above via volume thresholding | No | — |
| Market regime | Not covered in this pass — general regime-detection scripts (volatility/trend-state classifiers) exist broadly on TradingView but weren't evaluated against DeepCharts' specific "market regime" definition | Partial (unverified) | Needs targeted follow-up |
| Aggregated OI / liquidation heatmap | "Liquidation Heatmap ║ BullVision", "Aggregated Open Interest [Alpha Extract]", "liquidation Heatmap [Alpha_Precision_Charts]" — pull multi-exchange OI (Binance/Bybit/OKX/BitMEX/Kraken) and model liquidation clusters via assumed leverage tiers (5x–125x) | No native aggregation feature (confirmed this pass — see §3.12) | Modeled/estimated, not actual per-trader liquidation thresholds — no platform (TV or otherwise) has that data |

- **CandleViewer fit:** all seven DeepCharts sub-features above are buildable from Bybit's own v5 API (public trade stream for footprint/iceberg/sweep/imbalance/speed-of-tape proxies; open-interest and liquidation endpoints for the OI/heatmap category), generally to a *higher* fidelity than the TradingView community scripts, since CandleViewer can use real taker-side tick data rather than Pine Script's derived/candle-shape heuristics. "Market regime" and "Deep Stats/Big Trades" need dedicated design work — flagged as still-open below.
- Sources: https://in.tradingview.com/script/Y4HHvjwz-Iceberg-Detector-JOAT/ ; https://www.tradingview.com/script/FUbo2tfW-Orderflow-Detector-OmegaTools/ ; https://www.tradingview.com/script/b9oLRMRb-Liquidity-Sweep-Detector/ ; https://www.tradingview.com/script/jh37YcU3-Liquidity-Sweep-Hunter-BigBeluga/ ; https://www.tradingview.com/script/cplrUeQl-Liquidity-Sweep-Detector-Pro/ ; https://www.tradingview.com/script/acWxvvzw-Liquidation-Heatmap-BullVision/ ; https://www.tradingview.com/script/cM5WCKBL-Aggregated-Open-Interest-Alpha-Extract/

### 3.12 Aggregated OI / liquidation heatmap / cross-exchange funding — native feature check (was gap #3 in critic list)

**Confirmed: TradingView has no first-party, native aggregated-open-interest liquidation heatmap across exchanges as of 2026.** This functionality exists only via community Pine Script indicators (listed in §3.11), which pull OI from major venues (Binance, Bybit, OKX, BitMEX, Kraken) and model estimated liquidation clusters using assumed leverage tiers — these are estimates, not real per-position liquidation data (no platform has that). TradingView does offer a native per-symbol "Funding Rate" indicator (Financials tab) for major exchanges including Bybit, but it shows only the current rate — **no built-in countdown timer to the next funding settlement**, a recurring pain point for active perpetuals traders; the only fix is third-party browser extensions (e.g., "Funding Rate Overlay" for Binance) rather than anything native or cross-broker.
- **CandleViewer fit: STRONG.** Bybit's v5 API exposes open interest, funding rate, and next-funding-time endpoints/WebSocket topics directly and natively — a live funding countdown and (if desired) a modeled liquidation-density overlay are both straightforward first-party features, with no need to reverse-engineer multi-exchange aggregation the way community TV scripts must.
- Sources: https://www.tradingview.com/support/solutions/43000762390-funding-rate/ ; https://www.tradingview.com/script/IHFS6uCQ-Funding-Rate-CryptoSea/ ; https://chromewebstore.google.com/detail/funding-rate-overlay/jekcilbdpkjbkifblagdhdgifkjfnfll ; https://www.tradingview.com/script/acWxvvzw-Liquidation-Heatmap-BullVision/ ; https://bitsgap.com/blog/crypto-liquidation-heatmap-explained ; https://kalena.ai/blog/liquidation-heatmap-tradingview-why-what-you-see-on-the-chart-isn-t-what-you-think-it-is

### 3.13 Performance/lag with heavy charts (was Open Question 2 — still largely unresolved)

No direct, well-corroborated first-hand complaint threads (Reddit or otherwise) about TradingView chart lag/browser-tab crashes with many indicators were surfaced in this follow-up pass either — searches for this topic were not re-run with dedicated queries in this session due to tool budget prioritization toward the other 8 gaps. **This remains an open question**; flagged again in Open Questions below rather than falsely marked resolved.

### 3.14 Multi-account / sub-account support (was Open Question 3 — now researched)

**Gap 23 — Sub-account switching on TradingView (incl. via Bybit) is not seamless: the broker-connection session expires after ~24 hours (forcing reconnection), and there is no in-chart one-click toggle between sub-accounts.**
- TradingView officially supports connecting either a Bybit Main Account or a Sub-account during broker setup, and will prompt the user to switch if the active account lacks sufficient balance — but switching *between* sub-accounts mid-session requires going back through the connection/account-management flow rather than a single in-chart toggle (bybit.com/en/help-center — "How to Get Started With Trading on Bybit From TradingView").
- Bybit itself allows up to 5 Standard Sub-accounts (up to 20 for VIP/KYC-verified users) (bybit.com/en/help-center/article/FAQ-Standard-Subaccount), but this is a Bybit-side limit, not a TradingView one.
- TradingView's Advanced Charts / Trading Terminal documentation does describe a "multiple accounts" capability at the charting-library level (tradingview.com/charting-library-docs/latest/trading_terminal/account-manager/multiple-accounts/), suggesting the underlying framework supports multi-account UX — but this is a broker/integrator-side implementation detail, not something end-users of the hosted TradingView.com product control, which likely explains why the switching experience feels incomplete for retail Bybit users specifically.
- **CandleViewer fit: MODERATE→STRONG,** even though this is explicitly a lower-priority item for a single/few-user private tool per the brief: since CandleViewer owns the account-manager UI directly, a clean in-chart sub-account switcher (no 24h re-auth, no reconnect flow) is cheap to build correctly from the start and avoids replicating this friction for the "few account managers" use case.
- Sources: https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Trading-on-Bybit-From-TradingView ; https://www.bybit.com/en/help-center/article/FAQ-Standard-Subaccount ; https://www.tradingview.com/broker/Bybit/reviews/ ; https://www.tradingview.com/charting-library-docs/latest/trading_terminal/account-manager/multiple-accounts/

---

## 5. Key takeaways for CandleViewer architecture

1. **The single biggest, best-evidenced gap is genuine order flow** — TradingView's footprint/DOM features are explicitly acknowledged by TradingView's own script ecosystem as estimates, not real bid/ask execution data, and are paywalled behind Premium/Ultimate. Bybit's WebSocket `publicTrade` and `orderbook` topics give CandleViewer the real taker-side and depth data needed to build an honest footprint/DeepDOM — this should be treated as the flagship differentiator.
2. **Removing the TradingView-broker-bridge architecture entirely** (no 24h re-auth, no third-party webhook relay, no 3-second timeout/no-retry risk, no lowest-common-denominator order types) resolves a cluster of independently-documented pain points (Gaps 7, 8, 13, 17, 21) simply by virtue of talking to Bybit's v5 API directly.
3. **Realistic paper trading is a solved problem if we lean on Bybit's own demo-trading environment** (real matching engine, real liquidity) rather than building a synthetic fill simulator — this directly addresses the most detailed, evidence-backed paper-trading complaint (Gap 9), and third-party automation vendors already recommend this exact approach over TradingView's native paper trading.
4. **Tick-level replay/backtesting (DeepCharts "tick replay") and true historical footprint depth are valuable but should be phased**, since they require building and maintaining our own tick-level historical data store — treat as a later milestone, not v1, given this is a research-only phase with no sprint planning yet.
5. **Pricing/billing/support complaints are structurally inapplicable** to a private tool, but they matter as context: much of TradingView's negative sentiment is about the business layer, not the charting engine — validating that a "TradingView killer, but private and free of tiers" framing is coherent and not just chasing a non-issue.
6. **Weakest-evidenced items (hotkeys/ladder trading, multi-account UX, general performance/lag)** should be validated with the user's own first-hand experience of TradingView/Bybit before being treated as confirmed requirements — flagged explicitly in Open Questions below.

---

## Sources

- https://es.tradingview.com/scripts/footprint
- https://th.tradingview.com/scripts/footprint
- https://th.tradingview.com/scripts/footprint/page-2
- https://kr.tradingview.com/scripts/footprint
- https://th.tradingview.com/scripts/footprintchart?script_access=all
- https://bookmap.com/de/blog/comparing-bookmap-to-dom-footprint-and-volume-profile
- https://toolkit4trading.digitalpress.blog/footprint-charts
- https://supa.is/article/tradingview-volume-profile-vs-footprint-chart-order-flow-analysis-2026
- https://www.gocharting.com/blog/footprint-charts/comparison-bookmaps-with-footprints-volume-profiles-and-dom
- https://nexusfi.com/a/market-structure/order-flow-heatmaps-liquidity-visualization
- https://www.reddit.com/r/TradingView/comments/1kehx2a/tradingviews_pricing_misses_the_mark_for_casual
- https://www.reddit.com/r/TradingView/comments/1je3nth/cant_use_alerts_on_free_plan_anymore
- https://www.reddit.com/r/TradingView/comments/1iecpoo/major_complaint_regarding_premium_plan_user
- https://www.tradingview.com/pricing
- https://jojapi.com/hub/api/tradingview/pricing
- https://github.com/akmoy655/tradingview
- https://www.cmcmarkets.com/en-gb/trading-platforms/tradingview/tradingview-pricing-explained
- https://www.g2.com/products/tradingview/pricing
- https://pro.stockalarm.io/blog/tradingview-price-increase-2026
- https://pineify.app/resources/blog/tradingview-subscription-offers-complete-guide-to-plans-pricing-and-discounts
- https://tickerly.net/pine-script-strategy-tester-limitations
- https://www.tradingview.com/pine-script-docs/v5/writing/limitations
- https://blog.traderspost.io/article/pine-script-backtesting-limitations-and-validation
- https://nexusfi.com/a/platforms/pine-script-strategy-backtesting
- https://www.tradingview.com/blog/en/new-features-pine-script-realistic-backtests-heikin-ashi-built-ins-for-symbol-info-39050/
- https://www.tradingview.com/support/folders/43000548798-troubleshooting-scripts-and-strategies
- https://pineify.app/pine-script-limitations
- https://stackoverflow.com/questions/72593336/backtesting-precision-use-bar-magnifier
- https://crosstrade.io/blog/pine-script-repainting
- https://pinescriptstrategy.com/posts/top-5-pine-script-backtesting-mistakes-to-avoid
- https://www.tv-hub.org/docs/exchanges
- https://www.tv-hub.org/docs/exchanges/bybit
- https://coincub.com/blog/tradingview-paper-trading
- https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Trading-on-Bybit-From-TradingView
- https://www.tradingview.com/broker/Bybit/reviews
- https://nexusfi.com/a/platforms/tradingview-broker-integration
- https://www.tv-hub.org/blog
- https://docs.pickmytrade.trade/docs/connecting-your-tradovate-account-to-tradingview-pickmytrade-guide
- https://bitcointalk.org/index.php?topic=5210163.0
- https://bikotrading.com/atas-vs-tradingview
- https://tradingbrokers.com/atas-vs-tradingview/
- https://sourceforge.net/software/compare/ATAS-vs-TradingView/
- https://tradingsfx.com/blog/tradingview-bar-replay-limits
- https://www.zeiierman.com/blog/tradingview-bar-replay-data-limits
- https://www.redditmedia.com/r/TradingView/comments/1je1xwf/wtf_is_wrong_with_the_replay_feature_im_a_premium/
- https://tradereplay.app/blog/tradingview-replay-limitations
- https://entriq.ai/en/blog/3-tradingview-bar-replay-limitations
- https://www.tradingview.com/script/HQgxb0Ul-Open-Interest-liquidation-map-Ox-kali/
- https://br.tradingview.com/script/0o1cu0xB/
- https://in.tradingview.com/scripts/openinterest/
- https://tradingview.pissedconsumer.com/complaints/RT-P.html
- https://www.trustpilot.com/review/tradingview.com
- https://www.complaintsboard.com/tradingview-b134859
- https://tradersunion.com/reviews/tradingview-com/
- https://www.tradingview.com/news/financemagnates:5dd5f7671094b:0-trustpilot-fake-reviews-and-the-complicated-truth-about-transparency/
- https://blog.pickmytrade.trade/why-your-tradingview-webhook-timeout-the-3-second-limit/
- https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/
- https://ultramegatrader.com/blogs/news/tradingview-webhook-timeout-request-took-too-long
- https://clearedge.trading/post/tradingview-alert-delay-causes-solutions
- https://www.tv-hub.org/blog/tradingview-webhook-latency/
- https://supa.is/article/tradingview-webhook-retry-queue-fix-duplicate-and-out-of-order-alerts-2026
- https://finestel.com/blog/auto-trading-in-tradingview-guide/
- https://in.tradingview.com/scripts/algotrading/
- https://blog.ontologytrading.com/how-to-automate-a-tradingview-strategy-in-2026-full-guide/
- https://www.tradingview.com/support/solutions/43000480920-i-d-like-to-place-orders-without-having-to-confirm-them-every-time/
- https://www.financialtechwiz.com/post/tradingview-order-book-dom/
- https://www.financialtechwiz.com/post/tradingview-shortcuts/
- https://chartwisehub.com/tradingview-cheat-sheet/
- https://www.financialtechwiz.com/post/how-much-is-tradingview/
- https://friendofthetrend.com/tradingview/plan-comparison/
- https://pineify.app/resources/blog/how-much-does-tradingview-cost-a-complete-pricing-guide
- https://impactwealth.org/how-much-does-tradingview-really-cost-full-pricing-breakdown-2026/
- https://tradeproperly.com/tradingview-pricing
- https://in.tradingview.com/script/Y4HHvjwz-Iceberg-Detector-JOAT/
- https://in.tradingview.com/scripts/icebergorders/
- https://in.tradingview.com/script/xvqS2qCm-A618-Liquidity-Tracker-and-Iceberg-Detector-V2-Pro/
- https://www.tradingview.com/script/FUbo2tfW-Orderflow-Detector-OmegaTools/
- https://www.tradingview.com/script/b9oLRMRb-Liquidity-Sweep-Detector/
- https://www.tradingview.com/script/jh37YcU3-Liquidity-Sweep-Hunter-BigBeluga/
- https://www.tradingview.com/script/cplrUeQl-Liquidity-Sweep-Detector-Pro/
- https://github.com/PineGen-AI/liquidity-sweep-market-structure-strategy
- https://www.tradingview.com/script/acWxvvzw-Liquidation-Heatmap-BullVision/
- https://www.tradingview.com/script/cM5WCKBL-Aggregated-Open-Interest-Alpha-Extract/
- https://br.tradingview.com/script/tftKHphr/
- https://bitsgap.com/blog/crypto-liquidation-heatmap-explained
- https://kalena.ai/blog/liquidation-heatmap-tradingview-why-what-you-see-on-the-chart-isn-t-what-you-think-it-is
- https://www.tradingview.com/support/solutions/43000762390-funding-rate/
- https://www.tradingview.com/script/IHFS6uCQ-Funding-Rate-CryptoSea/
- https://chromewebstore.google.com/detail/funding-rate-overlay/jekcilbdpkjbkifblagdhdgifkjfnfll
- https://www.bybit.com/en/help-center/article/FAQ-Standard-Subaccount
- https://www.tradingview.com/charting-library-docs/latest/trading_terminal/account-manager/multiple-accounts/
- https://www.tradingview.com/pine-script-docs/en/v5/concepts/Requests.html
- https://pineify.app/resources/blog/understanding-pine-scripts-requestsecurity-function

## Open questions

1. ~~Hotkeys/one-click/ladder trading on TradingView~~ **RESOLVED (§3.9):** confirmed as a real gap — TradingView has panel-level one-click trading and DOM click-to-trade (L2-broker-dependent) but no user-programmable, ladder-native hotkey system comparable to Bookmap/Sierra Chart/NinjaTrader/Jigsaw.
2. **General performance/lag complaints with many indicators/heavy charts** — still not corroborated with direct sources after this follow-up pass either (see §3.13); genuinely unresolved, not merely under-searched. Recommend a targeted future pass specifically on r/TradingView + r/Daytrading with direct Reddit access if this becomes decision-relevant.
3. ~~Multi-account / sub-account support complaints~~ **RESOLVED (§3.14):** confirmed — 24h broker re-auth requirement and no in-chart sub-account toggle are real, evidenced gaps (Bybit help center + TradingView charting-library docs), though this remains lower-priority for CandleViewer's single/few-user scope per the original brief.
4. ~~Exact current (Sept 2026) TradingView pricing/tier feature matrix — sources disagree slightly on numbers~~ **RESOLVED (§3.10, corrected below):** $199.95 and $239.95 are not conflicting figures — they are the same Ultimate plan's annual-billing ($199.95/mo, billed yearly) vs. monthly-billing ($239.95/mo) prices. No disagreement; the original framing as "disputed" was itself the error. *Corrected: gap 18's citation and open question 4 have been amended — see §3.10.*
5. ~~Speed of tape / imbalance tracker / stopruns / iceberg detector specific TradingView equivalents~~ **RESOLVED (§3.11):** full mapping table added for Deep Print, iceberg detector, stop-run/sweep, imbalance/speed-of-tape, and aggregated OI/liquidation heatmap. **Still open:** no dedicated TradingView community equivalent was identified this pass for "Deep Stats" or "Big Trades" specifically as named DeepCharts features, nor for "market regime" classifiers matched to DeepCharts' specific definition — these need a further targeted search pass.
6. **Verification of Reddit thread content** — still unresolved; this follow-up pass did not perform direct Reddit/old.reddit.com scraping (continued reliance on WebSearch synthesis after Parallel Search MCP hit its rate limit again immediately at the start of this session). Recommend a dedicated pass with direct Reddit access before using any exact quotes in outward-facing docs.
7. **Rate limiting continued to constrain this follow-up pass** — the Parallel Search MCP free-tier limit was already exhausted at the start of this session (all `web_search`/`web_fetch` calls failed immediately), so every new query in this pass, including the primary-source verification checks (Pine Script docs, TradingView pricing page, Trustpilot live page, official webhook docs), had to route through the WebSearch fallback tool, which returns synthesized summaries rather than raw page excerpts. Confidence markers have been added inline per claim; nothing here should be treated as independently re-verified against the raw primary-source HTML — only against WebSearch's synthesis of it.
8. **New unresolved item — "Deep Stats" / "Big Trades" / "market regime" TradingView equivalents** (surfaced by §3.11's mapping exercise): unlike the other five DeepCharts sub-features, no specific, well-known community script could be identified for these three in this pass. Needs a dedicated follow-up search.
