# E12 bar builders & series — black-box test plan

Ticket: E12-Q01 (issue #393). Owner: QA. Status: **Authored — peer review and staging dry run pending (§10).**
Style references: `qa/plans/e08-market-data-test-plan.md`, `docs/qa/e35-rule-engine-test-plan.md`.

Written against the observable surface only: `GET /market/klines`, `GET /market/bars`
(`docs/plan/22-api-openapi.yaml`), WS topic `bars.{symbol}.{bar_type}.{param}` / `BarsBatch`
(`docs/plan/23-ws-protocol.md` §14.3), screens `SCR-041/042/044/045/047/048`, components `CMP-029/180/181/199/
220/222`, and the metrics in §0. No step names an internal class or module. Stories are from
`docs/plan/11-user-stories.md`; bar invariants BI-1..BI-5 from `docs/plan/24-internal-schemas.md` §3.4.

## 0. How to use this plan

- **Fixtures, not live Bybit.** Every case names a fixture from the appendix (§8). No case calls an exchange.
- **Case id:** `E12-TC-<group><nn>`; groups A–F = §1–§6 (one per story group), X = §7 cross-bar invariants.
- **Case columns:** Case · Preconditions/fixture · Steps · Expected · Verifies (`US-*` + child ticket) ·
  Automation (`Q02` golden-fixture suite, `Q03` Playwright, `Q04` contract, or `manual-only`).
- **Build status tag** (state of the code at authoring, from the closed tickets' QA verdicts):
  `shipped` = merged and QA-passed; `in-review` = PR open; `pending` = child ticket not yet merged — the case
  is written now and becomes executable when the child lands. A `pending` case is never counted as passing.
- **Oracles:** expected bar boundaries and values are derived from the fixture tape by an **independent**
  calculation (notebook `qa/plans/e12-oracles/bars_oracle.ipynb`, owner E12-Q02; not yet committed), never copied
  from the implementation's output. Until it exists, a case with a numeric expectation uses the hand-built
  tape given in its steps.
- **Timing:** qualitative only ("interactive before all history arrives"). Budgets (frame time, ≤300 ms cached
  first paint, ≤10 s rebuild of 1 M prints) belong to `E12-Q05`.
- **Each group runs in <40 min** by one SDET.
- **A11y:** keyboard/screen-reader cases are owned by `E12-Q07` (keyboard interval switching, `SCR-045`
  data-table alternative, live-region bar-close announcement). Each group below links to it; not re-tested here.
- **Adversarial input** (injection into `param`, huge `limit`) is owned by `E12-X02`; only the honest-error
  happy-edge is covered here.
- **Metrics to read on failure** (`GET /metrics`): `bars_build_duration_seconds`, `bars_rebuild_total{bar_type}`,
  `backfill_pages_fetched_total`, `ws_topic_gap_total{topic="bars"}`, `bars_late_trade_dropped_total`;
  log field `build_version` (also returned on every response with `spec_hash`).
- **No secrets:** fixtures are public market data; confirm none embeds a key or account id before use.
- **Run log:** record build sha, fixture set and pass/fail per case for `E12-Q08`.

## 0.1 Defect conventions for this epic

Severity follows `docs/plan/03-testing-strategy.md` §11.3 (taxonomy P0–P3 → labels `priority/p0-critical` …),
with the epic override for risk **R7 Data accuracy**: downstream order-flow epics treat bars as evidence.

| Observation | Severity / label |
|---|---|
| **Any bar-value discrepancy against the tape** (OHLC, volume, delta, trade_count, boundary, split, brick) | `priority/p0-critical`, **by definition**, regardless of how rare |
| Σ-volume ≠ Σ trade sizes (BI-1), non-identical rebuild (BI-4), restore divergence (BI-5) | `priority/p0-critical` |
| Unconfirmed bar presented as closed, or two `confirm:false` bars in one series | `priority/p0-critical` |
| Honest degradation (partial-history marker, `null` delta, `stale`) that clears correctly | at most `priority/p2` |
| Wrong/missing marker where data *is* correct (e.g. marker at wrong timestamp) | `priority/p1` |
| Cosmetic legend/label defect, no data impact | `priority/p3` |

Every defect records: case id, build sha, fixture, **observed vs expected bar boundary or value** (first
differing bar index, field, both values), request URL, `build_version`, `spec_hash`. The failing fixture
tape slice is attached; if the oracle is in doubt, the oracle is re-derived first, but the defect stays open.
Known, already-ticketed gaps are linked in the case instead of re-filed (see C-section notes).

---

## 1. Group A — Candlestick rendering & historical load (US-CHART-001, US-MKT-008; E12-S01, E12-S05, E12-S06)

Screens `SCR-047`, `SCR-048`; components `CMP-180`, `CMP-181`; endpoint `GET /market/klines`.
Metrics: `backfill_pages_fetched_total`. A11y pointer: `E12-Q07`.

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-A01 | `btcusdt-2026-09-01`; BTCUSDT `1m` | `GET /market/klines?symbol=BTCUSDT&interval=1m&from=…&to=…` for one hour | 200; `bars` ascending by `t`; 60 rows; each `o,h,l,c,v` equals the oracle fold of the tape for that minute; `meta.sources` names the tier(s) touched | US-CHART-001 · E12-T05 | Q04 + Q02 · shipped |
| E12-TC-A02 | Same | Trade at 10:00:59.900 and one at 10:01:00.100 (hand tape `edge-ticks` §8) | First trade in the 10:00 bar, second opens 10:01; 10:00 bar closes exactly once; no re-close on later clock ticks | US-CHART-001 · E12-S01 | Q02 · shipped |
| E12-TC-A03 | `ethusdt-2026-09-03-thin` (empty 1 m intervals) | Request `1m` across a quiet stretch | No phantom zero-volume bars; the next bar after the stretch carries `gap_before=true`; chart draws a gap, not a flat line of fake bars | US-CHART-001 · E12-S01 | Q02 + Q03 · shipped (render: pending S06) |
| E12-TC-A04 | `btcusdt-2026-09-01`; WS `bars.BTCUSDT.time.1m` | Subscribe; let one trade arrive in the forming bar | Forming bar updates in place (same `t`, `confirm:false`); no full redraw of closed bars (draw-call count unchanged in the engine stats overlay) | US-CHART-001 · E12-T06, E12-S06 | Q03 · pending (T06, S06) |
| E12-TC-A05 | A trade older than the last closed bar's window, inside the late window | Replay a late trade | Closed bar returned with `amended=true`; later bars untouched; a trade beyond the late window changes nothing and increments `bars_late_trade_dropped_total{reason="late_window"}` | US-CHART-001 · E12-S01 | Q02 · shipped |
| E12-TC-A06 | Symbol with no bars in range (`newlist-2026-09-04`, window before listing) | Open the chart at that window | Explicit empty state naming the first available timestamp — not an empty grid | US-CHART-001 · E12-S06 | Q03 · pending (S06) |
| E12-TC-A07 | Local store holds 450 BTCUSDT 1 m klines (`rest/kline_BTCUSDT_1_page{0,1,2}.json`) | Open BTCUSDT 5m with days-to-load covering them | Backfill pages ≤1 000 rows each; progress shown; `backfill_pages_fetched_total` increments per page; chart interactive before the last page; second open loads from the store and fetches only the tail | US-MKT-008 · E12-S05 | Q02 + Q03 · shipped (UI: pending) |
| E12-TC-A08 | Fixture `rest/error_10018.json` (rate limit) injected on page 2 | Open the chart | Backoff with jitter; page 0–1 bars stay usable; "loading older bars…" visible and non-blocking; no blocking dialog; recovers when the stub stops failing | US-MKT-008 · E12-S05 | Q02 · shipped (UI: pending) |

**A-notes.** `include_delta=true` on klines with no recorded tape returns `delta`/`min_delta`/`max_delta`/`cvd`
present and `null` (not `0`) with `meta.recording_started_at` set (case F03). Where the tape and klines overlap,
tape wins (`meta.sources` lists `tape`; case A01 with a recorded hour).

## 2. Group B — Alternative series types (US-CHART-002; E12-S07, E12-S08)

Components `CMP-222 ChartTypeToggle`, `CMP-199 ChartLegend`, volume sub-pane. Both child tickets are not yet
merged, so every case is `pending`. A11y pointer: `E12-Q07` (type selector accessible names).

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-B01 | `btcusdt-2026-09-01`, 1m candles shown | Switch candles → Heikin-Ashi via `CMP-222` | No `/market/bars` or `/market/klines` request is issued (network log); HA values match the oracle transform of the same bars; a drawing anchored at a real time/price keeps its time/price | US-CHART-002 · E12-S07 | Q03 · pending |
| E12-TC-B02 | Same | Cycle OHLC, line, area, baseline, hollow candle | Each type renders from the same data; legend `CMP-199` shows the real (non-HA) O/H/L/C for the hovered bar; each type has an accessible name | US-CHART-002 · E12-S07 | Q03 · pending |
| E12-TC-B03 | Same | Enable volume column pane | Linked sub-pane shares time axis and crosshair: hover bar *n* in either pane highlights bar *n* in both; pane volume equals the bar `v` | US-CHART-002 · E12-S08 | Q03 · pending |
| E12-TC-B04 | `btcusdt-2026-09-01`, footprint view | Request Heikin-Ashi together with footprint cells | Message that footprint requires a real-price bar type; offer to switch back; nothing silently drawn | US-CHART-002 · E12-S07 | Q03 · pending |
| E12-TC-B05 | Keyboard only | Reach `CMP-222`, change type, enable volume pane | Same results as pointer path (detail in `E12-Q07`) | US-CHART-002 · E12-S07 | Q03 · pending |

## 3. Group C — Activity-based bars (US-CHART-003; E12-S02, E12-T03)

Screen `SCR-042`; `GET /market/bars?bar_type=tick|volume`; tables `bars_tick`, `bars_volume`.
Metrics: `bars_build_duration_seconds`, `bars_rebuild_total{bar_type}`. Param floors: tick 100..1 000 000;
volume ≥10 quantity steps.

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-C01 | `btcusdt-2026-09-01` | `GET /market/bars?symbol=BTCUSDT&bar_type=tick&param=500` | Every closed bar has `trade_count == 500` (prints, not volume); first bar of the window may be partial and flagged; ascending; each bar carries `close_t_ms` | US-CHART-003 · E12-S02 | Q02 + Q04 · shipped |
| E12-TC-C02 | Same | `bar_type=volume&param=1500` | Every closed bar `v == 1500` exactly (Decimal equality); open bar `v < 1500` | US-CHART-003 · E12-S02 | Q02 · shipped |
| E12-TC-C03 | `edge-ticks`: volume threshold 1500, open bar at 1400, then a 300 print | Build volume bars | Bar closes at exactly 1500; remainder 200 opens the next bar at the same price/timestamp; both emissions carry the originating trade id; remainder delta reflects only its share | US-CHART-003 · E12-S02 | Q02 · shipped |
| E12-TC-C04 | `edge-ticks`: threshold 1500, single 5000 print | Build volume bars | **Exact-threshold overshoot:** 3 closed bars of exactly 1500 (identical OHLC) plus an open bar of 500; Σv == 5000. A builder that does not split fails here; record observed vs expected boundary; P0 per §0.1. Known: split bars share `open_time` (#2014, p1 — link, do not re-file) | US-CHART-003 · E12-S02 | Q02 · shipped |
| E12-TC-C05 | `edge-ticks`: tick 500 over 1 200 trades | Feed in chunks of 1, 7, 50, 1200 | Identical closed bars regardless of chunking | US-CHART-003 · E12-S02 | Q02 · shipped |
| E12-TC-C06 | Block trade in `edge-ticks` | Build tick and volume bars | Block trade counts as one tick and its full volume counts (BI-1). `exclude_block_trades=true` is **deferred** (ADR-0033, #1968) — not testable | US-CHART-003 · E12-S02 | Q02 · shipped |
| E12-TC-C07 | Builder state exists for a series | Restart the staging API mid-bar; compare with an uninterrupted run of the same fixture | Final series identical, including a cut taken mid-split (BI-5) | US-CHART-003 · E12-T03 | Q02 · shipped |
| E12-TC-C08 | Staging with spec caps in force | Open specs beyond 8 per user / 32 per symbol / 512 process-wide | Refusal `spec_cap_exceeded` naming the cap; no other user's spec hash in the message; existing series keep updating | US-CHART-003 · E12-T03 | Q02 · shipped |
| E12-TC-C09 | Series consumer releases its last lease | Wait past the grace period; separately re-open within it | Beyond grace: builder torn down, final state persisted. Within grace: state kept | US-CHART-003 · E12-T03 | Q02 · shipped |
| E12-TC-C10 | Corrupt state blob (truncated, wrong version, wrong `spec_hash`, >8 MiB) | Start the series | No crash; series rebuilds from the tape; discard counted | US-CHART-003 · E12-T03 | Q02 · shipped |
| E12-TC-C11 | `btcusdt-2026-09-01` (1.2 M prints) | Rebuild volume bars over the day | Completes; equals a second rebuild (X01). Time budget is owned by `E12-Q05` | US-CHART-003 · E12-S02 | manual-only (budget → Q05) |


## 4. Group D — Range, delta and renko bars (US-CHART-004; E12-S03, E12-S04, E12-T04, E12-T05)

`GET /market/bars?bar_type=range|delta|renko`; tables `bars_range`, `bars_delta`, `bars_renko`
(`open_source_ts` on range/renko); rebuild progress. Range/renko `param` is in **ticks** (2..100 000), so the
instrument tick size must be known; an unknown tick size is a hard error naming the symbol.

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-D01 | `edge-ticks`: range 20 ticks, tick 0.10; prices 100.0, 101.5, 102.0 | Build range bars | Closes when span reaches 2.0 **inclusive**; span 1.9 does not close; next bar opens at the previous close, `gap_before=false` | US-CHART-004 · E12-S03 | Q02 · shipped |
| E12-TC-D02 | `edge-ticks`: open bar low 100.0, trade at 110.0, then 110.1 (qty 3/7/2) | Build range bars | Exactly one close; **no phantom bars**; new bar has `gap_before=true`; Σv = 12 = traded 12; no zero-volume bar | US-CHART-004 · E12-S03 | Q02 · shipped |
| E12-TC-D03 | `edge-ticks`: delta threshold 2000; buy 2000 then sell 100 | Build delta bars | Bar closes at delta 2000; the sell opens the next bar (closure is final) | US-CHART-004 · E12-S03 | Q02 · shipped |
| E12-TC-D04 | `edge-ticks`: delta 2000; one print taking delta to 2400 | Build delta bars | Closes at delta 2400; the print is **not split** (no `split_from_trade_id`) | US-CHART-004 · E12-S03 | Q02 · shipped |
| E12-TC-D05 | Symbol absent from the instrument cache (`ZZZUSDT`) | Request range bars | Hard failure naming the symbol; no builder created | US-CHART-004 · E12-S03 | Q02 + Q04 · shipped |
| E12-TC-D06 | `btcusdt-2026-09-01`; `range&param=20`, `delta&param=1200` | Request both | 200, ascending, `meta.sources=["tape"]`; each closed range bar span ≥ 20 ticks; delta bars satisfy BI-2, BI-3 | US-CHART-004 · E12-T05 | Q04 · shipped |
| E12-TC-D07 | `edge-ticks`: renko 20 ticks | Build bricks | Brick closes at exactly one brick size; reversal needs the reversal-cost move; each brick sets `open_source_ts` | US-CHART-004 · E12-S04 | Q02 · in-review (#2125) |
| E12-TC-D08 | `edge-ticks`: one print spanning several bricks | Build bricks | Volume allocated **once** (Σ brick volume == print qty); >1 000 bricks from one print is rejected and counted (SR-E12-15). Open review finding on #2125: allocated volume not yet persisted/on the wire — case stays `in-review` until fixed | US-CHART-004 · E12-S04 | Q02 · in-review (#2125) |
| E12-TC-D09 | `btcusdt-2026-09-01`, range 20 on chart | Change range to 40 on `SCR-042` | Rebuild from stored prints with progress indicator; cancel restores the previous series; drawings re-anchor by timestamp; param persists in the template | US-CHART-004 · E12-S12 | Q03 · pending |
| E12-TC-D10 | `btcusdt-2026-09-01` | Non-time request over the window cap (>31 d) | 422 `bar_window_too_large` (if the window also predates recording, `no_data_recorded` wins) | US-CHART-004 · E12-T05 | Q04 · shipped |
| E12-TC-D11 | `btcusdt-2026-09-01` | Page via `meta.next_cursor`; then tamper the cursor | Pages concatenate with no duplicate/missing bar; tampered cursor → `invalid_cursor`, client restarts | US-CHART-004 · E12-T05 | Q04 · shipped |
| E12-TC-D12 | Params out of range (`tick=50`, `range=1`) | Request | 400 `validation_failed` naming the param; no data | US-CHART-004 · E12-T05 | Q04 · shipped |
| E12-TC-D13 | Golden corpus `packages/fixtures/golden/bars/*` | Run the determinism harness (BI-1..BI-5, BI-6 per §3.4 when merged) | Property suite green over ≥1 M synthetic trades | US-CHART-004 · E12-T04 | Q02 · pending (T04) |

Chart-side rebuild progress/cancel (D09) depends on E12-S12; the REST contract (D06, D10–D12) is already shipped.

## 5. Group E — Symbol & timeframe switching (US-CHART-005; E12-S11, E12-S05)

Screen `SCR-041`; `CMP-220 IntervalPicker`; `CMP-029 Skeleton-Chart`. Keyboard hotkeys: `E12-Q07`.

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-E01 | `btcusdt-2026-09-01`, 1m chart, bars cached | Press the 5m hotkey | Chart switches reusing cached bars; the centre timestamp of the visible window is unchanged (±1 bar); no flash of empty chart (`CMP-029` only while data is absent) | US-CHART-005 · E12-S11 | Q03 · pending |
| E12-TC-E02 | Recording starts 11:17Z (`newlist-2026-09-04`) | Select 5 s | Bars are built from recorded prints; partial-history marker at 11:17Z where recording is shallower than the view | US-CHART-005 · E12-S11, E12-T05 | Q03 + Q04 · pending (UI) |
| E12-TC-E03 | 1m data stored | Enter custom `7m` | Bars aggregated from 1m: each 7m bar's OHLCV equals the fold of its seven 1m bars; `7m` added to the recent list | US-CHART-005 · E12-S11 | Q02 + Q03 · pending |
| E12-TC-E04 | Two symbols (BTCUSDT, ETHUSDT thin) | Switch symbol, then back | Engine is not torn down (same canvas, no reload); data of the previous symbol is never shown under the new symbol's title; no leaked subscriptions (WS topic list shows only the active topic) | US-CHART-005 · E12-S11 | Q03 · pending |
| E12-TC-E05 | Switch during an in-flight backfill | Switch interval mid-load | Old request cancelled; result of the old interval never painted | US-CHART-005 · E12-S11, E12-S05 | Q03 · pending |
| E12-TC-E06 | Switch to a bar type via `CMP-220` (tick 500) | Select | `SCR-042` shows tick series; interval list reflects the active bar mode | US-CHART-005 · E12-S12 | Q03 · pending |
| E12-TC-E07 | `btcusdt-2026-09-01`, 1m chart, 5 000 bars loaded | Pan by dragging horizontally; then by keyboard (arrow keys; `Home` resets) | View pans along the time axis with no refetch for already-loaded bars; inertia is off under `prefers-reduced-motion`; keyboard path reaches the same positions as drag | US-CHART-006 · E12-S09 | pending → E12-Q03 (#419) |
| E12-TC-E08 | Same | Scroll-wheel zoom with the pointer over a known bar; repeat with `+`/`-` | The bar under the cursor stays under the cursor (anchor) within 1 px; the visible range changes monotonically; no blank frame | US-CHART-006 · E12-S09 | pending → E12-Q03 (#419) |
| E12-TC-E09 | Same, autoscale on | Pan until a different price range is visible; drag the price axis; double-click the axis | Autoscale fits the visible highs/lows; dragging the axis disengages it and shows a lock badge; double-click restores auto-fit | US-CHART-006 · E12-S09 | pending → E12-Q03 (#419) |

E07–E09 close the US-CHART-006 gap recorded on #419 (comment 6085451276); frame-rate budgets are `E12-Q05`.

## 6. Group F — Days-to-load & history honesty (US-CHART-010; E12-S06, E12-T06)

`meta.recording_started_at`, partial-history marker, `SCR-047`, `SCR-044`. This plan tests the *honesty* of the
marker, not recorder retention (E16).

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-F01 | `btcusdt-2026-09-01`, 1m chart | Set days-to-load = 30 | Only that window is requested (network log `from`); the estimated memory footprint is displayed (±20 % of measured) | US-CHART-010 · E12-S06 | Q03 · pending |
| E12-TC-F02 | `newlist-2026-09-04` | `GET /market/bars?symbol=…&bar_type=tick&param=500&from=2026-09-04T00:00:00Z` | **422 `no_data_recorded`**, no `bars` key, no storage read, REST klines **not** substituted. Chart shows the partial-history marker at 11:17Z, not an empty grid | US-CHART-010, US-CHART-003 · E12-T05, E12-S06 | Q04 + Q03 · API shipped / UI pending |
| E12-TC-F03 | Recording starts after the klines corpus; `include_delta=true` | `GET /market/klines` | 200; `delta`/`min_delta`/`max_delta`/`cvd` present and `null` (not `0`); `meta.recording_started_at` set | US-CHART-010, US-MKT-008 · E12-T05 | Q04 · shipped |
| E12-TC-F04 | Request would exceed the client memory budget | Set 365 d on 1 s | Warning with the estimate; load only after explicit confirm; declining loads nothing | US-CHART-010 · E12-S06 | Q03 · pending |
| E12-TC-F05 | Settings screen | Inspect per-view defaults | Chart, footprint, profile and replay each have their own default lookback | US-CHART-010 · E12-S06 | Q03 · pending |
| E12-TC-F06 | `btcusdt-2026-09-02-gap` (deliberate WS gap) | Request time bars across the gap; watch the WS topic | Bars across the gap are rebuilt from REST/tape consistently; `ws_topic_gap_total{topic="bars"}` increments and the client resyncs from a snapshot; no duplicated or missing bar after resync | US-CHART-010 · E12-T06 | Q04 + Q03 · pending (T06) |
| E12-TC-F07 | `btcusdt-2026-09-01`, time `1m` | `GET /market/klines` over a window wider than `limit × interval` (e.g. `limit=200`, 2 days) | **200, not 422:** the first page holds the oldest `limit` bars of the window, oldest→newest, with `meta.has_more=true` and `meta.next_cursor`; following the cursor until `has_more=false` yields every bar once. 422 `bar_window_too_large` applies only at the hard caps: time windows over 400 d, non-time windows over 31 d (D10) | US-CHART-010 · E12-T05 | Q04 · shipped |

## 7. Group X — Cross-bar-type invariants (no single child ticket owns these)

Run each case for **all six bar types** (time 1m, tick 500, volume 1500, range 20, delta 1200, renko 20) over
`btcusdt-2026-09-01` unless stated. Any failure is `priority/p0-critical` (§0.1). Metric `bars_rebuild_total`
must increase per rebuild so a no-op "rebuild" cannot pass.

| Case | Preconditions / fixture | Steps | Expected | Verifies | Automation |
|---|---|---|---|---|---|
| E12-TC-X01 | Fixture tape loaded | Rebuild the series twice from the same tape; fetch all bars each time; compare raw response bodies minus `meta.generated_at`/transient fields | **Byte-identical** bars including `spec_hash` (BI-4); also identical across a restore-from-snapshot run (BI-5) | US-CHART-003, 004 · E12-T03, E12-T04 | Q02 · shipped (renko in-review) |
| E12-TC-X02 | Same; independent sum of trade sizes from the fixture tape for the window (oracle) | Σ `v` over all bars of the family (open bar included) | Σv == Σ trade sizes (BI-1), Decimal equality, for every family, including after volume/renko splitting | US-CHART-003, 004 · E12-S02..S04 | Q02 + Q04 · shipped (renko in-review) |
| E12-TC-X03 | Include the open bar (`include_open=true`; WS `BarsBatch`) | Count bars with `confirm:false` per series | **Exactly one** `confirm:false` bar per series, and it is the last; none when the window ends on a closed bar and `include_open=false`; an unconfirmed bar is never styled as closed | US-CHART-001, 003 · E12-T05, E12-T06 | Q04 · shipped (WS pending T06) |
| E12-TC-X04 | Non-time families | Inspect every returned bar of tick/volume/range/delta/renko | Each carries `close_t_ms` (closed bars: last trade time; open bar per contract); time bars are defined by interval | US-CHART-003, 004 · E12-T05 | Q04 · shipped |
| E12-TC-X05 | Same | Check BI-2 (`delta == buy_volume − sell_volume`) and BI-3 (`min_delta ≤ delta ≤ max_delta`) on every bar | Hold for all bars of all families | US-CHART-003, 004 · E12-T04 | Q02 · shipped |
| E12-TC-X06 | Any response | Inspect `meta` | `build_version` and `spec_hash` present; `meta.sources` lists only tiers actually read; tape wins over klines on overlap | US-MKT-008, US-CHART-001 · E12-T05 | Q04 · shipped |
| E12-TC-X07 | Caller holding `orders:read` only (no `marketdata:read`) | `GET /market/bars` and `GET /market/klines` | **403**; response body contains no bars and no market data | US-CHART-001, 003 · E12-T05 | Q04 · shipped |
| E12-TC-X08 | No principal (no/invalid session) | Same two requests | **401**; no market data disclosed. (A bars router with no resolver wired fails closed with 501 — verified on #398, not a staging case) | US-CHART-001, 003 · E12-T05 | Q04 · shipped |

## 8. Fixture & test-data appendix

### 8.1 Recorded fixtures that exist today (verified in the repository at authoring)

| Path | Contents | Used by |
|---|---|---|
| `packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json` | 450 BTCUSDT 1 m kline rows, limit 200 | A07, A08, F03 |
| `…/rest/error_10018.json`, `error_10002.json`, `error_503.json` | Rate-limit, clock-drift, 5xx bodies | A08 |
| `…/rest/recent_trade_BTCUSDT.json` | Tape oracle (REST recent-trade) | X02 |
| `…/ws/clean_publicTrade_{BTCUSDT,ETHUSDT,SOLUSDT}.jsonl` | Clean 3 h trade windows | A01, C01, D06, X01–X05 |
| `…/ws/reconnect_publicTrade_ETHUSDT.jsonl`, `publicTrade_BTCUSDT.jsonl` | Reconnect with REST backfill overlap | F06 (interim) |
| `…/ws/gap_orderbook_ETHUSDT.jsonl`, `orderbook_BTCUSDT.jsonl` | Book sequence gap (not a trade gap) | reference only |
| `…/rest/instruments_{before,after}.json` | Tick-size change, delisting | D05 |
| `packages/fixtures/golden/bars/{time,activity,threshold}_bars_BTCUSDT.jsonl`, `bar-model.schema.json`, `spec_hash_vectors.json` | Golden bar outputs from the recorded tape | A02, C01–C05, D01–D04, X01 |
| `packages/fixtures/golden/storage/bars_range.golden.json` | `bars_range` row layout | D06 |
| `services/api/tests/fixtures/ingestion/` | Ingestion fixtures (no `bybit/` directory exists under `services/api/tests/fixtures`) | reference |

The corpus is **built from documented shapes**, not live-captured (`packages/fixtures/bybit/README.md`); real
recorder captures replace it once E16 lands. Hence the 1.2 M-print day does not exist yet.

### 8.2 Named symbol-days from the ticket — status

| Name | Purpose | Status | Interim stand-in |
|---|---|---|---|
| `btcusdt-2026-09-01` | Dense day, 1.2 M prints | **to be recorded — owner: E12-Q02** | `clean_publicTrade_BTCUSDT.jsonl` (3 h) |
| `btcusdt-2026-09-02-gap` | Deliberate WS sequence gap | **to be recorded — owner: E12-Q02** | none (F06 blocked) |
| `ethusdt-2026-09-03-thin` | Thin tape, many empty 1 m intervals | **to be recorded — owner: E12-Q02** | `clean_publicTrade_ETHUSDT.jsonl` |
| `newlist-2026-09-04` | Listed mid-day, recording starts 11:17Z | **to be recorded — owner: E12-Q02** | none (C/E/F cases blocked) |
| `edge-ticks` | Synthetic: exact-threshold volume, exact-range, exact-brick crossings | **to be recorded — owner: E12-Q02** (synthetic generator, seeded) | hand tapes quoted in each case |

**E12-Q02 bank** (`packages/fixtures/golden/bars/conformance/`, `MANIFEST.toml`): five *synthetic* tapes (seeded
generator, exception #1778 A; dense is capped at 200k prints, not 1.2 M) plus a golden per (tape, pair) for the
matrix through the live `BarBuilderSet`. The "gap" tape is a *hole plus late backfill* (150 prints missing, 80 re-delivered ~650 s late, dropped as `late_window` per §3.3c); it is not a sequence-gap detector test (that is F06/E08). `renko:atr:14` (ADR-0033) and `heikin_ashi:5` (not a builder) are recorded
as rejected pairs. **Golden update workflow:** `make golden-update` (dry run + diff summary);
`make golden-update WRITE=1 CV_GOLDEN_REASON="why"` writes; refused under CI, without a reason, or without a `BUILD_VERSIONS`
bump for a changed kind. Review the `git diff --stat` in the PR.

No payloads are invented here. Expected values come from the independent oracle (§0), committed by E12-Q02.
Each fixture needs a README line (source, date, symbol, env, redaction) per C-13.5.

## 9. Traceability (US × cases × automation)

Conventions of `docs/plan/18-traceability-matrix.md` (story id, then coverage). Status is written as text, not
colour. "Pending" = child ticket unmerged. No story has an empty row.

| Story | Cases | Automated in Q02/Q03/Q04 | Manual-only |
|---|---|---|---|
| US-CHART-001 | A01–A06, X03, X06–X08 | A01–A06, X03, X06–X08 | — |
| US-CHART-002 | B01–B05 | B01–B05 (Q03, pending) | — |
| US-CHART-003 | C01–C11, E06, F02, X01–X05, X07, X08 | all except C11 | C11 (budget → Q05) |
| US-CHART-004 | D01–D13, X01, X02, X04, X05 | all | — |
| US-CHART-005 | E01–E06 | E01–E06 (Q03, pending) | — |
| US-CHART-006 | E07–E09 | E07–E09 (Q03 #419, pending) | — |
| US-CHART-010 | F01–F07 | F01–F07 | — |
| US-MKT-008 | A07, A08, F03, X06–X08 | A07, A08, F03, X06–X08 | — |

Pan/zoom/autoscale (US-CHART-006) is engine-owned; cases E07–E09 cover it and were requested on #419.

Case counts: A 8, B 5, C 11, D 13, E 9, F 7, X 8 = **61**.

## 10. Review, dry run and cross-links

- **Peer review checklist:** every correctness case has an oracle; every case names a fixture; no step names an
  internal class or module; case ids spelled per `18-traceability-matrix.md`. Reviewers: second SDET + E12 tech
  lead (owner approval substitutes per the agent-delivery adaptations).
- **Dry run:** one case per group (A02, B03, C04, D02, E01, F02, X01) against staging. **Status: not executed** —
  the oracle notebook and recorded fixtures (§8.2) do not exist yet; results to be linked on #393. Unexecutable
  steps are rewritten, not waived.
- **Automation split:** `E12-Q02` golden fixtures + oracle notebook (and the five fixtures in §8.2),
  `E12-Q03` Playwright, `E12-Q04` contract, `E12-Q05` perf budgets, `E12-Q06` chaos (feed gaps/clock skew, F06),
  `E12-Q07` a11y, `E12-Q08` rollup. Adversarial input: `E12-X02`.
