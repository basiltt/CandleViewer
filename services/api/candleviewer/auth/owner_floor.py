"""Owner-floor guard (E09-T03, QA #1648 defect 2).

The last active `owner` can never be demoted or removed through the API.
The database trigger stays as defence in depth but is never the only guard
(ticket AC "Owner floor cannot be removed through the API").
"""

from __future__ import annotations

from collections.abc import Collection


class OwnerFloorError(Exception):
    """The change would leave the system with no active owner."""


def assert_owner_floor(
    *,
    current_roles: Collection[str],
    new_roles: Collection[str],
    active_owner_count: int,
) -> None:
    """Raise `OwnerFloorError` if `new_roles` strips `owner` from the only
    remaining active owner. `active_owner_count` includes the target when
    the target currently holds `owner`. Fail-closed: a count < 1 for an
    owner target is treated as "last owner"."""
    if "owner" in current_roles and "owner" not in new_roles and active_owner_count <= 1:
        raise OwnerFloorError("cannot remove the owner role from the last active owner")
