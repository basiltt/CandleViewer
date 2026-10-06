# E12-K01 renko/rebuild spike harness (throwaway)

Run from `services/api`: `PYTHONPATH=. python -m bench.renko_rebuild.run --rows 1000000 --repeats 5 --trials 20 --out out.json`.
Seeded (12001), no network; input is a synthetic-from-corpus day (see ADR-0033). Raw run: `docs/research/e12/renko-rebuild-results.json`.
