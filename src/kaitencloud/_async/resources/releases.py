# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Sequence

from ..._utils import api_path, compact
from ...types import Release
from ._base import AsyncResource

__all__ = ["AsyncReleases"]


class AsyncReleases(AsyncResource):
    """Releases: immutable, versioned sets of components.

    A release cannot be edited. Changing one means deleting it and creating another, which
    loses the deployment history attached to the first.
    """

    async def list(self) -> builtins.list[Release]:
        """Return every release, walking all pages."""
        return await self._api.list_all("/releases", Release)

    async def get(self, release_slug: str) -> Release:
        """Return the release identified by ``release_slug``, with its components."""
        return await self._api.get(api_path("releases", release_slug), Release)

    async def create(
        self,
        *,
        version: str,
        description: str | None = None,
        component_ids: Sequence[str] | None = None,
        slug: str | None = None,
    ) -> Release:
        """Create a release.

        Args:
            version: Its version, e.g. ``"v1.4.0"``, unique in the organization.
            description: A description or changelog, up to 500 characters.
            component_ids: The ids of the components it is made of, fixed from now on.
            slug: Its URL-friendly identifier, generated when omitted.
        """
        body = compact(
            {
                "version": version,
                "description": description,
                "componentIds": list(component_ids) if component_ids is not None else None,
                "slug": slug,
            }
        )
        return await self._api.send("POST", "/releases", Release, body=body)

    async def delete(self, release_slug: str) -> None:
        """Delete the release identified by ``release_slug``."""
        await self._api.send_empty("DELETE", api_path("releases", release_slug))
