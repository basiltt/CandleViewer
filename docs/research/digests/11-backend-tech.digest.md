# Digest: 11-backend-tech.md (Python backend architecture for Bybit order-flow terminal)
## Scope
- Ingest Bybit WS (public: trades, L2 depth deltas 50/200/500/1000, tickers, liquidations; private: orders/executions/positions/wallet), N symbols (BTCUSDT, ETHUSDT initial, expandable).
- Local book reconstruction (snapshot+delta); bar building (time/tick/volume/range/delta); footprint/profile/CVD/imbalance/heatmap/Deep Stats aggregation.
- Fan-out to React over WS, backpressure, snapshot+delta, optional binary encoding.
- OMS: state machine, idempotent submission (`orderLinkId`), reconnect reconciliation, rule engine, paper-trading matching engine.
- Persistence for tick/L2/OHLC suited to replay/footprint queries; deterministic replay engine w/ speed control.
- Deploy: WSL Ubuntu now → small dedicated server later.
## 2. Bybit v5 WS API surface

### 2.1 Public streams
| Stream | Topic | Depth | Frequency | Notes |
|---|---|---|---|---|
| Orderbook | `orderbook.{depth}.{symbol}` | Linear: 1/50/200/500; Spot: 1/50/200; Option: 25/100 | Linear L1 10ms, L50 20ms, L200/L500 100ms; Spot L1 10ms, L50 20ms, L200 200ms; Option L25 20ms, L100 100ms | Snapshot on subscribe then deltas; `amount=0`=delete, new price=insert, else update. Snapshot forces full rebuild. **Correction**: earlier "1/50/200/1000" depth and single "200ms" freq figure could not be re-confirmed; linear tops at 500 not 1000, spot tops at 200 — flagged for re-verify at implementation vs primary docs [45][46]. |
| Trade | `publicTrade.{symbol}` | n/a | real-time | side, price, size, trade id, block-trade flag |
| Ticker | `tickers.{symbol}` | n/a | ~100ms throttled | 24h stats, mark/index price, funding, OI |
| Kline | `kline.{interval}.{symbol}` | n/a | 1–60s | sanity cross-check only, not primary (custom bars needed) |
| Liquidation | `liquidation.{symbol}` | n/a | real-time | deprecated → `allLiquidation` |
| All-liquidation | `allLiquidation.{symbol}` | n/a | real-time, snapshot only, 1s aggregated | replacement stream |

### 2.2 Private streams (single `/v5/private`)
- `position`, `order`, `execution`, `execution.fast` (lower-latency, recommended for fills), `wallet`, `greeks` (not needed now).
- Connect: `/v5/ws/connect`, ops subscribe/unsubscribe/auth/ping, JSON envelope `{req_id,op,args}`, ack `{success,ret_msg,op,conn_id}`, pushes `{topic,type,ts,data}`.

### 2.3 Order entry over WS
- `order.create`/`amend`/`cancel` via WS trade ops (`wss://stream.bybit.com/v5/trade`) — lower latency than REST. **Demo trading does NOT support WS trade API** — must use REST for demo order entry.

### 2.4 Demo trading
- Domain: REST `api-demo.bybit.com`, WS private `stream-demo.bybit.com`; public data uses normal mainnet WS (no separate demo public feed).
- `testnet` and `demoTrading` mutually exclusive.
- Demo: separate sub-account, own API keys, limited endpoints (market data, order CUD, open orders/history, position list, set-leverage, switch position-mode), 7-day order retention, non-upgradable rate limits.
- Architecture needs explicit env enum (`demo`/`live`/`testnet`) swapping base URLs, disabling WS order entry in demo.
- Re-verified Sept 2026: WS-trade-unsupported-on-demo still current. New 2026 Bybit policy changes: (a) API key IP-allowlist now browser-only config (Feb 2026); (b) new accounts have cooldown before API key creation; (c) some REST rate limits (e.g. transaction-log polling) tightened in 2026. Don't assume IP-allowlisting can be automated; re-check changelog before implementation [40][63].

### 2.5 Idempotency & reconciliation
- `orderLinkId`: client-supplied ID for idempotent submission; Bybit dedupes within retention window.
- Reconciliation after reconnect/crash: (1) re-auth private WS, (2) REST `GET /v5/order/realtime` + `GET /v5/position/list` for authoritative state, (3) diff vs local cache keyed by `orderLinkId`, (4) backfill executions via `GET /v5/execution/list` for gap window, (5) resume streaming.
- **Clock drift / recv_window**: signed REST requires `timestamp`; rejected (error **10002**) if outside `server_time - recv_window <= ts < server_time+1000`; default `recv_window`=**5000ms**. Mitigations in order: (1) NTP (chrony/ntpd) on host — primary fix; (2) periodic `GET /v5/market/time` offset calc (pybit/ccxt `adjustForTimeDifference` do this); (3) raising recv_window (e.g. to 10000ms) only as stopgap (widens replay-attack tolerance). OMS REST adapter should surface 10002 distinctly (diagnose as clock-sync issue).
- Node SDK `tiagosiebler/bybit-api` pattern: heartbeat disconn detection (~24h forced disconnect claim — **third-party, unconfirmed against Bybit's own docs**, treat as plausible-but-unverified), auto reconnect+resubscribe, `reconnected` event. No mature async Python client with same ergonomics — CandleViewer must hand-build this.

### 2.6 Rate/connection limits (hard ceilings)
- **Max 10 topics/args per `subscribe` request** — chunk subscriptions into ≤10 groups from day one.
- **WS connections**: ≤500 new connections/5min per IP; ≤1000 concurrent per IP for market data (counted per category). Avoid reconnect churn; use exponential backoff.
- **REST order endpoints**: per-UID, per-endpoint, rolling window; headers `X-Bapi-Limit`/`X-Bapi-Limit-Status`/`X-Bapi-Limit-Reset-Timestamp`; default non-VIP UTA ~**10 req/s** for order create/amend/cancel, scales up by VIP tier. Must respect headers or use conservative local token bucket; treat 429 as backoff+requeue signal.
- **Ping/keepalive**: send `{"op":"ping"}` ~every 20s; run heartbeat as dedicated task independent of message loop (avoid GC/backpressure starving ping).

### 2.7 UTA vs Classic
- Target **UTA exclusively** (Bybit phasing out Classic). Implications: (1) single unified wallet — don't assume Classic's multi-wallet shape; (2) position mode (one-way/hedge) via `/v5/position/switch-mode`, category-scoped, must be read/respected before order placement (mismatched `positionIdx` rejected); (3) leverage per-symbol via `/v5/position/set-leverage`, interacts with unified margin pool under cross margin. OMS should read/cache position+margin mode at startup; treat mismatch as hard startup error, not auto-switch.

## 3. Reference OSS architectures
- **NautilusTrader** — most architecturally relevant. Rust-core, Python bindings. MessageBus (pub/sub+req/rep+point-to-point, topic hierarchy), DataEngine, ExecutionEngine, RiskEngine, Portfolio, Cache, Trader/actors. Environment contexts: Backtest/Sandbox(paper)/Live share same strategy code — **copy this pattern** for paper vs live split. Bar aggregation (tick/volume/value/time) is first-class/well-trodden. Migrating v1 Cython→v2 Rust core w/ PyO3 — validates "hot path in Rust, orchestration in Python." Bybit adapter in Rust; demo mode has no trade WS (batch ops fall back to individual HTTP) — corroborates §2.4. **Takeaway**: don't adopt wholesale (too big/opinionated), but mirror skeleton: central async bus, DataEngine-equivalent (book+bar/footprint), ExecutionEngine-equivalent (OMS+reconciliation), shared Cache.
- **Freqtrade** — ccxt-based, threaded/polling not asyncio-streaming; OHLCV-only, no footprint/DOM. FastAPI RPC + SQLite OMS persistence pattern useful reference only.
- **Hummingbot** — Cython/Python market-making; connector pattern (OrderBookTracker/UserStreamTracker/Exchange per venue, independently restartable) — good modularity template for multi-exchange-ready adapter layer. Thin analytics layer, not useful for footprint reference.
- **Jesse** — OHLCV/strategy-class backtesting, Postgres storage. Confirms Postgres/Timescale-family common for candles+trades; limited other value.
- **cryptofeed** (bmoscon) — asyncio, normalizes many exchanges incl. Bybit into common callback API (trades, L2/L3, ticker, OI, funding, liquidations). Confirmed active Bybit v5 support, 2.5.0 (2026-08-08) fixed L2_BOOK timestamp normalization, 2.4.0 fixed private-channel connection/subscription issues. Pluggable backends: Redis, ZeroMQ, Kafka, Postgres, **QuestDB**, InfluxDB v2, MongoDB, raw sockets. Architecture: FeedHandler→Feed(per exchange)→ConnectionHandler+subscription map; async callbacks. **Recommendation: use as ingestion+book-reconstruction layer.** Trade-off: adds normalization overhead, smaller community than ccxt; private-stream Bybit support less battle-tested — validate against raw payloads before trusting for OMS.
- **tardis-machine** (Node.js, not Python) — local replay server, same WS message shape live vs replay — exactly the abstraction CandleViewer's replay engine should copy.
- **Cryptostore** — cryptofeed companion for archival (Arctic/Mongo-oriented), smaller/less maintained; design reference only, not to adopt directly.

## 4. Async web framework & performance substrate

### 4.1 Framework comparison
| Framework | Notes |
|---|---|
| FastAPI (+Starlette+uvicorn) | Most widely used, huge ecosystem, Pydantic validation; multi-worker in-process broadcast doesn't span workers (needs Redis or single-worker — fine for single-user) |
| Litestar | 3 WS styles; msgspec-first serialization, faster JSON/DI throughput than FastAPI in stock benchmarks; smaller ecosystem |
| aiohttp | Own server not ASGI; mature both server & client (relevant as Bybit connector client too) |
| Sanic | Raw throughput focus, not clearly better for this use case |
| Tornado | Legacy, no reason to pick over FastAPI/Litestar |
| Raw `websockets` lib | Purpose-built asyncio, ~10K conn/core/core ceiling (irrelevant at this scale), has `broadcast()` helper |

**Recommendation**: FastAPI for REST control/config/auth; high-freq WS fan-out on raw Starlette WebSocket (bypass Pydantic) or Litestar if msgspec end-to-end desired. Single-process design avoids needing Redis pub/sub for multi-worker broadcast. If multi-worker ever needed: Redis Pub/Sub or Streams as shared broadcast bus (no client-side changes needed).

### 4.2 asyncio/threads/uvloop/GIL
- **uvloop**: enable explicitly for ingestion/fan-out (bundled via `uvicorn[standard]`).
- Ingestion/fan-out/OMS I/O map to single asyncio loop + uvloop; CPU-bound (bar/footprint/heatmap/CVD) risks blocking loop. Mitigations: (a) O(1)/O(log n) per-tick updates, vectorized batch flush via numpy/polars; (b) offload heavy batch recompute to `ProcessPoolExecutor` or Rust/PyO3; (c) numba-jit hot loops via `run_in_executor`.
- **Free-threaded Python 3.13/3.14** (PEP 703): experimental/opt-in (`python3.13t`), ecosystem compat not universal (numpy etc. incrementally adding support). **Not yet dependable default** — design CPU hot path extractable to Rust/process regardless of GIL fate.

### 4.3 Serialization
- **msgspec**: decodes+validates faster than orjson decodes alone; Struct types 5–60x faster than dataclasses/attrs; 10–80x faster encode/decode vs alternatives. Supports MessagePack/YAML/TOML too.
- **orjson**: fast Rust-backed JSON, but slower than msgspec. Ranking: msgspec > simdjson > orjson > stdlib json.
- **Recommendation**: standardize bus + outbound protocol on msgspec (`Struct` types; JSON for dev, MessagePack for production binary framing), get schema validation "for free."

#### 4.3.1 Binary framing & backpressure
- **MessagePack** (via msgspec): lowest implementation cost, reuse existing tooling; slightly larger wire size than fixed-schema binary — minor at LAN scale.
- **Protobuf**: smaller payloads/schema evolution but needs `.proto`+codegen — hard to justify for single internal consumer.
- **FlatBuffers/Cap'n Proto**: zero-copy, fastest for very large messages, higher complexity — not worth it for CandleViewer's small per-tick messages.
- **permessage-deflate (RFC7692)**: transport-level compression; skip for msgpack high-freq stream (CPU cost > benefit on compact frames); reserve only for a future JSON debug path.
- **Overall**: msgpack via msgspec is the pragmatic choice; revisit protobuf/FlatBuffers only if profiling shows serialization/bandwidth bottleneck.
- **Backpressure strategy** (standard asyncio pattern, no extra deps):
  1. Bounded `asyncio.Queue(maxsize=N)` per WS connection (N small e.g. 2–8 for DOM/heatmap; larger for low-freq streams like bar closes).
  2. Full queue → **drop-oldest-and-coalesce** for state streams (DOM/heatmap/book snapshots — replace w/ latest full snapshot); **disconnect-the-slow-client** for event streams (trade prints, fills, footprint deltas) rather than silently drop.
  3. Dedicated sender task per connection drains queue → decouples publish path from slow client I/O.
  4. Monitor per-connection queue depth metric; disconnect if persistently full beyond threshold (few seconds).

### 4.4 Numeric/aggregation layer
- **polars vs pandas**: ~order of magnitude faster on filter/groupby/join/aggregate; less memory; polars import ~70ms vs pandas ~520ms. Use polars for replay/batch recompute.
- **numpy**: right tool for live per-tick incremental aggregation (footprint cell increments, running CVD, rolling VWAP) — avoid polars/pandas per-call overhead for single-row updates; use plain objects/numpy scalars/ring buffers.
- **numba**: JIT for CPU-bound hot loops hard to vectorize (full heatmap/footprint rebuild during replay); warm-up cost + debugging opacity trade-offs.
- **Rust via PyO3/maturin**: highest ceiling for latency-critical paths (book delta application, matching engine, footprint updates at tick rate). `maturin` is standard toolchain (same as polars' own bindings). **Recommendation: treat as phase-2** — start pure Python/numpy/polars, only build PyO3 extension for whichever hot path profiling flags as bottleneck (most likely candidate: multi-symbol/multi-depth L2 delta application, given 200-depth pushes every 100ms and 1000-depth every 200ms/symbol).

## 5. Bybit client library choice
| Option | Assessment |
|---|---|
| **pybit** (official) | REST sync, WS thread-based (`websocket-client`+`threading`, manual ping/pong). Official = fastest to reflect API changes, but thread-based WS needs asyncio bridge (`run_coroutine_threadsafe`/queue). |
| **ccxt/ccxt.pro** | ccxt.pro (paid, confirmed still paid as of 2026) has asyncio-native `watch*` methods w/ auto-reconnect; unified cross-exchange API good for multi-exchange future but normalizes away exchange-specific fields (sequence numbers, block-trade flags); free ccxt has no WS support at all. |
| **cryptofeed** | Fully asyncio, native Bybit market-data normalization, free/OSS, actively maintained (2026 L2 timestamp fix). Does NOT cover order entry/execution — public-stream half only. |
| **Custom websockets/aiohttp client** | Max control, no dep risk, but reimplements auth/ping/reconnect state machine — higher dev/maintenance cost and risk of mishandling Bybit edge cases. |

**Recommendation**: cryptofeed for public market data (solves L2 snapshot/delta reconstruction — highest-risk piece). pybit for private/execution streams + REST order entry (official, fastest-to-update), wrapped in asyncio bridge (queue.Queue fed from callback thread, drained via asyncio task) — OR a thin custom asyncio private-WS client (private topic surface is small; genuine open design choice, prototype both — see Open Q1). Do NOT adopt ccxt.pro (cost + normalization trade-off not worth it given cryptofeed+pybit combo).

## 6. Persistence layer comparison
| Store | Ingest | Compression | Query fit | Ops | Notes |
|---|---|---|---|---|---|
| **TimescaleDB** | Good (Postgres/WAL-bound) | Native columnar on old chunks | Full SQL, joins w/ OMS tables in same DB | Low-medium ("just Postgres") | Best if want normal relational DB that also does TS well |
| **QuestDB** | Very high — vendor claims ~5x faster than ClickHouse, ~8x vs Timescale, ~16x vs InfluxDB (disputed: ClickHouse maintainer showed indexed ClickHouse beats QuestDB ~3x less disk in rebuttal — treat ingestion claims as directionally true, competitor query benchmarks as vendor-dependent) | Native Parquet export/tiering | `ASOF JOIN`/`SAMPLE BY`/`LATEST ON` map directly to order-flow patterns | Low (single binary, Postgres-wire compatible, first-class cryptofeed backend) | Purpose-built for tick/trades/orderbook/OHLC; strongest fit for raw ingest if no heavy relational joins needed |
| **ClickHouse** | Very high w/ proper indexing | Excellent (best-in-class in cited rebuttal, ~3x smaller than QuestDB) | Powerful SQL/OLAP, less native TS ergonomics | Medium (cluster-oriented, heavier for single-node) | Best raw perf/compression ceiling but over-engineered ops for single user unless scale grows |
| **DuckDB + Parquet** | N/A for streaming row inserts — buffer then periodic flush to time-partitioned Parquet | Excellent (Parquet columnar) | Excellent for replay/footprint batch queries, integrates w/ polars | Lowest (no daemon) | Best as replay/cold-storage/analytics tier, not live ingest target |
| **ArcticDB** (Man Group) | Strong bulk DataFrame writes | Good, Arrow/Parquet-adjacent | Very good for "load DataFrame per symbol/date-range" (backtesting pattern) | Low local/embedded, more setup for S3 | Worth prototyping for replay read path; less proven, smaller community than QuestDB/DuckDB/Timescale |
| **SQLite** | Adequate low-moderate rate via WAL, not for L2 firehose | Reasonable, no native columnar | Fine for OMS/state tables | Lowest (single file) | Recommended for OMS/state tables only, not tick/L2/footprint data |

### Recommendation: two-tier hybrid
1. **Hot/live**: QuestDB — ingest via cryptofeed QuestDB backend or ILP line-protocol; `SAMPLE BY`/`ASOF JOIN`/`LATEST ON` build bars/footprint/CVD/heatmap directly; Postgres-wire compatible; replay engine reads recent history here.
2. **Cold/archive**: Parquet + DuckDB — periodic (e.g. daily) roll-off from QuestDB for cheap long-term archival + batch analytics via DuckDB+polars; bounds live QuestDB dataset size.
3. **Relational/OMS**: Postgres (Timescale mode optionally) or SQLite for orders/executions/positions cache/rule-engine config/user-role records/audit journal. SQLite sufficient for single-user; reuse same Postgres instance (plain tables) if Timescale already running.
4. **Bars/candles**: materialize as QuestDB tables from `SAMPLE BY` for fast repeated loads, but raw tick/L2 remains source of truth for deterministic backfill of new bar types/footprint metrics.

### 6.1 Storage sizing (BTCUSDT+ETHUSDT, 200-depth, unverified planning estimate)
- L2 deltas: ~10 msg/s/symbol, ~20 levels/msg, ~20 bytes/level → **~6.9 GB/day raw**, **~0.7–1.4 GB/day compressed**.
- Trades: ~4 trades/s/symbol, ~80 bytes/trade → **~55 MB/day raw**, **~10–20 MB/day compressed**.
- Tickers/funding/OI: negligible.
- **Total (200-depth, 2 symbols)**: ~7 GB/day raw → **~1–1.5 GB/day compressed** ≈ **~30–45 GB/month, ~0.4–0.5 TB/year** compressed.
- **1000-depth instead**: ~2–3x multiplier → ~14–20 GB/day raw, ~2–4 GB/day compressed → ~60–120 GB/month, ~1–1.5 TB/year compressed.
- Not measured — instrument actual volume in week 1 and adjust retention/downsampling. Storage cost not expected to be binding constraint at 2–5 symbol scale.

## 7. Replay engine design
- Goals: tick-level replay from stored trades+L2 deltas, adjustable speed (as-fast-as-possible / 1x / Nx), deterministic bar/footprint rebuild.
1. **Single code path live/replay**: `ReplaySource` reads ordered events from QuestDB/Parquet, publishes onto same bus topics (`data.trade.{symbol}`, `data.book.delta.{symbol}`) as live cryptofeed path — downstream consumers agnostic to source.
2. **Deterministic ordering**: preserve exact stored order (sequence numbers/timestamps), not wall-clock re-sort; writer persists strictly monotonic sequence key per symbol.
3. **Speed control**: scheduler computes delay from previous event's stored timestamp × speed multiplier (0=as-fast-as-possible, 1.0=real-time, >1.0=accelerated) via `loop.call_later`/scaled `asyncio.sleep`.
4. **Deterministic bar rebuild**: aggregator is pure function of ordered event stream — rebuilding new bar type/footprint metric = re-running replay reader; justifies persisting raw ticks/L2, not just OHLC.
5. **Testing**: record short real WS sessions as fixtures, replay through same `ReplaySource` path in unit/integration tests asserting deterministic output (bar OHLCV, footprint totals, CVD).

## 8. Recommended architecture

### 8.1 Component diagram (textual)
Bybit Public WS → cryptofeed FeedHandler (book reconstruction) → internal MessageBus.
Bybit Private WS → Private WS client (pybit or custom asyncio) → MessageBus.
Bybit REST ↔ OMS Adapter (pybit) ↔ OMS.
Bus → BarEngine (time/tick/volume/range/delta) → Bus.
Bus → FootprintEngine (footprint/profile/CVD/imbalance/heatmap, numpy/polars, Rust ext if needed) → Bus.
Bus → OMS (state machine, orderLinkId idempotency, reconciliation, rule engine).
Bus → PaperEngine (paper trading matching engine).
ReplaySource → Bus (deterministic replay).
Bus → QuestDB (hot tier) -.roll off.-> Parquet+DuckDB (cold tier); both → ReplaySource.
OMS → Relational (Postgres/SQLite).
Bus → FanOut (FastAPI/Litestar WS, snapshot+delta, msgpack) → React UI.
UI → REST Control API (FastAPI, JWT) → OMS, Relational.

### 8.2 Data flow (7 steps)
1. Ingestion: cryptofeed maintains L2 book per symbol/depth, emits normalized events; private client streams order/exec/position/wallet onto same bus.
2. Aggregation: BarEngine + Footprint/CVD/Imbalance/Heatmap subscribe to raw trade/book-delta, publish derived bar-close/cell-update events, written to QuestDB hot tier.
3. OMS: subscribes to private topics, maintains state keyed by `orderLinkId`, issues REST/WS-trade commands, runs reconciliation on reconnect.
4. Rule engine/stops: evaluates rules against live bus events, issues OMS commands (cancel/replace/market-out) on trigger.
5. Paper trading: matching engine subscribes to same live book/trade events, simulates fills, shares OMS state-machine code (mirrors Nautilus Sandbox).
6. Persistence: raw events → QuestDB hot; scheduled job rolls old partitions → Parquet cold; OMS/account/config → relational tier.
7. Replay: ReplaySource reads QuestDB/Parquet history in deterministic order, republishes onto same bus topics at controllable speed.
8. Fan-out: WS Fan-out subscribes to bus topics needed per client, pushes snapshot+delta (msgpack for high-volume L2/DOM, JSON elsewhere); REST Control API handles auth/config/order-placement, delegates to OMS.

### 8.3 Why single-process/single-asyncio-loop
- Given scale (1 user + few managers, 2–handful symbols), avoids multi-process/Redis-bridging complexity. Single asyncio process (uvloop) holds bus, aggregation state, OMS state, fan-out connections in memory — simpler, no cross-process race conditions, sufficient at this scale. Mirrors NautilusTrader's own single-thread design note. CPU-bound hotspots (footprint/heatmap, matching engine) are candidates for process-pool/Rust offload *precisely because* rest of system stays single-process.

### 8.4 Message bus implementation options
| Option | Throughput/latency | Multi-process? | Ops burden | Fit |
|---|---|---|---|---|
| **In-process asyncio.Queue/pub-sub registry** | Fastest (nanosecond, no serialization) | No | Zero | **Recommended phase-1** — matches single-process design |
| **Redis Streams** | Good (single-digit ms, localhost) | Yes | Medium (Redis instance) | Adopt only if/when splitting ingestion/fan-out across processes; replay/consumer-group semantics also fit replay engine but not required (QuestDB/Parquet already serve that) |
| **Redis Pub/Sub** | Good, lower overhead than Streams (no log) | Yes | Medium | Simpler than Streams if bus durability never needed (real durability need already met by QuestDB); Streams still better default if Redis ever adopted |
| **ZeroMQ (pyzmq)** | Very high, lowest latency (no broker) | Yes, cross-machine, no daemon | Low-medium (must handle delivery/backpressure in app code) | Credible Redis alternative if cross-process messaging needed without new service; no benefit over in-process option at phase-1 scale; slow-SUB silently drops by default |

**Recommendation**: build bus as thin in-process asyncio abstraction now (typed pub/sub registry over `asyncio.Queue`, msgspec Struct messages), with publish/subscribe-by-topic interface designed so transport can be swapped later (Redis Streams recommended over Pub/Sub for durability, over ZeroMQ for simpler ops) — deferred, not-yet-needed option.

## 9. Cross-cutting concerns

### 9.1 Auth
- JWT session auth (FastAPI) against local user table (Postgres/SQLite); roles owner/admin (full) vs viewer/manager (restricted). `python-jose`/`PyJWT` + `passlib`/`argon2-cffi`.
- Self-hosted OIDC (Authelia/Keycloak) only if scope grows/external access needed — over-engineering now.
- WS auth via short-lived token at connect time (query param/first-message handshake), not cookies alone.

### 9.2 Configuration and secrets
- Separate API key/secret per environment (demo/live/testnet) and per account manager if multiple sub-accounts; `.env`/`pydantic-settings`/`python-dotenv`, restrictive FS perms; no dedicated secrets manager warranted at this scale.
- Config models environment enum explicitly with per-env base URLs baked into adapter layer.
- Concrete practices: env vars via untracked `docker-compose.override.yml`/`.env`, never committed; **isolate demo/live keys as distinct typed config sections** (type error if wrong env used, not runtime accident); key rotation quarterly + on suspected exposure (manual, one-file-edit+restart); `.env` `chmod 600` under WSL; vault (Hashicorp/AWS) not warranted at this scale.

### 9.3 Observability
- Structured logging (`structlog`/stdlib+JSON); correlate by symbol and `orderLinkId`.
- Metrics: WS uptime/reconnect counts, ingest rate, aggregation lag, OMS reconciliation events. Local Prometheus+Grafana (docker compose) or simpler local endpoint+log alerting.
- Alerting on disconnects (esp. private stream — risks missing fills/liquidations): webhook (Telegram/Discord/email) or desktop notification; full paging system unnecessary.

### 9.4 Deployment
- Now: docker compose (core service, QuestDB, Postgres if separate); React frontend on same box or own dev/build; systemd/WSL service mgmt supervises, restart on crash.
- Later: same compose stack portable to small Ubuntu VPS/mini-PC — argument for containerizing now.
- Dedicated server: firewall to expose frontend/API only via VPN/SSH tunnel, not open internet (not for public release; API keys have live trading permissions).

### 9.5 Testing
- Recorded WS fixtures: normal operation, snapshot resync, 24h forced disconnect/reconnect, order lifecycle events (new/partial-fill/full-fill/cancel/reject) — replayed through ingestion+aggregation+OMS in automated tests.
- Deterministic replay tests: byte-identical/numerically-identical output across runs; bar-type switch/footprint backfill produces expected recomputed values.
- OMS reconciliation tests: simulate disconnect-during-open-orders against fixture REST responses; assert correct state reconstruction + idempotent orderLinkId handling.
- Paper-trading matching engine tests: verify simulated fills vs recorded live book fixture match expected price/size/timing.
- **Load/soak testing methodology** (addresses top risk — pure-Python not sustaining tick rates):
  1. Synthetic multi-symbol load generator: replay fixtures at N× real-time (find throughput ceiling) and at sustained real-time for multi-hour soak (catch leaks/queue-depth creep/GC growth).
  2. Event-loop lag monitoring as core health metric: `loop.call_later` heartbeat delta expected-vs-actual fire time; or `aiomonitor`/`PYTHONASYNCIODEBUG=1`.
  3. Throughput/latency benchmark harness: measure per-event latency + sustained max ingest rate at increasing symbol counts (2/5/10/20) and depth tiers (50→200→500) until event-loop lag crosses threshold (e.g. 50–100ms) — produces concrete "N symbols at 200-depth = practical single-process ceiling" number.
  4. CI integration: short-duration harness per-commit; multi-hour soak as periodic (weekly/pre-release) job, not blocking every CI run.

## 10. Risks table
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pure-Python aggregation can't sustain tick/L2 rates at N symbols | Medium | High (stale charts, wrong metrics, missed triggers) | Profile early; Rust/PyO3 fallback ready for whichever hot loop bottlenecks |
| cryptofeed private-stream support less battle-tested than public | Medium | High (incorrect position/order state) | Use pybit for private streams/order entry; validate cryptofeed public data against raw payloads |
| pybit thread-based WS bridging bugs (races, dropped msgs under load) | Medium | Medium-High | Prototype bridge w/ synthetic high-rate generator; consider custom minimal asyncio private-WS client instead |
| QuestDB benchmark claims partly disputed | Medium | Low-Medium | Prototype actual footprint/replay queries on realistic dataset; keep Parquet/DuckDB as escape hatch |
| Bybit v5 API changes break adapters (frequent changes through Aug 2026) | Medium-High | Medium | Pin to official pybit for private/exec path; monitor changelog; integration test vs demo before live changes |
| Free-threaded Python 3.13+ immaturity mistakenly relied on | Low (if §4.2 followed) | Medium if mis-planned | Treat as not-yet-dependable; design hot paths extractable to process/Rust regardless |
| Single-process core becomes scaling bottleneck if symbol/manager count grows | Low at stated scope | Medium if scope grows | Keep logic behind bus abstraction so process split (Redis/NATS) is moderate rework, not rewrite |
| Storage sizing estimates unverified (could be off 2-3x) | Medium | Low (storage cheap) | Instrument actual volume week 1, adjust retention/downsampling |
| Demo trading limited endpoints/no WS-trade could cause demo-vs-live behavioral divergence | Medium | Medium | Explicitly test both WS-trade (live only) and REST order paths (both demo/live) in OMS suite |
| REST rate-limit / 10-topic WS subscribe limit exceeded under load | Low-Medium now, rising with symbol growth | Medium-High (rejected stop/exit = direct trading risk) | Respect `X-Bapi-Limit-Status` headers + local token bucket; chunk WS subs ≤10 topics from day one |
| OMS misbehaves if pointed at Classic account or position-mode mismatch | Low (if UTA-only followed) | Medium (rejected orders / unintended behavior) | Target UTA only; cache position/margin mode at startup; mismatch = hard startup error |
| Local clock drift beyond recv_window causes intermittent signed-request rejection | Low if NTP running, Medium if not | High (rejected stop/exit at wrong moment = capital risk) | NTP baseline requirement + server-time-offset fallback; surface error 10002 distinctly |

## Open questions (verbatim intent, condensed)
1. **Private-stream client choice**: pybit (official, thread+bridge) vs custom asyncio client — prototype both against demo account; highest-leverage OMS-correctness decision.
2. **cryptofeed private-stream reliability**: no strong evidence of production-hardness vs pybit for order/execution/position parity — validate side-by-side before deciding if cryptofeed could handle both public+private (simplify to "one library").
3. **QuestDB vs TimescaleDB for hot tier**: given disputed benchmark, worth prototyping both against CandleViewer's actual footprint/replay query shapes (not synthetic IoT benchmarks) before committing; TimescaleDB's unified-Postgres advantage may outweigh QuestDB's raw ingest edge at this modest scale.
4. **Exact Bybit message rates for BTCUSDT/ETHUSDT at 200-/1000-depth**: no public stats found; §6.1 figures are first-principles estimates, need real instrumentation once running.
5. **Rust/PyO3 extension timing**: deferring until profiling shows bottleneck (§4.4) vs building book-reconstruction/aggregation core in Rust from day one (given Nautilus's own trajectory) — open sequencing question.
6. **Free-threaded Python 3.13/3.14 maturity**: current post-research-date status of free-threaded wheel availability for numpy/polars/uvloop — re-check periodically, affects viability of no-GIL as alternative to process/Rust offload.
7. **Multi-exchange abstraction boundary**: Bybit-specific event schema now (faster to ship) + normalize later when 2nd exchange added, vs cryptofeed-style normalized schema from day one — document leans latter but trade-off not deeply quantified.
8. **Demo-trading fidelity for rule-engine testing**: given demo lacks WS trade-order support + reduced endpoints, how much of rule-engine logic can be validated end-to-end in demo vs requiring careful live-mode testing — needs dedicated test-plan pass before trusting real capital.

## Key numeric limits (consolidated)
- Max 10 topics/subscribe request.
- ≤500 new WS connections/5min/IP; ≤1000 concurrent/IP for market data (per category).
- REST order endpoints: ~10 req/s default non-VIP UTA (scales w/ VIP tier).
- WS ping interval: ~20s.
- `recv_window` default: 5000ms (error 10002 on violation); window = `server_time - recv_window <= ts < server_time+1000`.
- Demo order retention: 7 days.
- Orderbook depth/frequency: Linear 1(10ms)/50(20ms)/200(100ms)/500(100ms); Spot 1(10ms)/50(20ms)/200(200ms); Option 25(20ms)/100(100ms).
- Storage: ~7 GB/day raw, ~1–1.5 GB/day compressed (200-depth, 2 symbols) → ~30–45 GB/month, ~0.4–0.5 TB/year; 1000-depth ~2-3x → ~1–1.5 TB/year.
- Event-loop lag acceptable threshold for load testing: ~50–100ms.
