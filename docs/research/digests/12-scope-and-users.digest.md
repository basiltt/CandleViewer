# Digest: 12-scope-and-users.md — Bybit multi-user terminal scoping

## 1. Bybit account structures
- **UTA (Unified Trading Account)** — combines Spot/USDT-USDC Perps/Options/Margin under one wallet, shared collateral/cross-margin.
- **Standard Sub-accounts** — created only from Main; own login+API keys+wallet; funded via internal transfer; cannot create further sub-accounts.
- **Design decision**: one sub-account per managed strategy/manager → blast-radius isolation, independent freeze/defund.
- **Numeric cap**: regular (non-KYC-business) Main = max **5** Standard Subaccounts (effective 14 Aug 2026); pre-existing >5 grandfathered. VIP/Business-KYC Main = up to **20**. Separate "AI Subaccount" category not counted in this cap.
- **Capacity constraint**: >5 managers requires Business KYC (→20 cap) or consolidating managers per sub-account (loses isolation).
- API key config per key: Read-Only/Read-Write per permission group (Orders, Positions, Trade, Wallet, Derivatives, Copy Trading, Block Trading, Exchange, NFT, Affiliate).
- **Withdrawal permission**: off by default, separate checkbox — must leave OFF.
- **IP whitelist**: key can bind to specific source IP(s); unwhitelisted = usable anywhere (less secure). Max **20 IPs/key** (unverified, third-party).
- Sub-account API keys can be created programmatically from Main (pybit `create_sub_uid`), with `readOnly` flag (0=RW,1=RO) + `permissions` object.
- **New-account restriction**: API key creation blocked for first **48 hours** after account registration — budget 2 days lead time onboarding a manager.
- **2FA required** to create API key.
- **API version**: use **V5 only** (V1–V3 legacy/deprecated).
- **Max API keys per UID**: unresolved — conflicting figures (5/10/20/30/100); most-repeated 10–20; confirm live in dashboard.
- **Key expiry**: no IP bound → expires after **90 days** (unverified); IP bound → no forced expiry, rotation must be CandleViewer-enforced policy (e.g. 90/180-day cadence).

### Demo trading
- Separate environment from mainnet/testnet; distinct API keys, not interchangeable.
- **RESOLVED**: private WS endpoint exists for demo: `wss://stream-demo.bybit.com` (official docs), supports `order`/`position`/`execution`/`wallet` topics + `op:"order.create"`. Removes prior assumption that demo lacked WS — CandleViewer paper mode CAN use same WS-driven architecture as live.

### UTA 2.0 margin modes
- Three modes: **Regular (Cross)**, **Isolated**, **Portfolio Margin** (whole-account net-risk calc, reduces margin for hedges but single liquidation risk domain). 70+ eligible collateral currencies with haircuts.
- **Sub-account isolation**: each sub-account's wallet/margin is separate from Main and other sub-accounts — a manager's loss cannot draw down Main or other managers' funds (corroborated but not from single authoritative spec page).
- Design implication: fund each sub-account only with capital owner accepts as that manager's risk ceiling (app-layer enforcement, §2.3).
- Sub-accounts must be upgraded to UTA individually, generally before Main account upgrade; may require closing positions/aligning margin modes first.

## 2. Security architecture decisions
- **2.1 Least privilege**: every stored key = withdrawal OFF (enforced by startup self-check refusing "trading" mode if withdrawal enabled) + IP-whitelisted to trading box + scoped to only used permission groups. One key pair per sub-account **per role** (trading key vs read-only reporting key) — compromise of low-trust surface can't place orders.
- **2.2 Storage**: never plaintext secrets in config/source/DB. Use OS-native credential store where possible; since backend runs WSL Ubuntu (no reliable headless keyring) → **application-level envelope encryption**: KEK held outside DB (OS keyring/.env with restrictive perms/age/sops/Vault-lite). "HSM-lite": KEK in OS keyring/TPM (Windows Hello/TPM or YubiKey+age/gpg smartcard); KEK never unencrypted on disk/repo/backup. TLS for all internal hops. Rotate keys periodically + immediately on suspected compromise (Bybit exposes create/delete key endpoints → scriptable rotation).
- **2.3 RBAC (app-layer, independent of Bybit roles)**:
  - **Owner**: full admin, view/edit all managers' sub-accounts, create/revoke keys, transfers (via Bybit UI, outside tool).
  - **Manager**: scoped to assigned sub-account(s) only; place/modify/cancel orders, view positions; cannot see other managers; cannot manage keys.
  - **Viewer**: read-only.
  - Enforce server-side on every route (not just frontend). Maintain strict mapping: app user → allowed sub-account(s) → API key id(s).
- **2.4 Audit logging**: log every order action (place/amend/cancel/fill) with timestamp, user, sub-account, symbol, side, size, price/type, Bybit order ID, raw payload (secrets redacted). Log every auth event + every key-management event. **Append-only** storage (write-once table or external sink) — supports journal/compliance requirement.
- **2.5 Auth/network isolation**: App-level 2FA (TOTP) independent of Bybit's. Backend not exposed to public internet — use **Tailscale** (WireGuard mesh); combine with Tailscale ACLs for per-port restriction. **WSL2 caveat**: binds to 0.0.0.0 can leak to LAN/internet via portproxy/UPnP misconfig — bind to 127.0.0.1/WSL-internal only; run Tailscale client on Windows host; verify via netstat/firewall audit. Bybit IP whitelist = the real outbound exit IP (home/server public IP), separate from Tailscale inbound path for managers — do not conflate.
- **2.6 Owner account hardening (beyond API key)**:
  - **Withdrawal address whitelist**: only pre-verified addresses; ~24h hold on new entries — defends against compromised login (not just key theft). Must-have.
  - **Anti-Phishing Code**: free, embedded in genuine Bybit emails/SMS; absence = phishing signal. Must-have for owner + every manager.
  - **Device/session management**: trusted-device list, login-activity log — periodic review recommended (API exposure unconfirmed).

## 3. Workflows → screens
### Session workflow (9 steps)
1. Session prep (overnight levels, funding, OI, macro calendar, watchlist).
2. Watchlist screening (scanner: rel. volume, volatility, funding, OI change, proximity to levels).
3. Level marking (persisted horizontal levels/VWAP anchors/session opens).
4. Multi-timeframe context (synced crosshair/levels across higher/lower TF charts).
5. Order-flow read: footprint/Deep Print, Deep Profile (volume profile/value area), Deep Stats (delta/cum delta/absorption), Big Trades/tape, imbalance tracker, speed-of-tape, DeepDOM (heatmap ladder), liquidity tracker, stop-run detector, iceberg detector, market regime indicator.
6. Execution: hotkeys, one-click market/limit, bracket orders, DOM click-to-trade, position sizing calculator, custom rule-based stops/exits.
7. Risk monitoring: live P&L per position/aggregate, max daily loss/drawdown auto-flatten/lockout, per-manager risk limits.
8. Journaling: auto-logged trades w/ screenshots/replay link, tags, notes; post-session stats (win rate, expectancy, R-distribution).
9. Backtesting/replay: tick/bar replay, rule-based exit rehearsal without live risk.

### Personas
| Persona | Goal | Key needs |
|---|---|---|
| Owner/Admin | Oversight/delegation/control | Global dashboard, instant freeze/kill any manager, full audit access, key mgmt, per-manager risk config |
| Manager (discretionary) | Trade assigned sub-account(s) | Fast execution, footprint/DOM/heatmap, hotkeys, personal journal, own P&L/risk dash, isolation from other managers |
| Manager (swing) | Lower-freq HTF decisions | Multi-TF layouts, alerting, less tick-speed reliance, daily/4h profile + journal emphasis |
| Viewer (owner-as-reviewer) | Audit without interfering | Read-only dashboard, journal review, audit log, analytics, no order entry |

### Screens (13)
1. Login/2FA. 2. Global Owner Dashboard (all sub-accounts equity/P&L/risk/kill-switches). 3. Main Trading Terminal (chart+footprint+MTF tabs+drawing/VWAP/vol profile; DOM+heatmap panel; order ticket; positions/orders panel w/ quick flatten; tape panel; imbalance/absorption strip; regime badge). 4. Watchlist/Scanner. 5. Risk Dashboard (per-manager+aggregate exposure, drawdown, auto-flatten status, margin/leverage). 6. Journal (filterable trade list, per-trade detail, aggregate stats). 7. Replay/Backtest. 8. Paper Trading toggle (demo API or local sim engine). 9. Admin—Users & Roles (Owner only). 10. Admin—API Keys (Owner only; permission/IP self-check). 11. Audit Log (Owner + Viewer read). 12. Alerts/Notifications. 13. Settings (layout, hotkeys, theme, retention).

## 4. Legal/ToS
- Bybit "API Terms & Conditions" help page points to live legal doc (not fully retrieved — open question). Global Platform T&Cs "last updated" 24 Jun 2025; EU entity T&Cs "last updated" 23 Jan 2026 (prior "1 Jul 2026" date was mis-parse, corrected).
- Defines **"API Client"** = software acting on behalf of a User's account; **"API Limits"** = rate/frequency/connection/order-weight restrictions, changeable at will.
- CandleViewer = "API Client" acting for each User; managers = **"Authorized Individuals"** under owner's account — not independent third parties — as long as not offered publicly/resold (avoids needing "API Broker Program"/broker registration).
- No blanket prohibition found on private self-built tools; reasoned inference only, not legal opinion — counsel needed before scaling beyond a few managers.
- **Regional restrictions**: Bybit EU restricted-country list includes USA, Canada, Singapore, Malaysia, Hong Kong, Russia, sanctioned states — check owner/manager residency against applicable entity's list.
- **Charting library licensing**:
  - Lightweight Charts™ = Apache-2.0, fully open source, free for any use (attribution/notice required).
  - Advanced Charts / Trading Platform = Proprietary, separate license agreement, application/approval gated (even "free" tier).
  - **Recommendation**: build custom canvas/WebGL overlays (footprint/DOM/heatmap) on Lightweight Charts base — lower legal risk than pursuing Advanced Charts license.
  - TradingView's "non-professional use" data-subscription gate is irrelevant (CandleViewer sources data from Bybit directly).
- **DeepCharts IP**: replicate feature concepts only (footprint, Deep Profile/Stats, Big Trades, imbalance tracker, speed-of-tape, VWAPs, DOM heatmap, liquidity tracker, stop-runs, iceberg detector, regime, replay, journal) — these are generic order-flow techniques (also in Bookmap/ATAS/Sierra Chart/Jigsaw), not exclusive IP. Do NOT reuse DeepCharts trademarked names ("Deep Print," "DeepDOM," "DeepGamma," "AEM"), logos, or copied UI/text. Use generic internal names ("Footprint Chart," "DOM Heatmap," "Volume Profile").

## 5. MVP MoSCoW (~80 features; M=Must/S=Should/C=Could/W=Won't)

### 5.1 Charting
| # | Feature | Pri |
|---|---|---|
|1|Candlestick OHLCV pan/zoom|M|
|2|Multi-timeframe switching (1m–1D)|M|
|3|Multiple synced chart panels|M|
|4|Horizontal level drawing, persisted per symbol|M|
|5|Trendline/ray/rectangle tools|S|
|6|VWAP (session) overlay|M|
|7|Anchored VWAP|S|
|8|Volume profile (session/fixed range)|M|
|9|Composite/visible-range volume profile|S|
|10|Footprint chart (bid/ask vol per price/candle)|M|
|11|Footprint delta coloring/imbalance highlight|M|
|12|Market regime indicator|S|
|13|Standard TA indicators (MA/EMA/RSI)|S|
|14|Custom indicator scripting|C|
|15|Chart templates/layout save-load|M|
|16|Crosshair sync across panels|M|
|17|Chart screenshot/export|C|

### 5.2 Order flow / microstructure
|#|Feature|Pri|
|---|---|---|
|18|DOM (order book ladder)|M|
|19|DOM liquidity heatmap overlay|M|
|20|Click-to-trade from DOM|S|
|21|Time & Sales (tape)|M|
|22|Speed-of-tape (prints/sec)|S|
|23|Big trades/large-print highlighting|M|
|24|Imbalance tracker (stacked bid/ask)|M|
|25|Absorption/Deep Stats delta metrics|S|
|26|Liquidity tracker (resting size changes)|C|
|27|Stop-run detector|C|
|28|Iceberg order detector|C|
|29|Cumulative delta chart|S|

### 5.3 Data
|#|Feature|Pri|
|---|---|---|
|30|Live WS market data (klines/trades/orderbook)/symbol|M|
|31|Historical OHLCV backfill/storage|M|
|32|Historical tick/trade storage for replay|S|
|33|Multi-symbol simultaneous subscriptions|M|
|34|Funding rate/open interest tracking|S|
|35|Data retention policy & pruning|S|
|36|Local caching for fast chart reload|M|

### 5.4 Trading
|#|Feature|Pri|
|---|---|---|
|37|Market/limit order entry|M|
|38|Stop/stop-limit orders|M|
|39|Bracket orders (entry+stop+target)|M|
|40|Fast order entry/hotkeys|M|
|41|Position sizing calculator (risk %)|M|
|42|One-click flatten/cancel-all|M|
|43|Reduce-only/post-only flags|S|
|44|OCO orders|S|
|45|Multi-account order routing (per-manager scope)|M|
|46|Leverage/margin mode control (UTA-aware)|S|

### 5.5 Automation/rule-based stops
|#|Feature|Pri|
|---|---|---|
|47|Rule-based trailing stop (ticks/ATR)|M|
|48|Breakeven-at-R-multiple auto-move|S|
|49|Time-based auto-exit|S|
|50|Custom rule builder (conditional exits)|S|
|51|Price/level alert triggers|M|
|52|Alert-to-action automation|C|
|53|Daily loss limit auto-flatten/lockout|M|

### 5.6 Paper trading
|#|Feature|Pri|
|---|---|---|
|54|Bybit demo-trading integration (REST)|M|
|55|Local simulated fill engine (covers demo WS gap)|S|
|56|Paper P&L tracking identical to live UI|M|
|57|Switch live/paper per session|M|

### 5.7 Replay/backtest
|#|Feature|Pri|
|---|---|---|
|58|Bar replay mode|S|
|59|Tick-by-tick replay|C|
|60|Rule-based strategy backtest vs replay data|C|
|61|Replay speed control/step-by-step|S|

### 5.8 Journal
|#|Feature|Pri|
|---|---|---|
|62|Auto-logged trade journal (entry/exit/size/P&L)|M|
|63|Manual notes/tags per trade|M|
|64|Chart snapshot attached to trade|S|
|65|Aggregate stats (win rate/expectancy/R distribution)|S|
|66|Journal export (CSV)|C|

### 5.9 Multi-account/admin
|#|Feature|Pri|
|---|---|---|
|67|Sub-account mapping per manager|M|
|68|RBAC (Owner/Manager/Viewer)|M|
|69|Per-manager risk limits set by Owner|M|
|70|Global Owner dashboard across sub-accounts|M|
|71|Owner kill-switch (freeze manager instantly)|M|
|72|API key management UI (add/rotate/revoke)|M|
|73|API key permission/IP-whitelist self-check|M|
|74|Audit log (orders/logins/key changes)|M|
|75|2FA login|M|
|76|Manager onboarding workflow (new sub-account, 48h wait handling)|S|

### 5.10 Non-functional/platform
|#|Feature|Pri|
|---|---|---|
|77|Tailscale-based remote access for managers|M|
|78|Encrypted-at-rest API key storage|M|
|79|Centralized market-data fan-out (single WS per symbol)|M|
|80|Multi-exchange abstraction layer (Bybit first, extensible)|S|

## 6. Non-functional targets (numeric)
- **WS→screen latency**: target ≤150–250ms total (backend ingest ~20–50ms, internal fan-out ~5–20ms, frontend render ~16–50ms/1-2 frames).
- **Order round-trip**: click→ack display target ≤300–500ms (REST, normal network).
- **Uptime**: ~99% during active trading hours (personal server); risk-critical subsystems (position monitor, stop/rule engine, daily-loss auto-flatten) held to higher bar. Recommend watchdog alerting/force-flatten if Bybit WS/REST connection drops >10–30s threshold while positions open.
- **Data retention**:
  - Tick/trade data: full resolution rolling 30–90 days, then downsample to 1-min bars.
  - OHLCV bars: retain indefinitely at 1m+ resolution.
  - Audit logs/journal/order history: retain indefinitely.
  - Explicit pruning job + documented per-data-class retention policy required.

## Open questions
1. Full Bybit API Terms & Conditions text not fetched — need clauses on automated/algorithmic tools, liability, multi-user restrictions.
2. Exact current Bybit V5 rate limits by endpoint/VIP tier — unresolved, pull from official docs at implementation.
3. TradingView Advanced Charts full license text — only available post-application; needed only if Lightweight Charts+overlays insufficient.
4. Whether Bybit's automatic partner-IP-whitelisting applies to CandleViewer vs manual whitelisting (likely moot; manual sufficient) — unconfirmed.
5. Precise numeric rate limits for order placement/amend/cancel per sub-account — affects rule-based auto-exit polling design; needs confirmation.
6. RESOLVED: Demo trading WS support confirmed (`wss://stream-demo.bybit.com`); full topic/order-type parity with live WS not exhaustively verified (residual uncertainty).
7. Legal/regulatory status of "managers" trading on owner's behalf (investment-adviser-like activity) — out of scope technically; rough grounding given for US (Investment Advisers Act, "for compensation"/"in the business of" triggers), UK (FCA "by way of business" threshold), EU (MiFID II "investment service" definition); common thread = compensation + commerciality determines regulatory trigger; no fee charged is favorable but number of managers/indirect benefit/"holding out" remain risk factors — counsel required, not resolved.
8. Unresolved numeric limits despite research: max API keys per UID (conflicting 5/10/20/30/100 figures), exact temporary IP-ban duration for rate-limit violations, precise meaning of error code `10018` — all need confirmation against live Bybit dashboard/error-code reference at implementation time.
