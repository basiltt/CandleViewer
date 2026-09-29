# First-hour checklist (new joiner onboarding)

Owner: E02-T12 (docs/plan). Acceptance evidence for this checklist is E02-Q02's
non-author validation charter — do not mark this Done without it.

Tick every box in order, on a machine with **no Bybit credentials**. If any
step fails, check the Troubleshooting section in `/README.md` first; if that
doesn't resolve it, stop and file the gap against E02-T12 (do not silently
work around it — C-4.9).

- [ ] Cloned the repo and read `/README.md` end to end (not skimmed).
- [ ] Installed the pinned prerequisite versions listed in `/README.md`
      Prerequisites (node, pnpm, python, uv, docker) — confirmed each with
      its `--version` command.
- [ ] Ran `pnpm install` and `uv sync --frozen --project services/api` with
      no errors.
- [ ] Ran `pnpm verify` (or the documented equivalent) and it was green,
      without needing to ask the ticket's author anything.
- [ ] Ran `make dev` on a clean machine and watched the compose stack reach
      healthy, the api log a synthetic-feed start line, and the web dev
      server start.
- [ ] Opened `http://127.0.0.1:8000/metrics` and saw `cv_bus_publish_total`
      incrementing for `trade` and `ticker` event types.
- [ ] Opened the `apps/web` placeholder route in a browser.
- [ ] Ran `make down` and confirmed the stack stops cleanly.
- [ ] Could explain, in one sentence, what `CV_FEED=synthetic` does and why
      it exists (R10 key-person mitigation, C-2.3 normalised events).
- [ ] Knows where to find: `AGENTS.md` §4 (commands), `CONTRIBUTING.md`
      (process), `docs/plan/20-architecture.md` (architecture).

## Sign-off

New joiner name/date: ______________________
Validated without contacting the ticket's author: yes / no (if no, note what
required author contact, so the README can be fixed)
