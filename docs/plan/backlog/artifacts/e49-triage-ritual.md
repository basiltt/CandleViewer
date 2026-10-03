# E49 weekly defect triage ritual (E49-T01)

**Cadence/length:** weekly, 45 minutes. **Attendees:** QA lead, Architect, one engineer per area,
designer for `design-qa` findings (Agent-delivery: owner stands in for human roles).

## Agenda
1. (5 min) Queue health: open P0/P1 (must be 0 for GA), P2 count vs <=10, `sla-breached`, `needs-dor`.
2. (15 min) Walk **Untriaged** view oldest-first; assign severity per `03-testing-strategy.md` §11.3.
3. (10 min) **SLA at risk** and **Missing DoR** views; name an owner for each `needs-dor`.
4. (10 min) **By root-cause cluster** (`cluster/<name>`, from E49-K01): plan next wave by theme.
5. (5 min) Record decisions; apply `triaged` label.

## Decision taxonomy (exactly one per bug)
fix now | fix this wave | accept with owner + expiry | close as works-as-designed | re-file as post-GA Story

## Record
Append a dated section to `docs/plan/backlog/artifacts/e49-triage-log.md`: attendees, counts, one line
per decision (`#issue — decision — owner — target sprint/expiry`).

## Views (GitHub Project, existing fields only)
GA burn-down (Kind=Bug, Status!=Done), Untriaged (no `triaged` label), SLA at risk (`sla-at-risk`|`sla-breached`),
Missing DoR (`needs-dor`), By component, By root-cause cluster (`cluster/*`).
Views are created in the Project UI; they cannot be committed.
