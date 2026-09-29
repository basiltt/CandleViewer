# E02-Q02 — Charter Session 2: "From zero to running stack"

Format per `docs/plan/03-testing-strategy.md` §11.2.

## Environment constraint (read first)

**Docker is not installed on the non-author machine available for this
charter run** (no Docker Desktop, no Docker Engine — confirmed via
`docker --version` → command not found). Per this ticket's own scope note
("CI runner environments (E03)" is out of scope, and the target is WSL
Ubuntu with Docker Desktop's WSL2 integration per `20-architecture.md` §5),
a live `make up` / `make down` / `make reset` execution could not be
performed in this session. This is reported as a **genuine coverage gap**,
not silently worked around: Session 2's dynamic acceptance criteria (AC1,
AC3) are **not directly verified** here and are flagged below as needing a
follow-up run on a machine with Docker. Everything that can be assessed
**statically** from the committed compose files, healthcheck script, and
`Makefile` — which is most of what a first-time joiner actually hits before
`docker compose up` even starts pulling images — was assessed and is
reported with full confidence.

## Charter

**Mission:** starting from only the committed docs and compose files,
determine whether `make up` / `make dev` / `make down` / `make reset` would
bring a new joiner to a healthy stack without contacting the scaffold's
author, and whether the trust-boundary (B2) and credential-free (`CV_FEED`)
guarantees the README promises actually hold in the compose definitions.

**Areas to probe:**

- `make up` / `down` / `reset` targets and what they actually invoke.
- `infra/scripts/healthcheck.sh`'s polling behaviour and failure mode.
- Host port bindings — specifically whether anything is reachable beyond
  `127.0.0.1` (B2, `20-architecture.md` §2.2 — security-labelled, P0 if
  violated).
- Whether `CV_FEED=synthetic` really requires zero Bybit credentials, and
  whether `CV_FEED=live` without credentials fails fast per the README's claim.
- Documented port list vs. actual compose port list (used for the
  port-conflict Troubleshooting entry).

**Oracles (what "looks wrong"):**

- Any service port bound to `0.0.0.0` or a LAN-reachable interface instead of
  `127.0.0.1` — immediate P0-critical per this ticket's Security notes.
- `README.md`'s documented port-conflict list not matching the compose file's
  actual bound ports (a new joiner freeing the wrong port).
- Any doc or code path that would accept/require a real credential for the
  default onboarding flow.
- `make up`/`healthcheck.sh` hanging with no timeout on failure (must be a
  clear, actionable error, per AC3).

## Session log (static analysis — no Docker available)

| Area                                                          | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Makefile targets**                                          | `up` = `docker compose -f infra/docker-compose.dev.yml --profile core --profile obs up -d` then `infra/scripts/healthcheck.sh core obs`; `down` adds `--profile cold` and tears down (keeps volumes); `reset` = same as `down` plus `-v` (drops volumes). `dev` = `up` + `pnpm --filter @candleviewer/web dev`; `dev-down` aliases `down`. Matches README's documented commands exactly — no drift.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Compose file layering**                                     | Root `infra/docker-compose.dev.yml` is a thin `include:` pointer at `infra/compose/docker-compose.yml` (base) + `infra/compose/docker-compose.dev.yml` (dev override: hot-reload `api`, bind-mounts source, hard-sets `CV_FEED: synthetic`). Consistent with the header comments in both files; the pointer exists specifically so the documented root-relative command works without a joiner needing to know about `infra/compose/` internals — a deliberate, well-documented design, not a defect.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **Healthcheck timeout behaviour**                             | `infra/scripts/healthcheck.sh` polls every 3s up to `HEALTHCHECK_TIMEOUT_S` (default 120s), then **exits 1 with a clear stderr message** ("healthcheck: timed out after 120s...") plus a `docker compose ps` dump for diagnosis. This satisfies AC3's "never a hang" requirement structurally: worst case is a bounded 120s wait with an actionable error, not an indefinite hang. **Could not be dynamically confirmed** (needs Docker) but the script logic itself contains no unbounded loop or blocking call — reviewed line-by-line, confirmed bounded.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **B2 trust boundary (host/LAN exposure) — SECURITY-CRITICAL** | Every service in `infra/compose/docker-compose.yml` binds its host port explicitly to `127.0.0.1`: postgres `127.0.0.1:5432`, questdb `127.0.0.1:8812/9009/9000`, api `127.0.0.1:8000`, prometheus `127.0.0.1:9090`, grafana `127.0.0.1:3001:3000`, minio `127.0.0.1:9002/9003`. The dev override only changes the `api` service's build target/entrypoint/env/volumes — it does not add or widen any port binding. **No LAN/Windows-host-reachable exposure found in the compose definitions.** This is the one item that would have been filed `priority/p0-critical` per this ticket's Security notes if it had been violated — it was not. Recorded as a **verified-clean** finding, not a bug.                                                                                                                                                                                                                                                                                                   |
| **Port list accuracy (Troubleshooting doc)**                  | README's Troubleshooting lists conflict-candidate ports as "`5432`, `8000`, `8812`/`9009`, `9090` or `3000`". Actual bound host ports per the compose file: `5432, 8812, 9009, 9000, 8000, 9090, 3001, 9002, 9003`. The README's list **omits QuestDB's HTTP console port (`9000`, default `QUESTDB_HTTP_PORT`) and both MinIO ports (`9002`/`9003`, `cold` profile only, so arguably lower-priority), and states Grafana's port as `3000` when the compose file actually maps host `3001` → container `3000`** (i.e. the _documented_ conflict port for Grafana is the container-internal port, not the host port a joiner would actually need to free / query). A joiner following the doc literally to free a "port 3000 conflict" would be checking the wrong host port. **Filed as a documentation defect (P2)** — see Bugs filed.                                                                                                                                                               |
| **`CV_FEED` credential-free default**                         | `services/api/candleviewer/settings.py` (§7.3 per its own docstring reference) defaults `CV_FEED` to `synthetic`, which replays `packages/fixtures/raw/synthetic_sample.jsonl` — no Bybit credentials read or required on that path (confirmed by reading the settings module and the dev-compose override, which additionally hard-pins `CV_FEED: synthetic` for the dev profile). Setting `CV_FEED=live` without `CV_BYBIT_API_KEY`/`CV_BYBIT_API_SECRET` raises a `ValueError` at settings-validation time (a `pydantic` validator), i.e. fails fast before the app starts serving, not partway through — matches the README's claim exactly. **No credential-prompting default found; no default-credential-left-unchanged risk found** (postgres password is a required env var with no default — `${POSTGRES_PASSWORD:?set in infra/compose/.env}` — fails the compose parse if unset, which is the correct posture).                                                                           |
| **Image digests**                                             | Every image in the base compose file carries a `sha256:` digest pin (no bare tags, no `:latest`) as `infra/scripts/lint_compose.py` is said to enforce. However, the file's own header comment discloses these are **well-formed placeholder digests**, not real resolved digests (E02-T08's author had no Docker either, per that PR's own note). This means `docker compose up` **will fail to pull any image** on the first real run anywhere until the digests are re-resolved — a real, structural blocker for AC1 ("reach a... healthy `make up`"), not something either this or the prior session author's environment constraints can currently verify past. **This is the most significant finding of Session 2, filed as a bug (P1)** — see Bugs filed: without Docker on _any_ contributor's machine so far, the compose stack has never actually been proven to start end-to-end, and the placeholder-digest residual flagged in E02-T08/E02-X01/E02-X02 as "R4" has not yet been closed. |

## Bugs filed

See `E02-Q02-bugs-filed.md` for the full list with reproduction steps
(BUG-1 through BUG-5 in this document's numbering — BUG-3 corresponds to
this session's port-doc mismatch, BUG-4 to the placeholder-digest blocker).

## Time split

- Setup (reading Makefile/compose/healthcheck/settings): ~35 min
- Testing (static verification against each acceptance criterion, cross-
  referencing README claims against code): ~45 min
- Bug reporting / write-up: ~10 min
  (No dynamic `make up` execution time — no Docker available; see Environment
  constraint above.)

## Coverage assessment

**Areas explored:** 6 (Makefile targets, compose layering, healthcheck
timeout logic, B2 port-exposure audit, port-doc accuracy, `CV_FEED`
credential-free behaviour).
**Risks found:** 2 substantive (image-digest placeholder blocking any real
`make up`, port-doc mismatch); B2 boundary explicitly checked and found
**clean** (a pass is itself a meaningful, reportable result for a
security-labelled area, not just an absence of findings).
**Bugs filed:** 2 from this session (P1 digest blocker, P2 port-doc
mismatch), contributing to 4 total across both sessions plus 1 tracking
note (see the combined bug log).
**Not covered / needs follow-up:** AC1 ("all six services reach healthy") and
AC3 ("no network + warmed cache → success or clear error, never a hang") need
a dynamic run on a Docker-equipped, non-author machine before E02 can be
marked Done — recorded as an explicit residual, matching the same "R4"
residual already tracked against E02-T08/E02-X01/E02-X02. This charter did
not silently substitute a partial check for the real one: the gap is named
so QA can schedule the dynamic re-run.
