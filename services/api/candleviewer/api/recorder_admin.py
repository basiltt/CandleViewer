"""`POST /admin/recorder/compact` + `GET /admin/jobs/{jobId}` (E16-T05).

RBAC is resolved server-side (C-12.4): compaction needs `recording:write`,
polling needs `admin:read` (22-api-openapi.yaml `x-rbac`). Every compaction
request — accepted, denied or failed — is audited as `recorder.compact`.
`Idempotency-Key` (UUID) is required: a replay returns the same job id.
The compaction itself is an injected coroutine (the storage-side
`compact_all`), so this module never reaches a storage driver (ADR-0003).
Jobs run as tracked tasks with a bounded store; one compaction at a time.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability import spawn

RECORDING_WRITE = "recording:write"
ADMIN_READ = "admin:read"
MAX_JOBS = 256
#: Job.kind enum in 22-api-openapi.yaml has no compaction value; a retention-family job.
JOB_KIND = "retention_sweep"

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
#: (symbols | None, older_than_days | None, progress callback) -> result document.
CompactionRunner = Callable[
    [list[str] | None, int | None, Callable[[float], None]], Awaitable[dict[str, object]]
]


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


class CompactRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: list[str] | None = Field(default=None, max_length=500)
    older_than_days: int | None = Field(default=None, ge=1, le=3650)

    def checked(self) -> CompactRequest:
        for s in self.symbols or []:
            if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", s):
                raise ValueError("invalid symbol")
        return self


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    progress_pct: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, object] | None = None
    error: str | None = None

    def view(self) -> dict[str, object]:
        def iso(d: datetime | None) -> str | None:
            return d.isoformat().replace("+00:00", "Z") if d else None

        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress_pct": round(self.progress_pct, 2),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "result": self.result,
            "error": self.error,
        }


class JobConflict(Exception):
    """A compaction job is already queued or running."""


class AdminJobStore:
    """Bounded in-process job registry (oldest finished jobs evicted)."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._by_key: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._clock = clock

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def by_idempotency_key(self, key: str) -> Job | None:
        job_id = self._by_key.get(key)
        return None if job_id is None else self._jobs.get(job_id)

    def _evict(self) -> None:
        while len(self._jobs) > MAX_JOBS:
            victim = next(
                (j for j in self._jobs.values() if j.status not in ("queued", "running")), None
            )
            if victim is None:
                return
            del self._jobs[victim.id]
            self._by_key = {k: v for k, v in self._by_key.items() if v != victim.id}

    def submit(
        self,
        kind: str,
        key: str,
        work: Callable[[Callable[[float], None]], Awaitable[dict[str, object]]],
        on_done: Callable[[Job], Awaitable[None]],
    ) -> Job:
        if any(j.kind == kind and j.status in ("queued", "running") for j in self._jobs.values()):
            raise JobConflict(kind)
        job = Job(id=str(uuid.uuid4()), kind=kind)
        self._jobs[job.id] = job
        self._by_key[key] = job.id
        self._evict()

        def progress(pct: float) -> None:
            job.progress_pct = max(job.progress_pct, min(100.0, pct))

        async def _run() -> None:
            job.status = "running"
            job.started_at = self._clock()
            try:
                job.result = await work(progress)
                job.status = "succeeded"
                job.progress_pct = 100.0
            except asyncio.CancelledError:
                job.status = "cancelled"
                raise
            except Exception as exc:
                job.status = "failed"
                job.error = type(exc).__name__
            finally:
                job.finished_at = self._clock()
                self._tasks.pop(job.id, None)
            await on_done(job)

        self._tasks[job.id] = spawn(_run(), name=f"admin-job-{kind}")
        return job

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass


def _problem(status: int, title: str, detail: str, code: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    body["detail"] = detail
    if code:
        body["code"] = code
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def make_recorder_admin_router(
    jobs: AdminJobStore,
    runner: CompactionRunner | None,
    audit: _Emitter | None,
    principal_resolver: _PrincipalResolver | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.post("/recorder/compact")
    async def compact(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if audit is None or runner is None:
            return _problem(503, "Service unavailable", "compaction backend is not wired")
        common: dict[str, Any] = {
            "actor_label": principal.username,
            "actor_user_id": principal.user_id,
            "actor_ip": principal.ip,
            "session_id": principal.session_id,
            "object_kind": "recorder_compaction",
            "request_id": principal.request_id,
        }
        if not principal.has(RECORDING_WRITE):
            await audit.emit(
                "recorder.compact",
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=f"missing_permission:{RECORDING_WRITE}",
                **common,
            )
            return _problem(403, "Forbidden", f"requires {RECORDING_WRITE}")
        key = request.headers.get("idempotency-key", "")
        try:
            key = str(uuid.UUID(key))
        except ValueError:
            return _problem(400, "Bad request", "Idempotency-Key (UUID) is required")
        prior = jobs.by_idempotency_key(key)
        if prior is not None:
            return JSONResponse(status_code=202, content={"job_id": prior.id})
        try:
            raw = await request.body()
            body = CompactRequest.model_validate(json.loads(raw) if raw else {}).checked()
        except (ValidationError, ValueError):
            return _problem(400, "Bad request", "invalid compaction request")
        params = {"symbols": body.symbols or [], "older_than_days": body.older_than_days or 0}

        async def work(progress: Callable[[float], None]) -> dict[str, object]:
            return await runner(body.symbols, body.older_than_days, progress)

        async def done(job: Job) -> None:
            ok = job.status == "succeeded"
            await audit.emit(
                "recorder.compact",
                outcome=AuditOutcome.SUCCESS if ok else AuditOutcome.FAILURE,
                severity=Severity.INFO if ok else Severity.ERROR,
                reason=None if ok else job.error,
                object_id=job.id,
                after_state={"params": params, "result": job.result or {}},
                **common,
            )

        try:
            job = jobs.submit(JOB_KIND, key, work, done)
        except JobConflict:
            return _problem(409, "Conflict", "a compaction job is already running", "job_running")
        await audit.emit(
            "recorder.compact", object_id=job.id, before_state={"params": params}, **common
        )
        return JSONResponse(status_code=202, content={"job_id": job.id})

    @router.get("/jobs/{jobId}")
    async def get_job(jobId: str, request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(ADMIN_READ):
            return _problem(403, "Forbidden", f"requires {ADMIN_READ}")
        job = jobs.get(jobId)
        if job is None:
            return _problem(404, "Not found", "unknown job")
        return JSONResponse(job.view())

    return router
