# QuestDB hot-tier perf regression harness (E07-T03)

Re-runs the `E07-K01` spike's shapes A-F (`spikes/storage/bench.py`,
`docs/plan/spikes/S2-hot-tier.md`) against a **real** QuestDB instance, and
compares the result to the committed baseline.

Per the ticket's Definition of Done item — *"Perf regression harness
committed with baseline numbers recorded (not yet gating, per R0 quality
gates)"* — this harness is a **reporter, not a CI gate**: `compare.py`
always exits `0`. Wiring it into a required check is a separate, future
ticket once R0 exits and perf becomes gating.

## Files

- `runner.py` — re-executes shapes A-F against a live QuestDB endpoint
  (PGWire reads via the real `candleviewer.storage.questdb.reader` query
  builders, plus an ILP sustained-rows/s write measurement). Skips cleanly
  (prints to stderr, exits 0) when `CV_QUESTDB_PG_DSN` / `CV_QUESTDB_ILP_HOST`
  are unset — there is no QuestDB instance available in this repo's test
  environment (no docker).
- `compare.py` — diffs a run's JSON against `baseline.json` with a
  configurable `--tolerance-pct` (default 25%, matching the spike's own
  `worse_by_more_than_25pct` rule) and prints a table. Always exits 0.
- `baseline.json` — the E07-K01 spike's `results.json`, committed verbatim
  as the baseline for shapes A-F. See **Provenance** below.
- `tests/` — unit tests for `compare.py`'s diff logic and `runner.py`'s
  skip-when-unconfigured path. No network, no sleeps, no live QuestDB.

## Provenance of `baseline.json`

| Field | Value |
|---|---|
| Source | `spikes/storage/results.json` (E07-K01 spike harness) |
| Source commit | `947ce8934d2fc28c2b9fed72c44fbeb8a5295837` |
| Date recorded | 2026-09-29 |
| Machine | Spike harness measurement (rows-scanned + documented constant-factor
  model, **not** a live QuestDB container — no docker/QuestDB installation was
  available in the E07-K01 execution environment; see the methodology field
  inside the JSON and `docs/plan/spikes/S2-hot-tier.md`) |
| Engine overhead constants | `ENGINE_OVERHEAD_MS["questdb"] = 4.0` (network + planning, no secondary index) |
| Decision | `confirm-questdb` (all shapes A-F meet target) |

This baseline is a **model-derived** number, not a wall-clock measurement
against a running QuestDB container (E07-K01 documents why: no docker in
that environment). The first real run of `runner.py` against a live QuestDB
instance (tracked as the named follow-up spike `E07-S07`) should replace
`baseline.json` with genuine wall-clock numbers in its own PR, with the
provenance table above updated accordingly.

## Usage

```bash
export CV_QUESTDB_PG_DSN="postgresql://user:pass@localhost:8812/qdb"
export CV_QUESTDB_ILP_HOST="localhost:9009"
cd services/api
uv run python -m benchmarks.questdb_hot_tier.runner --out /tmp/run.json
uv run python -m benchmarks.questdb_hot_tier.compare --run /tmp/run.json
```

Without a QuestDB instance (e.g. local dev without docker, or this repo's
CI), the runner prints `SKIPPED: ...` to stderr and exits `0` — it is not
wired into any required check (no `make bench-questdb` convention exists in
`AGENTS.md` §4 yet for backend perf harnesses; the two commands above are
the documented invocation until one is added).

## Unit tests

```bash
cd services/api
uv run pytest benchmarks/questdb_hot_tier/tests -q
```

Covers: regression detected / within tolerance / missing shape in
`compare.py`, and the skip-when-unconfigured path in `runner.py`. No
network, no sleeps, no live QuestDB dependency.
