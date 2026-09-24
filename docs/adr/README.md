# Architecture Decision Records

This directory contains the Architecture Decision Records (ADRs) for CandleViewer, following the [MADR](https://adr.github.io/madr/) (Markdown Any Decision Records) format.

## What is an ADR?

An ADR captures an important architectural or technical decision, along with its context and consequences, so future contributors understand *why* something was built the way it was — not just *what* was built.

## When to write one

Write an ADR when a decision:

* Affects the overall technology stack, project structure, or a core subsystem (chart engine, data layer, scripting sandbox, etc.)
* Is hard or costly to reverse
* Involves meaningful trade-offs that future contributors will want to understand
* Resolves an open design question referenced in the README or roadmap

Small, easily reversible implementation details don't need an ADR.

## How to write one

1. Copy `0000-adr-template.md` to a new file named `NNNN-short-title.md`, where `NNNN` is the next sequential number.
2. Fill in the template — context, decision drivers, considered options, and the outcome.
3. Open a pull request. Discussion happens in the PR; once merged, the ADR's status becomes `accepted`.
4. If a later decision replaces an earlier one, update the old ADR's status to `superseded by ADR-NNNN` rather than deleting it — ADRs are a historical record.

## Index

| ADR | Title | Status |
|---|---|---|
| [0000](0000-adr-template.md) | ADR Template | — |
| 0001 | Core stack decision | planned (M0) |
