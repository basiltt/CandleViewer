"""Daily checkpoint job (ticket "Scope / Deliverables": "Daily checkpoint job
writing the head hash to `audit_checkpoints` and to a file outside the
database volume").

Writes one row to `audit_checkpoints` (head id, head hash, row count) and
appends the same triple as a JSON line to `checkpoint_path` — a location the
caller must configure outside the Postgres data volume so a full-volume loss
does not also destroy the tamper-evidence record (ticket "Context": "an
off-box file so tail truncation is detectable").
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from candleviewer.audit.repository import AuditRepository


class CheckpointResult:
    __slots__ = ("created_at", "head_hash", "head_id", "row_count")

    def __init__(self, head_id: int, head_hash: str, row_count: int, created_at: datetime) -> None:
        self.head_id = head_id
        self.head_hash = head_hash
        self.row_count = row_count
        self.created_at = created_at


async def run_checkpoint(
    repository: AuditRepository,
    *,
    off_box_path: str,
    signed_by: str = "cv-audit-key-v1",
) -> CheckpointResult | None:
    """Run one checkpoint. Returns `None` if `audit_log` is empty (nothing to
    checkpoint yet — a fresh environment). Idempotent per `head_id` (the
    `ON CONFLICT DO NOTHING` in the repository's insert) so re-running the
    job twice in one day (retry after a transient failure) never
    double-inserts."""
    head = await repository.read_head()
    if head is None:
        return None
    head_id, head_hash = head
    row_count = await repository.count()
    created_at = datetime.now(UTC)
    await repository.write_checkpoint(
        checkpoint_id=str(uuid.uuid4()),
        head_id=head_id,
        head_hash=head_hash,
        row_count=row_count,
        signed_by=signed_by,
    )

    _append_off_box(off_box_path, head_id, head_hash, row_count, created_at)
    return CheckpointResult(head_id, head_hash, row_count, created_at)


def _append_off_box(
    off_box_path: str, head_id: int, head_hash: str, row_count: int, created_at: datetime
) -> None:
    path = Path(off_box_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "head_id": head_id,
            "head_hash": head_hash,
            "row_count": row_count,
            "created_at": created_at.isoformat(),
        },
        sort_keys=True,
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
