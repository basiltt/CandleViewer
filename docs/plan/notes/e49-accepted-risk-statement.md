# Accepted-risk statement for the GA PRR pack (E49-T03)

Date: 2026-10-06 · **Provisional** — agent recommendations; every decision below is the Owner's.
Detail: `docs/plan/backlog/artifacts/e49-accepted-risk-inventory.md`. Enforcement:
`tools/ci/check_accepted_risk_expiry.py` (governance job + weekly run).

## Position

53 dated acceptances are mechanically tracked; **0 expired, 0 inside 30 days** today. Nothing is
silently extended: this review changed no approver or expiry.

| Source                                                                | Count | Severity                                     | Owner role              | Soonest expiry |
| --------------------------------------------------------------------- | ----- | -------------------------------------------- | ----------------------- | -------------- |
| Register `Accepted` rows                                              | 3     | 1 Critical (prov.), 2 Medium                 | SEC ×2, OWN ×1          | 2027-03-25     |
| `accepted-risks.yaml`                                                 | 8     | 6 High, 2 Low (licence)                      | OWN approver; SEC owner | 2026-12-31     |
| §16.2 exceptions                                                      | 2     | High / testnet-only                          | SEC                     | 2026-12-31     |
| In-source `nosemgrep`                                                 | 40    | scanner High (naming, not a boundary breach) | SEC ×38, OWN ×2         | 2026-12-31     |
| Ticket-level evidence deferrals (#1778 A–D), not mechanically tracked | 17    | n/a (missing evidence)                       | OWN                     | PRR            |

Accessibility (E47): **#1313 NVDA/Electron per-screen cost, #1320 themes, #1321 preferences** are accepted
as deferrals; E47 has not yet published its non-conformance list, so none is final. Performance (E46):
none accepted yet. Pen-test (E43): none accepted yet; the sweep must re-run when they publish.

## Soonest expiries

2026-12-31: EX-06 braces (#1737), EX-01 seeder (approval pending), 3 migration-0004 entries, 38 in-source
suppressions. 2027-03-25: psycopg licences ×2, signer.py, 0002 bootstrap print, RSK-053, RSK-055.

## Open escalations to the Owner (all in #1778)

1. **RSK-053** re-scored 10→15 (Critical): decide GA acceptance of review-only runbook integrity.
2. **EX-01** `--allow-no-mfa` seeder: approval still Pending — approve or retire.
3. **#1051 / RSK-056**: three xfail abuse cases are real control gaps; recommend GA-block until OMS lands.
4. **0002_rbac_seed clear-text print**: accept to GA, or fund the structured bootstrap channel.
5. **Year-end cliff**: 44 tracked items share 2026-12-31 (EX-06 and its yaml entry are one decision); approve one re-review session (week of 2026-12-14),
   and consider aligning the three 0004 entries to the GA cut.
6. **RSK-055**: confirm E44 live enablement is a mandatory re-review of the Manager-diagnostics acceptance.
7. **#1778 deferrals** have no expiry; approve the proposed PRR-linked expiries in inventory §5.
