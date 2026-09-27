# services/api

CandleViewer backend — Python 3.12+ modular monolith (FastAPI/asyncio), per
`docs/plan/20-architecture.md` §2.1 and `CONSTITUTION.md` C-2.1.

This package is the target of the `services/api` command table in `AGENTS.md` §4
(mirrored in `CLAUDE.md` §8). Run every command from this directory.

| Task | Command |
|---|---|
| Install dev deps | `uv sync --frozen` |
| Lint | `ruff check .` |
| Format check / fix | `black --check .` / `black .` |
| Typecheck | `mypy --strict .` |
| Unit tests | `pytest -m "not integration" --cov=. --cov-fail-under=85` |
| Integration tests (needs docker compose stack) | `pytest -m integration` |
| Architecture contracts | `lint-imports` |

This ticket (E02-T02) creates only the toolchain and an empty `candleviewer`
package with a settings placeholder. The module tree (M1–M24) and composition
root land in E02-T05; import-linter **contracts** land in E02-T06.
