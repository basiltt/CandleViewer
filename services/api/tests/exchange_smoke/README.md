# `exchange_smoke` - demo connectivity smoke suite (E08-T05)

Proves real connectivity to Bybit **demo**. It covers the instrument catalogue, the server-time
offset, one kline page, a public WS subscribe/receive for trades, tickers and the order book,
and a clean shutdown.

```bash
cd services/api
CV_EXCHANGE_SMOKE=1 uv run pytest tests/exchange_smoke -m exchange_smoke --no-cov
```

## The demo-only guard (`_guard.py`)

- **Opt-in.** Without `CV_EXCHANGE_SMOKE=1`, every test is skipped. The default CI py lane
  also runs `-m "not exchange_smoke"`, so it never selects them.
- **Demo-only, fail closed.** Before any socket opens, the session aborts with
  `SmokeGuardError` in any of these cases:
  - `CV_ENVIRONMENT`, `CV_SMOKE_ENV` or `CV_BYBIT_ENV` is set to anything other than `demo`.
  - `CV_BYBIT_REST_BASE_URL` is not `https://api-demo.bybit.com`.
  - Any `CV_BYBIT*` value names a live host.
- **No credentials.** The run is refused if any `CV_*API_KEY` / `CV_*API_SECRET` is set. The
  suite only calls unauthenticated endpoints.
- **Network guard.** After the guard passes, only the resolved IPs of `api-demo.bybit.com` and
  `stream.bybit.com` are added to the test network allow-list. Demo has no public stream of its
  own (C-2.11).

`tests/unit/fixtures_corpus/test_smoke_guard.py` holds the negative tests. It runs in the
default lane.
