`publicTrade_BTCUSDT.jsonl` / `recent_trade_BTCUSDT.json`: assembled from the Bybit v5 `publicTrade.{symbol}`
and `GET /v5/market/recent-trade` documented shapes (docs/plan/24-internal-schemas.md section 2.1), env=live
public, symbol BTCUSDT; trade ids are synthetic UUIDs, no credentials/UIDs. NOT a live capture: replace with a
recorder capture once E16 lands. Taker-side semantics: `S`/`side` = "Buy" means the taker lifted the ask
(trade id ...0001 is a taker buy at 63120.50; ...0002 a taker sell at 63120.40).
Scenario: frames 1-2 live, reconnect, frame 3 live; the REST page covers ids 0001,0003-0007 (0001/0003/0007
overlap live; 0004-0006 fill the gap).
