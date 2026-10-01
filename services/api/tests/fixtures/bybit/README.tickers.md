`tickers_BTCUSDT.jsonl`: assembled from the Bybit v5 `tickers.{symbol}` documented shape
(docs/plan/24-internal-schemas.md section 2.3), env=live public, symbol BTCUSDT, no credentials or ids.
NOT a live capture: replace with a recorder capture once E16 lands.

Perf (measured, E08-S03): 50 symbols x 20 frames through TickerStream.handle_frame (merge+bus publish): p95 = 0.55 ms (budget 20 ms); see test_ingest_to_bus_latency_50_symbols_measured.
