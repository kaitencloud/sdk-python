# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ...._utils import api_path, validate_uuid
from .._base import AsyncResource

__all__ = ["AsyncPlatformUsers"]


class AsyncPlatformUsers(AsyncResource):
    """Users, across every organization.

    Users are provisioned when they first sign in, so deletion is the only operation.
    """

    async def delete(self, user_id: str) -> None:
        """Delete a user, in every organization.

        The user is soft-deleted -- rows it created keep their attribution -- and signing in
        again does not bring it back. Requires ``delete:users``.
        """
        await self._api.send_empty(
            "DELETE", api_path("platform", "users", validate_uuid(user_id, "user_id"))
        )
