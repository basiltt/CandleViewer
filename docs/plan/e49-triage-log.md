
## Review items 3-5 (fixer pass)

**Project #10 views** - created via `createProjectV2View` (TABLE_LAYOUT): GA burn-down, Untriaged,
SLA at risk, Missing DoR, By component (bugs), By root-cause cluster. The API's
`ProjectV2ViewConfigurationInput` only accepts `visibleFieldIds`; **filters, grouping and sort cannot
be set via the API**. Owner must set in the UI: GA burn-down `kind:Bug -status:Done`; Untriaged
`kind:Bug -label:triaged`; SLA at risk `label:sla-at-risk,sla-breached`; Missing DoR
`label:needs-dor,needs-severity`; By component group by Component; By root-cause cluster group by
Labels (`cluster/*`). Views exist but are NOT yet filtered - item 3 is partial.

**Labels** - `cluster/unassigned` (namespace seed; E49-K01 adds `cluster/<name>`), needs-dor,
needs-severity, sla-at-risk, triaged, security-review created idempotently (`--force`).

**Security review of defect-triage.yml** - actions pinned to full SHAs; workflow `contents: read`,
jobs add `issues: write` only; no `pull_request_target`; no checkout of PR code; secrets only via
`env:` (never echoed); jobs use the ephemeral `GITHUB_TOKEN` (repo-scoped, issues write);
TRIAGE_TOKEN is fine-grained (repo + project), TRIAGE_DIGEST_WEBHOOK/TRIAGE_PROJECT_ID are
secrets. Note: `${{ github.event.issue.number }}` is an integer, not attacker text, so no
script-injection path.

**Scratch e2e** - `python -m tools.triage.scratch_e2e` (opt-in): created #1764, got `needs-dor`
+ comment, closed with marker. Nothing deleted.
