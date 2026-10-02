# E07 backup / restore drill (SR-090..093) - procedure

Status: scripted (`infra/scripts/restore_drill.sh`); execution to be dated on a docker-capable host.
Fixtures only; throwaway backup key (`openssl rand -out key 32`), never the runtime KEK.

1. Back up PG dump + one Parquet partition + config; encrypt with the throwaway key.
2. Attempt decryption without the key / with the runtime KEK: must fail (automated analogue:
   `test_sr092_backup_key.py`). Record the attempt here.
3. Run `restore_drill.sh <backup> <scratch>`; the app must start and the partition checksums match.
4. Record date, operator, result in this file.

| Date | Operator | Decrypt-without-key | Restore | Notes |
|---|---|---|---|---|
| (pending) | | | | not run locally: no docker |
