"""`PUT /users/{userId}/roles` (E09-T03, QA #1648 defects 1-2).

Enforces `users:write`, the owner-floor guard at API level, audits the
change, and notifies the WS layer so a downgrade takes effect on live
sockets. `principal_resolver=None` / `store=None` fail closed with 501
(same pattern as `api/audit.py`) until session verification is wired.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce

_SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class SnapshotResolver(Protocol):
    def resolve(self, request: Request) -> PrincipalSnapshot | None: ...


class UserRoleStore(Protocol):
    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None: ...

    async def count_active_owners(self) -> int: ...

    async def set_roles(self, user_id: uuid.UUID, roles: frozenset[str]) -> None: ...


class PermissionChangeNotifier(Protocol):
    async def roles_changed(self, user_id: uuid.UUID) -> None: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def make_users_router(
    store: UserRoleStore | None,
    emitter: _Emitter | None,
    principal_resolver: SnapshotResolver | None = None,
    notifier: PermissionChangeNotifier | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.put("/users/{userId}/roles")
    async def put_user_roles(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        if principal_resolver is None or store is None:
            return _problem(501, "Not implemented", "no principal resolver/store wired")
        principal = principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        try:
            await enforce(principal, Permission.USERS_WRITE, scope=Scope.NONE, emitter=emitter)
        except ForbiddenError as exc:
            return JSONResponse(
                status_code=403,
                content={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "forbidden",
                    "reason": exc.deny.reason.value,
                },
                media_type="application/problem+json",
            )
        try:
            body = await request.json()
        except ValueError:
            return _problem(400, "Bad request", "body must be JSON")
        roles_raw = body.get("roles") if isinstance(body, dict) else None
        if (
            not isinstance(roles_raw, list)
            or not roles_raw
            or not all(isinstance(r, str) and r in _SYSTEM_ROLES for r in roles_raw)
        ):
            return _problem(400, "Bad request", "roles must be a non-empty list of role names")
        new_roles = frozenset(roles_raw)
        current = await store.get_roles(user_id)
        if current is None:
            return _problem(404, "Not found", "user not found")
        try:
            assert_owner_floor(
                current_roles=current,
                new_roles=new_roles,
                active_owner_count=await store.count_active_owners(),
            )
        except OwnerFloorError:
            return _problem(409, "Conflict", "the last active owner cannot be demoted")
        await store.set_roles(user_id, new_roles)
        if emitter is not None:
            for action, changed in (
                ("roles.grant", sorted(new_roles - current)),
                ("roles.revoke", sorted(current - new_roles)),
            ):
                if changed:
                    await emitter.emit(
                        action,
                        actor_label=str(principal.user_id),
                        actor_user_id=principal.user_id,
                        object_kind="user",
                        object_id=str(user_id),
                        reason=",".join(changed),
                    )
        if notifier is not None:
            await notifier.roles_changed(user_id)
        return JSONResponse(
            status_code=200, content={"id": str(user_id), "roles": sorted(new_roles)}
        )

    return router
