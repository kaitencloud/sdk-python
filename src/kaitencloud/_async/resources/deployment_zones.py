# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any

from ..._utils import api_path, compact
from ...types import DeploymentZone
from ._base import AsyncResource

__all__ = ["AsyncDeploymentZones"]


class AsyncDeploymentZones(AsyncResource):
    """Deployment zones: the environments your instances run in, and the release on each."""

    async def list(self) -> builtins.list[DeploymentZone]:
        """Return every deployment zone, walking all pages."""
        return await self._api.list_all("/deployment-zones", DeploymentZone)

    async def get(self, deployment_zone_slug: str) -> DeploymentZone:
        """Return the deployment zone identified by ``deployment_zone_slug``."""
        return await self._api.get(
            api_path("deployment-zones", deployment_zone_slug), DeploymentZone
        )

    async def create(
        self,
        *,
        name: str,
        type: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        release_id: str | None = None,
        slug: str | None = None,
    ) -> DeploymentZone:
        """Create a deployment zone.

        Args:
            name: The zone's name, e.g. ``"AWS eu-west-1"``.
            type: Its environment class. Free-form, but ``production``, ``staging`` and
                ``development`` are the ones the console labels.
            description: A description.
            metadata: Typed metadata, validated against the organization's ``DEPLOYMENT_ZONE``
                metadata fields.
            release_id: The id of the release currently deployed to the zone.
            slug: Its URL-friendly identifier, generated when omitted. Immutable once set.
        """
        body = compact(
            {
                "name": name,
                "type": type,
                "description": description,
                "metadata": dict(metadata) if metadata is not None else None,
                "releaseId": release_id,
                "slug": slug,
            }
        )
        return await self._api.send("POST", "/deployment-zones", DeploymentZone, body=body)

    async def update(
        self,
        deployment_zone_slug: str,
        *,
        name: str,
        type: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        release_id: str | None = None,
    ) -> None:
        """Replace a deployment zone's details.

        A full replacement: send back the metadata and release to keep them. Setting a new
        ``release_id`` records a deployment of that release to the zone. The slug cannot be
        changed.
        """
        body = compact(
            {
                "name": name,
                "type": type,
                "description": description,
                "metadata": dict(metadata) if metadata is not None else None,
                "releaseId": release_id,
            }
        )
        await self._api.send_empty(
            "PUT", api_path("deployment-zones", deployment_zone_slug), body=body
        )

    async def delete(self, deployment_zone_slug: str) -> None:
        """Delete the deployment zone identified by ``deployment_zone_slug``."""
        await self._api.send_empty("DELETE", api_path("deployment-zones", deployment_zone_slug))
