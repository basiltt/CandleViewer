---
description: Fill the PR template from the ticket, run required local checks, and open the PR (after confirmation).
allowed-tools: Read, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(gh issue view:*), Bash(gh pr list:*), Bash(gh pr create:*), Bash(git push:*)
---
# /pr

1. Run `/ready-check`. If `NOT READY`, stop and print the fix list.
2. Derive the issue # from the branch/commits; `gh issue view <n> --json number,title,body,labels,milestone`.
3. Read `.github/PULL_REQUEST_TEMPLATE.md` and fill **every** section:
   - Title: conventional commit `<type>(<scope>): <summary>` (C-4.10), `!` if breaking.
   - `Closes #<n>` (C-4.7).
   - Summary, and an **AC → evidence** table (each acceptance criterion → test name / screenshot / bench diff).
   - Checks run locally with results (from `/ready-check`).
   - Risk, rollback, feature flag (C-4.13), migration notes (C-5.x), machine-hash change, security notes.
   - Deviations from the ticket and follow-up issues.
   - Template checklist items ticked only when true.
   - Final line: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
4. Show the title + body and ask for confirmation. Then `git push -u origin HEAD` (never `--force` on shared branches)
   and `gh pr create --base main --title "..." --body-file <tmp>`; add labels mirroring the issue.
5. Set issue status to In Review; print the PR URL. Do not merge (merging is human-only).
