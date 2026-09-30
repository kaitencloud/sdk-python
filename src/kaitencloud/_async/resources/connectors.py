# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any

from ..._utils import api_path
from ...types import (
    Connector,
    ConnectorActivation,
    ConnectorSettings,
    ConnectorSettingsSchema,
    ConnectorState,
)
from ._base import AsyncResource

__all__ = ["AsyncConnectors"]


class AsyncConnectors(AsyncResource):
    """Connectors: the integrations this deployment offers, and this organization's use of them.

    Registering a connector is deployment-wide and belongs to the Platform API
    (``KaitenPlatformClient.connectors``). Activating and configuring one is each
    organization's own decision, made here.
    """

    async def list(self) -> builtins.list[Connector]:
        """Return every connector registered with this deployment."""
        return await self._api.get_list("/connectors", Connector)

    async def get(self, connector_name: str) -> Connector:
        """Return the connector registered as ``connector_name``."""
        return await self._api.get(api_path("connectors", connector_name), Connector)

    async def get_state(self, connector_name: str) -> ConnectorState:
        """Return whether the connector is available, licensed, and activated for this organization.

        Three separate answers, where a single 404 could never tell "not registered here" from
        "not in your license" from "not turned on".
        """
        return await self._api.get(api_path("connectors", connector_name, "state"), ConnectorState)

    async def activate(self, connector_name: str) -> ConnectorActivation:
        """Activate the connector for this organization.

        Refused when the connector is gated by a BOOLEAN entitlement this organization's
        license does not grant.
        """
        return await self._api.send(
            "PUT", api_path("connectors", connector_name, "activation"), ConnectorActivation
        )

    async def deactivate(self, connector_name: str) -> None:
        """Deactivate the connector for this organization."""
        await self._api.send_empty("DELETE", api_path("connectors", connector_name, "activation"))

    async def get_settings_schema(self, connector_name: str) -> ConnectorSettingsSchema:
        """Return the JSON schema the connector's settings are validated against."""
        return await self._api.get(
            api_path("connectors", connector_name, "settings", "schema"), ConnectorSettingsSchema
        )

    async def get_settings(self, connector_name: str) -> ConnectorSettings:
        """Return this organization's settings for the connector.

        Secrets -- the ``writeOnly`` properties of the settings schema -- are never read back.
        """
        return await self._api.get(
            api_path("connectors", connector_name, "settings"), ConnectorSettings
        )

    async def update_settings(
        self, connector_name: str, settings: Mapping[str, Any]
    ) -> ConnectorSettings:
        """Replace this organization's settings for the connector, and return them.

        The settings are validated against the connector's settings schema.
        """
        return await self._api.send(
            "PUT",
            api_path("connectors", connector_name, "settings"),
            ConnectorSettings,
            body={"settings": dict(settings)},
        )

    async def delete_settings(self, connector_name: str) -> None:
        """Delete this organization's settings for the connector."""
        await self._api.send_empty("DELETE", api_path("connectors", connector_name, "settings"))
