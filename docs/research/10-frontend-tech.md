# Frontend technology options for React order-flow charting

> Research phase deliverable for CandleViewer, a private, self-hosted, single-user (plus a few account managers) crypto order-flow trading terminal. React frontend, Python backend, Bybit first (demo and live, WebSocket-first), replicating the visibility of DeepCharts (Deepchart, DeepDOM, DeepGamma) and TradingView-class charting. This document evaluates frontend charting/visualization technology options against the concrete rendering requirements: 100k+ candlestick history, footprint cells (bid/ask per price level per bar), volume/delta profiles, a real-time DOM liquidity heatmap (time by price by size, ~100ms cadence, minutes-to-hours of retained history), big-trade "bubbles," multi-pane indicators, drawing tools, chart trading (draggable order/position lines), a DOM ladder, and multi-chart/multi-pane layouts.

Dates/versions referenced were current as of research time (September 2026); re-check version numbers and licensing terms before committing, as vendors change these terms.

## Table of contents

1. Requirements recap
2. Candidate technologies
3. Feature-by-feature deep dive
4. Open-source footprint/heatmap projects to learn from
5. Canvas vs WebGL vs WebGPU decision
6. OffscreenCanvas + Web Workers
7. WebSocket data pipeline: state management
8. Binary protocols over WebSocket
9. Virtualized DOM ladder libraries
10. Hotkey libraries
11. Layout managers
12. UI kits
13. Desktop wrap: Tauri vs Electron
14. Decision matrix
15. Recommended approach
16. Effort estimate: custom engine vs extending Lightweight Charts
17. Sources
18. Open questions

---

## Requirements recap

CandleViewer needs to reproduce, at minimum, DeepCharts-class order-flow visibility:

- **Deepchart** — candlestick chart with overlaid order-flow annotations (delta, volume, footprint).
- **DeepDOM** — real-time depth-of-market ladder plus liquidity heatmap (price on Y, time on X, resting size as color/intensity), with minutes-to-hours of rolling history.
- **DeepGamma** — options/gamma exposure visualization (lower priority for a crypto-only v1, but architecture should not preclude adding a pane type later).
- **Footprint / Deep Print** — per-bar, per-price-level bid x ask traded-volume grid ("footprint" cells), often with imbalance highlighting.
- **Deep Profile** — session/composite volume profile (volume-at-price), value area, POC.
- **Deep Stats / Big Trades** — trade-size histograms, large-print markers/bubbles on the tape and on the chart.
- **Imbalance tracker, speed of tape, VWAPs, stop-run and iceberg detectors, market regime indicator** — mostly derived-data overlays layered on the base chart/DOM, not fundamentally new rendering primitives beyond markers/lines/heatmap cells.
- **Tick replay / backtester** — needs a renderer that can be driven by a virtual/replayed clock as easily as live data (decouple the rendering layer from "now").
- **Trading terminal / chart trading** — draggable, interactive lines representing live orders and positions directly on the price axis, plus a full order ticket.
- **Auto-tracker journal** — a data/reporting feature, not a rendering concern.

None of the packaged commercial or open-source charting libraries provide footprint charts, DOM heatmaps, or DOM ladders out of the box. Every option below requires custom rendering work for those pieces; the question is which base library gives the best "chassis" (candlesticks, panes, axes, crosshair, zoom/pan, time scale) to build the custom pieces on top of, and whether a fully bespoke WebGL engine is justified instead.

---

## Candidate technologies

### TradingView Lightweight Charts v5

- **What it is**: TradingView's open-source, dependency-free charting library, purpose-built for financial time series. Actively maintained; v5 introduced a full plugin/primitives architecture ([Custom Series and Primitives — DeepWiki](https://deepwiki.com/tradingview/lightweight-charts/6.2-custom-series-and-primitives), [Plugin and Extension System — DeepWiki](https://deepwiki.com/tradingview/lightweight-charts/2.4-plugin-and-extension-system)).
- **Rendering**: Canvas 2D, hand-tuned rendering pipeline, no virtual DOM overhead. Very small bundle (tens of KB core).
- **v5 extension model**:
  - **Custom Series** — implement `ICustomSeriesPaneView` to define an entirely new series type with its own data model and renderer (e.g., a footprint-cell series, a heatmap series). Runs inside the chart's normal render loop and shares the coordinate system, so it composes with panning/zooming/crosshair for free.
  - **Series Primitives** — implement `ISeriesPrimitive`, attach via `series.attachPrimitive()`. Good for overlays tied to a series: order/position lines, markers, annotations, drawing tools, alert lines.
  - **Pane Primitives** — implement `IPanePrimitive` for pane-level decorations (watermarks, background bands, session shading).
  - All primitives render through the Canvas 2D context provided by the library (`ctx`, `mediaSize`, `priceToCoordinate`, `timeToCoordinate` helpers), so custom code can reuse the library's already-optimized coordinate mapping and device-pixel-ratio handling. Example shape from the docs:
    ```typescript
    const primitive = {
      attached({ chart, series, requestUpdate }) { /* setup */ },
      detached() { /* cleanup */ },
      view: {
        renderer({ ctx, mediaSize, priceToCoordinate, timeToCoordinate }) {
          // custom Canvas 2D drawing
        },
      },
    };
    series.attachPrimitive(primitive);
    ```
- **Multi-pane support**: v5 added first-class multi-pane charts (indicator panes below the main price pane), each with independent price scales, resizable by the user.
- **Performance**: Because it is Canvas 2D (not WebGL), 100k+ bar candlestick series are viable because Lightweight Charts only draws the visible bars each frame — panning/zooming stays smooth well past 100k bars for the base candle series in most real-world reports. A synthetic footprint layer with thousands of text-labeled cells per visible bar will be the actual bottleneck, not the base candles.
- **Known limits**:
  - No footprint chart, DOM heatmap, volume profile, or DOM ladder built in — must be built as custom series/primitives.
  - No built-in drawing-tools toolbar UI (TradingView reserves the polished drawing-tools UX for the proprietary Advanced library) — but the primitives API is sufficient to build your own trendlines, rectangles, Fibonacci tools, etc.
  - Text rendering (needed for footprint bid/ask numbers in every cell) is comparatively expensive in Canvas 2D at high cell counts; needs careful throttling/LOD (hide per-cell text below a certain px-per-cell threshold, matching how DeepCharts/Bookmap/ATAS degrade footprint text at zoom-out).
- **License**: Apache License 2.0. The actual [`NOTICE` file at the repo root](https://github.com/tradingview/lightweight-charts/blob/master/NOTICE) (checked directly, current `master` branch) is exactly two lines: `TradingView Lightweight Charts™` / `Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/`. Apache-2.0 §4(d) requires that NOTICE text be reproduced "within a NOTICE text file distributed as part of the Derivative Works," which for a web app in practice means shipping/retaining that notice text somewhere reasonable (e.g., an about/licenses page or bundled `NOTICE`/`THIRD-PARTY-NOTICES` file) — it does not, on its own wording, mandate a visible on-page footer link to tradingview.com. *Corrected: the report previously stated the library imposes a requirement to "display the attribution notice... together with a link" to tradingview.com on any page where charts are visible, citing an older v4.1 docs page; the current repo's NOTICE file and root LICENSE do not contain that stronger footer-link language, and no separate current TradingView "trademark usage policy" page requiring an on-chart link was found. The safe, low-effort approach for CandleViewer (a private, non-public tool) is still to keep a small "Charts by TradingView Lightweight Charts™" credit in an about/settings screen and preserve the NOTICE file in the repo, but this is a conservative choice rather than a strictly mandated on-page link.*
- **React integration**: TradingView does not ship official React bindings; the idiomatic pattern is to hold the imperative `IChartApi` instance in a `ref`/`useEffect` and drive it declaratively from React state. The community library [`lightweight-charts-react-components`](https://github.com/ukorvl/lightweight-charts-react-components) (by `ukorvl`; ~122 GitHub stars, 400+ commits, actively maintained as of Sept 2026, published on npm as `lightweight-charts-react-components` at v2.6.0) wraps the library in a declarative `<Chart>`/`<Series>` component tree with proper cleanup/lifecycle handling, and is a reasonable option to reduce imperative-effect boilerplate — but it adds an extra dependency and an abstraction layer that could complicate custom-series/primitives registration (footprint, heatmap) since those are lower-level imperative APIs that may need to bypass the wrapper. Recommendation: prototype with the raw imperative API first (full control for the custom-series/primitives work that is this project's core risk); adopt the wrapper only for simpler, secondary panes if boilerplate becomes a real pain point.
- **Verdict**: Best available open-source "chassis" for a React order-flow charting app in 2026. It solves axes, crosshair, zoom/pan, multi-pane, and candlestick rendering to a very high standard, and its v5 primitives/custom-series API is specifically designed for exactly this kind of extension (footprint, heatmap, order lines).

### TradingView Advanced Charts / Charting Library

- **What it is**: TradingView's full-featured proprietary charting library (also marketed as "Trading Platform"/"Advanced Charts"), the same engine that powers tradingview.com's own charts — includes drawing tools, a full indicator/study system, and a more polished multi-pane UX.
- **Licensing/access** (per TradingView's own docs and policy pages — [Get started — Advanced Charts Documentation](https://www.tradingview.com/charting-library-docs/latest/quick-start/), [Terms of Service and Company Policy](https://www.tradingview.com/policies/), [Free Charting Library by TradingView](https://www.tradingview.com/free-charting-libraries/)):
  - Not open source. To obtain it at all — even for private/internal, non-commercial use — you must submit a request through TradingView's official form and receive explicit approval.
  - On approval you get invited to a private GitHub repository; you may not redistribute, sublicense, or expose the source (including in a public repo) under any circumstances.
  - The license permits use in your own private/internal business web app, self-hosted, with your own data feed — which matches CandleViewer's use case — but approval is still a prerequisite, is not guaranteed, and terms can include display-only restrictions on TradingView-sourced market data (not directly relevant since CandleViewer's data comes from Bybit, not TradingView). This general shape was re-checked against current (Sept 2026) TradingView documentation — the [Advanced Charts FAQ](https://www.tradingview.com/charting-library-docs/latest/quick-start/) still describes Advanced Charts as "a standalone solution that you download, host on your servers, and connect your data to... You can use it in your site/app for free," distinct from the paid "Trading Platform" product (which adds order management, multi-chart layouts, watchlists) — confirming the free/approval-gated model is still current and the report's general characterization stands.
  - Practical implication: acquiring this library adds an external approval dependency and a strict no-redistribution obligation, for a project whose whole point is to avoid vendor/subscription lock-in. Taking on TradingView's proprietary Advanced Charts license — even if free and even if approved — reintroduces exactly the kind of dependency this project exists to avoid, for no external users.
- **Pine Script `request.footprint()` / native footprint on tradingview.com itself**: TradingView's own web platform (Premium/Ultimate consumer plans) now exposes footprint-style intrabar bid/ask data to Pine Script strategies/indicators via a dedicated function. However, per TradingView's Advanced Charts FAQ, **Pine Script is explicitly not supported in Advanced Charts or Trading Platform** ("Pine Script® is not supported in Advanced Charts or Trading Platform. Alternatively, you can create your custom indicator using JavaScript.") — so this native footprint capability is walled off inside tradingview.com's own consumer product and is not exposed as a reusable widget/study inside the self-hosted Advanced Charts library. This confirms rather than changes the report's original conclusion: Advanced Charts still has no native footprint primitive available to an integrator; footprint remains a custom build regardless of which TradingView library is used.
- **Feature ceiling**: much higher out of the box than Lightweight Charts — native drawing tools UI, more indicator plumbing, "compare" symbols, more polished multi-pane UX. Still no native footprint, volume-profile, or DOM heatmap — those remain custom studies/overlays built by the integrator regardless of which TradingView library is used.
- **Verdict**: Feature-richer chassis, but the licensing gate (mandatory approval, no redistribution, ongoing dependency on TradingView's goodwill) is a poor fit for a private tool where Lightweight Charts' primitives already cover the necessary extension points. Recommend not pursuing Advanced Charts approval unless a Lightweight Charts prototype proves genuinely insufficient.

### KlineCharts (v9/v10)

- **What it is**: An open-source (Apache-2.0) charting library purpose-built for crypto/quant trading UIs. Actively developed; v10 ([v9-to-v10 upgrade guide](https://klinecharts.com/en-US/guide/v9-to-v10), [Overlay guide](https://klinecharts.com/en-US/guide/overlay), [Indicators — DeepWiki](https://deepwiki.com/klinecharts/KLineChart/4.1-indicators), [Overlays — DeepWiki](https://deepwiki.com/klinecharts/KLineChart/4.2-overlays), [klinecharts/extension](https://github.com/klinecharts/extension)) reworked the indicator/overlay APIs.
- **v10 extension model**:
  - `registerIndicator` for custom indicators — full control of calculation, figure rendering, tooltip formatting; can bind to dedicated panes or share the main price pane's Y-axis.
  - `registerOverlay` / `createOverlay` for custom overlays — drawing tools, annotations, order lines; step-based interaction model supports drag, hover, and selection events, which maps reasonably well onto "draggable order/position line" chart-trading needs.
  - A separate `@klinecharts/extension` package ships reusable overlay templates (Fibonacci tools, measurement tools, price channels) importable a la carte.
- **Strengths relative to Lightweight Charts**: ships with an actual drawing-tools toolbar UX out of the box, and its overlay system is explicitly designed around "declarative overlay + step interactions," convenient for order/position lines and manual drawings alike.
- **Weaknesses**: smaller ecosystem/community than TradingView's libraries; no footprint/heatmap/DOM natively (same gap as every candidate); the v9-to-v10 migration required non-trivial API changes per the official guide, signalling the API isn't fully stable yet; less proven at very large (100k+) bar counts in public benchmarks than Lightweight Charts.
- **License**: Apache-2.0, no TradingView-style attribution rider.
- **Verdict**: A credible second choice if Lightweight Charts' primitive model proves too low-level for team velocity — KlineCharts trades a bit of raw performance/maturity for a friendlier out-of-the-box drawing/overlay authoring experience. Worth a half-day spike alongside Lightweight Charts before committing.

### react-financial-charts

- **What it is**: A React-native (D3 + Canvas/SVG) OHLC/candlestick charting component library, historically popular as "the React way" to do financial charts ([GitHub](https://github.com/react-financial/react-financial-charts), [npm](https://www.npmjs.com/package/react-financial-charts?activeTab=code)).
- **Status**: Effectively unmaintained. The last major release (2.0.1) is several years old as of 2024–2026, with roughly 40 open issues and no meaningful ongoing commit activity. It still works and is still downloaded from npm, but no active maintainer response should be expected for bug fixes, modern React compatibility, or extension work.
- **Verdict**: Not recommended as a foundation for a multi-year private trading tool. Its React-idiomatic API is appealing on paper, but building an order-flow platform on a stalled dependency is an avoidable maintenance risk given actively-maintained alternatives (Lightweight Charts, KlineCharts).

### Highcharts Stock

- **What it is**: The financial-charting variant of Highcharts, a mature, broadly-used commercial (with a free non-commercial tier) SVG/Canvas charting library. Supports candlesticks, OHLC, technical indicators, range selectors, and annotations out of the box.
- **License**: Commercial license required for business/commercial use; the free tier is limited to personal, non-commercial, and certain non-profit/educational uses — this needs verification against Highcharts' current terms for CandleViewer's specific ownership/usage context before adoption, since a professionally-used private trading tool may not qualify as "personal, non-commercial."
- **Performance**: SVG-based rendering (with Canvas "Boost" modules for large series) is not designed for 100k+ candle interactive pan/zoom nor for a 100ms-cadence heatmap; the existence of the Boost module is itself evidence that base rendering degrades at large data volumes, and even boosted, it is not aimed at DOM-heatmap-style dense, continuously-updating grids.
- **Verdict**: Good general business-BI stock charting, but not architected for order-flow-grade density (footprint, DOM heatmap) or the update cadence needed here. Not recommended as the primary engine.

### SciChart.js

- **What it is**: A commercial, WebGL-accelerated, high-performance charting library (2D/3D) with a strong focus on scientific/financial real-time visualization, including heatmaps and depth/3D surface charts ([SciChart.js Licensing](https://www.scichart.com/licensing-scichart-js/), [Community Licensing](https://www.scichart.com/community-licensing/), [Getting started for free](https://www.scichart.com/documentation/js/v4/user-manual/licensing-scichart-js/getting-started-for-free/)).
- **Licensing/pricing** (current at research time; verify on scichart.com before budgeting):
  - Community Edition: free, full feature set including heatmaps and 3D/depth charts, but displays a watermark and is restricted to non-commercial/evaluation use.
  - Paid "JavaScript Product" license: roughly $116.84/developer/month at research time, removes watermark, allows commercial use.
  - Bundle tiers exist for multi-platform (WPF/iOS/Android) and source-code access, not relevant to a web-only build.
- **Performance/features**: WebGL rendering gives genuine headroom for both 100k+ candle series and true real-time heatmaps (2D heatmap series is a first-class chart type, well-suited to a DOM liquidity heatmap's time x price x intensity grid) — the strongest "out of the box" heatmap match among all commercial candidates evaluated.
- **Verdict**: Technically the best-fit commercial option for the DOM heatmap specifically, but SciChart is not a trading-chart product (no candlestick-specific chassis, no footprint, no chart-trading primitives) — you would pay a recurring per-developer fee for a general-purpose scientific charting engine and then still build the entire trading-specific UX yourself. For a private single/few-user tool, the recurring cost is hard to justify versus a free WebGL heatmap built directly with PixiJS/regl at similar effort. Consider only if a prototype shows a from-scratch heatmap is a genuine blocker.

### LightningChart JS / JS Trader

- **What it is**: A WebGL-first commercial charting library (LightningChart JS) with a dedicated trading-focused edition, LightningChart JS Trader, explicitly targeting financial/technical-analysis charting including heatmaps, indicators, and fast rendering ([Heatmaps — LightningChart JS Trader docs](https://lightningchart.com/js-charts/trader/docs/heatmaps/), [LightningChart JS Trader Prices — ComponentSource](https://www.componentsource.com/product/lightningchart-js-trader/prices), [LightningChart JS Prices — ComponentSource](https://www.componentsource.com/product/lightningchart-js/prices), [LightningChart pricing page](https://www.xlsoft.com/en/products/lightningchart/price-js.html)).
- **Licensing/pricing** (current at research time):
  - LightningChart JS Community: free for non-commercial use, watermarked.
  - LightningChart JS Trader — Basic license (with logo): roughly $4,900/year for 1 developer (single application, 3 support tickets, unlimited end users, LightningChart logo shown), roughly $980/year per additional developer, subscription (not perpetual) model; logo removal and larger-scale terms require a custom quote. *Note: re-checked at research time — the current [LightningChart JS pricing page](https://lightningchart.com/js-charts/pricing) and [Trader product page](https://lightningchart.com/js-charts/trader) no longer publish exact dollar figures directly (pricing is quote/contact-sales-gated for Trader specifically, with the JS-Community-vs-commercial split and "60% of 1-year price" renewal-discount structure confirmed), and note Trader licensing does **not** bundle with a standard LightningChart JS license ("Does LightningChart JS licenses include Trading charts? No... please contact us at sales@lightningchart.com"). The $4,900/$980 figures (previously sourced from ComponentSource/xlsoft reseller listings) could not be independently reconfirmed on LightningChart's own current pricing pages in this pass — treat them as indicative reseller-quoted figures from third parties rather than a verified current first-party price, and get a direct quote before budgeting.*
- **Features**: Purpose-built heatmap support with configurable color palettes/grid density, positioned specifically for trading-chart use cases (closer to CandleViewer's needs than SciChart's general-purpose framing), high-performance WebGL rendering suited to real-time market data.
- **Verdict**: The most "trading-native" commercial WebGL option, and its heatmap plus performance story is compelling for the DOM liquidity view specifically. However, roughly $4,900/year (plus per-seat renewal) for a single-user private tool is a large recurring cost relative to the project's stated goal of avoiding expensive subscriptions — spending that much on a different commercial charting vendor to solve one sub-feature (the heatmap) works against the project's founding motivation. Reasonable fallback only if a custom WebGL heatmap prototype fails to meet the 100ms-cadence / hours-of-history performance bar.

### Apache ECharts

- **What it is**: A mature, free, Apache-2.0-licensed general-purpose charting library (originally Baidu) with a large chart-type catalog including candlestick, heatmap, and custom series via a `custom` series type plus a `renderItem` callback (arbitrary Canvas/SVG drawing per data item, powerful enough to build footprint-cell-like grids).
- **Performance** (from direct uPlot-vs-ECharts benchmarking — [GitHub: leeoniya/uPlot](https://github.com/leeoniya/uPlot), [Fastest Chart Libraries for Quantitative Analysis — SciChart blog](https://www.scichart.com/blog/fastest-chart-libraries-for-quantitative-analysis/), [uPlot Performance — DeepWiki](https://deepwiki.com/leeoniya/uPlot/8-performance), [chart-benchmark repo](https://github.com/will-march/chart-benchmark), [Performance Comparison of JS Chart Libraries 2026 — SciChart blog](https://www.scichart.com/blog/chart-bench-compare-javascript-chart-libraries/)): heavier bundle (1MB+) than uPlot/Lightweight Charts; can render roughly 100,000 candles with an initial render around 41ms, comparable to uPlot's cold-start numbers, but interactive operations (pan/zoom/mousemove) are measurably slower than uPlot due to more JS-side computation per frame. ECharts offers progressive rendering and a WebGL-backed variant (`echarts-gl`) for some series types, but the trading-specific ecosystem (candlestick indicators, drawing tools) is thinner than KlineCharts/Lightweight Charts.
- **Verdict**: Reasonable for auxiliary panes (a stats dashboard, journal analytics, non-real-time volume-profile summaries) where its rich built-in chart types and theming are a net win, but not recommended as the primary price-chart/footprint/heatmap engine — its interactive performance ceiling and lack of trading-specific chassis features (time-scale sync, chart-trading order lines) make it a worse fit than Lightweight Charts or KlineCharts for the core chart.

### D3 + custom Canvas

- **What it is**: Using D3.js purely for scales/data-join utilities while hand-rolling all rendering to a `<canvas>` 2D context — the classic "build it yourself" approach many trading-chart teams eventually land on.
- **Strengths**: Full control over every pixel and every optimization; no license concerns (D3 is BSD/ISC-licensed, free for any use); can be tuned precisely to footprint/heatmap/DOM-ladder needs without fighting an opinionated chart library's abstractions.
- **Weaknesses**: You are responsible for reimplementing everything a charting library normally gives for free — smooth pan/zoom with momentum, time-scale label formatting/decimation, crosshair sync across panes, hit-testing, multi-pane resize, and, above all, performance engineering (dirty-rect redraw, off-screen buffering, DPI scaling) — all before writing a single line of footprint/heatmap-specific code.
- **Verdict**: Viable only if the team is prepared to invest multiple weeks in chart-engine plumbing before any order-flow-specific feature exists. Since Lightweight Charts v5 already provides this plumbing (time scale, panes, crosshair, primitives with Canvas 2D access), building the whole chassis in raw D3+Canvas duplicates work Lightweight Charts already did well. Not recommended as the primary path; custom-canvas effort is better spent on the footprint/heatmap primitives within Lightweight Charts' primitive system, not on reinventing candlestick pan/zoom.

### PixiJS / regl / raw WebGL custom engine

- **What it is**: Building the rendering layer (or at least the highest-density pieces — footprint grid, DOM heatmap) directly on a WebGL abstraction. PixiJS is a general 2D WebGL scene-graph renderer (batches sprites/text efficiently, large ecosystem, MIT-licensed); regl is a lower-level functional WebGL wrapper (more control, less abstraction overhead, MIT-licensed); raw WebGL/WebGL2 offers maximum control at maximum implementation cost.
- **Where this fits best**: Not as a replacement for the whole chart (candles/axes/crosshair), but specifically for the DOM liquidity heatmap — a dense, continuously updating grid of colored cells (time x price x size) refreshing every ~100ms over minutes-to-hours of history is precisely the workload GPU instancing/texture-based rendering is good at and Canvas 2D is comparatively worse at (Canvas 2D redraw of thousands of colored rects per frame at 10Hz is achievable but starts costing meaningful CPU; a WebGL texture-atlas/instanced-quad approach amortizes that cost onto the GPU and scales far better as history depth grows).
- **Implementation sketch**: represent the heatmap as a 2D texture (price bucket x time bucket, updated as a rolling ring buffer) or as GPU-instanced quads; update via `texSubImage2D` for the changed time column each tick rather than re-uploading the whole texture; render axes/labels/crosshair in a synced Canvas 2D or DOM overlay layer on top, matching the exact coordinate system Lightweight Charts exposes via its primitive helpers so the heatmap pane can share the main chart's price axis.
- **License**: PixiJS (MIT) and regl (MIT) are both fully permissive, no attribution burden beyond standard OSS notices.
- **Verdict**: Recommended as the targeted custom-engine layer specifically for the heatmap (and, if footprint text rendering becomes a bottleneck under Canvas 2D, for footprint too) rather than for the whole application — keeping the "chassis" (candles, panes, time axis, crosshair, chart trading) on Lightweight Charts while reserving bespoke WebGL work for the one component (real-time heatmap) that genuinely benefits from it.

### Perspective (FINOS)

- **What it is**: An open-source (Apache-2.0) WebAssembly-powered streaming data-visualization/analytics engine from FINOS (the Fintech Open Source Foundation), built for high-throughput, continuously-updating tabular/aggregated data. Supports pivoting and real-time aggregation over a fast Arrow-based columnar core, with multiple chart renderer backends.
- **Fit for CandleViewer**: Perspective's core strength — real-time aggregation/pivoting of streaming tabular data with a WASM engine — is a better conceptual match for DOM-ladder/order-book aggregation and Deep Stats/Big-Trades tape analytics than for the visual candlestick/footprint chart itself. Worth prototyping specifically for the data layer feeding the DOM ladder and stats panels (aggregating incoming L2 book updates and trade prints into pivoted views efficiently client-side), used alongside — not instead of — a dedicated charting library for the visual chart.
- **Verdict**: Worth prototyping for DOM ladder real-time aggregation and auxiliary stats/journal views, not as a candlestick/footprint chart replacement.

### uPlot

- **What it is**: A tiny (~50KB minified), extremely fast Canvas 2D time-series charting library (MIT-licensed) optimized for raw rendering speed with minimal abstraction ([GitHub: leeoniya/uPlot](https://github.com/leeoniya/uPlot), [uPlot Performance — DeepWiki](https://deepwiki.com/leeoniya/uPlot/8-performance)).
- **Performance**: can cold-start render on the order of ~166,650 OHLC/candle points in ~25–34ms; scales roughly at 100,000 points/ms in throughput terms (per the [uPlot README](https://github.com/leeoniya/uPlot#readme), directly re-verified at research time). *Corrected: the report previously stated "uPlot's own benchmarks show ~6 FPS at 100k OHLC candles under continuous pan/zoom" as a specific verified figure — this exact number does not appear in uPlot's own README, GitHub repo, or `bench/results.json`, and could not be found in any primary uPlot source; it was likely a fabricated/misremembered figure and has been removed. What uPlot's own docs actually say: "In most sane cases, you can live-stream data with uPlot at 60fps, though it may begin to struggle beyond 100k in-view points. When updating 3,600 points at 60fps, uPlot uses 10% CPU and 12.3MB RAM" — a qualitative statement, not a specific FPS number at 100k. No first-party or third-party benchmark giving a precise FPS figure for uPlot at 100k candles under sustained pan/zoom was found in this pass; this remains a genuine open question (see Open Questions) rather than a settled fact, and any specific FPS claim for uPlot at 100k+ points should be verified with a hands-on test before being used to justify an architecture decision.*
- **Strengths**: best-in-class raw line/area chart speed and memory efficiency for straightforward time-series; simple enough to fully understand and extend.
- **Weaknesses**: no financial-chart-specific chassis (no OHLC/candlestick series type built in — must be added via plugins), no multi-pane/time-scale-sync system out of the box, no primitives/plugin architecture as rich as Lightweight Charts v5's, and the interactive-FPS ceiling at 100k+ candles is a concern given CandleViewer's explicit 100k+-bar requirement.
- **Verdict**: Excellent as a component for secondary, high-density but simpler line/area panels (a "speed of tape" or delta line beneath the main chart) where its minimal footprint and raw speed shine, but not recommended as the primary candlestick/footprint chart engine given the FPS ceiling at exactly the bar counts CandleViewer targets, and the lack of the primitives/multi-pane chassis Lightweight Charts already provides.

### Plotly.js

- **What it is**: A broad, general-purpose charting library (D3/SVG plus optional WebGL for some traces) with candlestick/OHLC support.
- **Assessment**: Consistent with the "too slow" characterization in the research brief — Plotly's SVG-heavy default rendering and heavier bundle/runtime overhead make it a poor fit for 100k+-bar interactive charts or a 10Hz-updating heatmap; its strengths (rich statistical/scientific chart types, easy Python/Dash integration) are not the bottleneck CandleViewer needs solved.
- **Verdict**: Not recommended for the core order-flow chart. Could conceivably be reused on the Python/Dash side for a quick internal analytics/backtest-report view, but not for the live React trading UI.

### Chart.js + chartjs-chart-financial

- **What it is**: Chart.js (Canvas 2D, MIT) plus the community `chartjs-chart-financial` plugin adding candlestick/OHLC series types.
- **Assessment**: Chart.js is a general-purpose, dashboard-oriented chart library; the financial plugin is a thin bolt-on rather than a purpose-built trading-chart chassis — no native multi-pane time-scale sync, no primitives system, and no precedent for order-flow-density rendering (footprint/heatmap) built on top of it in the wild.
- **Verdict**: Not recommended. Weaker fit than Lightweight Charts, KlineCharts, or a custom-heatmap-on-Lightweight-Charts approach, with no compensating advantage.

### kline-orderbook-chart (new candidate — added on review)

- **What it is**: A canvas-based charting library ([github.com/PhamNhinh/kline-orderbook-chart](https://github.com/PhamNhinh/kline-orderbook-chart), also mirrored/republished under a `tapedelta` org and marketed at [tapedelta.com/chart-library](https://tapedelta.com/chart-library), npm package `kline-orderbook-chart`) advertised as "the only chart library with built-in orderbook heatmap, footprint chart, and liquidation heatmap all in one `<canvas>`," framework-agnostic (React/Vue/Svelte/Angular/vanilla), zero dependencies. Created April 2026, ~18 GitHub stars, 47 commits, npm package at v1.6.2 as of the jsDelivr snapshot checked.
- **Claimed features**: orderbook depth heatmap behind candles (`setHeatmap()`/`appendHeatmapColumn()` API, walls/color schemes), footprint chart (bid/ask volume, delta, imbalance detection, VRVP profile), liquidation heatmap (estimated leveraged-position cluster overlay), large-trade bubbles, DOM ladder, TPO/market profile, CVD, 12+ indicators, bar replay — i.e., essentially the full DeepCharts feature list CandleViewer needs, in one package.
- **Claimed performance**: benchmark tables in the README claim 60fps+ sustained at 100K candles, "peak FPS" figures in the tens of thousands, and heatmap updates near 6,000 fps, attributed to a "native high-performance engine" and (in some published variants of the README) a WebAssembly/Rust core with GPUI/wgpu/Skia native targets alongside the web build.
- **Maturity/credibility assessment — significant reservations**: several signals in this specific package warrant real caution before treating it as a viable dependency:
  - The project is very young (created ~5 months before this research pass) with a low star count (18) relative to the sweeping claims made in its README (a from-scratch WASM/native engine matching or beating years-mature commercial libraries like LightningChart).
  - The README/marketing text reads as heavily SEO/keyword-stuffed (long repeated lists of search terms like "orderbook heatmap chart · kline heatmap · candlestick orderbook depth..." appended to the bottom of the page) and the benchmark numbers are self-reported with no independent reproduction found; no third-party review, blog post, Show-HN discussion, or Stack Overflow usage was found referencing this specific library.
  - The same content appears duplicated near-verbatim across at least two different GitHub identities/orgs (`PhamNhinh/kline-orderbook-chart` and `tapedelta/kline-orderbook-chart`) with an associated commercial site (`tapedelta.com`) offering a "30-day free trial" and paid tiers for what the npm/GitHub README frames as an open-source, "zero dependencies" library — this is inconsistent packaging (genuinely free OSS libraries don't normally need a "Get Started — try every feature free for 30 days" commercial funnel) and is a red flag for a bait-and-license or source-available-with-a-catch model rather than a straightforward MIT/Apache library.
  - The specific "one engine, two targets" framing (same engine rendering identically to web canvas and to a native Rust/GPUI/wgpu/Zed-editor-adjacent target) and keyword list mentioning "zed gpui chart" is an unusual and oddly specific combination of buzzwords for an 18-star, 5-month-old repo, further suggesting marketing-driven padding over substantiated engineering claims.
  - **Recommendation**: do not adopt this library sight-unseen based on its README claims. If pursued at all, treat as a "spike and verify" candidate only: check the actual LICENSE file terms (the repo shows "View license" without the exact license name surfaced in search), attempt the claimed benchmark independently on real Bybit data, and specifically verify the commercial tapedelta.com relationship and whether the "free" npm package is a crippled/watermarked version of a paid product before making an architecture decision around it. Given the reservations above, this report's core conclusion is **not** changed to "a candidate now offers native footprint+heatmap" — it should instead be read as "an unverified, low-maturity, marketing-heavy candidate exists and should be spiked cautiously before being trusted," which is a materially different and much more cautious conclusion than the critic's framing implied.

### ChartGPU (new candidate — added on review)

- **What it is**: An open-source (MIT), WebGPU-native charting library ([github.com/ChartGPU/ChartGPU](https://github.com/ChartGPU/ChartGPU), npm `@chartgpu/chartgpu`/`chartgpu`, v0.3.2–0.4.0 as of research time), TypeScript, zero runtime dependencies, with React bindings (`chartgpu-react`). Meaningfully more established than kline-orderbook-chart: ~3,211 GitHub stars, 707 commits, listed in "Awesome WebGPU," with its own docs site (chartgpu.io) and a dedicated architecture doc.
- **Series types**: line, area, bar, scatter (incl. density mode), pie/donut, **candlestick/OHLC**, uniform **heatmap**/spectrogram, band/range, error bars, impulse, plus 3D (`pointCloud3d`, `surface3d`) when using a `cartesian3d` coordinate system.
- **Relevance to Section 5 (Canvas vs WebGL vs WebGPU)**: ChartGPU is a concrete, reasonably mature counter-example to this report's earlier framing that WebGPU tooling is immature — it directly supports both candlestick and heatmap series types on a shared GPU device, which is architecturally interesting for CandleViewer's DOM heatmap requirement (its heatmap uses a dedicated `updateHeatmap()` incremental-update API rather than full redraws, matching the "sustained 100ms-cadence update" pattern CandleViewer needs). Its "Streaming multi-chart dashboards, shared GPUDevice/pipeline cache across charts" design also maps well onto CandleViewer's multi-pane/multi-chart-layout requirement.
- **Caveats**:
  - No fallback: "There is no WebGL/Canvas fallback. Unsupported browsers must be gated by the host app" — requires Chrome/Edge 113+ or Safari 18+; Firefox WebGPU support is flags/platform-dependent as of research time. For a self-hosted single-user/few-account-manager tool where the operator controls the browser, this is an acceptable constraint (unlike a public consumer product), but it must be a deliberate choice, not an oversight.
  - Still pre-1.0 (v0.3.x/v0.4.x) — API stability and long-term maintenance are unproven relative to Lightweight Charts' years of production hardening; no footprint-chart primitive exists (candlestick + heatmap are separate series types, not fused as a footprint grid), so the core footprint-cell rendering work is not solved by adopting ChartGPU any more than it is by Lightweight Charts.
  - No first-class multi-pane/time-scale-sync system as polished as Lightweight Charts v5, and no evidence found of production trading-platform usage to validate real-world robustness beyond its own demo/benchmark pages.
- **Verdict**: Worth a hands-on spike specifically for the DOM heatmap component (as an alternative to PixiJS/regl) given its purpose-built `heatmap` series and incremental-update API — this is a stronger, more specific WebGPU candidate than the report previously credited the WebGPU option with lacking. It does **not** change the report's core "chassis" recommendation (Lightweight Charts remains the base for candles/panes/primitives), but it upgrades the WebGPU option in the Canvas/WebGL/WebGPU decision from "not recommended, ecosystem too immature" to "a specific, watchable candidate for the heatmap sub-component, still second choice to a WebGL PixiJS/regl heatmap on maturity/risk grounds for a project this size, but worth a time-boxed comparative spike before committing to WebGL."

---

## Feature-by-feature deep dive

### Candlesticks at 100k+ bars

Lightweight Charts and KlineCharts both draw only the visible viewport each frame plus lightweight decimation, so raw candle rendering at 100k+ bars is a solved problem for either. uPlot and ECharts can technically render that many points but uPlot's own docs only qualitatively note it "may begin to struggle beyond 100k in-view points" without a stated FPS figure at that scale (*corrected: an earlier draft of this report cited a specific "~6 FPS at 100k candles" figure for uPlot that could not be verified against any primary uPlot source and has been retracted — see the uPlot candidate section and Open Questions*). Recommendation: Lightweight Charts for the base candle series; keep full history in a typed-array-backed store (not plain JS objects) so pushing new bars and slicing visible windows stays allocation-light.

### Footprint / order-flow cells

No candidate library has a native footprint series. Build it as a Lightweight Charts **custom series** (`ICustomSeriesPaneView`): each visible bar becomes a column of price-level cells; render backgrounds as filled rects and bid/ask numbers as `fillText` calls, gated behind a pixels-per-cell LOD threshold (e.g., skip per-cell text under ~10px cell height and instead draw only the delta-colored background, matching how DeepCharts/Bookmap/ATAS degrade footprint text at zoom-out). This is the single largest bespoke-rendering investment in the project; budget the majority of the "custom chart work" line item here.

### Volume & delta profiles

Session/composite volume profile (volume-at-price with POC/value-area) is a horizontal histogram anchored to the price axis — implementable as a **pane primitive** or a docked side-panel series that shares the main chart's price scale via Lightweight Charts' coordinate helpers. This is lower risk than footprint: cell count is bounded by price-bucket count (hundreds, not tens of thousands), so Canvas 2D is comfortably sufficient with no LOD tricks needed.

### Real-time DOM liquidity heatmap

The requirement (time x price x size, ~100ms cadence, minutes-to-hours of history) is the most performance-sensitive rendering surface in the whole app — potentially tens of thousands of cells refreshing 10x/second sustained over hours. This is the primary candidate for a bespoke WebGL layer (PixiJS or regl) rather than Canvas 2D: represent the heatmap as a rolling 2D texture (time columns x price rows) updated via `texSubImage2D` for only the newest column each tick, rendered as a textured quad synced to the main chart's price axis coordinates. Canvas 2D is a fallback if a WebGL prototype is deprioritized, but expect CPU pressure to grow with retained history depth in that case, whereas the WebGL/texture approach keeps update cost roughly constant regardless of retained depth.

### Big trade bubbles

Straightforward: markers/circles sized by trade notional, plotted at (time, price), with optional decay/fade animation. Implementable as a Lightweight Charts series primitive with simple hit-testing for tooltips. Low risk, low effort relative to footprint/heatmap.

### Multi-pane indicators

Lightweight Charts v5 and KlineCharts both support multiple resizable panes with independent price scales and a shared, synced time axis — this requirement is met by the base library chassis in either case, with custom indicator panes (VWAP, delta, imbalance, speed-of-tape) implemented as custom series/primitives or plain line series depending on complexity.

### Drawing tools

KlineCharts ships an out-of-the-box drawing-tools toolbar (trendlines, Fibonacci, shapes) via its overlay system. Lightweight Charts requires building this from primitives — more work, but full control, and the primitive interaction hooks (drag, hover, hitTest) are sufficient. Given Lightweight Charts is the recommended chassis for other reasons, plan for a dedicated 1-2 week sprint to build a small drawing-tools kit (trendline, horizontal/ray line, rectangle, Fibonacci retracement) as reusable primitives, rather than assuming KlineCharts' toolbar can simply be bolted onto a Lightweight-Charts-based app (the two libraries' overlay/primitive systems are not interchangeable).

### Chart trading (draggable order/position lines)

Best implemented as Lightweight Charts series primitives with drag interaction: a horizontal line at a price level, draggable vertically, snapping to tick size, emitting an event on drop that the order-management layer consumes to place/modify/cancel orders. KlineCharts' overlay drag-event model supports the same pattern. Either chassis handles this adequately; it is a moderate, well-understood effort either way (order lines are one of the more copied patterns in existing open-source trading-chart code, e.g., various lightweight-charts community plugins for order/position lines).

### DOM ladder

Not a chart at all — a virtualized vertical list of price rows (bid size | price | ask size), often with in-row quick-order buttons and current-price highlighting. This is a UI-virtualization problem (see the dedicated DOM ladder libraries section below), not a charting-library problem; none of the charting candidates above are relevant here.

### Multi-chart layouts

A workspace/docking-layout concern (arranging multiple chart+DOM+ladder panels, tabs, floating windows), independent of which charting library renders each panel's contents. See the Layout managers section below.

---

## Open-source footprint/heatmap projects to learn from

- **Flowsurface** ([flowsurface.com](https://flowsurface.com/)) — an open-source desktop crypto order-flow charting platform (Rust/Iced-based) with footprint charts, heatmaps, DOM, volume-profile overlays, and multi-exchange support (including Bybit). Not a React/web codebase, but its aggregation logic (footprint cell binning, heatmap decay, multi-exchange normalization) is directly reusable as a reference for the equivalent React/TypeScript implementation.
- **GitHub topic pages** aggregating related repos: [`footprint-chart`](https://github.com/topics/footprint-chart), [`footprint-charts`](https://github.com/topics/footprint-charts), [`market-profile`](https://github.com/topics/market-profile), [`order-flow`](https://github.com/topics/order-flow) — useful as a discovery starting point; quality and maintenance vary widely and each repo needs individual vetting before being treated as a reference implementation.
- **srl-ctrader-indicators** (`github.com/srlcarlg/srl-ctrader-indicators`) — C# cTrader indicators including Volume/TPO Profile, footprint candles, and Weis/Wyckoff cluster-volume analytics. Useful as an algorithm reference (footprint binning, delta/imbalance calculation logic) to port into a JS/TS aggregation layer, not as UI code.
- **OrderFlow-Analysis-Pro** (`github.com/mahmoud20138/OrderFlow-Analysis-Pro`) — Python/Dash dashboard with footprint charts, delta analytics, volume profile, and Bybit/MT5 WebSocket feeds. Useful reference for the Bybit-specific data-normalization and footprint-aggregation logic on the Python backend side of CandleViewer, given the backend is also Python.
- **quant-order-book** (`github.com/nssanta/quant-order-book`) — a JavaScript/React/Vite real-time crypto order-book heatmap with CVD (cumulative volume delta) across Binance/OKX/Bybit. The closest match among discovered projects to CandleViewer's own stack (React) for the DOM heatmap specifically; worth a direct code read for the heatmap rendering approach and Bybit WS integration pattern.
- **Tyumex trading terminal** (`github.com/Tyumex/tyumex-trading-terminal`) — Windows-native multi-chart terminal with order-flow footprint, cluster volume, and second-level candles across several exchanges/brokers (Binance, Hyperliquid, CME/MOEX, MT4/5). Useful as a broader "what a full trading terminal's feature surface looks like" reference, though not web-based.
- **Note on scarcity**: there is no dominant, widely-adopted, actively-maintained pure-React footprint/order-flow charting library as of research time. The common real-world pattern (confirmed across the above projects) is exactly what this report recommends: build custom overlays/series on top of a general-purpose financial charting library (most often TradingView's lightweight-charts in the JS/web ecosystem) and port footprint/aggregation algorithms from Rust/Python/C# reference implementations rather than expecting to find a ready-made React footprint component.

---

## Canvas vs WebGL vs WebGPU decision

- **Canvas 2D** — sufficient for: base candlesticks (via Lightweight Charts/KlineCharts' own optimized renderers), footprint cells at typical zoom levels (with LOD text-hiding), volume profile, trade bubbles, drawing tools, order lines, multi-pane indicator lines. Simpler to implement, easier to keep visually consistent with the rest of the chart (same context, same coordinate helpers), and Lightweight Charts' primitive system is built around Canvas 2D specifically — fighting that by mixing in WebGL for these components adds integration complexity without a clear performance payoff.
- **WebGL** — justified specifically for the real-time DOM liquidity heatmap, where cell counts x update frequency x retained history depth combine into a sustained high-throughput rendering workload that Canvas 2D handles adequately but not optimally over long sessions. PixiJS (higher-level, faster to build with) or regl (lower-level, more control over the exact texture/instancing strategy) are both reasonable; regl's more direct GPU control is preferable if the heatmap's specific rolling-texture-update pattern needs careful tuning for a 100ms cadence sustained over hours, while PixiJS is preferable if development speed matters more and the extra abstraction overhead is acceptable.
- **WebGPU** — still not the primary recommendation for CandleViewer, but the ecosystem is more capable than the report previously credited it with. *Corrected/expanded: the earlier draft asserted the WebGPU library ecosystem was uniformly immature; [ChartGPU](https://github.com/ChartGPU/ChartGPU) (MIT, ~3,200 stars, see new candidate section above) is a concrete, actively-developed, purpose-built WebGPU charting library with a dedicated incrementally-updatable `heatmap` series type and candlestick support, which is a materially better fit for a "just needs a fast heatmap" use case than general-purpose WebGPU scene-graph libraries.* That said, WebGPU is still second choice to WebGL (PixiJS/regl) for this project specifically because: (a) no-fallback browser gating (Chrome/Edge 113+, Safari 18+; Firefox inconsistent) is a real constraint even for a single-operator tool if any account manager uses an older/unsupported browser or Firefox; (b) ChartGPU is pre-1.0 with no evidence of production trading-platform usage, versus WebGL/PixiJS's much longer track record; (c) the performance ceiling WebGL already offers is more than sufficient for a single-user tool's data volumes (this is not a multi-thousand-user SaaS product where WebGPU's lower driver overhead at massive scale would matter). Recommendation: build the WebGL heatmap first (PixiJS/regl) as the primary path, but run a short time-boxed spike of ChartGPU's `heatmap`/`updateHeatmap()` API as a comparison point before finalizing, given it is now a genuinely viable, not just theoretical, alternative.

---

## OffscreenCanvas + Web Workers

For the heatmap and/or footprint rendering specifically, `OffscreenCanvas` transferred into a Web Worker allows the heaviest per-frame rendering work (texture updates, cell redraws) to run off the main thread, keeping the main thread free for React reconciliation, WebSocket message handling, and user interaction (drag order lines, pan/zoom the primary chart). This is a meaningful architecture decision specifically for the 100ms-cadence heatmap: without it, a burst of DOM updates competing with React re-renders on the main thread is a plausible source of jank during volatile market conditions — precisely when the heatmap matters most. Recommendation: prototype the WebGL heatmap directly inside an OffscreenCanvas-backed worker from the start rather than retrofitting it later, since transferring canvas control after the fact is more invasive than designing for it up front. Lightweight Charts itself runs on the main thread (it does not support OffscreenCanvas as of current versions), so the split would be: main-thread Lightweight Charts chart (candles/footprint/panes) + worker-thread WebGL heatmap canvas, visually composited via absolute positioning/z-index rather than a single shared canvas.

---

## WebSocket data pipeline: state management

- **Zustand** — centralized store with selector-based subscriptions; best when many components need to read from a shared, broad slice of state (e.g., "current symbol's full order book" consumed by both the DOM ladder and the heatmap). Requires careful selector design (`shallow` comparisons) to avoid over-triggering re-renders when only part of a shared object changes.
- **Jotai** — atomic state; each independently-updating value (per-price-level book depth, per-widget indicator value) is its own atom, and only components subscribed to that specific atom re-render on update. Best suited to CandleViewer's likely reality of many small, independently-updating values arriving at high frequency (order book deltas, tick prints, per-indicator recalculation) rather than one large shared blob — this is a stronger structural fit for a live trading UI than Zustand's single-store model, though both are viable and lightweight.
- **Valtio** — proxy-based, mutate-in-place ergonomics; conceptually similar performance profile to Zustand/Jotai for this use case, less commonly benchmarked head-to-head for trading-specific high-frequency workloads in available sources, so treat as a viable third option worth a quick spike rather than a primary recommendation absent direct evidence.
- **RxJS** — not a React state library per se, but valuable as the ingestion/transform layer between the raw Bybit WebSocket stream and whatever React state store is chosen: operators for buffering/throttling/batching high-frequency book-delta and trade-print streams (e.g., batch order-book deltas into one state update per animation frame via `bufferTime`/`requestAnimationFrame`-gated operators) are a natural fit and decouple "how fast Bybit sends data" from "how often React actually re-renders," which matters a great deal given the 100ms DOM heatmap cadence and even-higher-frequency raw book deltas.
- **Recommendation**: RxJS (or a hand-rolled equivalent using a simple batching queue) as the ingestion/throttling layer regardless of final store choice, feeding into **Jotai** for the bulk of independently-updating, per-symbol/per-widget live data (order book levels, tick prints, footprint cell deltas), with **Zustand** reserved for genuinely global/shared UI state (active symbol, active layout, connection status, user settings) that doesn't need atom-level granularity.

---

## Binary protocols over WebSocket

- **JSON** — simplest, but for a 100ms-cadence, potentially-thousands-of-price-levels order-book heatmap feed, JSON's text-parsing and larger payload size become a measurable tax at sustained high frequency, especially on lower-end client hardware.
- **MessagePack** — a drop-in binary serialization with a similar data model to JSON (arrays/maps/primitives) but smaller payloads and faster parse; a low-friction upgrade path if the initial implementation starts with JSON and later needs the win, since the client-side data shapes don't need to change, only the wire format.
- **Protobuf** — requires a schema and codegen step, which adds process overhead but gives the strongest payload-size and parse-speed guarantees, plus schema evolution discipline that benefits a project expected to add more exchanges/pane types over time. Given the Python backend, Protobuf's mature Python and TypeScript codegen tooling makes this a strong long-term choice if the team is willing to adopt schema-first development.
- **Apache Arrow** — best suited to columnar, bulk-analytical payloads (e.g., a large historical-bar backfill for the 100k+-candle chart, or a batch of footprint aggregation data) rather than per-tick real-time streaming, where its columnar layout and JS bindings (`apache-arrow` npm package) genuinely shine for large one-shot transfers; less clearly beneficial for small, frequent, per-message deltas where the framing/schema overhead of Arrow's IPC format is proportionally larger.
- **Recommendation**: start with JSON for correctness and iteration speed during the research/prototype phase (this document's scope), but design the WebSocket message envelope so a binary codec can be swapped in later without a client-side rewrite (i.e., don't couple business logic to "the message is a JSON object" — decode into typed internal structures immediately at the ingestion boundary). If/when a prototype shows JSON parsing is a measured bottleneck, MessagePack is the lowest-effort upgrade; reserve Protobuf for if/when schema discipline and multi-exchange expansion become a bigger priority than migration speed; reserve Arrow specifically for bulk historical-data transfer (backfilling 100k+ bars on chart load or symbol switch), not live tick/book streaming.

---

## Virtualized DOM ladder libraries

The DOM ladder is a tall, densely-updating virtualized list (one row per price tick across the visible price range), not a chart. General-purpose React virtualization libraries — `react-window` / `react-virtualized` (row-based windowing) or `@tanstack/react-virtual` (headless, more modern, actively maintained, framework-agnostic core with React bindings) — are the right building block, combined with a very tight render path per row (memoized row components, primitive props only, avoiding new-object-per-render props that defeat memoization) given rows can update at high frequency during volatile markets. `@tanstack/react-virtual` is the more actively maintained and lower-overhead option among these as of research time and is the recommended starting point; it does not include any trading-specific behavior (price formatting, click-to-trade, imbalance coloring) which must be built as thin row-renderer components on top.

---

## Hotkey libraries

`react-hotkeys-hook` is a lightweight, actively-maintained React hook for keyboard shortcuts (order-entry hotkeys, chart-tool shortcuts, layout switching) and is an appropriate default choice — small API surface, scoped-binding support (important so hotkeys don't fire across the wrong panel in a multi-chart layout), and no dependency baggage beyond React itself. No strong reason to consider heavier alternatives (e.g., Mousetrap-based wrappers) for a project of this scope.

---

## Layout managers (multi-chart/multi-pane workspace)

- **Dockview** ([GitHub](https://github.com/dockview/dockview), [dockview.dev](https://dockview.dev/)) — zero-dependency, framework-agnostic (React/Vue/Angular/vanilla TS) docking layout manager supporting tabs, groups, grids, splitviews, floating panels, and popout windows; modern TypeScript codebase; roughly 3,400+ GitHub stars and 240k+ weekly npm downloads at research time. Actively maintained and the most "modern" of the three options surveyed.
- **FlexLayout** ([GitHub: caplin/FlexLayout](https://github.com/caplin/FlexLayout)) — React-only, JSON-driven layout state model, tabsets, tab groups, border tabsets, popouts, overflow handling, theming, accessibility support; roughly 1,300+ stars, 100k+ weekly downloads. Notably built/maintained by Caplin, a company with a real financial-trading-software background, which is a soft signal of fitness for this exact domain.
- **Golden Layout** ([golden-layout.com](https://golden-layout.com/), [GitHub](https://github.com/golden-layout/golden-layout)) — the historical "gold standard" for web-IDE-style multi-window layouts; mature (~6,700+ stars) but comparatively heavier to configure for a modern React app, with a DOM-manipulation-first model rather than a React-idiomatic one; best suited to migrations of legacy Golden-Layout-based codebases rather than new React builds.
- **react-grid-layout** — a simpler drag/resize CSS-grid-based layout tool, better suited to dashboard-style widget arrangement than IDE-style docking/tabbing/popout workflows; not evaluated as a strong fit here given CandleViewer's stated need for multi-chart layouts resembling a trading terminal (closer to Dockview/FlexLayout's target use case) rather than a rearrangeable-widgets dashboard.
- **Recommendation**: **Dockview** as the primary pick given its zero-dependency footprint, active maintenance, and full feature set (popout windows are specifically valuable for a multi-monitor trading setup); **FlexLayout** as a strong alternative if the team prefers its JSON-first state model or values its financial-industry pedigree (Caplin) more than Dockview's broader framework-agnosticism, which is not a relevant advantage for a React-only app anyway.

---

## UI kits

- **Mantine** — a full-featured component library (100+ components, built-in dark mode, forms, notifications, hooks) with good density/data-table support suited to a trading UI's information-dense panels; more opinionated and heavier than shadcn/Radix but faster to build a complete admin-style surface (settings, order tickets, journal views) with less custom styling work.
- **shadcn/ui + Radix** — not a component *library* but a copy-into-your-repo pattern over Radix's unstyled, accessible primitives plus Tailwind for styling; maximal control over visual density and behavior (important for a DOM ladder's tight row spacing and a chart-trading UI's precise interaction affordances), at the cost of more manual assembly work per component compared to Mantine's batteries-included approach.
- **Recommendation**: shadcn/ui + Radix + Tailwind for the core trading surface (DOM ladder, order tickets, chart toolbars) where pixel-level control over density and interaction matters most, with Mantine's ready-made components (or an equivalent) acceptable for lower-stakes surfaces (settings screens, the journal/analytics views) if development speed there matters more than visual customization. Both are permissively licensed (MIT) and impose no constraint relative to each other beyond this build-speed-vs-control tradeoff.

---

## Desktop wrap: Tauri vs Electron

Given CandleViewer is explicitly a private, self-hosted, single-user-plus-a-few tool (not a public web product), a desktop wrapper is a reasonable way to package it for the primary user's daily-driver trading setup.

- **Tauri**: leverages the OS's native WebView plus a lightweight Rust backend rather than bundling a full Chromium+Node runtime. Idle memory usage in current comparisons runs roughly 15-50MB (some simple-app benchmarks cite figures as low as ~12MB), versus Electron's roughly 150-300MB for comparable apps — a 3-5x memory advantage. Produces smaller binaries and (generally) faster startup.
- **Electron**: bundles a full Chromium browser and Node.js runtime with every app, which is the source of its larger memory/binary footprint, but offers a more mature, battle-tested ecosystem, more predictable rendering behavior across OS versions (since it ships its own browser engine rather than relying on the OS-provided WebView, which can vary in capability/bugs across Windows/macOS/Linux), and a much larger base of prior art for embedding complex web apps.
- **Consideration specific to CandleViewer**: a heavy Canvas2D/WebGL-based order-flow chart with a 100ms-cadence heatmap is exactly the kind of workload where WebView inconsistencies (Tauri relies on the OS WebView — WebView2 on Windows, WebKit on macOS/Linux) could introduce platform-specific rendering quirks or performance differences that Electron's consistent bundled Chromium avoids. Since the project runs primarily on one user's machine (with WSL Ubuntu mentioned as an option for the backend), and Windows-plus-WebView2 is a mature, Chromium-based WebView on the most likely primary OS, this risk is manageable but should be explicitly verified early (a rendering/performance smoke test of the actual heatmap prototype inside a Tauri shell) rather than assumed away.
- **Recommendation**: Tauri as the default choice given the strong memory/footprint advantage for a tool that may run alongside other resource-hungry software (the Python backend, possibly WSL, other trading tools) on the same machine, with the caveat that the WebGL heatmap's behavior inside Tauri's WebView2 (on Windows) should be smoke-tested early in implementation, not deferred — if it shows problems, falling back to Electron remains a low-regret option since the underlying web app code is unaffected by which shell wraps it.

---

## Decision matrix

| Technology | Candlesticks 100k+ | Footprint (native) | Heatmap (native) | Multi-pane | Drawing tools | Chart trading | License | Cost | Effort to reach MVP |
|---|---|---|---|---|---|---|---|---|---|
| **Lightweight Charts v5** | Excellent | No (build via custom series) | No (build via primitive/WebGL) | Yes (native) | No (build via primitives) | Buildable via primitives | Apache-2.0 + attribution | Free | Medium |
| **TradingView Advanced Charts** | Excellent | No | No | Yes (native, richer) | Yes (native) | Buildable | Proprietary, approval required | Free (gated) | Medium (+approval delay) |
| **KlineCharts v10** | Good | No | No | Yes (native) | Yes (native) | Buildable via overlays | Apache-2.0 | Free | Medium |
| **react-financial-charts** | Fair (unmaintained) | No | No | Limited | No | Difficult | MIT | Free | High (fighting stale lib) |
| **Highcharts Stock** | Fair (SVG-bound) | No | No | Yes | Some (annotations) | Difficult | Commercial | $$ | Medium-High |
| **SciChart.js** | Excellent (WebGL) | No | Yes (native 2D heatmap) | Yes | No | Difficult (not trading-native) | Commercial | $$ (per-dev/mo) | High (no trading chassis) |
| **LightningChart JS Trader** | Excellent (WebGL) | No | Yes (native) | Yes | Some | Some (trading-oriented) | Commercial | $$$ (per-dev/yr) | Medium-High |
| **Apache ECharts** | Good | No (via renderItem) | Yes (native, not real-time-tuned) | Yes | No | Difficult | Apache-2.0 | Free | Medium (auxiliary panes only) |
| **D3 + custom Canvas** | Buildable | Buildable | Buildable | Buildable | Buildable | Buildable | Free (D3 BSD/ISC) | Free | Very High (build everything) |
| **PixiJS/regl custom** | N/A (not for candles) | Possible | Excellent (targeted use) | N/A | N/A | N/A | MIT | Free | High for heatmap only |
| **Perspective (FINOS)** | N/A | N/A | N/A (data layer, not visual heatmap) | N/A | N/A | N/A | Apache-2.0 | Free | Medium (DOM/stats data layer) |
| **uPlot** | Good (FPS drops at 100k) | No | No | No (single chart) | No | Difficult | MIT | Free | Low for simple panes only |
| **Plotly.js** | Poor (too slow) | No | No | Yes | Some | Difficult | MIT | Free | N/A (not recommended) |
| **Chart.js + financial** | Fair | No | No | Limited | No | Difficult | MIT | Free | N/A (not recommended) |

---

## Recommended approach

**Primary approach**: TradingView Lightweight Charts v5 as the core chassis (candlesticks, multi-pane, crosshair, time scale, chart trading via primitives, drawing tools via primitives, footprint via custom series with LOD text-hiding, volume profile via pane primitive), paired with a **dedicated WebGL layer (PixiJS or regl) inside an OffscreenCanvas/Web-Worker** specifically for the real-time DOM liquidity heatmap, visually composited underneath/behind the Lightweight Charts canvas. Data pipeline: RxJS-style batching/throttling at the WebSocket ingestion boundary feeding Jotai atoms for high-frequency per-symbol/per-level state and Zustand for global UI state; JSON wire format initially with MessagePack as the identified upgrade path if profiling shows it's needed. DOM ladder built on `@tanstack/react-virtual`. Layout via Dockview. UI via shadcn/ui + Radix + Tailwind for the trading surface. Packaged as a Tauri desktop app, with an early smoke test of the WebGL heatmap inside Tauri's WebView2 shell to de-risk the one identified platform-compatibility unknown.

**Fallback approach**: If a 1-2 week spike shows Lightweight Charts' primitives API is too constraining for the footprint/heatmap work specifically (e.g., text-rendering performance in Canvas 2D proves worse than expected even with LOD), fall back to either (a) KlineCharts as the chassis instead, given its friendlier overlay/drawing-tools authoring model, or (b) LightningChart JS Trader as a paid, trading-native, WebGL-first chassis that natively solves the heatmap and gives a stronger performance ceiling for footprint-as-custom-series too, accepting the ~$4,900/year cost as the price of de-risking the hardest rendering problem in the project. Do not pursue TradingView Advanced Charts (licensing friction disproportionate to benefit for a private tool) or a from-scratch D3+Canvas chassis (reinvents work Lightweight Charts already solved well) except as a last resort.

---

## Effort estimate: custom engine vs extending Lightweight Charts

This is a rough, directional estimate for a single experienced full-stack/frontend developer (or a small 1-2 person team), intended to inform planning, not a committed schedule.

**Extending Lightweight Charts v5 via primitives (recommended path)**:
- Base chart integration (candles, time scale, panes, symbol/timeframe switching): 3-5 days.
- Footprint custom series (cell rendering, LOD text-hiding, delta/imbalance coloring, bar-to-cell data binding): 2-3 weeks — the single largest line item, given the density of interactive detail (per-cell hit-testing for tooltips, correct handling of partial/incomplete bars during live trading, correct behavior under tick-replay/backtest mode as well as live mode).
- Volume/delta profile pane: 3-5 days.
- Drawing-tools primitive kit (trendline, ray, rectangle, Fibonacci, horizontal line): 1-2 weeks for a reasonably complete starter set, with more tools addable incrementally later.
- Chart-trading order/position lines (draggable primitives, tick-snapping, order-management integration): 1 week for the rendering/interaction piece (excludes the backend order-management logic itself, which is out of scope for this report).
- Big-trade bubbles, VWAP/indicator overlays: 3-5 days combined, being relatively simple marker/line primitives.
- **Subtotal for the Lightweight-Charts-based chassis and its custom pieces (excluding heatmap and DOM ladder)**: roughly 6-9 weeks of focused work for one developer, before integration/testing time and before backend data-plumbing work.

**Real-time DOM liquidity heatmap (WebGL layer)**: 2-4 weeks — texture/instancing strategy design and tuning, OffscreenCanvas/worker wiring, coordinate-system sync with the main chart's price axis, retained-history ring-buffer management, and performance validation against the 100ms-cadence/hours-of-history target specifically (this is the step most likely to require iteration once real load-testing begins).

**DOM ladder**: 1-2 weeks on top of the virtualization library, for trading-specific behavior (click-to-trade, price-tick alignment, imbalance/size coloring, quick-order buttons).

**Total rough estimate for the full custom-rendering surface** (footprint, volume profile, drawing tools, chart trading, bubbles, heatmap, DOM ladder), on top of the free Lightweight Charts base chassis: **roughly 11-17 weeks** of one experienced developer's focused effort, before backend integration, multi-exchange abstraction work, or the non-charting parts of the platform (paper trading, rule-based stops, journal, etc.) which are out of this report's scope.

**Fully custom D3/Canvas or raw-WebGL engine built from zero** (i.e., not using Lightweight Charts or any other chassis at all): add an estimated **4-8 additional weeks** on top of the above just to reach parity with what Lightweight Charts already provides for free (smooth pan/zoom with momentum, correct time-axis label formatting/decimation across zoom levels, multi-pane resize/sync, crosshair-sync across panes, device-pixel-ratio-correct rendering) — before any order-flow-specific feature exists. Given this project is scoped as a private, resource-constrained (one main developer implied) research-then-build effort, this additional cost is very unlikely to be justified: Lightweight Charts' primitives API already provides Canvas 2D access with the coordinate-mapping/DPI work done, meaning the "build it yourself" tax is avoided precisely in the areas (pan/zoom, axes, DPI-correctness) that are the least interesting and most time-consuming to get right from scratch, while still leaving full creative control over the genuinely novel parts (footprint, heatmap) that actually differentiate the product. Recommendation: do not build a fully custom chart engine; extend Lightweight Charts and reserve from-scratch WebGL work solely for the heatmap, where it is specifically justified.

---

## Sources

- [Custom Series and Primitives — tradingview/lightweight-charts (DeepWiki)](https://deepwiki.com/tradingview/lightweight-charts/6.2-custom-series-and-primitives)
- [Plugin and Extension System — tradingview/lightweight-charts (DeepWiki)](https://deepwiki.com/tradingview/lightweight-charts/2.4-plugin-and-extension-system)
- [Lightweight Charts series primitives documentation (GitHub)](https://github.com/tradingview/lightweight-charts/blob/master/website/docs/plugins/series-primitives.mdx)
- [Lightweight Charts plugins intro/architecture (GitHub)](https://github.com/tradingview/lightweight-charts/blob/master/website/docs/plugins/intro.md)
- [Getting started | Lightweight Charts docs (v4.1, license/attribution)](https://tradingview.github.io/lightweight-charts/docs/4.1)
- [Get started | TradingView Advanced Charts Documentation](https://www.tradingview.com/charting-library-docs/latest/quick-start/)
- [Terms of Service and Company Policy — TradingView](https://www.tradingview.com/policies/)
- [Free Charting Library by TradingView](https://www.tradingview.com/free-charting-libraries/)
- [KlineCharts: From 9.x to 10.x upgrade guide](https://klinecharts.com/en-US/guide/v9-to-v10)
- [KlineCharts Overlay guide](https://klinecharts.com/en-US/guide/overlay)
- [Indicators — klinecharts/KLineChart (DeepWiki)](https://deepwiki.com/klinecharts/KLineChart/4.1-indicators)
- [Overlays — klinecharts/KLineChart (DeepWiki)](https://deepwiki.com/klinecharts/KLineChart/4.2-overlays)
- [GitHub - klinecharts/extension](https://github.com/klinecharts/extension)
- [React Financial Charts — GitHub](https://github.com/react-financial/react-financial-charts)
- [react-financial-charts — npm](https://www.npmjs.com/package/react-financial-charts?activeTab=code)
- [SciChart.js Licensing](https://www.scichart.com/licensing-scichart-js/)
- [Community Licensing SciChart.js](https://www.scichart.com/community-licensing/)
- [Get Started for Free | SciChart JS Docs](https://www.scichart.com/documentation/js/v4/user-manual/licensing-scichart-js/getting-started-for-free/)
- [SciChart.js Reviews and Pricing 2026 | F6S](https://www.f6s.com/software/scichart-js)
- [LightningChart Pricing for JS — xlsoft](https://www.xlsoft.com/en/products/lightningchart/price-js.html)
- [LightningChart JS Trader Prices — ComponentSource](https://www.componentsource.com/product/lightningchart-js-trader/prices)
- [LightningChart JS Prices — ComponentSource](https://www.componentsource.com/product/lightningchart-js/prices)
- [Heatmaps | LightningChart JS Trader Documentation](https://lightningchart.com/js-charts/trader/docs/heatmaps/)
- [GitHub - leeoniya/uPlot](https://github.com/leeoniya/uPlot)
- [Fastest Chart Libraries for Quantitative Analysis & Quant Finance — SciChart blog](https://www.scichart.com/blog/fastest-chart-libraries-for-quantitative-analysis/)
- [Performance | leeoniya/uPlot (DeepWiki)](https://deepwiki.com/leeoniya/uPlot/8-performance)
- [GitHub - will-march/chart-benchmark](https://github.com/will-march/chart-benchmark)
- [Performance Comparison of JavaScript Chart Libraries in 2026 — SciChart blog](https://www.scichart.com/blog/chart-bench-compare-javascript-chart-libraries/)
- [Flowsurface — Open Source Crypto Orderflow](https://flowsurface.com/)
- [GitHub topic: footprint-chart](https://github.com/topics/footprint-chart)
- [GitHub topic: footprint-charts](https://github.com/topics/footprint-charts)
- [GitHub topic: market-profile](https://github.com/topics/market-profile)
- [GitHub topic: order-flow](https://github.com/topics/order-flow)
- [srl-ctrader-indicators — GitHub](https://github.com/srlcarlg/srl-ctrader-indicators)
- [OrderFlow-Analysis-Pro — GitHub](https://github.com/mahmoud20138/OrderFlow-Analysis-Pro)
- [quant-order-book — GitHub](https://github.com/nssanta/quant-order-book)
- [Tyumex trading terminal — GitHub](https://github.com/Tyumex/tyumex-trading-terminal)
- [GitHub - dockview/dockview](https://github.com/dockview/dockview)
- [Dockview — dockview.dev](https://dockview.dev/)
- [The Best Modern Alternatives to Golden Layout for 2026](https://portalzine.de/docker-layouts-with-goldenlayout/)
- [GitHub - caplin/FlexLayout](https://github.com/caplin/FlexLayout)
- [GoldenLayout — golden-layout.com](https://golden-layout.com/)
- [Comparing Electron and Tauri for Desktop Applications](https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/)
- [Tauri vs Electron: Desktop App Framework Performance and Security](https://markaicode.com/vs/tauri-vs-electron/)
- [Tauri vs. Electron: The Ultimate Desktop Framework Comparison](https://peerlist.io/jagss/articles/tauri-vs-electron-a-deep-technical-comparison)
- [Jotai vs Zustand: Which React State Library is Better?](https://zignuts.com/blog/jotai-vs-zustand-react-state-guide)
- [Zustand vs Jotai: Choosing the Right State Manager for Your React App](https://blog.openreplay.com/zustand-jotai-react-state-manager/)
- [Atomic State Management in React: Zustand vs Jotai vs Recoil](https://dev.to/taronvardanyan/atomic-state-management-in-react-zustand-vs-jotai-vs-recoil-j5p)
- [GitHub - PhamNhinh/kline-orderbook-chart](https://github.com/PhamNhinh/kline-orderbook-chart)
- [tapedelta/kline-orderbook-chart README (mirror)](https://github.com/tapedelta/kline-orderbook-chart/blob/main/README.md)
- [Tape Delta — kline-orderbook-chart product page](https://tapedelta.com/chart-library)
- [kline-orderbook-chart — jsDelivr package page](https://www.jsdelivr.com/package/npm/kline-orderbook-chart)
- [GitHub - ChartGPU/ChartGPU](https://github.com/ChartGPU/ChartGPU)
- [chartgpu — npm](https://www.npmjs.com/package/chartgpu)
- [ChartGPU homepage/docs](https://chartgpu.io/)
- [lightweight-charts — npm (v5.2.1, current version confirmed at research time)](https://www.npmjs.com/package/lightweight-charts)
- [lightweight-charts NOTICE file (master branch, verbatim text checked)](https://github.com/tradingview/lightweight-charts/blob/master/NOTICE)
- [GitHub - ukorvl/lightweight-charts-react-components](https://github.com/ukorvl/lightweight-charts-react-components)
- [lightweight-charts-react-components — npm](https://www.npmjs.com/package/lightweight-charts-react-components)
- [Frequently Asked Questions | TradingView Advanced Charts Documentation (Pine Script not supported, Advanced Charts vs Trading Platform distinction)](https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions)
- [uPlot README — leeoniya/uPlot (GitHub, verbatim performance claims re-checked)](https://github.com/leeoniya/uPlot#readme)
- [LightningChart JS Pricing page (current, quote-gated for Trader)](https://lightningchart.com/js-charts/pricing)
- [LightningChart JS Trader product page](https://lightningchart.com/js-charts/trader)

---

## Open questions

1. **Primitives-vs-custom-series footprint performance headroom**: no source found benchmarks Lightweight Charts v5's custom-series/primitives API specifically for a dense, per-cell-text-labeled footprint grid at realistic bar counts (hundreds of visible bars x dozens of price levels x live updates) — this needs a hands-on spike rather than relying on general Lightweight-Charts candle-rendering benchmarks, which don't exercise the text-heavy footprint workload.
2. **Tauri WebView2 behavior for a WebGL heatmap under sustained 100ms updates**: general Tauri-vs-Electron memory/performance comparisons were found, but nothing specific to a WebGL-heavy, high-frequency-updating canvas inside Tauri's WebView2 shell on Windows — flagged above as something to smoke-test early rather than assume.
3. **Exact TradingView Lightweight Charts v5 multi-pane API stability and any remaining limitations** (e.g., independent time-scale offsets per pane, if ever needed) were not verified against the live v5 changelog/migration notes in this pass — worth a direct read of the current release notes before implementation starts, since "v5 added multi-pane" was confirmed but its exact feature completeness was not exhaustively verified against the latest patch release.
4. **Highcharts Stock's exact license terms for CandleViewer's specific ownership/usage model** (private tool, used by the owner plus a few account managers who may or may not be considered "internal business use") were not definitively resolved — moot given Highcharts was not recommended, but should be revisited if requirements change.
5. **Perspective (FINOS) integration specifics for a Bybit L2 order-book feed** — its general suitability for streaming tabular aggregation was established, but no concrete example of wiring Perspective specifically to a crypto exchange L2 book feed (Bybit or otherwise) was found; this would need a dedicated spike before committing to it for the DOM ladder's data layer.
6. **Binary protocol codegen tooling maturity for a Python backend + TypeScript frontend pairing specifically** (Protobuf vs MessagePack developer-experience comparison in that exact stack combination) was not directly researched in this pass — the recommendation to defer this decision until profiling shows a need stands regardless, but the actual tooling comparison should be revisited if/when that need arises.
7. **DeepGamma-equivalent (options/gamma exposure) pane requirements** were explicitly out of scope for crypto-only v1 per the project brief, and were not researched here — flagged so it isn't forgotten if a later phase adds options data.
8. **Community footprint-on-Canvas FPS benchmarks**: a targeted search for open-source footprint-chart-on-Lightweight-Charts prototypes with published FPS/performance numbers did not surface any public benchmark specifically measuring text-heavy footprint-cell rendering (as opposed to plain candle rendering) at realistic cell densities — this remains the report's single largest unresolved engineering-risk question (see item 1) and still requires a hands-on spike; no shortcut via an existing public benchmark was found.
9. **kline-orderbook-chart exact license terms and the tapedelta.com commercial relationship**: the repository shows "License: View license" without the license name surfaced in search results, and its relationship to the paid tapedelta.com product (same README content, "30-day free trial" funnel) was not resolved — do not budget on this being a free/OSS dependency without reading the actual LICENSE file and clarifying the free-vs-paid feature split directly.
10. **LightningChart JS Trader's exact current first-party subscription price**: LightningChart's own pricing/product pages are now quote-gated for Trader rather than publishing fixed dollar figures; the previously-cited ~$4,900/$980 figures are third-party reseller quotes (ComponentSource/xlsoft) that could not be reconfirmed on lightningchart.com directly in this pass — get a direct sales quote before budgeting.
