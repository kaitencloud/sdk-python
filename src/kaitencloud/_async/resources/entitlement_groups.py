# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins

from ..._utils import api_path, compact
from ...types import EntitlementGroup, EntitlementGroupUsage
from ._base import AsyncResource

__all__ = ["AsyncEntitlementGroups"]


class AsyncEntitlementGroups(AsyncResource):
    """Entitlement groups: named sets of entitlements, for display and for shared quotas."""

    async def list(self) -> builtins.list[EntitlementGroup]:
        """Return every entitlement group, walking all pages."""
        return await self._api.list_all("/entitlement-groups", EntitlementGroup)

    async def get(self, entitlement_group_slug: str) -> EntitlementGroup:
        """Return the entitlement group identified by ``entitlement_group_slug``."""
        return await self._api.get(
            api_path("entitlement-groups", entitlement_group_slug), EntitlementGroup
        )

    async def create(
        self,
        *,
        name: str,
        description: str | None = None,
        slug: str | None = None,
    ) -> EntitlementGroup:
        """Create an entitlement group.

        Args:
            name: The group's name, e.g. ``"AI quotas"``.
            description: A description. Always sent -- as null when omitted -- because the
                API requires the key.
            slug: Its URL-friendly identifier, generated when omitted. Immutable once set.
        """
        body = {"name": name, "description": description, **compact({"slug": slug})}
        return await self._api.send("POST", "/entitlement-groups", EntitlementGroup, body=body)

    async def update(
        self,
        entitlement_group_slug: str,
        *,
        name: str,
        description: str | None = None,
    ) -> None:
        """Replace an entitlement group's name and description. The slug cannot be changed."""
        await self._api.send_empty(
            "PUT",
            api_path("entitlement-groups", entitlement_group_slug),
            body={"name": name, "description": description},
        )

    async def delete(self, entitlement_group_slug: str) -> None:
        """Delete the entitlement group identified by ``entitlement_group_slug``."""
        await self._api.send_empty("DELETE", api_path("entitlement-groups", entitlement_group_slug))

    async def add_entitlement(self, entitlement_group_slug: str, entitlement_slug: str) -> None:
        """Add the entitlement identified by ``entitlement_slug`` to the group."""
        await self._api.send_empty(
            "POST",
            api_path("entitlement-groups", entitlement_group_slug, "entitlements"),
            body={"entitlementSlug": entitlement_slug},
        )

    async def remove_entitlement(self, entitlement_group_slug: str, entitlement_slug: str) -> None:
        """Remove the entitlement identified by ``entitlement_slug`` from the group."""
        await self._api.send_empty(
            "DELETE",
            api_path(
                "entitlement-groups", entitlement_group_slug, "entitlements", entitlement_slug
            ),
        )

    async def get_usage(
        self, entitlement_group_slug: str, instance_slug: str
    ) -> builtins.list[EntitlementGroupUsage]:
        """Return the grant and the usage of each of the group's entitlements, for one instance."""
        return await self._api.get_list(
            api_path("entitlement-groups", entitlement_group_slug, "usage"),
            EntitlementGroupUsage,
            params={"instance": instance_slug},
        )
