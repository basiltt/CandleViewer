# ADR-0004 — Modular monolith with an internal event bus

- Status: **decided**
- Date: 2026-09-14
- Deciders: Architect, Backend lead, DevSecOps
- Consulted: `docs/research/11-backend-tech.md` §4 and risk table, `docs/research/22-architecture-options.md` §1 and §10, planning brief "Locked decisions"
- Related: ADR-0001, ADR-0005, `docs/plan/20-architecture.md` §3, §4

## Context and problem statement

The backend comprises eleven substantial subsystems (ingestion, book engine, bar builders, order-flow engines, OMS, rule engine, paper matcher, recorder, replay, auth/RBAC, admin) with very different latency and reliability characteristics. We must choose a runtime decomposition: one process, several processes, or services. The deployment target today is a single WSL box for one owner and a handful of managers; tomorrow it is a small VPS. Over-decomposing now buys complexity we cannot afford; under-decomposing risks a tangle that cannot later be split.

## Decision drivers

- Single-box deployment, single-digit concurrent users, two to a few dozen symbols.
- Sub-50 ms internal latency budgets; inter-process hops cost real milliseconds and real failure modes.
- The team is 5 backend engineers working in parallel on separate modules — module boundaries must be enforceable in code review.
- Research risk item: "single-process core becomes a scaling bottleneck if symbol/manager count grows" — likelihood low at this scope, but the mitigation ("keep logic behind a bus abstraction so a process split is moderate rework, not a rewrite") must be designed in now.

## Considered options

1. **Modular monolith, single process, internal asyncio event bus** with strict module boundaries.
2. **Microservices** (ingestion service, OMS service, gateway service, …) over Redis/NATS.
3. **Two processes**: market-data pipeline and trading/control, split from day one.
4. **Unstructured monolith** — modules calling each other's functions directly.

## Decision outcome

**Chosen: option 1** — one deployable process (`cv-api`), internally decomposed into modules that communicate **only** through a typed internal event bus or explicit service interfaces.

Binding rules:

1. **No cross-module state access.** A module may import another module's public `Protocol`/interface and its domain models; it may never touch another module's internals. Enforced by an import-linter contract in CI (`services/api/tests/test_architecture.py`).
2. **Bus topics are strings of the form `{env}.{domain}.{symbol?}.{detail?}`** and every payload is an immutable pydantic model. No dicts on the bus.
3. **Every module implements the lifecycle contract** (`start`, `stop`, `health`) and owns its `asyncio.TaskGroup`; the supervisor starts in dependency order and stops in reverse.
4. **Queue policy is per topic-class, declared, and bounded** (`20-architecture.md` §4.2). Conflation is a first-class bus feature, not something each module reinvents.
5. **The bus interface is transport-agnostic**: `publish(topic, event)` / `subscribe(topic, policy)`. The in-process implementation uses `asyncio.Queue`; a Redis Streams or NATS implementation can be substituted without touching any module.

### Consequences

Positive:
- Zero inter-process latency and zero serialisation cost on the market-data hot path.
- One deployable, one log stream, one set of credentials, one restart — appropriate for a single-box, single-operator system.
- Parallel team development stays safe because boundaries are checked mechanically, not by convention.
- The split path is pre-designed: the most likely first split (ingestion + engines in one process, OMS + gateway in another) requires only a bus transport swap and a storage-connection change.

Negative / risks:
- A crash takes down everything at once. Mitigated by: the native exchange-side SL floor (ADR-0008/P4) meaning a crash never leaves an unprotected position; a fast, deterministic startup reconciliation; and an RTO target of ≤ 90 s.
- One GIL-bound loop for all modules. Mitigated by the priority-shedding matrix (order work is never shed), the loop-lag SLO and the escape-hatch ladder in ADR-0001.
- Module boundaries can erode under deadline pressure. Mitigated by the CI import contract and CODEOWNERS on module directories.

### Why not the alternatives

- **Microservices**: the operational surface (service discovery, distributed tracing, partial-failure semantics, N deployables) is unjustifiable for single-digit users on one box, and would add latency to the exact paths with the tightest budgets.
- **Two processes from day one**: a reasonable middle ground, but it pays the coordination cost immediately for a scaling problem we may never have, and it complicates the "one ingestion code path for live and replay" invariant. We keep it as the designated first split.
- **Unstructured monolith**: fastest to write, impossible to parallelise across 5 engineers, and forecloses any future split. Explicitly rejected.

## Validation

- CI architecture test: import-linter contracts asserting the module dependency graph is acyclic and respects the declared layers.
- Load test: sustained ingestion of the designed symbol set with p99 event-loop lag ≤ 50 ms.
- A documented (not executed) split rehearsal in `30-release-roadmap.md` R5, verifying the bus abstraction is genuinely sufficient.
