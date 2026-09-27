# services/api

CandleViewer backend — Python 3.12+ modular monolith (FastAPI/asyncio), per
`docs/plan/20-architecture.md` §2.1 and `CONSTITUTION.md` C-2.1.

This package is the target of the `services/api` command table in **`AGENTS.md` §4** (the single
source of truth for command names, C-16.5; mirrored pointer only in `CLAUDE.md` §8). Read that
table for install/lint/format/typecheck/test/architecture commands — do not restate them here.
Run every command from this directory.

This ticket (E02-T02) creates only the toolchain and an empty `candleviewer`
package with a settings placeholder. The module tree (M1–M24) and composition
root land in E02-T05; import-linter **contracts** land in E02-T06.
