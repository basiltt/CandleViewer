"""SR-092/093: exercise the real `infra/scripts/restore_drill.sh` decrypt path.

Encrypts with the exact openssl command line the script decrypts with, then
runs the script (file-level PARTIAL mode, no Postgres): the happy path passes;
a tampered ciphertext and a wrong key must both make the script fail.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "infra" / "scripts" / "restore_drill.sh"
BASH = shutil.which("bash")
OPENSSL = shutil.which("openssl")

pytestmark = pytest.mark.skipif(
    not (BASH and OPENSSL and SCRIPT.is_file()), reason="needs bash + openssl"
)


def _encrypt(src: Path, dst: Path, key_file: Path) -> None:
    assert OPENSSL is not None
    subprocess.run(  # noqa: S603 - fixed argv, throwaway fixtures
        [OPENSSL, "enc", "-aes-256-cbc", "-pbkdf2", "-in", str(src), "-out", str(dst),
         "-pass", f"file:{key_file}"],
        check=True,
    )  # fmt: skip


def _backup(tmp_path: Path, key: str) -> tuple[Path, Path]:
    key_file = tmp_path / "backup.key"
    key_file.write_text(key)
    payload = b"fixture-parquet-bytes"
    manifest = f"{hashlib.sha256(payload).hexdigest()}  part.parquet\n".encode()
    plain = tmp_path / "cold.tar.gz"
    with tarfile.open(plain, "w:gz") as tf:
        for name, data in (("part.parquet", payload), ("_manifests/checksums.sha256", manifest)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    backup = tmp_path / "backup"
    backup.mkdir()
    _encrypt(plain, backup / "cold.tar.gz.enc", key_file)
    return backup, key_file


def _run(backup: Path, scratch: Path, key_file: Path) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    env = {**os.environ, "CV_BACKUP_KEY_FILE": key_file.name, "CV_DRILL_ALLOW_NO_PG": "1"}
    return subprocess.run(  # noqa: S603 - fixed argv, throwaway fixtures
        [BASH, str(SCRIPT), backup.name, scratch.name],
        cwd=backup.parent,  # relative paths: GNU tar treats `C:` as a remote host
        env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_sr092_restore_drill_script_happy_path(tmp_path: Path) -> None:
    backup, key_file = _backup(tmp_path, "throwaway-backup-key")
    res = _run(backup, tmp_path / "scratch", key_file)
    assert res.returncode == 0, res.stderr
    assert "restore drill OK" in res.stdout


def test_sr092_restore_drill_script_fails_on_tampered_ciphertext(tmp_path: Path) -> None:
    backup, key_file = _backup(tmp_path, "throwaway-backup-key")
    blob = backup / "cold.tar.gz.enc"
    raw = bytearray(blob.read_bytes())
    raw[-1] ^= 0x01
    blob.write_bytes(bytes(raw))
    assert _run(backup, tmp_path / "scratch", key_file).returncode != 0


def test_sr092_restore_drill_script_fails_with_wrong_key(tmp_path: Path) -> None:
    backup, _ = _backup(tmp_path, "throwaway-backup-key")
    wrong = tmp_path / "wrong.key"
    wrong.write_text("runtime-kek-not-the-backup-key")
    res = _run(backup, tmp_path / "scratch", wrong)
    assert res.returncode != 0
    assert "restore drill OK" not in res.stdout
