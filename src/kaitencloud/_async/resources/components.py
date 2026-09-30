# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins

from ..._utils import api_path, compact
from ...types import Component
from ._base import AsyncResource

__all__ = ["AsyncComponents"]


class AsyncComponents(AsyncResource):
    """Components: the versioned building blocks of your product that releases are made of."""

    async def list(self) -> builtins.list[Component]:
        """Return every component, walking all pages."""
        return await self._api.list_all("/components", Component)

    async def get(self, component_slug: str) -> Component:
        """Return the component identified by ``component_slug``."""
        return await self._api.get(api_path("components", component_slug), Component)

    async def create(
        self,
        *,
        name: str,
        version: str,
        description: str | None = None,
        previous_component_id: str | None = None,
        slug: str | None = None,
    ) -> Component:
        """Create a component.

        Args:
            name: The component's name, e.g. ``"api-gateway"``.
            version: Its version, e.g. ``"v1.2.3"``.
            description: A description, up to 500 characters.
            previous_component_id: The id of the component this one succeeds. The link is set
                here, once: an update cannot change it.
            slug: Its URL-friendly identifier, generated when omitted. Immutable once set.
        """
        body = compact(
            {
                "name": name,
                "version": version,
                "description": description,
                "previousComponentId": previous_component_id,
                "slug": slug,
            }
        )
        return await self._api.send("POST", "/components", Component, body=body)

    async def update(
        self,
        component_slug: str,
        *,
        name: str,
        version: str,
        description: str | None = None,
    ) -> Component:
        """Replace a component's name, version and description, and return it.

        A full replacement: a description left out is cleared. Neither the slug nor the
        previous component can be changed.
        """
        body = compact({"name": name, "version": version, "description": description})
        return await self._api.send(
            "PUT", api_path("components", component_slug), Component, body=body
        )

    async def delete(self, component_slug: str) -> None:
        """Delete the component identified by ``component_slug``."""
        await self._api.send_empty("DELETE", api_path("components", component_slug))
