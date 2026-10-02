# E07 backup / restore drill (SR-090..093) - procedure

Status: executed 2026-10-02 (file-level drill, no docker: Postgres leg skipped by the script when no dump is present).
Fixtures only; throwaway backup key (`openssl rand -out key 32`), never the runtime KEK.

1. Back up PG dump + one Parquet partition + config; encrypt with the throwaway key.
2. Attempt decryption without the key / with the runtime KEK: must fail (automated analogue:
   `test_sr092_backup_key.py`). Record the attempt here.
3. Run `restore_drill.sh <backup> <scratch>`; the app must start and the partition checksums match.
4. Record date, operator, result in this file.

| Date | Operator | Decrypt-without-key | Restore | Notes |
|---|---|---|---|---|
| 2026-10-02 | claude-agent (E07-X02) | FAILED as required: wrong key (stands in for runtime KEK) -> `bad decrypt`; no key -> script refuses (`CV_BACKUP_KEY_FILE` required) | OK: `restore drill OK`; `trades/part-0000.parquet: OK` (sha256sum -c) | throwaway `openssl rand` keys, fixture bytes only; Postgres dump leg not run (no docker) |

## Execution record (2026-10-02)
Commands: build fixture tar + `_manifests/checksums.sha256`; encrypt with key A (`openssl enc -aes-256-cbc -pbkdf2`);
`CV_BACKUP_KEY_FILE=<key B> restore_drill.sh` -> `bad decrypt` (exit non-zero); with key A -> checksum OK and
`restore drill OK 2026-10-02T00:29:02Z`. The pg_restore leg (loopback scratch DB) runs on the docker-capable
nightly host; the SR-047 loopback restriction is enforced by the script's `-h 127.0.0.1`.
