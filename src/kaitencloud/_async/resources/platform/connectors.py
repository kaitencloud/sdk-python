# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...._utils import compact
from ....types import Connector
from .._base import AsyncResource

__all__ = ["AsyncPlatformConnectors"]


class AsyncPlatformConnectors(AsyncResource):
    """The connector registry: the connectors this deployment offers its organizations."""

    async def register(
        self,
        *,
        name: str,
        version: str,
        settings_schema: Mapping[str, Any] | None = None,
        entitlement_slug: str | None = None,
    ) -> Connector:
        """Record a connector's manifest, or update the one registered under the same name.

        An upsert on ``name``, so the process that hosts a connector can register it on every
        start. Registering says the connector exists in this deployment. Whether an
        organization may use it is a separate decision, which each organization makes over the
        Core API and ``entitlement_slug`` gates.

        Requires a platform credential holding ``write:organizations``.

        Args:
            name: The connector's stable identifier, e.g. ``"kaiten.integration.crm.attio"``.
            version: The build of the connector this deployment runs.
            settings_schema: The JSON schema organization settings are validated against, and
                consoles render a settings form from. A ``writeOnly`` property is a secret:
                accepted, never read back. Defaults to an empty schema.
            entitlement_slug: The BOOLEAN entitlement a license must grant before an
                organization may activate the connector. Omitted, the connector is ungated.
        """
        body = {
            "name": name,
            "version": version,
            "settings_schema": dict(settings_schema) if settings_schema is not None else {},
            **compact({"entitlement_slug": entitlement_slug}),
        }
        return await self._api.send(
            "POST", "/platform/connectors", Connector, body=body, idempotent=True
        )
