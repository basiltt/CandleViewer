"""Throwaway session/revocation model harness for E09-K01.

Not production code. In-memory simulation with a virtual clock — no network, no sleep,
no real database. See README.md in this directory for scope and rationale.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class SessionRow:
    id: str
    user_id: str
    revoked_at: float | None = None
    revoked_reason: str | None = None
    mfa_satisfied_at: float | None = None


@dataclass
class RotationEdge:
    prev_session_id: str
    next_session_id: str


class SessionStore:
    """Opaque-handle session store: dict-backed, O(1) lookup/revoke.

    Models the `sessions` (by id) and `sessions_rotation` (adjacency by prev->next)
    tables from 21-database-schema.md §3.1.4 well enough to measure algorithmic shape;
    it is not a benchmark of real Postgres index performance (no docker available).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRow] = {}
        self._rotation_next: dict[str, str] = {}  # prev_id -> next_id
        self.reuse_events: list[dict[str, str]] = []

    def create(self, user_id: str) -> SessionRow:
        row = SessionRow(id=_uuid(), user_id=user_id)
        self._sessions[row.id] = row
        return row

    def rotate(self, prev_id: str) -> SessionRow:
        """Issue a new session, revoke the old one as 'rotated', link them."""
        prev = self._sessions[prev_id]
        new = self.create(prev.user_id)
        prev.revoked_at = time.monotonic()
        prev.revoked_reason = "rotated"
        self._rotation_next[prev_id] = new.id
        return new

    def is_live(self, session_id: str) -> bool:
        """O(1) revocation check — this is the per-request/per-WS-frame hot path."""
        row = self._sessions.get(session_id)
        return row is not None and row.revoked_at is None

    def revoke(self, session_id: str, reason: str) -> None:
        row = self._sessions[session_id]
        row.revoked_at = time.monotonic()
        row.revoked_reason = reason

    def revoke_family(self, session_id: str, reason: str) -> int:
        """Walk the rotation chain in both directions and revoke every member.

        Cost is O(family length), i.e. O(depth) not O(total rows) — this is the
        number the ticket asks to record "at 10k rows".
        """
        # Build reverse edges lazily for the walk.
        prev_of: dict[str, str] = {v: k for k, v in self._rotation_next.items()}

        visited: set[str] = set()
        stack = [session_id]
        while stack:
            sid = stack.pop()
            if sid in visited or sid not in self._sessions:
                continue
            visited.add(sid)
            self.revoke(sid, reason)
            nxt = self._rotation_next.get(sid)
            if nxt is not None:
                stack.append(nxt)
            prv = prev_of.get(sid)
            if prv is not None:
                stack.append(prv)
        return len(visited)

    def detect_reuse(self, rotated_prev_id: str) -> None:
        """A revoked/rotated token was presented again: kill the whole family."""
        killed = self.revoke_family(rotated_prev_id, "rotation_reuse")
        self.reuse_events.append(
            {
                "event": "auth.refresh_reuse_detected",
                "severity": "critical",
                "session_id": rotated_prev_id,
                "family_size": str(killed),
            }
        )
