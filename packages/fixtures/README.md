# @candleviewer/fixtures

Recorded, **redacted** Bybit fixtures + golden outputs, shared by the
TypeScript and Python test suites (CONSTITUTION.md C-13.5, `.claude/rules/40-testing.md`).

## Layout

- `raw/` — recorded WS/REST captures (redacted: no API keys, signatures,
  UIDs, or order ids tied to a real account).
- `golden/` — expected outputs (bar aggregation, footprint, decoders) for
  regression comparisons.
- `scripts/verify.mjs` — the redaction gate: fails if any file under `raw/`
  or `golden/` contains a credential-shaped string (API key, signature,
  `Authorization` header, PEM key block). Every new fixture must pass this
  before being committed (E02-X01 threat: "recorded fixture leaks credentials").

**No fixture in this package may originate from a live network call in a test
or CI run.** Fixtures are recorded via the (future) recorder tool and reviewed
before commit.

## Scripts

- `pnpm --filter @candleviewer/fixtures verify` — runs the redaction check
  over `raw/` and `golden/`.
- `pnpm --filter @candleviewer/fixtures test` — Vitest unit tests for the
  verify script itself.
