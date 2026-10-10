# E27-K01 — KEK custody, injection and rotation (WSL and VPS)

- Ticket: E27-K01 (#832) · Feeds: E27-T02 (#835 credential broker + KEK loader), E09-S11 (#2119 break-glass CLI)
- Status: **finding — ★ defaults pre-approved for ratification by the owner (recorded on #1778)**
- Owners of the rules cited: ADR-0009, `04-security-program.md` SR-001/002/023/090–093, C-2.7, C-3.2, C-12.2
- No secret values appear in this document. Paths and variable names only.

## 1. Threat framing

Attacker holds a Postgres dump and/or read access to the WSL filesystem / Docker volumes, but not the
Windows host console. Each option is scored on: KEK at rest, KEK in transit, process visibility
(`/proc/*/environ`, `docker inspect`, WSL FS), auditability, failure mode, unattended restart.

**Evidence status.** This finding was produced desk-side. The measured items the ticket asks for
(per-mechanism start-up latency, non-visibility transcripts, restore-drill log) are **not fabricated
here**; they are owed by follow-up drill **FU-1** (§9) run on the real host against the T02 build.
Figures below marked *(budget)* are targets, not measurements.

## 2. KEK custody

| # | Custody | WSL deployment | VPS deployment | Verdict |
|---|---|---|---|---|
| C1 | Windows Credential Manager (host), read by a host-side launcher | ✔ outside WSL + volumes | n/a | ★ **WSL** |
| C2 | File `0400`, owned by service uid, outside every Docker volume and the repo | weak: WSL FS is in the threat model | acceptable only as source for C3 | dev only (`CV_KEK_SOURCE=file`) |
| C3 | systemd credential: `LoadCredentialEncrypted=` (TPM2 and/or host key sealed via `systemd-creds`) | n/a (no systemd guarantee in WSL) | ✔ unattended, never plaintext on disk | ★ **VPS** |
| C4 | `age`-encrypted file `0600` + identity file | identity sits beside it ⇒ no gain | fallback when no TPM2/`systemd-creds` | VPS fallback |
| C5 | Plain env var in compose `environment:` | visible via `docker inspect` | same | **rejected** |
| C6 | OS keyring inside WSL / password at boot / Vault / KMS | rejected by ADR-0009 | — | not re-litigated |

TPM: on a VPS a virtual TPM2 is used when the provider exposes one (`systemd-creds --with-key=tpm2`);
otherwise `--with-key=host` (key in `/var/lib/systemd/credential.secret`, root `0400`). Both keep the
KEK out of Postgres, out of backups (SR-090) and out of image layers (SR-002).

Offline backup of the KEK stays as ADR-0009 §7: owner-held `age`-encrypted copy, distinct from the
backup key (SR-091).

## 3. Injection path into `cv-api`

Candidates from the ticket:

| Mech | How | Where the KEK is visible | Unattended restart | Verdict |
|---|---|---|---|---|
| (a) `docker compose run --env` from launcher | launcher reads C1, passes env | `/proc/1/environ` of the container **and** `docker inspect` (`Config.Env`) | yes | **rejected** — fails non-visibility |
| (b) Compose `secrets:` backed by a pipe/FIFO | launcher writes to a host FIFO bind-mounted as `/run/secrets/cv_kek` | tmpfs-like mount inside the container only; not in `inspect` env; FIFO is on the WSL FS path but holds no data at rest | yes, if the launcher is the restart supervisor | ★ **chosen** |
| (c) Authenticated localhost unwrap call to a host agent | `cv-api` calls host agent at boot | KEK never enters container if agent unwraps DEKs; otherwise in transit over loopback | needs agent up + its own credential (bootstrap problem recurs) | rejected for v1 — new long-running host service, new auth secret, new network path |

★ **Read-once file descriptor contract.** Whatever the host side does, `cv-api` sees exactly one thing:
a path `CV_KEK_HANDLE` (default `/run/secrets/cv_kek`) that yields 32 raw bytes (or 64 hex chars) once.
- WSL: the Windows launcher (`infra/host/cv-launch.ps1`, owned by T02/infra) reads C1, writes into the
  FIFO, then starts/supervises compose. The loader reads, then the FIFO is empty — nothing at rest.
- VPS: systemd unit with `LoadCredentialEncrypted=cv_kek:...`; compose (or the bare service) gets
  `$CREDENTIALS_DIRECTORY/cv_kek` bind-mounted read-only at the same path. Not swappable, `0400`.
- Loader zeroes its read buffer (best effort, `bytearray`), never logs length or prefix, and the
  value never enters `os.environ` or `Settings`.

Rejecting (a): env vars leak into `docker inspect` and every child process. Rejecting (c): it re-creates
the custody problem for the agent's credential and adds a network surface the threat model does not need.

KEK acquisition budget: ≤500 ms added to boot *(budget; measure in FU-1)*.

## 4. Configuration vocabulary (fixed)

| Key | Values | Meaning |
|---|---|---|
| `CV_ENV` | `dev` · `ci` · `demo` · `live` | existing environment selector |
| `CV_KEK_SOURCE` | `handle` ★ (prod default) · `file` (dev/ci only) · `none` | how the loader obtains the KEK. Replaces today's placeholder `kek_source="host-keychain"` in `settings.py`; T02 changes the default to `handle` and keeps `host-keychain` as a deprecated alias for one release. |
| `CV_KEK_HANDLE` | path | `handle`: read-once path (default `/run/secrets/cv_kek`); `file`: path to a dev key file |
| `CV_KEK_VERSION` | int ≥ 1 | the version of the KEK being supplied; must equal the active version in the `kek_versions` metadata (T02) or the current max `api_keys.kek_version` |

Hard rules (startup, before any module starts):
- `CV_KEK_SOURCE=file` with `CV_ENV=live` ⇒ **fatal**, exit non-zero, error code `kek_source_not_permitted`.
- `CV_KEK_SOURCE=file` with `CV_ENV=demo` ⇒ allowed only with an explicit warning log; ★ demo should use `handle`.
- A `file` handle with group/other permission bits set ⇒ refuse (`kek_handle_permissions`).

## 5. Key hierarchy and rotation (re-wrap)

Rows (`21-database-schema.md` §3.2.2): `key_id_enc`, `secret_enc` (AES-256-GCM under the DEK),
`enc_nonce`, `enc_alg`, `dek_ref`, `kek_version ≥ 1`, index `ix_api_keys_kek`.

★ **Key check value.** Each KEK version is identified by a KCV = first 8 bytes of
HMAC-SHA256(KEK, `"cv-kek-kcv-v1"`), stored (non-secret) with the version. The loader verifies the
supplied KEK against the KCV of `CV_KEK_VERSION`; a mismatch is `kek_mismatch`, not a decrypt storm.

Rotation procedure (owner-run, app in maintenance or Degraded, no order flow required):
1. Provision KEK v(n+1) into custody (C1 / C3) alongside v(n); launcher supplies **both** handles
   (`CV_KEK_HANDLE` + `CV_KEK_PREV_HANDLE`, the latter only during rotation).
2. Re-wrap job (admin-invoked, under `candleviewer.admin` → `secrets`): for each row
   `WHERE kek_version = n` (via `ix_api_keys_kek`), unwrap DEK with v(n), wrap with v(n+1), update
   `dek_ref` + `kek_version` in **one transaction per row**; ciphertext and `enc_nonce` untouched.
   Idempotent and resumable: a crash resumes on the remaining `kek_version = n` rows.
3. Verify: zero rows at version n; each re-wrapped DEK decrypts its ciphertext (in memory, discarded).
4. Retire v(n) from custody; drop `CV_KEK_PREV_HANDLE`.
Budget: ≤50 rows in ≤5 s *(budget; measure in FU-1)*. Audit `security.kek_rotated` with from/to
versions and row count (no key material). Same job re-wraps E09 TOTP/recovery material once E09
moves onto the KEK (follow-up FU-3).

## 6. Degraded mode (fail CLOSED)

| Condition | Result |
|---|---|
| handle missing / unreadable / empty / wrong length | lifecycle → **Degraded**; reason `kek_unavailable` |
| KCV mismatch | Degraded; reason `kek_mismatch` |
| `file` + `live` | **fatal exit** (`kek_source_not_permitted`) — never Degraded |

In Degraded (KEK): market data stays live; **all signing is refused** — the broker raises a typed
`KekUnavailable` (`secrets.errors`), order-entry/key-management routes return **403** with problem
type `kek_unavailable` (E09 route gating), `/health` and the `system` WS topic report `secrets` red
with reason, a critical alert fires, the UI shows the blocking banner (E27-D03 / E27-S02), and this
remediation text is logged verbatim:
`KEK unavailable (reason=<r>): trading disabled. Ensure the host launcher/systemd credential supplies
CV_KEK_HANDLE, then restart cv-api. See docs/ops/runbooks/kek-custody.md.`
There is no runtime re-load in v1: recovery is a restart (simpler, auditable).

Observability (specified, implemented by T02): `cv_kek_load_seconds` (histogram),
`cv_kek_load_failures_total{reason}` (counter: `kek_unavailable|kek_mismatch|kek_handle_permissions`),
`cv_kek_version` (gauge). Audit: `security.kek_loaded`, `security.kek_load_failed`,
`security.kek_rotated`.

## 7. Loader interface for E27-T02

Lives in `candleviewer/secrets/` (M2). Only `secrets` holds the KEK; callers get operations, never bytes.

```python
class KekSource(Protocol):            # secrets/kek.py
    def load(self) -> LoadedKek: ...   # raises KekLoadError(reason=...)

class LoadedKek:                       # opaque; __repr__/__str__ -> "***", no __reduce__/pickling
    version: int
    def wrap_dek(self, dek: bytes) -> bytes: ...
    def unwrap_dek(self, wrapped: bytes) -> bytearray: ...
    def close(self) -> None: ...        # zeroes the buffer

def kek_source_from_settings(settings: Settings) -> KekSource: ...  # enforces §4 hard rules
```

Implementations: `HandleKekSource` (read-once path, ★ prod) and `FileKekSource` (dev/ci, refuses live).
`SecretsService.start()` calls `load()`; on `KekLoadError` it records the reason, emits the audit and
metric, and reports `HealthStatus` red so the supervisor enters Degraded (§6). Tests use an in-memory
fake source — never a real KEK, no network (C-13.5).

## 8. Break-glass CLI (#2119) — offline KEK load

Per the #2119 decision the CLI lives under `candleviewer.admin` (allowed to import `secrets`, C-3.2):
- Entry `python -m candleviewer.admin.breakglass`; it calls `kek_source_from_settings()` with the same
  `CV_KEK_SOURCE`/`CV_KEK_HANDLE`/`CV_KEK_VERSION`, so on WSL the operator runs it through the host
  launcher (`cv-launch.ps1 breakglass`) and on the VPS via `systemd-run -p LoadCredentialEncrypted=...`.
  No new custody path.
- Proof of KEK possession = successful `load()` + KCV match (§5). Fails closed otherwise.
- It connects to Postgres directly, opens no listener, and refuses if `cv-api` holds the run lock.
- `file` source in `live` is refused (same rule); a second explicit flag is required in `live`.
- Audit: host-local append-only file folded into `audit_log` on next boot (E09 threat model §3.6.1);
  that lifespan fold-in needs the Agent A ack noted on #2119.

## 9. Restore drill, inconclusive items, follow-ups

Restore drill (to run in FU-1): restore a Postgres dump on a host with `CV_KEK_SOURCE` unset/`none`;
expect `kek_unavailable`, Degraded, every order route 403, and zero decrypted rows. Then supply the
correct KEK → Running. Then a wrong KEK → `kek_mismatch` (KCV), still nothing decrypts.

Not proven desk-side (the ticket's "inconclusive" branch applies only to these):
- **FU-1** host drill: timing table for (a)/(b)/(c), non-visibility transcript (`docker inspect`,
  sibling `/proc/1/environ`, grep of every mounted volume), unattended-reboot test, restore-drill log.
  Interim control until FU-1: ★ (b) is used; T02 adds a CI test that the compose file has no
  `CV_KEK*` under `environment:`.
- **FU-2** `docs/ops/runbooks/kek-custody.md` (provisioning, rotation, loss = IR-08) written with T02.
- **FU-3** move E09 TOTP/recovery keys (`CV_AUTH_TOTP_KEY_HEX`) under KEK-wrapped DEKs.
- **FU-4** schema: non-secret `kek_versions(version, kcv, created_at, retired_at)` table (migration, T02).

## 10. ★ Recommendation summary

1. Custody: **WSL — Windows Credential Manager via host launcher; VPS — `systemd-creds`
   `LoadCredentialEncrypted` (TPM2 if present, else host key), `age` file `0600` as fallback.**
2. Injection: **(b) read-once handle at `/run/secrets/cv_kek`** (FIFO on WSL, systemd credential dir on
   VPS); never env, never compose `environment:`, never in `Settings`.
3. Rotation: dual-handle window + resumable per-row re-wrap keyed by `kek_version`, KCV per version.
4. Degraded: KEK failure ⇒ Degraded, signing refused, 403 on trading routes, health red, critical
   alert, fixed remediation text; `file`+`live` ⇒ fatal `kek_source_not_permitted`.
5. Interface: `KekSource.load() -> LoadedKek` (opaque wrap/unwrap) in `secrets`; break-glass CLI in
   `candleviewer.admin` uses the same factory.
