---
description: Claim a GitHub issue, verify blockers and DoR, create the branch, and print an execution brief.
argument-hint: <issue#>
allowed-tools: Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh pr list:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(git fetch:*), Bash(git switch:*), Bash(git status:*), Bash(git pull --rebase:*), Read, Grep, Glob
---
# /pickup $ARGUMENTS

Follow `.claude/rules/70-multi-agent.md` §1. Stop at the first failed gate and report it using the BLOCKER format.

1. **Fetch:** `gh issue view $ARGUMENTS --json number,title,body,labels,assignees,state,milestone,comments`.
   Also locate the ticket key in the title (e.g. `OMS-012`) and read the mirror in `docs/plan/backlog/all-tickets.json`.
2. **Gate: eligible.** Issue is open, has no assignee, is not labelled `retired`, `blocked`, `in-progress`,
   `needs-clarification`. Retired ticket: print its replacement and stop.
3. **Gate: blockers.** For each `blocked_by` key/issue in the body: `gh issue view <n> --json state`. Any open ⇒ stop.
4. **Gate: DoR.** Check C-11.1 / `docs/plan/02-definition-of-ready-done.md`: all 14 body sections present,
   acceptance criteria testable, write set explicit, references exist. If gaps: run the `ticket-triager` agent and stop.
5. **Gate: overlap.** `gh pr list --state open --json number,title,headRefName,files` — any PR touching the same
   paths ⇒ comment on both and stop (C-4.15).
6. **Claim:** `gh issue edit $ARGUMENTS --add-assignee @me --add-label in-progress` and
   `gh issue comment $ARGUMENTS --body "Claimed by <agent-id> on branch <branch>"`. Re-read comments; if an earlier claim exists, undo yours and stop.
7. **Branch:** `git fetch origin && git switch main && git pull --rebase origin main && git switch -c <type>/<epic-key>-<slug>`
   (C-4.4: lowercase kebab, ASCII, ≤60 chars; type from ticket kind — Story/Task→feat, Bug→fix, design→design, spike→spike).
8. **Brief** — print:
   - Ticket key, title, epic, priority, estimate, milestone, branch
   - Goal (1–2 lines) and acceptance criteria as a numbered checklist
   - Write set (files/dirs) and forbidden areas
   - Contracts/interfaces to read or create first
   - Rule files to load (`.claude/rules/*`) and the right subagent (`backend-implementer`, `frontend-implementer`,
     `chart-engine-implementer`, `statechart-author`, `test-writer`)
   - Test plan (unit / integration / contract / e2e) and required evidence
   - Commands to run before PR (from `AGENTS.md` §4)
