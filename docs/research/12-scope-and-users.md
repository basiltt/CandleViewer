# Product scoping: private multi-user Bybit terminal — personas, workflows, compliance/security

> Research phase document for CandleViewer. Scope: crypto-only, Bybit-first, private self-hosted terminal for the owner plus a small number of trusted account managers. No sprint planning; this is scoping/requirements research only.

## 1. Bybit account structures relevant to a private multi-user terminal

### 1.1 Account types
- **Main (Unified Trading Account, UTA)** — Bybit's current default account model. UTA combines Spot, USDT/USDC Perpetuals, USDC Futures, Options and Margin under one wallet, allowing shared collateral/cross-margin across products. (https://www.bybit.com/en/help-center/topic-list/unified-trading-account)
- **Sub-accounts** — Created from the Main account only ("Standard Subaccount"). Each sub-account has its own login, its own API keys, and (with UTA) its own unified wallet, which can be funded via internal transfer from the Main account. Sub-account creation, deletion/freezing, and asset transfer are managed from the Main account; sub-accounts cannot create further sub-accounts. (https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Standard-Subaccount)
- Practical implication for CandleViewer: model **one Bybit sub-account per managed strategy/manager** rather than sharing a single account across managers. This gives natural blast-radius isolation — a manager's API key only ever touches their sub-account's funds — and lets the owner freeze/defund a sub-account independently of others.
- **Numeric sub-account cap (new finding)** — As of a Bybit policy change effective **14 August 2026**, regular (VIP 0, non-KYC-business) Main accounts are limited to a maximum of **5 Standard Subaccounts**; accounts that already held more than 5 before the change keep their existing sub-accounts (grandfathered), but cannot exceed the new cap going forward without meeting VIP/Business-KYC criteria. **VIP tier and Business-KYC-verified Main accounts retain a higher cap of up to 20 Standard Subaccounts.** This cap does not include the separate, newer "AI Subaccount" category (see below). (https://www.bybit.com/en/help-center/article/FAQ-Standard-Subaccount; https://announcements.bybit.com/en/article/important-update-to-subaccounts--art5ebb9ca6e027/)
  - **Capacity planning implication:** onboarding "10 managers as 10 sub-accounts" is **not possible on a regular (non-KYC-business) Main account** under the current 5-subaccount cap — the owner would need Business KYC verification (raising the cap to 20) or would need to consolidate multiple managers per sub-account (losing per-manager blast-radius isolation) if managers > 5 and Business KYC is not pursued. This is a hard scoping constraint that should feed directly into onboarding-capacity planning.

### 1.2 API key permission granularity
When creating an API key (mainnet: https://www.bybit.com/app/user/api-management, testnet: https://testnet.bybit.com/app/user/api-management), Bybit lets you configure, per key:
- **Read-Only vs Read-Write** toggle for each permission group (Orders, Positions, Trade, Wallet, Derivatives, Copy Trading, Block Trading, Exchange, NFT, Affiliate, etc., varying by account type).
- **No withdrawal permission by default** — withdrawal permission is a separate, explicit checkbox that most third-party-tool guides instruct users to leave OFF. Example (Insilico Terminal onboarding doc): "The key does not have withdrawal access for your security." (https://docs.insilicoterminal.com/documentation/setup/creating-an-api-key/creating-a-bybit-api-key)
- **IP whitelist** — an API key can be bound to one or more specific source IPs ("Only IPs with permissions granted are allowed to access the Open API"); un-whitelisted keys are usable from any IP but Bybit's UI warns this is less secure. (https://support.cryptact.com/hc/en-us/articles/4412303076889-How-to-get-an-API-key-for-Bybit) Some partner integrations get Bybit-managed automatic allow-listing of the partner's own server IPs instead of the user entering their own — not applicable to a self-hosted tool, where the user enters their own static/reserved IP (e.g., a VPS or a Tailscale exit node's public IP if not using a VPN overlay).
  - **Max whitelisted IPs per key (new finding)**: up to **20 IP addresses** can be bound to a single API key's whitelist, per third-party security guides synthesizing Bybit's UI behavior; this was not confirmed on an official Bybit help-center page in this pass, so treat as **plausible but unverified — re-check against the live API-key-creation UI at implementation time.** (https://trilicity.com/articles/setting-up-ip-whitelisting-for/)
- **Sub-account API key creation from Main** — pybit's `create_sub_uid` / user-management endpoints show the Main account holder can create sub-account API keys programmatically, specifying `readOnly` (0 = read+write, 1 = read-only) and a `permissions` object naming allowed scopes. (https://github.com/bybit-exchange/pybit/blob/master/pybit/_v5_user.py)
- **New-account restriction** — API key creation is blocked for the first 48 hours after registering a new Bybit account (anti-fraud). Relevant if onboarding a new manager sub-account: budget 2 days' lead time before a manager can be given API access. *(Re-checked this pass: this 48-hour figure is repeated consistently across the Bybit help-center "How to Create Your API Key" article and multiple third-party guides in 2026 with no indication it has been lifted, so it is retained as-is, though no dated official changelog entry confirming it is still current in 2026 was found — treat as likely-current but not freshly dated.)* (https://www.bybit.com/en/help-center/article/How-to-create-your-API-key)
- **2FA required** — Google Authenticator (or similar) must be enabled before an API key can be created; API key creation itself also requires 2FA confirmation.
- **API versions** — V5 unified API is current and required for UTA; V1–V3 are legacy/deprecated paths. CandleViewer should integrate against **V5 only**. (https://www.bybit.com/en/learn/bybit-guide/how-to-create-a-bybit-api-key)
- **Max API keys per UID (new finding)** — third-party sources conflict sharply on the exact cap (figures of 5, 10, 20, 30, and 100 all appear across guides/wikis), and no single authoritative Bybit help-center page states a definitive numeric ceiling in the pages retrieved this pass. **This remains genuinely unresolved** — the most-repeated/plausible figure in current (2026) third-party guides is **10–20 keys per UID**, but this should be confirmed directly in the account's own API Management dashboard (which typically shows a live "X/Y keys used" counter) before finalizing onboarding-capacity assumptions, rather than trusting any single secondary source. (conflicting sources: https://www.bybit.com/en/help-center/article/How-to-create-your-API-key; https://aotrading.io/blogs/bybit-api-setup-guide-2026; https://wiki.tronsell.io/books/bybit-api-guide)
- **API key expiry / rotation (new finding)** — Bybit ties key expiration to IP-whitelist binding: an API key created **without** any IP bound to it automatically **expires after 90 days** and must be renewed/regenerated; an API key with **at least one IP address bound** to it has **no forced expiry** and remains valid indefinitely (subject to manual revocation). This directly supports CandleViewer's onboarding design: since CandleViewer's own least-privilege policy (§2.1) already mandates IP-whitelisting every key, in practice CandleViewer-managed keys will fall into the "no forced expiry" bucket, so key **rotation must be a CandleViewer-enforced policy/reminder** (e.g., a recommended 90/180-day rotation cadence surfaced in the Admin — API Keys screen), not something Bybit will force automatically. (https://papaproxy.net/blog/bybit-api-key-ip-whitelist.php — third-party source; not independently confirmed on an official Bybit help-center page in this pass, so treat the exact "90 days" figure as **plausible but unverified against a primary Bybit source** and re-check at implementation time.)

### 1.3 Demo trading
- Bybit's "Demo Trading" is a separate environment from both mainnet and the classic `testnet.bybit.com`. Demo API keys are generated from a distinct "Demo Trading" section in the UI and **are not interchangeable with live keys** — an integration must explicitly branch its base URL/host and key pair depending on whether the connected account is live or demo. (https://crypto-resources.com/manuals/bybitsub-account-and-api-creation)
- **Important limitation, re-verified this pass — CORRECTED FROM PRIOR DRAFT**: *(corrected: the previous claim that "demo trading does not support private WebSocket streams" was based on an ~18-month-old community SDK note (Jan 2025) and is now superseded.)* Bybit's official `bybit-exchange/docs` and `bybit-exchange/api-usage-examples` GitHub repositories confirm a **dedicated private WebSocket endpoint for Demo Trading exists: `wss://stream-demo.bybit.com`**, distinct from both the live private endpoint (`wss://stream.bybit.com/v5/private`) and the classic testnet endpoint (`wss://stream-testnet.bybit.com/v5/private`). It uses the same HMAC-SHA256 signed `auth` handshake as live/testnet, and supports the standard private topics (`order`, `position`, `execution`, `wallet`) as well as an order-placement-over-WebSocket flow (`op: "order.create"`) demonstrated in official multi-language samples. **This removes the previously assumed hard architectural constraint**: CandleViewer's paper/demo-trading mode **can** use the same WS-driven order/position update architecture as live mode, rather than requiring a REST-polling or optimistic-local-state fallback purely for demo. (https://bybit-exchange.github.io/docs/v5/demo; https://github.com/bybit-exchange/api-usage-examples/blob/master/V5_demo/wss_demo/go/ws_trade_api_demo.go; https://deepwiki.com/bybit-exchange/api-usage-examples/3.3-v5-websocket-demos)
  - **Residual uncertainty**: the exact set of private topics/ops supported over the demo WS endpoint, and whether it has full parity with live (e.g., all order types, all categories: spot/linear/inverse/options), was not exhaustively verified against the full V5 demo-trading reference page in this pass — this should be confirmed line-by-line against https://bybit-exchange.github.io/docs/v5/demo before finalizing the paper-trading module's architecture, since a REST-polling fallback may still be warranted for any gaps found.
- Testnet (`testnet.bybit.com`) still exists separately from demo trading and is explicitly deprioritized per project scope (low priority per user's brief), but is mentioned here because SDKs often conflate `testnet: true` flags with demo-trading flags — implementers must not confuse the two.

### 1.4 Rate limits
- Bybit enforces **IP-based rate limits** as well as **per-API-key / per-UID rate limits**, differentiated by endpoint class (public market data, private account data, order placement/amend/cancel). Exact numeric ceilings are tiered by account trading volume (VIP level) and are published in Bybit's official API docs (rate-limit page), which should be pulled at implementation time since limits change with account tier and are subject to revision.
- Third-party SDKs (e.g., `bybit-api` Node SDK) advertise that requests routed through their infrastructure get elevated rate limits (quoted "400 requests per second, higher than the highest VIP tier") as a value-add of using their client — this is a vendor-specific enhancement, not a baseline Bybit guarantee, and should not be relied upon for CandleViewer's own direct integration. (https://github.com/tiagosiebler/bybit-api/blob/master/README.md)
- Design implication: with several managers' sub-accounts each polling/streaming independently, CandleViewer's backend should **centralize public market data subscriptions** (one shared WS connection per symbol feed, fanned out internally to all UI sessions) to avoid multiplying connections against Bybit's per-IP/per-UID caps, while private (account) WS/REST connections are necessarily per-sub-account/per-key.
- **Rate-limit enforcement mechanics (new finding)** — Bybit's official V5 error-code reference (https://bybit-exchange.github.io/docs/v5/error) documents **error code `10006`: "Too many visits. Exceeded the API Rate Limit."** as the standard rate-limit-exceeded response — this is a normal REST error response (not a network-level ban) accompanied by `X-Bapi-Limit`, `X-Bapi-Limit-Status`, and `X-Bapi-Limit-Reset-Timestamp` response headers indicating quota and reset time, so a well-behaved client can back off and retry using those headers rather than needing blind exponential backoff. **`10018`** is not clearly documented as a standalone universal code in the primary sources retrieved this pass (third-party sources associate it loosely with broader/global limit or IP-ban scenarios) — **this specific code's meaning is unresolved and should be checked directly against the live https://bybit-exchange.github.io/docs/v5/error page at implementation time.** No official Bybit documentation found in this pass states a fixed **temporary IP-ban duration** for repeated rate-limit violations; anecdotal/community sources describe escalating soft blocks but no primary-source numeric duration was located — **treat exact ban duration as unconfirmed.**
  - **Design implication for §3/MoSCoW #55 (local fill engine for demo)**: since exceeding the rate limit surfaces as an ordinary HTTP error with informative headers rather than (per confirmed evidence) an opaque network ban, the rule-based auto-exit polling fallback for demo mode should implement **header-driven backoff** (respect `X-Bapi-Limit-Reset-Timestamp`) as the primary mitigation, with a conservative fixed-interval polling cadence (e.g., no tighter than 1 req/sec per key for non-time-critical polling) as a belt-and-braces default until real usage data is available.
- **Kill-switch mechanics — API key revocation does NOT cancel resting orders (new finding, directly relevant to MoSCoW #71 Owner kill-switch)**: revoking/deleting a Bybit API key only blocks *future* API calls made with that key/secret pair — it has **no effect on orders or positions already resting on Bybit's matching engine**, which remain live and can still fill until they are explicitly cancelled or naturally expire/fill. This was corroborated by a third-party integration-support source (no single authoritative Bybit help-center page stating this explicitly was found in this pass, so treat as **plausible, not fully primary-sourced**) (https://help.upcomers.com/en/articles/12176521-bybit-api-connection-troubleshooting-for-upcomers).
  - **Critical design implication**: CandleViewer's "Owner kill-switch" (MoSCoW #71) **must not be implemented as simple API-key revocation**. The kill-switch flow must explicitly: (1) issue cancel-all-orders and (optionally) flatten-all-positions calls using the still-valid key **first**, confirming success via response/positions-query, and only **then** (2) revoke/rotate the API key to prevent any further action by that manager. If the kill-switch is triggered because the key itself is suspected compromised (rather than a rogue manager), the correct order is reversed in practice — revoke the key immediately to stop new malicious orders, but then the owner must separately and promptly cancel any resting orders **via a different (owner-level) key or the Bybit web UI**, since the compromised key can no longer be trusted to submit the cancel-all call safely. This nuance (which key executes the emergency flatten) should be explicitly designed into the kill-switch UX, not assumed away.

### 1.5 Copy trading / leader features
- Bybit has a "Copy Trading" product line (help-center category exists: https://www.bybit.com/en/help-center/topic-list/api lists "Copy Trading" alongside API docs) allowing accounts to act as **Lead Traders** whom others can auto-copy. This is a consumer social-trading feature, not directly an account-management primitive for a private admin/managers structure — it is oriented at public followers copying a trader's positions for a profit-share fee, which is out of scope for a private terminal where the owner already trusts and directly authorizes each manager. Not recommended as an architectural building block for CandleViewer; sub-accounts + scoped API keys are the correct primitive instead.

### 1.6 Institutional / "Bybit Fund management" and API Broker Program
- Bybit's help-center topic list separately surfaces an **"API Broker Program"** distinct from ordinary retail API docs (https://www.bybit.com/en/help-center/topic-list/api) — this is aimed at businesses building large-scale client-facing trading products on top of Bybit (i.e., a real broker/reseller relationship with Bybit, requiring a business agreement), not applicable to a private single-owner tool with a few trusted managers using their own sub-account API keys. CandleViewer should **not** pursue broker/institutional API status; it should remain a self-service integration using standard retail sub-account API keys, which keeps the ToS posture simple (see §4).
- No dedicated "Fund management" role/API distinct from sub-accounts + API key `readOnly`/permission scoping was found in Bybit's public docs; multi-person account oversight on Bybit is achieved through the combination of (a) Main-account sub-accounts, (b) per-key permission scoping, and (c) manual transfer controls between Main and sub-accounts (only the Main account holder can move funds between sub-accounts). This maps naturally onto a "manager can trade sub-account X, cannot withdraw, cannot transfer between accounts" role model.

### 1.7 UTA margin modes and version differences (new section — addresses prior gap)
- **UTA versions**: Bybit's Unified Trading Account has progressed through **Classic → UTA 1.0 → UTA 2.0**, and account migration is **one-directional and generally irreversible** — an account cannot be downgraded back to Classic or from UTA 2.0 to UTA 1.0 once upgraded. Classic accounts can upgrade directly to UTA 2.0 (Pro), skipping UTA 1.0 entirely; existing UTA 1.0 (Pro) accounts must explicitly migrate to UTA 2.0 (Pro) to access newer features, and some migrations require closing specific open positions first or aligning margin/position modes to the unified standard before the upgrade completes. (https://www.bybit.com/en/help-center/article/FAQ-Unified-Trading-Account; https://www.bybit.com/en/help-center/article/Introduction-to-Bybit-Unified-Trading-Account; https://bybit-exchange.github.io/docs/v5/account/upgrade-unified-account)
- **Margin modes within UTA**: UTA 2.0 supports three margin modes selectable per account: **Regular (Cross) Margin**, **Isolated Margin** (per-position), and **Portfolio Margin**. Portfolio Margin calculates margin requirement at the **whole-account level** (net risk across correlated positions/products) rather than per-product, which can materially reduce total margin required for hedged/offsetting positions but also means a single account-level margin calculation governs liquidation risk across everything held in that account. UTA 2.0 also expanded eligible collateral to 70+ cryptocurrencies, each with its own collateral value/haircut ratio. (https://www.bybit.com/en/help-center/article/FAQ-Unified-Trading-Account)
- **Sub-account isolation from Main and from each other (directly addresses the critic's cross-margin risk concern)**: Bybit's own help-center material and 2026 product announcements (e.g., the "AI Subaccount" launch, which explicitly markets "fund isolation" as its headline security property) corroborate that **each sub-account's wallet/margin pool is separate from the Main account's and from every other sub-account's** — a sub-account's positions, margin, and potential liquidation are contained to that sub-account's own funded balance; a manager's leveraged loss in their sub-account **cannot draw down the Main account's or another sub-account's collateral**, because funds are not shared or auto-borrowed across sub-account boundaries the way products are shared *within* a single UTA wallet. (https://www.bybit.com/en/help-center/article/How-to-Manage-Funds-in-Unified-Trading-Account; https://announcements.bybit.com/en/article/launch-of-ai-subaccount-for-secure-and-isolated-ai-trading-execution-blta50e3efa96768430/)
  - **Residual caveat**: this isolation-between-sub-accounts finding is corroborated by multiple secondary/help-center sources but was not verified against a single authoritative "sub-account risk isolation" specification page; the practical takeaway for CandleViewer's design — **fund each manager's sub-account only with the capital the owner is willing to have that manager risk, and do not rely on any implicit shared-margin backstop between sub-accounts** — holds regardless, since under either interpretation the sub-account's own balance is the correct risk ceiling to enforce at the application layer (§2.3 risk limits).
- **Sub-account UTA upgrade eligibility**: sub-accounts must generally be upgraded to UTA (and to UTA 2.0 specifically) **individually**, and Bybit's guidance is that **sub-accounts should be upgraded before the Main account** in a migration, since some Main-account—level upgrade paths can be blocked or complicated if subordinate sub-accounts are still on an older account type. CandleViewer's onboarding flow for a new manager sub-account should therefore include a UTA-version compatibility check as a setup step, not assume all sub-accounts automatically inherit the Main account's UTA version.

---

## 2. Security best practices for a self-hosted terminal holding exchange keys

### 2.1 Principle of least privilege on the exchange side
- Every API key CandleViewer stores should be created with:
  - Withdrawal permission **off** (Bybit lets you omit this entirely — enforce this as a hard rule in onboarding UX, and validate it via a startup self-check API call that inspects the key's granted permissions and refuses to run in "trading" mode if withdrawal is enabled).
  - IP whitelist bound to the exact static IP (or IP range) of the box actually placing orders — this is the single highest-leverage mitigation against key theft, since a leaked key becomes useless off that IP.
  - Scoped to only the permission groups actually used (e.g., Orders + Positions + Wallet-read for a trading key; Read-only for any reporting/journal ingestion key used by a manager who should only view, not trade).
- One API key pair per sub-account per role (e.g., a "trading" key with order permissions and a separate "read-only" key for dashboards/journal ingestion), so a compromise of the lower-trust surface (e.g., a reporting dashboard) cannot place orders.

### 2.2 Key storage / encryption at rest
General secrets-management best practice for a self-hosted app (synthesized; not a single Bybit-specific doc, since Bybit does not prescribe client-side storage):
- Never store API keys/secrets in plaintext config files, source control, or unencrypted database columns.
- Use the **OS-native credential store** where the app runs: Windows Credential Manager / DPAPI on Windows, `libsecret`/GNOME Keyring or `kwallet` on Linux desktop, or — since backend runs in WSL Ubuntu — a Linux keyring is not always available headlessly, so the realistic option is an **application-level envelope-encryption scheme**: secrets encrypted at rest in the database with a key encryption key (KEK) held outside the DB (e.g., in an OS keyring, a `.env` file with restrictive permissions loaded only at process start, or a lightweight secrets manager such as `age`, `sops`, or HashiCorp Vault in dev mode / a lightweight self-hosted alternative).
- "HSM-lite" pattern for a personal server: since a real HSM is disproportionate for a single-owner private tool, a pragmatic middle ground is (a) storing the KEK in the OS keyring or TPM-backed store if the hardware supports it (Windows Hello/TPM, or a YubiKey used as a static secret holder via `age`/`gpg` smartcard mode), and (b) never allowing the KEK to be written to disk unencrypted or checked into any repo/backup unencrypted.
- Encrypt secrets **in transit** too: TLS for any network hop between frontend, backend, and any remote manager access (see Tailscale below), even on a private network — defense in depth against a compromised LAN device.
- Rotate API keys periodically and immediately upon any suspected compromise (Bybit exposes both create and delete key endpoints, so key rotation can be scripted).

### 2.3 Per-user roles and access control
- Model roles at the application layer independent of Bybit's own roles: e.g., **Owner** (full admin, can view/edit all managers' sub-accounts, can create/revoke API keys, can withdraw-adjacent operations like transfers between sub-accounts via Bybit UI outside the tool), **Manager** (scoped to one or more specific sub-accounts, can place/modify/cancel orders and view positions for those sub-accounts only, cannot see or touch other managers' sub-accounts, cannot create/rotate API keys), **Viewer** (read-only, e.g., for the owner reviewing a manager's performance without being able to trade).
- Enforce this at the backend authorization layer (not just hidden in frontend UI) — every API route must check the authenticated user's role + sub-account scope server-side.
- Maintain a strict mapping table: {app user} → {allowed Bybit sub-account(s)} → {API key id(s)}, never allowing a manager's session to reach a key outside their assigned sub-account.

### 2.4 Audit logging
- Log **every order-related action** (place, amend, cancel, and resulting fills) with: timestamp, acting app user, sub-account, symbol, side, size, price/type, resulting Bybit order ID, and the raw request/response payload (redacting secrets) for forensic replay.
- Log **every authentication event** (login, 2FA challenge, session creation/revocation) and every **API-key management event** (create/rotate/revoke) with the acting user.
- Store audit logs **append-only** (e.g., write-once table, or ship to an external log sink) so a compromised app account cannot retroactively cover its tracks; this is standard practice for any system handling financial transactions and directly supports the "journal"/compliance requirement from the DeepCharts feature parity (auto-tracker journal).

### 2.5 Authentication and network isolation
- **2FA** at the CandleViewer application login layer (TOTP), independent of Bybit's own 2FA — a manager's app account should require its own second factor since the app session, once open, can place trades.
- **Network isolation**: the backend should not be exposed directly to the public internet. For a single-owner setup with a few remote managers, the standard low-friction approach is a **Tailscale** (WireGuard-based mesh VPN) tailnet: each manager's device joins the tailnet, and the CandleViewer backend/frontend is only reachable via its Tailscale IP/MagicDNS name, never via a public port-forward. This avoids exposing the WSL/host box to internet scanning entirely, while still allowing remote managers full access from anywhere. Combine with Tailscale ACLs (tags/groups) to further restrict which manager devices can reach which internal service ports if the backend exposes more than one port (e.g., admin API vs trading API).
- **WSL2 exposure considerations**: WSL2 runs behind a virtualized NAT by default and its own IP changes on reboot; if the app binds to `0.0.0.0` inside WSL, Windows' `netsh interface portproxy` or Hyper-V firewall rules can inadvertently make the service reachable from the LAN or, if UPnP/router forwarding is misconfigured, the internet. Mitigations: bind services to `127.0.0.1`/the WSL-internal interface only unless deliberately proxying; if Tailscale is used, prefer running the Tailscale client on the Windows host (or use `tailscale serve`/Funnel deliberately, never Funnel for anything holding trading keys) rather than trying to expose WSL directly; verify with `netstat`/firewall audit that no unintended inbound rule exists after WSL or Docker Desktop networking changes (both are known to sometimes rewrite Windows Firewall rules).
- Keep the Bybit API IP-whitelist bound to the **stable IP the orders actually originate from** (the real exit IP as seen by Bybit) — if Tailscale or WSL NAT changes the effective source IP for outbound calls to Bybit, that must be accounted for (typically outbound calls exit via the host's normal internet connection, not through the tailnet, so the whitelist should be the home/server public IP, while *inbound* manager access is what goes through Tailscale — these are two different network paths and should not be conflated).

### 2.6 Owner-side Bybit account hardening beyond the API key itself (new section — addresses prior gap)
Since a compromised API key has no withdrawal permission (§2.1), the more consequential attack surface for fund *loss* (as opposed to unauthorized *trading*) is the **Main account's own login/session security**, not the API key. Bybit provides several account-level primitives CandleViewer's onboarding runbook should explicitly recommend the owner (and ideally each manager, for their own sub-account login) enable, none of which are API-key-scoped:
- **Withdrawal address whitelist** — when enabled, Bybit will only permit withdrawals to wallet addresses the account holder has pre-verified (via email + 2FA) and added to an allow-list; any withdrawal attempt to a non-whitelisted address is blocked outright, and adding/removing whitelist entries typically triggers a mandatory security delay (commonly a ~24-hour hold on newly added addresses) before that address becomes usable. This is defense-in-depth against a compromised Main-account *login* (as opposed to API key theft) — even if an attacker obtains the owner's password and 2FA, they cannot redirect funds to an address of their choosing without also passing the whitelist's verification/delay gate. Recommended as a **Must-have owner-onboarding step**, independent of the trading API key's own no-withdrawal restriction, since it protects against a different threat model (account takeover vs. key leakage). (https://www.bybit.com/en/help-center/article/How-to-add-your-withdrawal-wallet-address; https://www.bybit.com/en/help-center/article/How-to-Manage-Your-Withdrawal-Security)
- **Anti-Phishing Code** — a user-chosen string that Bybit then embeds in every genuine email/SMS sent to that account; its absence (or a wrong code) in a purported Bybit message is a strong phishing signal. Free, low-friction, no functional downside — recommended as a **Must-have onboarding checklist item** for the owner and every manager, since managers are also plausible phishing targets (a compromised manager email could be used for social-engineering attempts against their sub-account login, even though their API key itself is scoped). (https://www.bybit.com/en/help-center/article/How-to-Set-Up-the-Anti-Phishing-Code)
- **Device/session management** — Bybit's account security settings also expose a trusted-device list and login-activity log; reviewing these periodically (or programmatically, if exposed via API, which was not confirmed in this pass) is a further recommended hardening step for the owner's own Main-account hygiene, layered on top of (not a replacement for) the API-key-centric controls already specified in §2.1–§2.5. (https://www.bybit.com/en/help-center/article/How-to-Enhance-Your-Account-Security)

---

## 3. Discretionary crypto order-flow trader workflows → required views

### 3.1 Typical session workflow (synthesized from standard day-trading/order-flow practice; DeepCharts feature names per project brief)
1. **Session prep**: review overnight levels, funding rates, open interest changes, prior session's high/low/VAH/VAL (value area), macro calendar, watchlist of instruments with unusual volume/volatility.
2. **Watchlist screening**: multi-symbol scanner sortable by relative volume, volatility, funding rate, OI change, proximity to key levels.
3. **Level marking**: horizontal levels (support/resistance, prior day high/low, VWAP anchors, session opens), drawn once and persisted across sessions/timeframes.
4. **Multi-timeframe context**: a higher-timeframe chart (trend/structure) alongside a lower-timeframe execution chart, kept in sync (crosshair sync, level sync).
5. **Order-flow read**: footprint/Deep Print (bid/ask volume per price per candle), Deep Profile (session volume profile / value area), Deep Stats (delta, cumulative delta, absorption), Big Trades / large-print tape, imbalance tracker (stacked bid/ask imbalances), speed-of-tape (prints per second), DeepDOM (order book ladder with liquidity heatmap overlay), liquidity tracker, stop-run detector, iceberg detector, market regime indicator (trend vs range classification).
6. **Execution**: fast order entry (hotkeys, one-click market/limit, bracket orders with stop/target attached, DOM-based click-to-trade), position sizing calculator tied to risk %, custom rule-based stops/exits (e.g., trail after N ticks, breakeven at R multiple, time-based exit).
7. **Risk monitoring**: live P&L per position and aggregate, max daily loss / drawdown limits with auto-flatten or lockout, per-manager risk limits enforced by the owner.
8. **Journaling**: every trade auto-logged with entry/exit, screenshots or replay link, tags, and manual notes; post-session review view aggregating stats (win rate, expectancy, R-multiple distribution) — mirrors DeepCharts' "auto-tracker journal."
9. **Backtesting / replay**: tick-by-tick or bar-replay mode to rehearse a session or test a rule-based exit strategy against historical data without live risk.

### 3.2 Personas
| Persona | Goal | Key needs |
|---|---|---|
| **Owner/Admin** | Oversight of all capital, delegate to managers, ultimate control | Global dashboard across all sub-accounts, ability to freeze/kill any manager's trading instantly, full audit log access, API key management, risk-limit configuration per manager |
| **Manager (discretionary trader)** | Trade one or more assigned sub-accounts profitably within risk limits | Fast execution, footprint/DOM/heatmap, hotkeys, personal journal, own P&L/risk dashboard, cannot see other managers' accounts |
| **Manager (swing trader)** | Lower-frequency, higher-timeframe decisions | Multi-timeframe layouts, alerting (price/level/indicator triggers), less reliance on tick-level speed-of-tape, more emphasis on daily/4h profile and journal review |
| **Viewer (owner-as-reviewer)** | Audit a manager's performance without interfering | Read-only dashboard, journal review, audit log, performance analytics, no order entry rights |

### 3.3 Concrete screens list
1. **Login / 2FA** screen.
2. **Global Owner Dashboard** — all sub-accounts' equity, open P&L, daily P&L, risk-limit status, kill-switch buttons.
3. **Main Trading Terminal** (per sub-account context):
   - Primary chart panel: candlesticks + footprint overlay, multi-timeframe tabs, drawing tools/levels, VWAP(s), volume profile session/composite.
   - DOM + liquidity heatmap panel (DeepDOM equivalent), click-to-trade.
   - Order ticket / fast order entry panel (market/limit/stop, bracket, hotkeys, position size calculator).
   - Positions & Orders panel (open positions, working orders, quick flatten/cancel-all).
   - Tape/Time-and-Sales panel with speed-of-tape and big-trades highlighting.
   - Imbalance/absorption indicator strip.
   - Market regime indicator badge.
4. **Watchlist / Scanner** screen.
5. **Risk Dashboard** — per-manager and aggregate exposure, drawdown limits, auto-flatten status, margin/leverage usage (UTA-aware).
6. **Journal** screen — trade list with filters/tags, per-trade detail (chart snapshot/replay link, notes), aggregate stats (win rate, expectancy, R distribution), auto-populated from executed orders.
7. **Replay / Backtest** screen — tick or bar replay controls, strategy/rule-based stop-exit simulation.
8. **Paper Trading** mode toggle/screen — same terminal UI operating against Bybit demo trading (or a fully local simulated fill engine to cover the demo-trading WS gap noted in §1.3).
9. **Admin — Users & Roles** screen (Owner only) — create/deactivate managers, assign sub-accounts, set risk limits.
10. **Admin — API Keys** screen (Owner only) — add/rotate/revoke Bybit API keys per sub-account, permission/IP-whitelist self-check status indicator.
11. **Audit Log** screen (Owner only, Viewer read access) — searchable log of orders, logins, key changes.
12. **Alerts / Notifications** screen — price/level/indicator alert configuration and history.
13. **Settings** — layout persistence, hotkey configuration, theme, data retention settings.

---

## 4. Legal / ToS considerations

### 4.1 Bybit API Terms & Conditions
- Bybit maintains a distinct **"API Terms & Conditions"** help-center page (https://www.bybit.com/en/help-center/article/API-Terms), which states it is superseded by "the latest version" hosted elsewhere — i.e., the authoritative text is the live legal page, not the help-center summary. The umbrella **Bybit Platform Terms and Conditions** (effective date re-verified this pass — *corrected: the previously stated "effective 1 July 2026" could not be re-confirmed from an independent search pass and was likely a mis-parse of a template/placeholder date on the legal page; the global Bybit Platform Terms and Conditions page was found to carry a "last updated" date of 24 June 2025 in this pass, while the separate Bybit EU-entity Platform Terms and Conditions carry a "last updated" date of 23 January 2026 — Bybit maintains region-specific legal documents (global vs. EU vs. .eu domain) and the applicable version depends on which legal entity/jurisdiction the account is registered under. The exact effective date should be re-read directly off the live page at https://www.bybit.com/en/legal/terms-of-service/Bybit-BTL-Platform-Terms-and-Conditions immediately before finalizing any ToS-compliance stance, since it is legally load-bearing and this document should not be the last word on it.*) formally defines **"API Client"** as "any software, application, website or system that accesses, calls, commands, queries, requests, utilises or otherwise interacts with the API to perform certain actions in relation to a User's Account, for and on behalf of the User" and **"API Limits"** as the rate/frequency/connection/order-weight restrictions Bybit may impose and change at will. (https://www.bybit.com/en/legal/terms-of-service/Bybit-BTL-Platform-Terms-and-Conditions; global terms "last updated" 24 June 2025 and EU terms "last updated" 23 January 2026 per this pass's search — https://www.bybit.eu/en-EU/help-center/article/Bybit-Europe-Platform-Terms-and-Conditions)
- Under this definition, **CandleViewer itself is an "API Client" acting on behalf of each User (the account holder/sub-account holder)** — it does not need to be a registered broker as long as each manager is trading through their own authorized sub-account under the Main account holder's (owner's) control, and the tool is not offering the service to the public or acting as an unaffiliated intermediary reselling access. This supports treating each manager as an **"Authorized Individual"** (a term the Terms define as "any person that is authorised to access and use the Site, the App and the Platform... on behalf of a User") rather than as an independent unrelated third party — i.e., the owner should formally treat managers as authorized individuals acting on the owner's Bybit account/sub-accounts, not as separate unrelated account holders, to stay within a single coherent ToS relationship.
- The full API Terms document should be fetched and re-read at implementation time from the canonical "latest version" link referenced by the help-center page, since it governs rate limits, permitted automation, and liability — this document could not be fully retrieved in this research pass due to a search-tool rate limit; treat as an **open question / follow-up** (see below).
- **Restrictions on third-party tools**: no explicit blanket prohibition on self-built private trading tools was found in the excerpts retrieved; the "API Broker Program" (https://www.bybit.com/en/help-center/topic-list/api) exists specifically for businesses that want to offer Bybit-backed trading to their own external customers — this is the regime to avoid triggering. As long as CandleViewer is (a) privately operated by the account owner, (b) not offered/sold to unrelated third parties, and (c) each manager operates within the owner's own account structure (sub-accounts) rather than the tool holding third-party users' independent Bybit accounts, it should not require broker registration. **This is a reasoned inference from available material, not a legal opinion** — the user should have counsel confirm this against the actual live API Terms & Conditions text before going beyond a handful of trusted managers.
- **Regional restrictions**: Bybit maintains jurisdiction-specific restricted-country lists (e.g., Bybit EU's restricted list explicitly names USA, Canada, Singapore, Malaysia, Hong Kong, Russia, and sanctioned states among others: https://www.bybit.eu/en-EU/help-center/article/Service-Restricted-Countries). The owner and every manager's residency/location should be checked against the applicable Bybit entity's restricted-country list before onboarding, since this varies by which Bybit entity (global vs EU) holds the account.

### 4.2 TradingView Charting Library / Lightweight Charts licensing
- **Lightweight Charts™** is fully open-source under the **Apache License 2.0**, copyright TradingView Inc., hosted at https://github.com/tradingview/lightweight-charts — free to use, modify, and embed in a private commercial or non-commercial tool with no seat/user restriction, subject to standard Apache-2.0 attribution/notice requirements (retain the license file/notice). (https://github.com/tradingview/lightweight-charts/blob/master/LICENSE, https://github.com/tradingview/lightweight-charts/blob/master/README.md)
- **Advanced Charts** (formerly "Charting Library") and **Trading Platform** are, per TradingView's own comparison page, **Proprietary**, not open source, and require a separate license agreement directly with TradingView even though there is no listed monetary fee for "Free" tier access — they are gated behind an application/approval process, not a public npm/GitHub download. (http://tradingview.com/free-charting-libraries — "General License: Lightweight Charts™ Apache 2.0 · Advanced Charts Proprietary · Trading Platform Proprietary"; "Open source: Lightweight Charts yes, others no")
- For CandleViewer, given the footprint/DOM/heatmap feature requirements exceed what Lightweight Charts ships out of the box, the realistic paths are: (a) build custom canvas/WebGL rendering for footprint/DOM/heatmap on top of Lightweight Charts' base candlestick rendering (Lightweight Charts supports custom series/plugins), avoiding any TradingView proprietary-library agreement entirely, or (b) separately apply for TradingView's **Advanced Charts** free proprietary license (used by many retail-facing platforms) if its licensing terms (which restrict redistribution and require display of TradingView attribution, and historically restrict certain use cases) are acceptable for a private, non-redistributed internal tool — this requires reading TradingView's actual Advanced Charts license agreement, which is only provided after applying, so its exact terms could not be directly verified in this pass (flagged as an open question below). Given the project is private/non-commercial-distribution, **option (a) — Lightweight Charts (Apache-2.0) plus custom overlays — is the lower-legal-risk default recommendation.**
- TradingView's own Terms of Use also gate the "Essential/Plus/Premium" *subscription* market-data product (not the charting libraries) behind a "Non-professional use" self-certification (must be an individual, not a business entity, not registered with SEC/CFTC, not an investment adviser) — this is about TradingView's own data subscription, not about using the open-source Lightweight Charts library, and is not directly relevant unless CandleViewer also intends to pull TradingView-sourced market data (out of scope; CandleViewer sources market data from Bybit directly, per the project brief).

### 4.3 DeepCharts IP
- The project brief already correctly scopes this: **replicate the described feature concepts (footprint/Deep Print, Deep Profile, Deep Stats, Big Trades, imbalance tracker, speed-of-tape, VWAPs, DeepDOM heatmap, liquidity tracker, stopruns, iceberg detector, market regime, tick replay, journal), not any DeepCharts branding, trademarked product names, UI chrome, or proprietary source code/assets.** Feature concepts and chart types (footprint charts, volume profile, DOM heatmaps) are generic order-flow-analysis techniques used across many commercial platforms (also seen in Bookmap, ATAS, Sierra Chart, Jigsaw) and are not exclusive DeepCharts IP — but DeepCharts' specific product names ("Deep Print," "DeepDOM," "DeepGamma," "AEM," etc.), logos, and any copied UI/text/marketing copy should not be reused. CandleViewer should use its own generic names internally (e.g., "Footprint Chart," "DOM Heatmap," "Volume Profile") rather than DeepCharts' trademarked names, consistent with the project brief's own instruction.

---

## 5. MVP slicing — MoSCoW table (~80 features)

Legend: **M** = Must have (MVP), **S** = Should have (near-term post-MVP), **C** = Could have (valuable, later), **W** = Won't have (explicitly out of scope for now).

### 5.1 Charting
| # | Feature | Priority |
|---|---|---|
| 1 | Candlestick chart (OHLCV) with pan/zoom | M |
| 2 | Multi-timeframe switching (1m–1D) | M |
| 3 | Multiple synced chart panels (multi-timeframe layout) | M |
| 4 | Horizontal level drawing tool, persisted per symbol | M |
| 5 | Trendline/ray/rectangle drawing tools | S |
| 6 | VWAP (session) overlay | M |
| 7 | Anchored VWAP (custom anchor) | S |
| 8 | Volume profile (session, fixed range) | M |
| 9 | Composite/visible-range volume profile | S |
| 10 | Footprint chart (bid/ask volume per price per candle) | M |
| 11 | Footprint delta coloring / imbalance highlighting | M |
| 12 | Market regime indicator (trend/range classification) | S |
| 13 | Standard TA indicators (MA/EMA, RSI, etc.) | S |
| 14 | Custom indicator scripting | C |
| 15 | Chart templates/layout save-load | M |
| 16 | Crosshair sync across panels | M |
| 17 | Chart screenshot/export | C |

### 5.2 Order flow / market microstructure
| # | Feature | Priority |
|---|---|---|
| 18 | DOM (order book ladder) | M |
| 19 | DOM liquidity heatmap overlay | M |
| 20 | Click-to-trade from DOM | S |
| 21 | Time & Sales (tape) | M |
| 22 | Speed-of-tape indicator (prints/sec) | S |
| 23 | Big trades / large-print highlighting | M |
| 24 | Imbalance tracker (stacked bid/ask imbalance) | M |
| 25 | Absorption/Deep Stats delta metrics | S |
| 26 | Liquidity tracker (resting size changes over time) | C |
| 27 | Stop-run detector | C |
| 28 | Iceberg order detector | C |
| 29 | Cumulative delta chart | S |

### 5.3 Data
| # | Feature | Priority |
|---|---|---|
| 30 | Live WS market data (klines, trades, orderbook) per symbol | M |
| 31 | Historical OHLCV backfill/storage | M |
| 32 | Historical tick/trade storage for replay | S |
| 33 | Multi-symbol simultaneous subscriptions | M |
| 34 | Funding rate / open interest tracking | S |
| 35 | Data retention policy & pruning | S |
| 36 | Local caching for fast chart reload | M |

### 5.4 Trading
| # | Feature | Priority |
|---|---|---|
| 37 | Market/limit order entry | M |
| 38 | Stop/stop-limit orders | M |
| 39 | Bracket orders (entry+stop+target) | M |
| 40 | Fast order entry / hotkeys | M |
| 41 | Position sizing calculator (risk %) | M |
| 42 | One-click flatten / cancel-all | M |
| 43 | Reduce-only / post-only order flags | S |
| 44 | OCO (one-cancels-other) | S |
| 45 | Multi-account order routing (per manager scope) | M |
| 46 | Leverage/margin mode control (UTA-aware) | S |

### 5.5 Automation / rule-based stops
| # | Feature | Priority |
|---|---|---|
| 47 | Rule-based trailing stop (ticks/ATR) | M |
| 48 | Breakeven-at-R-multiple auto-move | S |
| 49 | Time-based auto-exit | S |
| 50 | Custom rule builder (conditional exits) | S |
| 51 | Price/level alert triggers | M |
| 52 | Alert-to-action automation (alert triggers order) | C |
| 53 | Daily loss limit auto-flatten/lockout | M |

### 5.6 Paper trading
| # | Feature | Priority |
|---|---|---|
| 54 | Bybit demo-trading integration (REST) | M |
| 55 | Local simulated fill engine (covers demo WS gap) | S |
| 56 | Paper P&L tracking identical to live UI | M |
| 57 | Switch live/paper per session | M |

### 5.7 Replay / backtest
| # | Feature | Priority |
|---|---|---|
| 58 | Bar replay mode | S |
| 59 | Tick-by-tick replay | C |
| 60 | Rule-based strategy backtest against replay data | C |
| 61 | Replay speed control / step-by-step | S |

### 5.8 Journal
| # | Feature | Priority |
|---|---|---|
| 62 | Auto-logged trade journal (entry/exit, size, P&L) | M |
| 63 | Manual notes/tags per trade | M |
| 64 | Chart snapshot attached to trade | S |
| 65 | Aggregate stats (win rate, expectancy, R distribution) | S |
| 66 | Journal export (CSV) | C |

### 5.9 Multi-account / admin
| # | Feature | Priority |
|---|---|---|
| 67 | Sub-account mapping per manager | M |
| 68 | Role-based access control (Owner/Manager/Viewer) | M |
| 69 | Per-manager risk limits set by Owner | M |
| 70 | Global Owner dashboard across sub-accounts | M |
| 71 | Owner kill-switch (freeze a manager instantly) | M |
| 72 | API key management UI (add/rotate/revoke) | M |
| 73 | API key permission/IP-whitelist self-check | M |
| 74 | Audit log (orders, logins, key changes) | M |
| 75 | 2FA login | M |
| 76 | Manager onboarding workflow (new sub-account, 48h wait handling) | S |

### 5.10 Non-functional / platform
| # | Feature | Priority |
|---|---|---|
| 77 | Tailscale-based remote access for managers | M |
| 78 | Encrypted-at-rest API key storage | M |
| 79 | Centralized market-data fan-out (single WS per symbol) | M |
| 80 | Multi-exchange abstraction layer (Bybit first, extensible) | S |

---

## 6. Non-functional targets

- **Latency budget (WS → screen)**: for a discretionary human trader (not HFT), a reasonable target is **≤150–250ms** end-to-end from Bybit WS message receipt to a re-rendered chart/DOM/tape update in the browser, broken down roughly as: network+processing at the backend ingestion layer (~20–50ms), internal fan-out to the frontend over local WS/SSE (~5–20ms on a LAN/tailnet), and frontend render (~16–50ms, ideally within one to two animation frames). This is generous compared to HFT/market-making latency budgets (sub-millisecond) because the tool is for human decision-making, not algorithmic execution — but should still feel "live" with no visible stutter on the tape/DOM.
- **Order round-trip target**: order placement click → Bybit acknowledgment display should target **≤300–500ms** under normal network conditions (REST order placement, not WS), since discretionary execution quality depends on the trader trusting the fill was fast.
- **Uptime for a personal server**: since this is a single-owner private tool (not a public SaaS), a pragmatic target is **~99% during active trading hours** (i.e., tolerate brief restarts/deploys outside trading hours) rather than 99.9%+ enterprise SLAs — but the **risk-critical subsystems (position monitoring, stop/rule engine, daily-loss-limit auto-flatten) should be held to a higher bar**, since an outage there while a position is open is a real capital-risk event, not just an inconvenience. Recommend: watchdog process that alerts (and optionally force-flattens or at least notifies all managers) if the backend's connection to Bybit's private WS/REST drops for more than a configurable threshold (e.g., 10–30 seconds) while positions are open.
- **Data retention**: 
  - Tick/trade-level data needed for footprint/replay: retain at **full resolution for a rolling recent window** (e.g., 30–90 days) given tick data volume, then downsample/aggregate (e.g., to 1-minute bars) for longer-term storage.
  - OHLCV bar data: retain **indefinitely** at 1m+ resolution (storage-cheap) to support long-horizon charting/backtesting.
  - Audit logs / journal / order history: retain **indefinitely** (compliance and personal record-keeping value, low storage cost relative to tick data).
  - Define an explicit pruning job and a documented retention policy per data class so this doesn't grow unbounded on a personal server's disk.

---

## Sources

- Bybit — How to Create and Set Up a Bybit API Key: https://www.bybit.com/en/learn/bybit-guide/how-to-create-a-bybit-api-key
- Bybit — How to Create Your API Key? (Help Center): https://www.bybit.com/en/help-center/article/How-to-create-your-API-key
- Bybit — Unified Trading Account (Help Center topic list): https://www.bybit.com/en/help-center/topic-list/unified-trading-account
- Bybit — API (Help Center topic list, incl. API Broker Program, Copy Trading): https://www.bybit.com/en/help-center/topic-list/api
- Bybit — How to Get Started With a Standard Subaccount: https://www.bybit.com/en/help-center/article/How-to-Get-Started-With-Standard-Subaccount
- Bybit — API Terms & Conditions (Help Center pointer page): https://www.bybit.com/en/help-center/article/API-Terms
- Bybit — Terms of Service (Help Center topic list): https://www.bybit.com/en/help-center/topic-list/terms-of-services
- Bybit — Terms of Service (legal hub): https://www.bybit.com/en/legal/terms-of-service
- Bybit — Platform Terms and Conditions (BTL; global version "last updated" 24 June 2025 per this pass — corrected from a prior "effective 1 July 2026" claim, see §4.1 footnote): https://www.bybit.com/en/legal/terms-of-service/Bybit-BTL-Platform-Terms-and-Conditions
- Bybit EU — Platform Terms and Conditions ("last updated" 23 January 2026): https://www.bybit.eu/en-EU/help-center/article/Bybit-Europe-Platform-Terms-and-Conditions
- Bybit Help Center — FAQ: Standard Subaccount (5/20 sub-account caps): https://www.bybit.com/en/help-center/article/FAQ-Standard-Subaccount
- Bybit Announcement — Important update to Subaccounts (Aug 2026 cap change): https://announcements.bybit.com/en/article/important-update-to-subaccounts--art5ebb9ca6e027/
- Bybit Help Center — FAQ: Unified Trading Account (UTA margin modes, collateral): https://www.bybit.com/en/help-center/article/FAQ-Unified-Trading-Account
- Bybit Help Center — Introduction to Bybit Unified Trading Account (UTA): https://www.bybit.com/en/help-center/article/Introduction-to-Bybit-Unified-Trading-Account
- Bybit API Docs — Account Upgrade to Unified Account: https://bybit-exchange.github.io/docs/v5/account/upgrade-unified-account
- Bybit Help Center — How to Manage Funds in Unified Trading Account: https://www.bybit.com/en/help-center/article/How-to-Manage-Funds-in-Unified-Trading-Account
- Bybit Announcement — Launch of AI Subaccount for secure and isolated AI trading execution: https://announcements.bybit.com/en/article/launch-of-ai-subaccount-for-secure-and-isolated-ai-trading-execution-blta50e3efa96768430/
- Bybit Help Center — How to Add a Withdrawal Wallet Address: https://www.bybit.com/en/help-center/article/How-to-add-your-withdrawal-wallet-address
- Bybit Help Center — How to Manage Your Withdrawal Security: https://www.bybit.com/en/help-center/article/How-to-Manage-Your-Withdrawal-Security
- Bybit Help Center — How to Set Up the Anti-Phishing Code: https://www.bybit.com/en/help-center/article/How-to-Set-Up-the-Anti-Phishing-Code
- Bybit Help Center — How to Enhance the Security of Your Account: https://www.bybit.com/en/help-center/article/How-to-Enhance-Your-Account-Security
- Bybit API Documentation — Error Codes (official V5 error-code reference, incl. 10006 rate-limit code): https://bybit-exchange.github.io/docs/v5/error
- Bybit API Documentation — Demo Trading Service (official; confirms `wss://stream-demo.bybit.com` private WS endpoint): https://bybit-exchange.github.io/docs/v5/demo
- bybit-exchange/api-usage-examples — V5 demo-trading WebSocket trade API example (Go): https://github.com/bybit-exchange/api-usage-examples/blob/master/V5_demo/wss_demo/go/ws_trade_api_demo.go
- Upcomers Help Center — Bybit API connection troubleshooting (API key revocation does not cancel resting orders — third-party, not primary-sourced): https://help.upcomers.com/en/articles/12176521-bybit-api-connection-troubleshooting-for-upcomers
- Trilicity — Securing Bybit API Keys with IP Whitelisting (20-IP-per-key figure — third-party, not primary-sourced): https://trilicity.com/articles/setting-up-ip-whitelisting-for/
- PapaProxy — Bybit API Key IP Whitelist: Why Keys Expire in 90 Days (90-day/no-IP expiry figure — third-party, not primary-sourced): https://papaproxy.net/blog/bybit-api-key-ip-whitelist.php
- Bybit.eu — Terms of Service (Help Center topic list): https://www.bybit.eu/en-EU/help-center/topic-list/terms-of-services
- Bybit.eu — Service Restricted Countries: https://www.bybit.eu/en-EU/help-center/article/Service-Restricted-Countries
- Crypto-resources.com — Bybit: Sub-account and API creation guide (incl. demo API key distinction): https://crypto-resources.com/manuals/bybitsub-account-and-api-creation
- Insilico Terminal docs — Creating a Bybit API Key (no-withdrawal guidance): https://docs.insilicoterminal.com/documentation/setup/creating-an-api-key/creating-a-bybit-api-key
- Cryptact Help Center — How to get an API key for Bybit (IP whitelist example, UTA vs standard permission checklist): https://support.cryptact.com/hc/en-us/articles/4412303076889-How-to-get-an-API-key-for-Bybit
- pybit (official Bybit Python SDK) — `_v5_user.py`, sub-UID/API-key permission fields: https://github.com/bybit-exchange/pybit/blob/master/pybit/_v5_user.py
- tiagosiebler/bybit-api (Node SDK) — README, demo trading WS limitation (Jan 2025) and rate-limit notes: https://github.com/tiagosiebler/bybit-api/blob/master/README.md
- TradingView — Lightweight Charts™ GitHub repository: https://github.com/tradingview/lightweight-charts
- TradingView — Lightweight Charts™ LICENSE (Apache-2.0): https://github.com/tradingview/lightweight-charts/blob/master/LICENSE
- TradingView — Lightweight Charts™ README (license section): https://github.com/tradingview/lightweight-charts/blob/master/README.md
- TradingView — Lightweight Charts™ product page: https://www.tradingview.com/lightweight-charts
- TradingView — Free Charting Libraries comparison page (Lightweight Charts vs Advanced Charts vs Trading Platform licensing): http://tradingview.com/free-charting-libraries
- TradingView — Terms of Use / Non-professional data-use certification (context on TradingView's own data subscription terms, not the charting libraries): (retrieved via search excerpt of TradingView Terms of Use page)

## Open questions

1. **Full Bybit API Terms & Conditions text** — the canonical "latest version" document (linked from https://www.bybit.com/en/help-center/article/API-Terms) was not directly fetched in this pass due to a search-tool rate limit; it should be read in full before finalizing the ToS-compliance stance, particularly any clause on automated/algorithmic trading tools, liability for API-driven losses, and any explicit restriction on multi-user internal tooling.
2. **Exact current Bybit V5 rate limits by endpoint and VIP tier** — numeric ceilings should be pulled directly from Bybit's official rate-limit documentation page at implementation time (tier-dependent, subject to change) rather than relied on from this research pass.
3. **TradingView Advanced Charts license agreement full text** — only available after formally applying for access; its exact restrictions on private/internal (non-redistributed) use, attribution requirements, and whether a small private multi-user tool would even qualify for the free tier, could not be verified here. Needed only if the team later decides Lightweight Charts + custom overlays is insufficient and wants to pursue Advanced Charts instead.
4. **Whether Bybit's automatic IP-whitelisting-for-partners** (seen in some third-party terminal integrations, e.g., Insilico Terminal) is something CandleViewer could ever qualify for, versus manually whitelisting a static home/server IP — likely moot for a private tool (manual whitelisting is sufficient and simpler), but worth confirming Bybit doesn't require a distinct partner registration purely to whitelist one's own IP (it should not, but this exact interaction wasn't directly documented in the retrieved pages).
5. **Precise current Bybit numeric API rate limits for order placement/amend/cancel per sub-account**, which directly affects how aggressively CandleViewer can implement rule-based auto-exit polling/cancel-replace patterns without tripping limits — needs direct confirmation from Bybit's official V5 API rate-limit reference at implementation time.
6. ~~**Demo trading WS support status may change**~~ — **RESOLVED this pass** (see §1.3): official Bybit sources (`bybit-exchange.github.io/docs/v5/demo` and the `bybit-exchange/api-usage-examples` repo) confirm a dedicated private WebSocket endpoint (`wss://stream-demo.bybit.com`) exists for demo trading, superseding the prior January-2025 community-SDK-sourced claim that demo lacked private WS support. Remaining residual uncertainty: full topic/order-type parity with live WS was not exhaustively verified (see §1.3 residual-uncertainty note).
7. **Legal/regulatory status of "managers" trading on the owner's behalf** — while this research treats managers as "Authorized Individuals" under Bybit's own Terms, whether this arrangement has any regulatory implication for the owner (e.g., discretionary account management potentially resembling investment-adviser activity in some jurisdictions, even privately) was explicitly out of scope for this technical/ToS research and should be checked with actual legal counsel given the brief's mention of "managing the owner's accounts." **Rough jurisdictional grounding added this pass (not a substitute for counsel):**
   - **United States**: The Investment Advisers Act of 1940 and most state equivalents generally trigger registration/licensing requirements based on whether a person provides advice **"for compensation"** as a regular business. Unpaid, one-off, or purely personal/family discretionary trading typically falls outside adviser-registration triggers because the "for compensation" and "in the business of" elements are not met — however, this is a **fact-specific, multi-factor test** (frequency, number of people managed, any indirect compensation such as a profit share or even reciprocal favors, and whether it's held out as a service to the public), and having **multiple non-family "managers"** trading sub-accounts on the owner's behalf (rather than the reverse — the owner trading on others' behalf) is a **different fact pattern** from the classic adviser scenario and was not found addressed directly in any primary regulatory source in this pass.
   - **United Kingdom**: The FCA's regulated-activities framework (FSMA 2000, Regulated Activities Order) treats "managing investments" and "advising on investments" as regulated activities requiring authorization *when carried on "by way of business"* — genuinely gratuitous, non-business arrangements (e.g., a friend or family member with no fee, profit-share, or commercial arrangement) are generally understood to fall outside this "by way of business" threshold, but the FCA does not publish a bright-line exemption for "unpaid discretionary management," and the analysis again turns on frequency/scale/commerciality.
   - **EU**: MiFID II's "portfolio management" and "investment advice" definitions similarly hinge on activity being carried out as an "investment service" for clients in a commercial/professional capacity; purely gratuitous private arrangements are generally outside scope, but this is not explicitly codified as a blanket exemption in the directive text itself.
   - **Common thread across all three**: the recurring, load-bearing variable in every jurisdiction is **whether any compensation (direct or indirect) changes hands and whether the activity is conducted "as a business"/"by way of business"** — CandleViewer's own brief states no fees are charged, which is a materially favorable fact, but the **number of managers, any indirect benefit to the owner, and whether the arrangement could be perceived as "holding out" a service** all remain fact-specific risk factors that only a jurisdiction-specific lawyer can properly close out. **This paragraph is a starting orientation only, not a legal opinion, and does not resolve open question #7** — it remains open and counsel should still be consulted before onboarding non-family managers at any scale.
8. **Exact numeric limits could not be fully pinned down despite additional research this pass**: max API keys per UID (conflicting third-party figures of 5/10/20/30/100, no single authoritative Bybit page found stating a number), the exact temporary IP-ban duration for repeated rate-limit violations (no primary source found), and the precise meaning of Bybit error code `10018` (loosely described in secondary sources, not confirmed against the live official error-code page). All three should be confirmed directly against the live Bybit API Management dashboard / official error-code reference (https://bybit-exchange.github.io/docs/v5/error) at implementation time rather than relied upon from this research pass.
