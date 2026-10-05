# E08-Q02 coverage of the E08-Q01 black-box plan

Source: `qa/plans/e08-market-data-test-plan.md`. Every case whose owner column names `E08-Q02`
is either implemented here (the test's docstring cites the `E08-TC-*` id) or listed below as
deferred. `test_contract_q01_mapping.py` fails if an owned id is in neither place, or in both.

Browser/client halves (`E08-Q05`) are out of scope; the server half is covered where noted.

## Deferred

Rows are parsed by the meta-test: keep the `| E08-TC-XNN | deferred -> #ticket | reason |` shape.

| Case       | Status            | Reason                                                                     |
| ---------- | ----------------- | -------------------------------------------------------------------------- |
| E08-TC-C07 | deferred -> #1878 | needs the WS `sub ticker` topic-scoped error (limit 40): WS gateway is E17 |
| E08-TC-D02 | deferred -> #1878 | needs WS `trades.{symbol}` `TradesBatch` frames: WS gateway is E17         |
| E08-TC-E05 | deferred -> #1878 | needs WS `resync {last_seq}` handling: WS gateway is E17                   |
| E08-TC-E07 | deferred -> #1878 | needs WS `book.{symbol}.{depth}` tier change: WS gateway is E17            |
| E08-TC-E08 | deferred -> #1878 | needs `snap` `meta.reason=instrument_revision` over WS: gateway is E17     |
| E08-TC-F02 | deferred -> #1878 | needs `GET /market/data-coverage`, which does not exist yet                |

## Partial implementations (adapter/REST half only)

- D04: gap counter, backfill rows and oracle equality are asserted; the `/market/data-coverage` and
  tape-panel halves follow with #1878.
- E01/E02/E06: adapter and engine level (`BookSnapshot`/`BookDelta`, `BookEngine`) plus the REST
  read surface; the WS `snap`/`d` framing follows with #1878.
- A08/B01/B04/B07: server half; the client re-validation is E08-Q05.
