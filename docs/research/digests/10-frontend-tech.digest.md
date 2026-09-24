# Digest: 10-frontend-tech.md (Frontend charting tech for order-flow terminal)

Source scope: React frontend, Python backend, Bybit (WS-first). Needs: 100k+ candles, footprint cells, volume/delta profiles, real-time DOM heatmap (~100ms cadence, hrs history), big-trade bubbles, multi-pane indicators, drawing tools, chart trading (draggable order lines), DOM ladder, multi-chart layouts. No candidate library ships footprint/heatmap/DOM natively — all require custom rendering.

## Candidate libraries (decision matrix)

| Library | 100k+ candles | Footprint | Heatmap | Multi-pane | Drawing tools | Chart trading | License | Cost | Effort |
|---|---|---|---|---|---|---|---|---|---|
| **Lightweight Charts v5** (RECOMMENDED CHASSIS) | Excellent | No, build via custom series | No, build via primitive/WebGL | Yes native | No, build via primitives | Buildable via primitives | Apache-2.0 + notice | Free | Medium |
| TradingView Advanced Charts | Excellent | No | No | Yes native, richer | Yes native | Buildable | Proprietary, approval required | Free (gated) | Medium+approval delay |
| KlineCharts v9/v10 (fallback #1) | Good | No | No | Yes native | Yes native | Buildable via overlays | Apache-2.0 | Free | Medium |
| react-financial-charts | Fair, unmaintained | No | No | Limited | No | Difficult | MIT | Free | High (stale lib) |
| Highcharts Stock | Fair, SVG-bound | No | No | Yes | Some (annotations) | Difficult | Commercial | $$ | Medium-High |
| SciChart.js | Excellent WebGL | No | Yes, native 2D | Yes | No | Difficult | Commercial | ~$116.84/dev/mo | High, no trading chassis |
| LightningChart JS Trader (fallback #2) | Excellent WebGL | No | Yes native | Yes | Some | Some | Commercial | ~$4,900/yr 1st dev (unverified, quote-gated now), ~$980/yr/extra dev | Medium-High |
| Apache ECharts | Good | No, via renderItem | Yes native, not real-time-tuned | Yes | No | Difficult | Apache-2.0 | Free | Medium, aux panes only |
| D3 + custom Canvas | Buildable | Buildable | Buildable | Buildable | Buildable | Buildable | Free (BSD/ISC) | Free | Very High |
| PixiJS/regl custom (RECOMMENDED for heatmap) | N/A | Possible | Excellent targeted | N/A | N/A | N/A | MIT | Free | High for heatmap only |
| Perspective (FINOS) | N/A | N/A | N/A, data layer only | N/A | N/A | N/A | Apache-2.0 | Free | Medium, DOM/stats data layer |
| uPlot | Good, FPS drops at 100k (unverified specifics) | No | No | No, single chart | No | Difficult | MIT | Free | Low, simple panes only |
| Plotly.js | Poor, too slow | No | No | Yes | Some | Difficult | MIT | Free | Not recommended |
| Chart.js + chartjs-chart-financial | Fair | No | No | Limited | No | Difficult | MIT | Free | Not recommended |
| ChartGPU (new, WebGPU) | n/a | No fused footprint | Yes, native heatmap+incremental update | No polished multi-pane | n/a | n/a | MIT | Free | Spike candidate for heatmap only |
| kline-orderbook-chart (new, low-trust) | Claimed 60fps+@100k | Claimed native | Claimed native | n/a | Claimed | Claimed | Unclear/red flags | Unclear (OSS+paid funnel) | DO NOT adopt sight-unseen |

## Per-library notes

- **Lightweight Charts v5** — Canvas 2D, dependency-free, tens-of-KB core. v5 primitives: Custom Series (`ICustomSeriesPaneView`, new series type e.g. footprint/heatmap), Series Primitives (`ISeriesPrimitive`, order lines/markers/drawing), Pane Primitives (`IPanePrimitive`, watermarks/bands). Native multi-pane w/ independent price scales. Only draws visible bars → 100k+ candles fine; footprint text-cell rendering is the real bottleneck. No drawing-tools UI, no footprint/heatmap/DOM/ladder built in. License Apache-2.0; NOTICE file requires reproducing 2-line notice somewhere reasonable (about/settings page) — no mandatory on-chart footer link (earlier draft's stronger claim retracted). No official React bindings; community wrapper `lightweight-charts-react-components` (npm v2.6.0, ~122 stars) exists but recommend raw imperative API first for footprint/heatmap primitives. **Verdict: best OSS chassis, recommended.**
- **TradingView Advanced Charts** — proprietary, requires approval via form, private GitHub repo invite, no redistribution/sublicense. Richer chassis (native drawing tools, indicator system, polished multi-pane) but still no native footprint/heatmap/DOM. Pine Script `request.footprint()` exists only on tradingview.com consumer product, NOT exposed in Advanced Charts/Trading Platform (Pine Script unsupported there). **Verdict: not recommended** — approval dependency conflicts with project's anti-lock-in goal; only pursue if LWC prototype fails.
- **KlineCharts v9/v10** — Apache-2.0, crypto/quant-purpose-built. `registerIndicator`, `registerOverlay`/`createOverlay` (drag/hover/selection events, good fit for order lines), `@klinecharts/extension` package for Fibonacci/measurement/price-channel overlays. Ships actual drawing-tools toolbar OOB. Weaknesses: smaller ecosystem, v9→v10 migration was non-trivial (API not fully stable), less proven at 100k+ bars than LWC. **Verdict: credible fallback #1**, worth half-day spike.
- **react-financial-charts** — D3+Canvas/SVG, effectively unmaintained (last release 2.0.1, years old, ~40 open issues). Not recommended.
- **Highcharts Stock** — commercial (free tier only personal/non-commercial, unclear fit for CandleViewer's usage model — needs verification, moot since not recommended). SVG-based, Boost module needed for scale — not real-time-heatmap-grade. Not recommended.
- **SciChart.js** — WebGL, Community Edition free but watermarked/non-commercial; paid ~$116.84/dev/mo removes watermark. Best OOB heatmap match among commercial options but no trading chassis (no candlesticks/footprint/chart-trading) — would still build entire trading UX yourself. Consider only if custom WebGL heatmap fails.
- **LightningChart JS Trader** — WebGL, trading-native, purpose-built heatmap. Community free/watermarked/non-commercial. Trader Basic license reseller-quoted (unverified first-party) ~$4,900/yr (1 dev) + ~$980/yr/extra dev, subscription not perpetual; does NOT bundle with standard LightningChart JS license. **Verdict: fallback #2** if custom WebGL heatmap prototype fails performance bar.
- **Apache ECharts** — Apache-2.0, free, large chart catalog incl. candlestick/heatmap/`custom` series w/ `renderItem`. ~100k candles initial render ~41ms (comparable to uPlot cold-start) but interactive pan/zoom/mousemove measurably slower than uPlot. Bundle 1MB+. Recommended only for auxiliary panes (stats dashboard, journal analytics), not primary chart.
- **D3 + custom Canvas** — full control, BSD/ISC free, but must reimplement pan/zoom momentum, axis label decimation, crosshair sync, hit-testing, multi-pane resize, DPI/perf engineering before any order-flow feature exists. Not recommended as primary path; would duplicate what LWC already solves.
- **PixiJS/regl custom WebGL** — targeted use for DOM heatmap only (and footprint text if Canvas2D becomes bottleneck). PixiJS = higher-level scene-graph (MIT), regl = lower-level functional WebGL wrapper (MIT, more direct GPU control, preferable for tuned rolling-texture 100ms-cadence updates). Implementation: 2D texture (price bucket x time bucket) as rolling ring buffer, `texSubImage2D` updates only changed column per tick, axes/crosshair rendered in synced overlay. **Recommended for heatmap layer.**
- **Perspective (FINOS)** — Apache-2.0, WASM streaming analytics/pivoting engine, Arrow-based columnar core. Best fit as DOM-ladder/order-book aggregation data layer + stats/journal views, not as chart replacement. Worth prototyping for that specific use.
- **uPlot** — MIT, ~50KB minified, Canvas2D, fastest raw line/area rendering. Cold-start ~166,650 OHLC points in ~25-34ms; ~100,000 points/ms throughput (README, re-verified). Correction: earlier draft's "~6 FPS at 100k candles" claim was fabricated/unverifiable and retracted — actual uPlot docs only say qualitatively "may begin to struggle beyond 100k in-view points," live-stream 3,600 pts@60fps uses 10% CPU/12.3MB RAM. No OHLC/candlestick type built in (plugin needed), no multi-pane/time-scale-sync, no rich primitives system. Good for secondary simple panels (speed-of-tape, delta line) only.
- **Plotly.js** — SVG-heavy, too slow for 100k+ bars or 10Hz heatmap. Not recommended for core chart; maybe reusable for Python/Dash-side quick analytics reports.
- **Chart.js + chartjs-chart-financial** — general dashboard lib + thin bolt-on plugin, no multi-pane sync, no primitives, no order-flow precedent. Not recommended.
- **kline-orderbook-chart** (new candidate, low trust) — claims built-in orderbook heatmap+footprint+liquidation heatmap all-in-one canvas, framework-agnostic, zero deps, npm v1.6.2, created Apr 2026, ~18 GitHub stars/47 commits. Claims 60fps+@100K candles, heatmap updates ~6,000fps, WASM/Rust core w/ GPUI/wgpu/Skia native targets. **Red flags**: young/low-star vs sweeping claims; SEO-keyword-stuffed README; content duplicated across `PhamNhinh` and `tapedelta` orgs, tapedelta.com sells "30-day free trial" commercial version of a supposedly free/OSS zero-dep lib (inconsistent licensing model); unverified license terms (repo shows "View license" w/o name); no independent benchmark reproduction, no third-party review/Show-HN/SO mentions found. **Recommendation: do NOT adopt sight-unseen; spike-and-verify only** (check LICENSE, benchmark independently, clarify tapedelta.com relationship, verify free vs paid feature split) before any architecture decision.
- **ChartGPU** (new candidate) — MIT, WebGPU-native, TS, zero deps, React bindings (`chartgpu-react`), npm `@chartgpu/chartgpu`/`chartgpu` v0.3.2–0.4.0, ~3,211 stars/707 commits, listed "Awesome WebGPU," docs at chartgpu.io. Series types: line/area/bar/scatter(+density)/pie/donut/candlestick/OHLC/heatmap(spectrogram)/band/error-bars/impulse/3D. Heatmap has dedicated `updateHeatmap()` incremental-update API (matches 100ms-cadence need) and shares GPUDevice across multi-chart layouts. Caveats: no WebGL/Canvas fallback (requires Chrome/Edge 113+ or Safari 18+, Firefox flags/platform-dependent — acceptable for single-operator tool but must be deliberate); pre-1.0, no footprint primitive, no polished multi-pane/time-scale-sync, no evidence of production trading-platform usage. **Verdict: upgraded from "not recommended" to "worth a time-boxed spike specifically for heatmap"**, still 2nd choice vs WebGL PixiJS/regl on maturity/risk grounds; does not change core LWC chassis recommendation.

## Feature-by-feature notes

- **Candlesticks 100k+**: LWC and KlineCharts both viewport-only render → solved either way. Recommendation: LWC + typed-array-backed data store (not plain JS objects) for allocation-light push/slice.
- **Footprint/order-flow cells**: no library has native footprint. Build as LWC custom series (`ICustomSeriesPaneView`): per-bar column of price-level cells, filled rects + `fillText` bid/ask numbers, LOD-gated (skip per-cell text below ~10px cell height, background-only at zoom-out, matching Bookmap/ATAS/DeepCharts pattern). **Single largest bespoke-rendering investment in project.**
- **Volume/delta profiles**: horizontal histogram anchored to price axis, implement as pane primitive or docked side-panel sharing main price scale. Lower risk — cell count bounded (hundreds), Canvas 2D sufficient, no LOD needed.
- **Real-time DOM liquidity heatmap**: most performance-sensitive surface (tens of thousands of cells @ 10Hz over hours). Primary WebGL candidate: rolling 2D texture (time cols x price rows), `texSubImage2D` per-tick update of newest column only, textured quad synced to main chart's price axis. Canvas2D fallback possible but CPU pressure grows with retained depth; WebGL/texture keeps update cost ~constant.
- **Big trade bubbles**: simple markers/circles sized by notional at (time,price), optional decay/fade, LWC series primitive w/ hit-testing. Low risk/effort.
- **Multi-pane indicators**: both LWC v5 and KlineCharts support multiple resizable panes w/ independent price scales + synced shared time axis — met by base chassis either way.
- **Drawing tools**: KlineCharts ships OOB toolbar via overlay system. LWC requires building from primitives (more work, full control) — budget dedicated 1-2 week sprint for a small kit (trendline, h-line/ray, rectangle, Fibonacci) as reusable primitives; the two libs' overlay systems are not interchangeable.
- **Chart trading (draggable order/position lines)**: LWC series primitives w/ drag interaction — horizontal line, vertical drag, tick-snap, drop event → order-management layer. KlineCharts overlay drag-event model supports same pattern. Moderate, well-understood effort either way.
- **DOM ladder**: not a chart — virtualized vertical price-row list w/ quick-order buttons + current-price highlight. UI-virtualization problem, not charting-library problem.
- **Multi-chart layouts**: workspace/docking-layout concern, independent of per-panel chart library — see Layout managers section.

## Reference OSS projects (not adoptable as-is, but reference-worthy)

- **Flowsurface** (flowsurface.com) — Rust/Iced desktop crypto order-flow platform: footprint, heatmaps, DOM, volume-profile, multi-exchange incl. Bybit. Reuse aggregation logic (cell binning, heatmap decay, normalization) as algorithm reference.
- GitHub topic pages: `footprint-chart`, `footprint-charts`, `market-profile`, `order-flow` — discovery starting points, vet individually.
- **srl-ctrader-indicators** (C#) — Volume/TPO Profile, footprint candles, Weis/Wyckoff cluster-volume — algorithm reference only.
- **OrderFlow-Analysis-Pro** (Python/Dash) — footprint, delta analytics, volume profile, Bybit/MT5 WS feeds — reference for Python backend Bybit normalization/aggregation.
- **quant-order-book** (JS/React/Vite) — real-time crypto order-book heatmap + CVD across Binance/OKX/Bybit — closest stack match; read directly for heatmap rendering + Bybit WS pattern.
- **Tyumex trading terminal** (Windows-native) — multi-chart footprint/cluster-volume/2nd-level candles across exchanges — feature-surface reference only, not web-based.
- **No dominant pure-React footprint/order-flow library exists** as of research time; standard real-world pattern = custom overlays on general financial charting lib (usually LWC) + port aggregation algorithms from Rust/Python/C# references.

## Canvas vs WebGL vs WebGPU

- **Canvas 2D**: sufficient for candlesticks, footprint at typical zoom (w/ LOD), volume profile, bubbles, drawing tools, order lines, indicator lines. Matches LWC's primitive system natively.
- **WebGL**: justified specifically for DOM heatmap. PixiJS (faster to build, more abstraction) vs regl (more control, better for tuned 100ms-cadence texture updates) — regl preferred if cadence tuning is critical.
- **WebGPU**: not primary rec, but ecosystem more capable than previously thought (ChartGPU exists). Still 2nd choice because: (a) no-fallback browser gating (Chrome/Edge 113+, Safari 18+, Firefox inconsistent), (b) ChartGPU pre-1.0/unproven in production trading, (c) WebGL ceiling already sufficient for single-user data volumes. Recommendation: build WebGL heatmap first; run short ChartGPU `heatmap`/`updateHeatmap()` spike as comparison before finalizing.

## OffscreenCanvas + Web Workers

Move heaviest per-frame heatmap/footprint rendering (texture updates, cell redraws) off main thread via `OffscreenCanvas` in a Worker — keeps main thread free for React reconciliation, WS handling, drag/pan interactions. Recommendation: prototype WebGL heatmap inside OffscreenCanvas-backed worker from the start (retrofitting later is more invasive). LWC itself runs main-thread only (no OffscreenCanvas support currently) → architecture = main-thread LWC (candles/footprint/panes) + worker-thread WebGL heatmap canvas, composited via absolute positioning/z-index.

## WebSocket data pipeline / state management

- **Zustand** — centralized store, selector subscriptions; needs careful `shallow` comparison to avoid over-triggering.
- **Jotai** (RECOMMENDED for high-frequency data) — atomic state, best fit for many independently-updating small values (book deltas, tick prints, per-indicator values) at high frequency.
- **Valtio** — proxy-based mutate-in-place, similar profile, less benchmarked for trading workloads — viable 3rd option, spike only.
- **RxJS** (RECOMMENDED as ingestion layer) — not a state lib; use as batching/throttling layer between raw Bybit WS and React state (e.g. `bufferTime`/rAF-gated batching of book deltas into one update/frame).
- **Final recommendation**: RxJS (or hand-rolled batching) ingestion layer → Jotai for high-frequency per-symbol/per-widget data → Zustand for global UI state (active symbol/layout/connection status/settings).

## Binary protocols over WebSocket

- **JSON**: simplest; parsing/payload-size tax measurable at 100ms-cadence/thousands-of-levels scale on lower-end hardware.
- **MessagePack**: drop-in binary, similar data model, smaller/faster — low-friction upgrade path from JSON.
- **Protobuf**: schema+codegen overhead, strongest size/speed guarantees + schema evolution discipline; good given Python backend's mature Protobuf tooling — strong long-term choice if schema-first accepted.
- **Apache Arrow**: best for columnar bulk transfers (100k+-bar backfill, footprint aggregation batches), not per-tick streaming (framing overhead too high for small frequent messages).
- **Recommendation**: start JSON (decode into typed structures immediately at ingestion boundary so codec is swappable later, don't couple business logic to JSON-object assumption); upgrade to MessagePack if profiling shows JSON bottleneck; Protobuf if/when schema discipline + multi-exchange expansion prioritized; Arrow reserved for bulk historical transfer only.

## Virtualized DOM ladder libraries

`react-window`/`react-virtualized` (row-based) vs `@tanstack/react-virtual` (headless, modern, actively maintained, framework-agnostic core) — **`@tanstack/react-virtual` recommended**. Needs tight per-row render path (memoized rows, primitive-only props) since rows update at high frequency in volatile markets. No trading-specific behavior built in — must layer price formatting/click-to-trade/imbalance coloring on top.

## Hotkey libraries

`react-hotkeys-hook` recommended — lightweight, scoped-binding support (important for multi-chart layout so hotkeys don't leak across panels), no extra dependency baggage.

## Layout managers

- **Dockview** (RECOMMENDED) — zero-dependency, framework-agnostic, tabs/groups/grids/splitviews/floating panels/popout windows, ~3,400+ stars, 240k+ weekly downloads, actively maintained, most modern. Popout windows valuable for multi-monitor trading setup.
- **FlexLayout** (alternative) — React-only, JSON-driven state, tabsets/border tabsets/popouts/overflow/theming/a11y, ~1,300+ stars/100k+ weekly downloads, built by Caplin (financial-trading-software pedigree).
- **Golden Layout** — historical gold standard, ~6,700+ stars, but DOM-manipulation-first (not React-idiomatic), heavier to configure — best for migrating legacy codebases only.
- **react-grid-layout** — simpler drag/resize CSS-grid dashboard tool, not IDE-style docking/tabbing — not a strong fit here.

## UI kits

- **Mantine** — 100+ components, dark mode/forms/notifications/hooks, good data-table density, faster for complete admin-style surfaces, more opinionated/heavier.
- **shadcn/ui + Radix + Tailwind** (RECOMMENDED for core trading surface) — copy-into-repo over unstyled accessible Radix primitives + Tailwind, maximal control over density/interaction (important for DOM ladder row spacing, chart-trading precision), more manual assembly.
- **Recommendation**: shadcn/ui+Radix+Tailwind for DOM ladder/order tickets/chart toolbars; Mantine acceptable for settings/journal/analytics screens where dev speed > visual customization. Both MIT.

## Desktop wrap: Tauri vs Electron

- **Tauri** (RECOMMENDED) — OS-native WebView + lightweight Rust backend; idle memory ~15-50MB (some benchmarks as low as ~12MB) vs Electron's ~150-300MB (3-5x advantage); smaller binaries, faster startup.
- **Electron** — bundles full Chromium+Node; larger footprint but more mature/predictable rendering across OS versions (own bundled browser engine vs OS-provided WebView variability).
- **Risk specific to CandleViewer**: heavy Canvas2D/WebGL + 100ms-cadence heatmap could hit WebView2 (Windows)/WebKit (macOS/Linux) inconsistencies that Electron's bundled Chromium avoids — must be smoke-tested early, not assumed away.
- **Recommendation**: Tauri as default (memory/footprint advantage matters when running alongside Python backend/WSL/other tools on the same machine); smoke-test WebGL heatmap inside Tauri's WebView2 early; fallback to Electron is low-regret since web app code is shell-independent.

## Overall recommended architecture

**Primary**: TradingView Lightweight Charts v5 chassis (candles, multi-pane, crosshair, time scale, chart trading via primitives, drawing tools via primitives, footprint via custom series + LOD text-hiding, volume profile via pane primitive) + dedicated WebGL layer (PixiJS or regl) inside OffscreenCanvas/Worker for DOM heatmap, composited behind/under LWC canvas. Data pipeline: RxJS batching/throttling at WS ingestion → Jotai (high-freq per-symbol/level state) + Zustand (global UI state). JSON wire format initially, MessagePack as identified upgrade path. DOM ladder on `@tanstack/react-virtual`. Layout via Dockview. UI via shadcn/ui+Radix+Tailwind. Packaged as Tauri desktop app w/ early WebView2 WebGL smoke test.

**Fallback**: if 1-2 week LWC primitives spike proves too constraining for footprint/heatmap → (a) switch chassis to KlineCharts (friendlier overlay/drawing-tools model), or (b) adopt LightningChart JS Trader (paid, WebGL-first, natively solves heatmap, ~$4,900/yr) accepting cost as risk-reduction price. Do NOT pursue TradingView Advanced Charts (licensing friction) or from-scratch D3+Canvas engine except as last resort.

## Effort estimates (single experienced dev)

- Base LWC integration (candles/time-scale/panes/symbol switching): 3-5 days
- Footprint custom series (cell rendering, LOD, delta/imbalance coloring, bar-cell binding, live+replay modes): **2-3 weeks — single largest line item**
- Volume/delta profile pane: 3-5 days
- Drawing-tools primitive kit (trendline/ray/rectangle/Fibonacci/h-line): 1-2 weeks (starter set)
- Chart-trading order/position lines (rendering/interaction only, excl. backend order mgmt): 1 week
- Big-trade bubbles + VWAP/indicator overlays combined: 3-5 days
- **Subtotal LWC chassis + custom pieces (excl. heatmap/ladder)**: ~6-9 weeks
- Real-time DOM heatmap (WebGL layer, texture/instancing design, OffscreenCanvas wiring, coord sync, perf validation): 2-4 weeks
- DOM ladder (on top of virtualization lib, trading-specific behavior): 1-2 weeks
- **Total full custom-rendering surface**: ~11-17 weeks, before backend integration/multi-exchange/non-charting features
- Fully custom D3/Canvas or raw-WebGL engine from zero: add **4-8 additional weeks** just to reach LWC parity (pan/zoom momentum, axis decimation, multi-pane sync, crosshair sync, DPI correctness) before any order-flow feature — **not recommended**.

## Open questions (10)

1. No benchmark found for LWC v5 custom-series/primitives specifically under dense per-cell-text-labeled footprint grid at realistic bar/price-level counts — needs hands-on spike.
2. No data on Tauri WebView2 behavior for WebGL heatmap under sustained 100ms updates — needs early smoke test.
3. Exact LWC v5 multi-pane API stability/completeness (e.g. independent time-scale offsets per pane) not fully verified against latest patch release — read current release notes before implementation.
4. Highcharts Stock's exact license terms for CandleViewer's ownership/usage model (private tool + few account managers) unresolved — moot since not recommended, revisit if requirements change.
5. Perspective (FINOS) integration specifics for a Bybit L2 feed not found — needs dedicated spike before committing for DOM ladder data layer.
6. Binary protocol codegen tooling maturity for Python backend + TypeScript frontend pairing (Protobuf vs MessagePack DX) not directly researched — revisit if/when profiling shows need.
7. DeepGamma-equivalent (options/gamma exposure) pane requirements explicitly out of scope for crypto-only v1, not researched — flag for later phase if options data added.
8. No public benchmark found for text-heavy footprint-cell rendering (vs plain candle rendering) at realistic densities — largest unresolved engineering-risk question, requires hands-on spike.
9. kline-orderbook-chart's exact license terms and tapedelta.com commercial relationship unresolved ("View license" w/o name shown) — do not budget as free/OSS without reading actual LICENSE and clarifying free-vs-paid split.
10. LightningChart JS Trader's exact current first-party price unresolved (pricing now quote-gated; ~$4,900/$980 figures are third-party reseller quotes, unconfirmed on lightningchart.com) — get direct sales quote before budgeting.
