# 21 — Gap Analysis: TradingView vs. DeepCharts vs. CandleViewer

Synthesis pass, 2026-09-14. Sources: digests 01–12, 23 (see citations inline as `[NN]`). This document does not introduce new research — it recombines the 13 source digests into a decision-oriented narrative for the owner.

---

## 1. Where TradingView falls short for a crypto/Bybit order-flow trader (ranked)

Ranked by how directly each gap blocks the owner's actual workflow (order-flow reading → fast execution → rule-based risk), using evidence strength from `[03]`.

| Rank | Gap | Evidence | Why it matters here |
|---|---|---|---|
| 1 | **No true tick bid/ask footprint** — native `request.footprint()` (Premium/Ultimate only, unverified tier) uses estimated splits, not real aggressor-side data; thins/blanks on older bars and higher timeframes | Strong `[03#1,#4]` | Order-flow reading is the whole point of this tool. Bybit's `publicTrade` WS gives the real taker side (`S` field) directly — no estimation needed `[08§2]`. |
| 2 | **No DOM/order-book liquidity heatmap** (vs. Bookmap/Sierra Chart/ATAS) | Moderate `[03#2]` | DeepDOM-style visibility is a named goal of this project; TV has only a basic ladder row, no heatmap `[01, §10 table]`. |
| 3 | **No native Bybit execution — broker-bridge architecture** — 24h forced re-auth, no native webhook/automation (3rd-party bridges like PickMyTrade with inconsistent TP fields), 3-second webhook timeout with no retry on timeout, ports 80/443 only | Strong `[03#7,#8,#13]` | Every fragility point here (re-auth, timeout, bridge quirks) evaporates once CandleViewer talks to Bybit v5 REST/WS directly `[03, key rec #2]`. |
| 4 | **Paper trading = idealized fills, no slippage/queue modeling** | Strong `[03#9]` | Bybit's own demo-trading environment has a real matching engine and now confirmed WS support (`wss://stream-demo.bybit.com`) `[03#9, 12§1]` — strictly better than building a synthetic simulator. |
| 5 | **No native scale-in, laddered entries, or rule-based auto-exits** without Pine strategies/3rd-party bots | Weak-moderate `[03#11]` | This is core scope for CandleViewer (Rule Builder, View 16 `[23#16]`), not an add-on. |
| 6 | **OCO/bracket limitations** — can't attach OCO to open positions on many brokers; Bybit's own OCO is spot/UI-only, not exposed via API at all `[09§2]` | Strong `[03#10]` | Confirms CandleViewer must build true OCO client-side (race two orders, cancel loser on fill) regardless of platform — TV doesn't solve this generically either. |
| 7 | **Alert/webhook limits** — 3s webhook timeout, no retry on timeout, 3/20/100/400/1,000 alert caps by tier, 1-2mo expiry except top tier | Strong `[03#12,#13]` | Moot for a private tool with no tiers, but validates "uncapped, non-expiring, rule-based" as a real differentiator, not vanity. |
| 8 | **Pine Script sandbox** — no external API/HTTP/WebSocket, no ML/DB, hard 40 `request.*()` calls/bar, 2-min compile limit, 20-40s execution cap, single-symbol trading only | Strong (official docs) `[03#15, 02§8]` | Any serious order-flow/rule logic (footprint math, iceberg heuristics, multi-account risk rules) is architecturally impossible in Pine — needs a real backend. |
| 9 | **No true tick-level backtest** — bar-close fill model default, Bar Magnifier only approximates, Deep Backtesting caps at 2M bars/1M trades, disabling default fill assumption cuts perf 15-30% | Strong `[03#14, 02§9]` | Long-term item (needs own tick store) but flags that "backtest looked good on TV" is not trustworthy for microstructure strategies. |
| 10 | **No ladder-native, user-programmable hotkey system** (DOM click-to-trade exists but requires broker-supplied L2; one-click Buy/Sell toggle is real, not a gap) | Confirmed gap, narrowly scoped `[03#22, §3.9]` | Directly maps to View 13 (Trading Terminal) hotkey requirements `[23#13]`. |
| 11 | **Multi-account/sub-account UX** — 24h re-auth per broker session, no in-chart sub-account toggle | Confirmed, Bybit-side cap not TV's fault `[03#23]` | Lower priority given small user base (≤5 managers), but still a real UX gap TV doesn't solve. |
| 12 | **Aggregated OI/liquidations/funding limited to a fixed exchange list**; historical bar limits scale by tier (5K–40K bars) | Moderate/Strong, both **moot** for self-hosted single-exchange tool `[03#5,#6]` | Included for completeness; not an actual gap once self-hosted against one's own DB. |
| 13 | **Pricing, support quality, Trustpilot 1.6/5** | Strong but **moot** — no subscription, no tiers, no support queue | Validates the "private tool, no vendor risk" framing rhetorically, not functionally. |

**Bottom line** `[03, key rec #1-2]`: the flagship differentiator is genuine order flow built directly from Bybit's own real tick/depth data, combined with cutting out the TradingView-broker-bridge layer entirely by talking to Bybit v5 directly.

---

## 2. What DeepCharts adds and why it matters (plain-language glossary for the owner)

DeepCharts (built on the "Volumetrica" engine) is a suite of three products — **Deepchart** (footprint/order-flow charting), **DeepDOM** (order-book heatmap/ladder), **DeepGamma** (options gamma, not relevant — crypto has no equivalent liquid options market yet) `[05]`. None of it natively supports crypto exchanges at all — it's a futures/equities tool `[04§21, 05]`. Below is what each concept *means* and why a Bybit trader would care.

- **Footprint / bid-ask cells ("Deep Print")** — Instead of a plain candle, each price level inside a candle shows how much volume traded by market-buyers (askers, "lifted the offer") vs. market-sellers (bidders, "hit the bid"). This reveals *who was aggressive* at each price, not just where price ended up. Bybit's `publicTrade` stream already tags every trade with the aggressor side (`S`=Buy/Sell), so this is fully buildable, no estimation `[04#1, 08§3]`.
- **Delta & CVD (Cumulative Volume Delta)** — Delta = (aggressive buy volume − aggressive sell volume) for one bar; CVD is the running total across many bars. A rising price with falling CVD ("divergence") is a classic warning that the move lacks real buying conviction. Fully computable from the same trade stream `[04#2,#10, 08§2]`.
- **Imbalances** — When one side dramatically outweighs the diagonal opposite (e.g. buy volume at price P is 3x+ the sell volume one tick below), that's flagged as a directional pressure signal; several in a row ("stacked imbalance") is a stronger signal. Pure math on footprint cells, no special feed needed `[04#5, 08§3]`.
- **POC / Value Area** — POC ("Point of Control") = the single price level with the most volume traded in a period; Value Area = the price band (typically ~70%) around POC containing most of the volume. Together they show where the market "agreed" on fair value vs. where it passed through quickly. Computable locally from trade history `[04#3, 08§4]`.
- **Profiles (Volume Profile / TPO)** — A sideways histogram of volume-by-price (or, for TPO, time-spent-at-price) built up over a session/day/week. Used to find support/resistance shelves invisible on a normal candle chart `[04#3,#11, 08§4]`.
- **Heatmap (DeepDOM)** — A visual, color-coded view of the resting limit-order book (how much size is waiting to buy/sell at each price, updating live) laid behind a clickable price ladder. Shows where big passive orders are sitting, which price levels are likely to act as friction. Buildable from Bybit's L2 order book WS (`orderbook.50/200/500`) at the "aggregated" (MBP) level — not per-individual-order (MBO), which Bybit doesn't expose `[04#20, 05§3, 08§9]`.
- **Big Trades** — Flags unusually large individual trades (or clusters of trades in a tight time window) as markers/bubbles on the tape, sized/colored by side — a proxy for "smart money" or institutional activity. Fully buildable from trade-size distribution `[04#4, 08§12]`.
- **Speed of tape** — A live gauge of how many trades (or how much volume) are printing per second, and whether that rate is accelerating vs. its own recent baseline. Useful for spotting the moment before a fast move. Pure rate-of-events math, no special feed `[04#8, 08§13]`.
- **Iceberg / stop-run detectors** — *Iceberg*: a large hidden order that keeps refreshing at the same price after being filled, detected by watching a resting size repeatedly "reload." *Stop-run*: a fast price spike through a well-known high/low that sweeps resting stop-loss orders before (often) reversing. Both require true order-level (MBO) data to detect with certainty on other platforms; Bybit exposes neither MBO nor a genuine order-count feed, so these must be built as **heuristic, confidence-scored proxies** (reload patterns, sweep+reversal patterns), clearly labeled as estimates, not certainties `[04#24, 05§4.9, 08§12]`.
- **Absorption** — When a large amount of aggressive volume hits a price level and price *doesn't move* — meaning passive resting orders are "absorbing" the aggression. Signals potential exhaustion of the aggressive side. Buildable from footprint cells (large volume, small price move) `[04#25, 08§15]`.
- **Market regime** — A classifier that labels current conditions as trending/ranging/volatile/calm, so a trader knows whether trend-following or mean-reversion tactics fit better right now. Turns out **DeepCharts doesn't have one single confirmed "Market Regime" feature at all** — it's built from standard building blocks (ADX, ATR, book-thickness clustering) `[04#25 correction, 05, 08§16]`. CandleViewer would need to design its own from these primitives — not a parity gap, an open design task.

**Overall relevance**: 26 of ~27 catalogued DeepCharts/DeepDOM sub-features are assessed as fully or mostly buildable from Bybit's public data at *higher fidelity* than most community TradingView Pine scripts (which only approximate order-flow from OHLCV) `[03, DeepCharts↔TV mapping table]`. The two structural exceptions are true iceberg/MBO detection (no L3 feed exists on any crypto exchange, not just Bybit) and options-gamma (crypto options are out of scope for now).

---

## 3. CRITICAL GAPS CANDLEVIEWER FILLS (the intersection)

These are gaps that exist at the *intersection* of TV's weaknesses and DeepCharts' non-existent crypto support — i.e., gaps neither incumbent solves for this exact user, each made concrete with a user story.

### 3.1 Bybit-native order flow (no exchange integrates real Bybit tick/depth data into an order-flow view)
- **User story**: "I want to see whether the last leg up on BTCUSDT was driven by real aggressive buying or just illiquid drift, on Bybit specifically, right now — not on Binance data pretending to represent Bybit."
- **TV lacks**: footprint is estimated, not true tape, and gated behind Premium/Ultimate tiers anyway `[03#1,#3]`.
- **DeepCharts lacks**: no crypto exchange connector exists at all, Bybit or otherwise `[04§21, 05]`.
- **CandleViewer fills it**: `publicTrade.{symbol}` + `orderbook.{depth}.{symbol}` WS give real Bybit taker-side and depth data natively `[08§2,§9]`.

### 3.2 DOM/heatmap visibility on Bybit
- **User story**: "I want to see resting liquidity walls on Bybit's actual order book before I place a limit order, not guess from a plain ladder."
- **TV lacks**: only a basic DOM row for supported brokers, no heatmap `[01, §10 table]`.
- **DeepCharts lacks**: Windows-only desktop app with zero crypto feed support `[05§2]`.
- **CandleViewer fills it**: `orderbook.50/200/500` gives MBP-level heatmap+ladder data natively, cross-platform (web) `[04#20, 08§9]`.

### 3.3 Fast, integrated execution (no bridge, no 24h re-auth, no webhook fragility)
- **User story**: "I want one click from 'I see a setup' to 'order is live' — not chart→alert→webhook→3rd-party-bridge→broker, any one link of which can silently fail."
- **TV lacks**: broker-bridge architecture, 24h forced re-auth, 3-second webhook timeout with no retry, ports 80/443-only `[03#7,#8,#13,#17]`.
- **DeepCharts lacks**: no execution connector to any crypto exchange exists `[05§21]`.
- **CandleViewer fills it**: direct Bybit v5 REST + private WS order/execution streams, single integrated process `[06§5,§10, 03 key rec #2]`.

### 3.4 Rule-based risk that actually executes (not just alerts)
- **User story**: "I want 'move stop to breakeven after 1R, tighten by ATR after that, and hard-flatten everything if today's loss hits $X' to run unattended and correctly, 24/7, without me watching the screen."
- **TV lacks**: Pine sandbox forbids external calls/persistent multi-symbol state; alert→webhook→bridge chain is fragile and rate-limited `[03#13,#15]`.
- **DeepCharts lacks**: Pattern Builder is a visual condition-builder for *backtesting/flagging*, not a live order-executing rule engine tied to a broker `[04#15]`.
- **CandleViewer fills it**: a real Rule Builder (View 16) with condition→action DSL executing via the same order path as manual trading, metric vocabulary spanning OHLCV/delta/CVD/OI/funding/regime `[09§7, 23#16]`.

### 3.5 Demo/live parity with a real matching engine
- **User story**: "I want to test a new setup risk-free but against the *same* liquidity/fill behavior I'll get live, not an idealized simulator that lies to me about slippage."
- **TV lacks**: paper trading = perfect fills, no slippage/queue modeling `[03#9]`.
- **DeepCharts lacks**: not applicable — no execution layer for crypto at all.
- **CandleViewer fills it**: Bybit's own demo-trading environment (`api-demo.bybit.com`, real matching engine, now-confirmed WS support) used directly instead of a synthetic simulator `[03#9, 12§1]`.

### 3.6 Multi-account / multi-manager with real isolation
- **User story**: "I want to hand a manager trading access to a bounded slice of capital, watch everything they do, and instantly freeze them if something looks wrong — without them being able to see or touch other managers' books."
- **TV lacks**: broker-bridge re-auth every 24h, no in-chart sub-account switcher; TV has no concept of "managers" at all `[03#23]`.
- **DeepCharts lacks**: single-user desktop tool, no multi-account/RBAC concept `[05, no reference found]`.
- **CandleViewer fills it**: one Bybit sub-account per manager (isolation of funds/positions/orders), scoped API keys (trade+read-only, withdrawal always off), app-layer RBAC (Owner/Manager/Viewer), owner kill-switch, audit log `[12§2.1-2.4, 09§10]`.

### 3.7 Affordable, self-hosted, no vendor lock-in
- **User story**: "I don't want to pay $60-240/mo indefinitely for a chart tool plus $39-100/mo for a DOM tool plus per-manager broker-bridge subscriptions, when I can run one box I own."
- **TV lacks**: this is table stakes SaaS pricing they can't drop `[03#18]`.
- **DeepCharts lacks**: same — $59-100/mo Deepchart tiers, $39/mo DeepDOM, both Windows-only `[04 pricing, 05 pricing]`.
- **CandleViewer fills it**: one self-hosted monolith, zero subscriptions, full control of retention/features (see §7 cost comparison).

---

## 4. What we deliberately drop

Scoped out, not because they're impossible but because they don't serve this project's actual use case (private, few users, crypto/Bybit-only, order-flow + execution focus):

- **True MBO (per-order) iceberg/stop-run detection** — no crypto exchange, Bybit included, exposes L3/order-level data publicly. All iceberg/stop-run/absorption features become confidence-scored heuristics, explicitly labeled "(estimated)" in the UI, never presented as certain `[04#9, 08§12, 23 cross-cutting notes]`.
- **DeepGamma / options gamma exposure** — SPX-style GEX relies on real CBOE market-maker data with no crypto analog at that fidelity; Deribit has public options OI/IV but building a credible GEX model is a distinct, deferred research/design phase `[05§5]`.
- **Multi-exchange aggregation (Binance/OKX/etc.)** — v1 is Bybit-only by design; aggregated OI/liquidation-heatmap-style features that TV/Coinglass/Hyblock offer across many exchanges are explicitly deferred to "later, if ever" `[03#5]`.
- **TradingView's Advanced Charts library** — free license terms explicitly prohibit private/unpublished/internal tools; a commercial license is uncertain to even be offered for this use case. Not pursuing it; building on OSS Lightweight Charts (Apache-2.0) instead `[02§16]`.
- **Pine Script / Pine-script-compatible scripting sandbox** — no need to replicate Pine's sandboxed mini-language; a real Python backend removes the reason for a restricted scripting layer entirely `[03#15]`.
- **TradingView-style social/community layer** (ideas feed, publish scripts, follow other traders) — irrelevant for a private single-owner tool.
- **Copy Trading as a distinct API surface** — confirmed to be just a thin wrapper over standard order creation requiring Master Trader UI approval; not useful for the manager-fanout model, de-scoped `[06§18]`.
- **Deep-M Effort / Deep-M IVB** (DeepCharts' proprietary futures-tuned trend/ORB models) — proprietary, undocumented algorithms tuned to specific futures instruments/sessions; not portable to 24/7 crypto without full redesign, and their exact logic isn't published to replicate anyway `[04#12,#13]`.
- **True tick-level backtesting / multi-year deep historical footprint replay** — requires a mature, long-running local tick store; phased as a later milestone once the recorder has meaningfully long history, not a v1 commitment `[03#14,#20, 08 key recs]`.
- **Options trading (Bybit `option` category)** — out of initial scope entirely; linear/inverse perps and spot are the focus `[06§3]`.
- **Server-side/broker-native OCO** — Bybit doesn't expose this via API at all (spot OCO is UI-only); CandleViewer emulates true OCO client-side rather than chasing a feature the exchange itself doesn't offer over the API `[09§2]`.

---

## 5. Feasibility constraints from Bybit data + mitigations

| Constraint | Detail | Mitigation |
|---|---|---|
| **No L3/MBO feed** | Bybit exposes only aggregated order-book levels (MBP: `orderbook.1/50/200/500/1000`), never per-order IDs `[04§16, 08§9]` | Iceberg/stop-run/absorption presented as heuristic, confidence-scored, visibly labeled "(estimated)" — never as certainties `[23 cross-cutting notes]` |
| **No REST tick-level history beyond a short recent window** | `recent-trade` REST caps at 1000 (linear/inverse), 60/500 default by category; no deep historical trade REST endpoint at all `[06§4, 08§1]` | Recorder-first architecture from day one: continuous WS capture (`publicTrade`, `orderbook.*`, `allLiquidation`) persisted locally is the actual source of truth; REST only for backfill/cross-check `[08 key recs]` |
| **Trade history for the pre-launch gap only via bulk CSV dumps** | `public.bybit.com/trading/{SYMBOL}/` — no auth, scriptable, but **different timestamp units** (derivatives=fractional seconds, spot=ms integers) — parser must branch; orderbook/kline bulk-file schemas not yet inspected `[06§15, 08 open Q4]` | Use bulk CSVs to backfill only the gap before the recorder started; verify exact schema (download+inspect a real file) before building the importer; live WS recording is the ongoing source of truth going forward |
| **Depth-tier push cadence varies (10ms–200ms depending on depth/category)** | linear/inverse/spot: 1@10ms, 50@20ms, 200@100ms, 1000@200ms; option: 25@20ms, 100@100ms; no checksum field on any tier — must drop+resubscribe on suspected desync `[06§9]` | Decouple UI render throttling from feed cadence; track `u`/`seq` monotonic IDs and rebuild book on gap detection rather than attempting self-healing |
| **REST rate limits (per-UID, shared across all API keys on that UID)** | Global ~600 req/5s/IP; trade-endpoint limits 10-20 req/s by category; error 10006 on excess; headers `X-Bapi-Limit*` available for self-throttling `[06§13]` | Single shared rate-limit tracker per UID (not per key) across all managers' sub-accounts sharing the Main UID's aggregate budget; self-throttle off response headers proactively rather than waiting for 10006 |
| **No dedicated liquidation-history REST endpoint** | Only the live `allLiquidation.{symbol}` WS topic exists; historical liquidation depth is capped by however long the recorder has been running `[23#7]` | Explicit "empty/partial-history" UI states for any view relying on liquidation history younger than the recorder's uptime |
| **Order-book depth caps (max 1000 levels, some categories max 25)** vs. desired heatmap resolution | option category maxes at depth 25; spot/linear/inverse max 1000 `[06§4]` | Heatmap resolution/depth-tier selection should be category-aware, not a single global setting |
| **48-hour new-account API-key restriction; sub-account cap (5 standard / 20 KYC-business)** | Blocks same-day manager onboarding; hard ceiling on number of concurrently supported managers without Business KYC `[12§1]` | Budget 2-day lead time in manager onboarding workflow; surface the 5/20 cap explicitly in the Admin/Users UI (View 21) so the owner doesn't hit it by surprise `[23#21]` |
| **Demo trading has no WS order-entry support (order placement)** — private data-stream WS now confirmed, but the *order-entry* WS channel explicitly excludes demo | `wss://stream.bybit.com/v5/trade` (order entry) "Not supported: Demo Trading" `[06§11]` | Demo-mode order placement always goes over REST, never WS-trade; this is a deliberate, documented code-path split, not an oversight |
| **Trailing stop = fixed price distance, not %** | Bybit's native trailing stop takes a price offset, not a percentage `[06§6]` | Client-side translation layer converts desired %-based trailing UX into the correct absolute price distance before sending to Bybit |
| **Sub-account demo-trading eligibility unconfirmed** | Open question — unclear if sub-accounts can independently enable demo mode, separate from Main `[06§2, 12 open Q6 resolved-partial]` | Empirical test required before finalizing per-manager demo UX; flagged as a pre-implementation validation task, not blocking design |

---

## 6. Product risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Iceberg/stop-run/absorption heuristics produce false confidence** — no L3 data means these are approximations that could be trusted as if they were certain, leading to bad trading decisions | Medium | High | Mandatory visible "(estimated)" badges in UI on every heuristic-derived signal, tunable/visible confidence thresholds, never gate automated rule actions on these signals alone without also requiring a corroborating hard-data condition `[04#9, 08§12]` |
| 2 | **Rule-engine failover risk** — if the backend running rule-based stops/exits goes down or the WS connection lags/drops while positions are open, automated protection stops working exactly when needed | Medium | Critical (real money) | Always keep a native hard stop-loss placed on the exchange itself as a floor (not just app-side logic); watchdog/heartbeat monitoring with alerting; auto-flatten if connection drop exceeds a threshold (10-30s) while positions are open `[09§5, 12§6 non-functional targets]` |
| 3 | **Orderbook desync silently corrupting the heatmap/DOM view** — Bybit provides no checksum field; a missed message could leave the local book state wrong indefinitely | Medium | Medium-High (bad execution decisions off a wrong heatmap) | Track monotonic `u`/`seq` IDs per message; on any gap, drop and resubscribe fresh rather than attempting incremental repair `[06§9,§14]` |
| 4 | **Recorder data loss / gaps** — since Bybit provides no deep historical tick/L2 REST, any recorder downtime is permanently unrecoverable history (bulk CSVs only fill the pre-launch gap) | Medium | Medium (degrades Profile/Replay/Journal features, not safety-critical) | Recorder uptime monitoring/alerting as a first-class ops concern from day one; explicit "partial history" UI states rather than silently showing gapped data as if complete `[08 key recs, 23 cross-cutting notes]` |
| 5 | **Sub-account cap (5, or 20 with Business KYC) blocks scaling past current "few managers" plan** | Low (given current scope) | Medium if the owner wants to add more managers later | Surface the cap explicitly in Admin UI; document the KYC upgrade path as a known future dependency, not a silent wall `[12§1]` |
| 6 | **Regulatory ambiguity around "managers" trading on the owner's behalf** — could resemble investment-adviser-like activity depending on compensation/structure, across US/UK/EU frameworks | Low-Medium (depends on real-world arrangement, not just software) | High if triggered (legal/compliance exposure) | Explicitly out of this project's technical scope; flagged for the owner to get actual counsel before scaling the number of managers or any compensation arrangement `[12§4, 12 open Q7]` |
| 7 | **Self-hosted security surface** — API keys with trading permission, run on a personal box, WSL2 networking quirks (accidental 0.0.0.0 binding could leak the trading interface to LAN/internet) | Medium | Critical (fund loss if a key is exposed) | Withdrawal permission always off on every key; IP-whitelist every key to the trading box's egress IP; Tailscale-only remote access, bind services to 127.0.0.1/WSL-internal only, verify via netstat/firewall audit; envelope-encrypt keys at rest, KEK never unencrypted on disk `[12§2.2,§2.5]` |
| 8 | **Single point of failure** — one self-hosted box, ~99% uptime target during active trading hours only, no redundant infrastructure like a commercial SaaS would have | Medium | Medium-High (missed exits, stuck orders during downtime) | Risk-critical subsystems (position monitor, stop/rule engine, daily-loss auto-flatten) held to a higher reliability bar than the rest of the app; documented incident response (manual flatten via Bybit's own UI as the ultimate fallback) `[12§6]` |
| 9 | **Rate-limit exhaustion under multi-manager load** — REST limits are per-UID, shared across all sub-account keys under the same Main UID; a busy day across several managers could hit shared caps | Low-Medium | Medium (delayed/rejected orders at the worst moment) | Centralized, shared rate-limit tracker per UID (not per key), proactive self-throttling off `X-Bapi-Limit*` response headers, prefer WS over REST wherever an equivalent exists `[06§13, 08§1]` |
| 10 | **Scope creep toward DeepCharts/TV feature parity for its own sake** — chasing every catalogued sub-feature (140+ items across 21 views) risks an unshippable v1 | High | Medium (delivery risk, not safety) | MoSCoW prioritization already exists (`[12§5]`); hold the line on Must-have execution/risk/order-flow basics before Could-have polish items (custom indicator scripting, screenshot/export, etc.) |

---

## 7. Cost comparison: TV Premium + DeepCharts vs. self-hosting

Approximate current published pricing (see digests for exact tier breakdowns; figures below are monthly, "if paying monthly" unless noted):

| Stack | Component | Monthly | Annual (if cheaper) |
|---|---|---|---|
| **Commercial stack** | TradingView Premium | $69.95/mo | — |
| | TradingView Ultimate *(needed for Tick Replay/Deep Backtesting/uncapped alerts)* | $239.95/mo (or $199.95/mo billed annually, $2,399.40/yr) | $2,399.40/yr |
| | DeepCharts Orderflow tier (Big Trades, Deep Print, Deep Profile, CVD, Deep Stats, Imbalance, Speed of Tape) | $59/mo | $708/yr |
| | DeepCharts Full Advanced (adds premium studies) | $79/mo | $948/yr |
| | DeepCharts Pro (full Deepchart bundle incl. DeepGamma) | $100/mo | $1,200/yr |
| | DeepDOM standalone (heatmap + DOM) | $39/mo | $468/yr |
| | *Combined Deepchart+DeepDOM bundle alternative* | — | $1,599/yr (+ course/Discord extras) |
| | **Representative realistic combo**: TV Ultimate + DeepCharts Orderflow + DeepDOM | **~$307-337/mo** (Ultimate monthly billing) or **~$264/mo equivalent** (all annual: $2,399.40 + $708 + $468 = $3,575.40/yr) | ~$3,575/yr minimum, before any per-manager multiplication |
| | **Per-manager multiplier**: each of these products/licenses is typically single-seat; adding "a few account managers" as separate paid seats could multiply most of the above by N managers (exact multi-seat pricing not confirmed in research, but no evidence of a built-in team/multi-user tier at these prices) | — | Potentially 2-5x the above if managers need independent seats |
| | *Plus*: none of this includes a working execution layer — no native crypto trading/automation exists in DeepCharts at all `[04§21]`, and TV's Bybit execution path requires a fragile bridge for full automation `[03#8,#17]` | — | — |
| **Self-hosted CandleViewer** | One personal server (existing WSL Ubuntu box — assume already owned, no incremental hardware cost) | $0 incremental (or modest VPS cost if hosted, ~$10-40/mo for a capable box) | — |
| | Bybit API access | $0 (public API, no subscription) | — |
| | Software licenses | $0 (Apache-2.0 Lightweight Charts; own backend code) | — |
| | Multi-manager access | $0 additional — sub-accounts + RBAC are architecture, not paid seats | — |
| | Ongoing cost | Owner's own dev/maintenance time (not zero, but not a recurring bill) | — |

**Bottom line**: the commercial stack most closely matching the target feature set (real footprint/order-flow + DOM heatmap + reasonable historical depth) runs roughly **$260-340/mo (~$3,100-4,100/yr)** for a *single* user, before accounting for the fact that it still lacks a working Bybit execution/automation layer and would likely need per-manager seat multiplication for the "few account managers" requirement. Self-hosting eliminates the subscription entirely at the cost of the owner's own build/maintenance effort, and is the only option that natively unifies order-flow visibility, direct Bybit execution, and multi-manager RBAC in one place — no combination of TV+DeepCharts achieves that combination at any price.

---

## Section list
1. Where TradingView falls short for a crypto/Bybit order-flow trader (ranked)
2. What DeepCharts adds and why it matters (plain-language glossary)
3. CRITICAL GAPS CANDLEVIEWER FILLS (the intersection)
4. What we deliberately drop
5. Feasibility constraints from Bybit data + mitigations
6. Product risk register
7. Cost comparison: TV Premium + DeepCharts vs. self-hosting
